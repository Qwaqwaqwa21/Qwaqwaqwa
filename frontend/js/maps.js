/*
 * Картопостроение: карта устьев и сеточные карты по горизонтам.
 * Палитры physics / physics reverse, изолинии с подписями, контуры из SHP.
 */
(function () {
  // Палитра «physics» (как в Surfer/Petrel): фиолет→синий→циан→зелёный→жёлтый→красный
  var PHYSICS = [
    [0.00, [40, 0, 90]], [0.15, [0, 60, 200]], [0.32, [0, 170, 220]],
    [0.50, [0, 190, 120]], [0.66, [180, 220, 40]], [0.82, [250, 190, 30]],
    [1.00, [220, 30, 30]]
  ];

  function ramp(t, reverse) {
    t = Math.max(0, Math.min(1, reverse ? 1 - t : t));
    for (var i = 1; i < PHYSICS.length; i++) {
      if (t <= PHYSICS[i][0]) {
        var a = PHYSICS[i - 1], b = PHYSICS[i];
        var f = (t - a[0]) / (b[0] - a[0] || 1);
        return 'rgb(' + Math.round(a[1][0] + f * (b[1][0] - a[1][0])) + ','
          + Math.round(a[1][1] + f * (b[1][1] - a[1][1])) + ','
          + Math.round(a[1][2] + f * (b[1][2] - a[1][2])) + ')';
      }
    }
    return 'rgb(220,30,30)';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function pid() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && typeof a._pid === 'function') ? a._pid()
         : ((a && a.projects && a.projects[0]) ? a.projects[0].id : null);
  }

  window.MapsView = {
    data: null, wellheads: null, shapes: null, horizons: [],
    excluded: {},          // {wellId: true} — исключены из интерполяции

    isExcluded: function (id) { return !!this.excluded[id]; },

    toggleWell: async function (id) {
      if (this.excluded[id]) delete this.excluded[id]; else this.excluded[id] = true;
      this._markWellList();
      await this.load();
    },

    _markWellList: function () {
      var self = this;
      document.querySelectorAll('.well-item').forEach(function (el) {
        var id = parseInt(el.getAttribute('data-id'), 10);
        el.classList.toggle('map-off', self.isExcluded(id));
      });
    },

    _excludeParam: function () {
      var ids = Object.keys(this.excluded);
      return ids.length ? '&exclude=' + ids.join(',') : '';
    },


    load: async function () {
      var host = document.getElementById('mapsContent');
      var p = pid();
      if (!p) { if (host) host.innerHTML = '<p style="color:#8b949e">Откройте проект.</p>'; return; }
      if (host) host.innerHTML = '<p style="color:#8b949e">Построение карты…</p>';
      // список горизонтов
      try {
        var hz = await app._api('/projects/' + p + '/horizons');
        this.horizons = hz.horizons || [];
        var sel = document.getElementById('mapHorizon');
        if (sel && sel.options.length !== this.horizons.length) {
          sel.innerHTML = this.horizons.map(function (h) {
            return '<option value="' + esc(h) + '">' + esc(h) + '</option>';
          }).join('');
        }
      } catch (e) { /* нет отбивок */ }
      try { this.shapes = await app._api('/projects/' + p + '/shapes'); } catch (e) { this.shapes = null; }

      var param = (document.getElementById('mapParam') || {}).value || 'thickness';
      try {
        if (param === 'wellheads') {
          this.wellheads = await app._api('/projects/' + p + '/map/wellheads');
          this.data = null;
        } else {
          var h = (document.getElementById('mapHorizon') || {}).value || '';
          if (!h) {
            // Без горизонта карта параметра не считается: не дёргаем сервер
            // ради заведомого 400, а сразу объясняем, чего не хватает.
            this.data = null;
            this.wellheads = null;
            if (host) host.innerHTML = '<p style="color:#f85149">Укажите горизонт — '
              + 'в проекте нет отбивок, загрузите их во вкладке «Отбивки»</p>';
            return;
          }
          var pw = (document.getElementById('mapPower') || {}).value || '2';
          this.data = await app._api('/projects/' + p + '/map/grid?param=' + param
            + '&horizon=' + encodeURIComponent(h) + '&power=' + pw + '&nx=150&ny=150'
            + this._excludeParam());
          this.wellheads = null;
        }
      } catch (e) {
        // запрос вытеснен более новым (дедупликация в app._api) — не ошибка:
        // карту дорисует тот вызов, который его вытеснил
        if (/superseded/i.test((e && e.message) || '')) return;
        if (host) host.innerHTML = '<p style="color:#f85149">' + esc(e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    importCoordFile: async function (file) {
      if (!file) return;
      var p = pid();
      if (!p) { GeoToast.warn('Откройте проект'); return; }
      try {
        var fd = new FormData();
        fd.append('file', file);
        var resp = await fetch('/api/projects/' + p + '/wells/coordinates/import', {
          method: 'POST', headers: { 'X-User-Role': app.currentRole || 'viewer' }, body: fd
        });
        var j = await resp.json();
        if (!resp.ok) throw new Error(j.detail || ('HTTP ' + resp.status));
        GeoToast.success('Координаты: обновлено ' + j.updated + ' скв.'
          + (j.missing && j.missing.length ? ', не найдено: ' + j.missing.join(', ') : ''));
        await this.load();
      } catch (e) { GeoToast.error('Импорт не удался: ' + (e.message || e)); }
    },

    showInventory: async function () {
      var p = pid();
      if (!p) { GeoToast.warn('Откройте проект'); return; }
      var host = document.getElementById('mapsContent');
      host.innerHTML = '<p style=\"color:#8b949e\">Сбор сведений…</p>';
      var inv;
      try { inv = await app._api('/projects/' + p + '/inventory'); }
      catch (e) {
        if (/superseded/i.test((e && e.message) || '')) return;
        host.innerHTML = '<p style=\"color:#f85149\">' + esc(e.message || e) + '</p>';
        return;
      }
      var s = inv.summary;
      var yes = function (v) { return v ? '<span style=\"color:#3fb950\">✔</span>' : '<span style=\"color:#f85149\">—</span>'; };
      var h = '<h3 style=\"color:#c9d1d9;margin:0 0 10px\">Что есть в скважинах</h3>';
      h += '<div style=\"display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px\">';
      [['Скважин', s.wells, '#c9d1d9'], ['С координатами', s.with_coords + ' (' + s.coords_pct + '%)', '#58a6ff'],
       ['С альтитудой', s.with_altitude, '#58a6ff'], ['С инклинометрией', s.with_inkl + ' (' + s.inkl_pct + '%)', '#58a6ff'],
       ['С ГИС', s.with_gis, '#3fb950'], ['С РИГИС', s.with_rigis, '#3fb950'],
       ['С отбивками', s.with_tops, '#d29922']].forEach(function (b) {
        h += '<div style=\"background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 12px;min-width:110px\">'
          + '<div style=\"color:#8b949e;font-size:11px\">' + b[0] + '</div>'
          + '<div style=\"color:' + b[2] + ';font-size:17px;font-weight:600\">' + b[1] + '</div></div>';
      });
      h += '</div><div style=\"overflow-x:auto\"><table style=\"border-collapse:collapse;font-size:12px;white-space:nowrap\">';
      h += '<tr style=\"color:#8b949e;border-bottom:1px solid #30363d\">'
        + '<th style=\"text-align:left;padding:6px 8px\">Скважина</th>'
        + '<th style=\"padding:6px 8px\">Коорд.</th><th style=\"padding:6px 8px\">X</th><th style=\"padding:6px 8px\">Y</th>'
        + '<th style=\"padding:6px 8px\">Альтитуда</th><th style=\"padding:6px 8px\">ИНКЛ</th>'
        + '<th style=\"padding:6px 8px\">ГИС</th><th style=\"text-align:left;padding:6px 8px\">Методы</th>'
        + '<th style=\"padding:6px 8px\">РИГИС</th><th style=\"padding:6px 8px\">Отбивки</th>'
        + '<th style=\"padding:6px 8px\">Интервал, м</th><th style=\"padding:6px 8px\">Заметки</th></tr>';
      inv.rows.forEach(function (r) {
        h += '<tr style=\"border-bottom:1px solid #21262d\">'
          + '<td style=\"padding:5px 8px;color:#c9d1d9;font-weight:600\">' + esc(r.well_name) + '</td>'
          + '<td style=\"text-align:center\">' + yes(r.coords) + '</td>'
          + '<td style=\"padding:5px 8px;text-align:right;color:#8b949e\">' + (r.x != null ? r.x.toFixed(1) : '—') + '</td>'
          + '<td style=\"padding:5px 8px;text-align:right;color:#8b949e\">' + (r.y != null ? r.y.toFixed(1) : '—') + '</td>'
          + '<td style=\"padding:5px 8px;text-align:right;color:#8b949e\">' + (r.altitude != null ? r.altitude.toFixed(1) : '—') + '</td>'
          + '<td style=\"text-align:center\">' + yes(r.inkl) + '</td>'
          + '<td style=\"text-align:center;color:#3fb950\">' + (r.gis_count || '—') + '</td>'
          + '<td style=\"padding:5px 8px;color:#8b949e\">' + esc(r.gis.join(' ')) + '</td>'
          + '<td style=\"text-align:center;color:#3fb950\">' + (r.rigis_count || '—') + '</td>'
          + '<td style=\"text-align:center;color:#d29922\">' + (r.tops || '—') + '</td>'
          + '<td style=\"padding:5px 8px;text-align:center;color:#8b949e\">'
          + (r.depth_from != null ? r.depth_from + '–' + r.depth_to : '—') + '</td>'
          + '<td style=\"text-align:center;color:#8b949e\">' + (r.notes || '—') + '</td></tr>';
      });
      h += '</table></div>';
      host.innerHTML = h;
      var info = document.getElementById('mapInfo');
      if (info) info.textContent = 'Инвентаризация · ' + s.wells + ' скв.';
    },

    // Текущий масштаб и сдвиг карты. Хранится отдельно от данных: смена
    // горизонта не должна сбрасывать то, куда пользователь смотрит.
    view: { zoom: 1, dx: 0, dy: 0 },

    // Выгрузка карты файлом. Параметры берём те же, что и при построении,
    // иначе в файле окажется не то, что на экране.
    exportMap: function (fmt) {
      var p = pid();
      if (!p) { GeoToast.warn('Откройте проект'); return; }
      var param = (document.getElementById('mapParam') || {}).value || 'thickness';
      if (param === 'wellheads') { GeoToast.warn('Карта устьев не выгружается — постройте карту параметра'); return; }
      var h = (document.getElementById('mapHorizon') || {}).value || '';
      if (param !== 'altitude' && !h) { GeoToast.warn('Выберите горизонт'); return; }
      var pw = (document.getElementById('mapPower') || {}).value || 2;
      var url = '/api/projects/' + p + '/map/export?fmt=' + fmt
        + '&param=' + encodeURIComponent(param)
        + '&horizon=' + encodeURIComponent(h)
        + '&power=' + pw + '&nx=150&ny=150' + this._excludeParam();
      GeoToast.info('Готовим ' + fmt.toUpperCase() + '…');
      var a = document.createElement('a');
      a.href = url; a.download = '';
      document.body.appendChild(a); a.click(); a.remove();
    },

    resetView: function () {
      this.view = { zoom: 1, dx: 0, dy: 0 };
      this.render();
    },

    zoomBy: function (k, cx, cy) {
      var v = this.view, geom = this._lastGeom;
      var next = Math.min(40, Math.max(1, v.zoom * k));
      if (next === v.zoom) return;
      if (geom && cx != null) {
        // масштабируем ОТНОСИТЕЛЬНО точки под курсором, иначе карта уползает
        var r = next / v.zoom;
        v.dx = cx - r * (cx - v.dx);
        v.dy = cy - r * (cy - v.dy);
      }
      v.zoom = next;
      if (next === 1) { v.dx = 0; v.dy = 0; }
      this.render();
    },

    // Колесо — масштаб, перетаскивание — сдвиг. Вешается на холст после
    // каждой отрисовки: холст создаётся заново.
    _bindViewControls: function (cv) {
      var self = this;
      cv.onwheel = function (e) {
        e.preventDefault();
        var r = cv.getBoundingClientRect();
        self.zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top);
      };
      var drag = null;
      cv.onmousedown = function (e) {
        drag = { x: e.clientX, y: e.clientY, dx: self.view.dx, dy: self.view.dy };
        cv.style.cursor = 'grabbing';
      };
      window.addEventListener('mousemove', function (e) {
        if (!drag) return;
        self.view.dx = drag.dx + (e.clientX - drag.x);
        self.view.dy = drag.dy + (e.clientY - drag.y);
        self.render();
      });
      window.addEventListener('mouseup', function () {
        if (drag) { drag = null; cv.style.cursor = 'grab'; }
      });
      cv.style.cursor = 'grab';
      cv.title = 'колесо — масштаб, перетаскивание — сдвиг';
    },

    render: function () {
      var host = document.getElementById('mapsContent');
      if (!host) return;
      var d = this.data, wh = this.wellheads;
      var W = 980, H = 690;
      var info = document.getElementById('mapInfo');
      if (d && info) info.textContent = d.title + ' · ' + d.used + ' скв. · R=' + d.radius + ' м';
      if (wh && info) info.textContent = 'Карта устьев · ' + wh.count + ' скв.';

      host.innerHTML = '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">'
        + '<canvas id="geoMapCanvas" style="flex:0 0 auto"></canvas>'
        + '<div id="geoMapLegend" style="min-width:170px"></div></div>';
      var cv = document.getElementById('geoMapCanvas'), dpr = window.devicePixelRatio || 1;
      if (!cv) return;
      cv.style.width = W + 'px'; cv.style.height = H + 'px';
      cv.width = W * dpr; cv.height = H * dpr;
      var g = cv.getContext('2d'); g.scale(dpr, dpr);
      g.fillStyle = '#0d1117'; g.fillRect(0, 0, W, H);
      g.strokeStyle = '#30363d'; g.strokeRect(.5, .5, W - 1, H - 1);

      var m = { l: 70, r: 20, t: 20, b: 46 };
      var pts = d ? d.wells.filter(function (p) { return p.x != null; })
                  : (wh ? wh.wells : []);
      if (!pts.length) { host.innerHTML = '<p style="color:#8b949e">Нет координат.</p>'; return; }

      var x0, x1, y0, y1;
      if (d) { x0 = d.x0; x1 = d.x1; y0 = d.y0; y1 = d.y1; }
      else {
        x0 = Math.min.apply(null, pts.map(function (p) { return p.x; }));
        x1 = Math.max.apply(null, pts.map(function (p) { return p.x; }));
        y0 = Math.min.apply(null, pts.map(function (p) { return p.y; }));
        y1 = Math.max.apply(null, pts.map(function (p) { return p.y; }));
        var px = (x1 - x0) * 0.12 || 500, py = (y1 - y0) * 0.12 || 500;
        x0 -= px; x1 += px; y0 -= py; y1 += py;
      }
      // равный масштаб по осям; поверх — пользовательский зум и сдвиг
      var availW = W - m.l - m.r, availH = H - m.t - m.b;
      var base = Math.min(availW / (x1 - x0), availH / (y1 - y0));
      var zoom = this.view.zoom || 1;
      var sc = base * zoom;
      var offX = m.l + (availW - (x1 - x0) * sc) / 2 + (this.view.dx || 0);
      var offY = m.t + (availH - (y1 - y0) * sc) / 2 + (this.view.dy || 0);
      this._lastGeom = { x0: x0, x1: x1, y0: y0, y1: y1, sc: sc, base: base,
                         offX: offX, offY: offY, m: m, W: W, H: H };
      var X = function (v) { return offX + (v - x0) * sc; };
      var Y = function (v) { return offY + (y1 - v) * sc; };   // север вверх

      var rev = !!(document.getElementById('mapReverse') || {}).checked;

      g.save();
      g.beginPath();
      g.rect(m.l, m.t, availW, availH);
      g.clip();   // при зуме содержимое не должно вылезать на поля

      // ── заливка сетки ──
      if (d) {
        var nx = d.nx, ny = d.ny, vmin = d.vmin, vmax = d.vmax, rng = (vmax - vmin) || 1;
        var cw = (d.x1 - d.x0) / (nx - 1) * sc, ch = (d.y1 - d.y0) / (ny - 1) * sc;
        for (var j = 0; j < ny; j++) {
          for (var i = 0; i < nx; i++) {
            var v = d.grid[j][i];
            if (v == null) continue;
            g.fillStyle = ramp((v - vmin) / rng, rev);
            var gxv = d.x0 + i * (d.x1 - d.x0) / (nx - 1);
            var gyv = d.y0 + j * (d.y1 - d.y0) / (ny - 1);
            g.fillRect(X(gxv) - cw / 2 - 0.5, Y(gyv) - ch / 2 - 0.5, cw + 1, ch + 1);
          }
        }
        try { this._contours(g, d, X, Y, vmin, vmax); } catch (e) { console.warn('contours', e); }
      }

      // ── контуры лицензий/месторождений из SHP ──
      if (this.shapes && this.shapes.layers) {
        g.save(); g.strokeStyle = '#f0b429'; g.lineWidth = 1.8; g.setLineDash([7, 4]);
        this.shapes.layers.forEach(function (L) {
          (L.shapes || []).forEach(function (sh) {
            (sh.rings || []).forEach(function (r) {
              g.beginPath();
              r.forEach(function (pt, k) { k ? g.lineTo(X(pt[0]), Y(pt[1])) : g.moveTo(X(pt[0]), Y(pt[1])); });
              g.stroke();
            });
          });
        });
        g.restore();
      }

      // ── скважины ──
      // На трёх тысячах скважин кружки радиусом 4.5 с подписями сливались в
      // сплошную кашу и полностью закрывали построенную поверхность. Размер
      // значка и наличие подписей теперь зависят от того, сколько скважин
      // реально попало в видимую область, и от масштаба.
      var visible = pts.filter(function (p) {
        var px = X(p.x), py = Y(p.y);
        return px >= m.l - 20 && px <= m.l + availW + 20
            && py >= m.t - 20 && py <= m.t + availH + 20;
      });
      var labelMode = (document.getElementById('mapLabels') || {}).value || 'auto';
      var showLabels = labelMode === 'on'
        || (labelMode === 'auto' && visible.length <= 60);
      var rad = visible.length > 1200 ? 1.6
              : visible.length > 400 ? 2.4
              : visible.length > 120 ? 3.4 : 4.5;

      visible.forEach(function (p) {
        var px = X(p.x), py = Y(p.y);
        var noData = d && (p.value == null);
        var zero = d && (p.value != null && p.value <= 1e-9);
        var off = p.excluded || (typeof MapsView !== 'undefined' && MapsView.isExcluded(p.id));
        g.save();
        if (off) g.globalAlpha = 0.4;
        g.beginPath(); g.arc(px, py, rad, 0, 6.283);
        g.fillStyle = noData ? '#484f58' : (zero ? '#0d1117' : '#ffffff');
        g.fill();
        if (rad >= 2.4) {                 // тонкая обводка неразличима и съедает поверхность
          g.lineWidth = rad >= 4 ? 1.4 : 1;
          g.strokeStyle = off ? '#f0b429' : (zero ? '#f85149' : '#0d1117');
          if (off) { g.setLineDash([2, 2]); g.lineWidth = 1.8; }
          g.stroke();
        }
        g.restore();
        if (!showLabels) return;
        g.fillStyle = '#ffffff'; g.font = '11px system-ui,sans-serif'; g.textAlign = 'left';
        g.fillText(p.name, px + 7, py - 5);
        if (d && p.value != null) {
          g.fillStyle = '#c9d1d9'; g.font = '10px system-ui,sans-serif';
          g.fillText(p.value.toFixed(p.value < 1 ? 3 : 1), px + 7, py + 8);
        }
      });
      g.restore();   // снимаем обрезку поля карты

      // ── рамка, север, масштаб ──
      g.strokeStyle = '#484f58'; g.lineWidth = 1;
      g.strokeRect(offX, offY, (x1 - x0) * sc, (y1 - y0) * sc);
      g.fillStyle = '#8b949e'; g.font = '11px system-ui,sans-serif'; g.textAlign = 'center';
      g.fillText('С', offX + (x1 - x0) * sc - 16, offY + 14);
      g.beginPath(); g.moveTo(offX + (x1 - x0) * sc - 16, offY + 34);
      g.lineTo(offX + (x1 - x0) * sc - 16, offY + 18); g.stroke();
      // масштабная линейка
      var barM = Math.pow(10, Math.round(Math.log10((x1 - x0) / 5)));
      var barPx = barM * sc;
      var bx = offX + 10, by = offY + (y1 - y0) * sc - 14;
      g.strokeStyle = '#c9d1d9'; g.lineWidth = 2;
      g.beginPath(); g.moveTo(bx, by); g.lineTo(bx + barPx, by); g.stroke();
      g.fillStyle = '#c9d1d9'; g.textAlign = 'left';
      g.fillText(barM >= 1000 ? (barM / 1000) + ' км' : barM + ' м', bx, by - 6);
      // подписи осей координат
      g.fillStyle = '#6e7681'; g.textAlign = 'center';
      g.fillText('X, м (СК-63)', W / 2, H - 12);
      g.save(); g.translate(16, H / 2); g.rotate(-Math.PI / 2);
      g.fillText('Y, м (СК-63)', 0, 0); g.restore();

      // указатель масштаба: без него непонятно, почему видна часть площади
      if ((this.view.zoom || 1) > 1.001) {
        g.fillStyle = '#f0b429'; g.font = '11px system-ui,sans-serif'; g.textAlign = 'right';
        g.fillText('масштаб ×' + this.view.zoom.toFixed(1) + '  (двойной щелчок — сброс)',
                   W - m.r, m.t - 6);
      }

      this._bindViewControls(cv);
      cv.ondblclick = function () { MapsView.resetView(); };

      var lg = document.getElementById('geoMapLegend');
      if (lg) lg.innerHTML = this._legend(d, rev);
    },

    // ── изолинии (marching squares) с подписями ──
    _contours: function (g, d, X, Y, vmin, vmax) {
      var nLev = parseInt((document.getElementById('mapLevels') || {}).value || '8', 10);
      var step = (vmax - vmin) / (nLev + 1);
      if (!(step > 0)) return;
      var nx = d.nx, ny = d.ny;
      var gxOf = function (i) { return d.x0 + i * (d.x1 - d.x0) / (nx - 1); };
      var gyOf = function (j) { return d.y0 + j * (d.y1 - d.y0) / (ny - 1); };
      g.save();
      g.lineWidth = 1.1;
      for (var L = 1; L <= nLev; L++) {
        var lev = vmin + L * step;
        var segs = [];
        for (var j = 0; j < ny - 1; j++) {
          for (var i = 0; i < nx - 1; i++) {
            var v00 = d.grid[j][i], v10 = d.grid[j][i + 1],
                v01 = d.grid[j + 1][i], v11 = d.grid[j + 1][i + 1];
            if (v00 == null || v10 == null || v01 == null || v11 == null) continue;
            var idx = (v00 > lev ? 1 : 0) | (v10 > lev ? 2 : 0) | (v11 > lev ? 4 : 0) | (v01 > lev ? 8 : 0);
            if (idx === 0 || idx === 15) continue;
            var ip = function (a, b, va, vb) { return a + (lev - va) / (vb - va) * (b - a); };
            var pB = [ip(gxOf(i), gxOf(i + 1), v00, v10), gyOf(j)];
            var pR = [gxOf(i + 1), ip(gyOf(j), gyOf(j + 1), v10, v11)];
            var pT = [ip(gxOf(i), gxOf(i + 1), v01, v11), gyOf(j + 1)];
            var pL = [gxOf(i), ip(gyOf(j), gyOf(j + 1), v00, v01)];
            var E = { 1: [pB, pL], 2: [pB, pR], 3: [pL, pR], 4: [pR, pT], 5: [pB, pT],
                      6: [pB, pT], 7: [pL, pT], 8: [pL, pT], 9: [pB, pT], 10: [pB, pT],
                      11: [pR, pT], 12: [pL, pR], 13: [pB, pR], 14: [pB, pL] };
            var e = E[idx];
            if (e) segs.push(e);
          }
        }
        if (!segs.length) continue;
        g.strokeStyle = 'rgba(13,17,23,.75)';
        g.beginPath();
        segs.forEach(function (s) { g.moveTo(X(s[0][0]), Y(s[0][1])); g.lineTo(X(s[1][0]), Y(s[1][1])); });
        g.stroke();
        // подпись изолинии — на нескольких точках, с «разрывом» фона
        var lbl = lev.toFixed(lev < 1 ? 3 : (lev < 10 ? 1 : 0));
        g.font = '600 10px system-ui,sans-serif';
        g.textAlign = 'center'; g.textBaseline = 'middle';
        var everyN = Math.max(1, Math.floor(segs.length / 3));
        for (var k = Math.floor(everyN / 2); k < segs.length; k += everyN) {
          var s = segs[k];
          var lx = X((s[0][0] + s[1][0]) / 2), ly = Y((s[0][1] + s[1][1]) / 2);
          var w = g.measureText(lbl).width + 5;
          g.fillStyle = 'rgba(13,17,23,.82)';
          g.fillRect(lx - w / 2, ly - 7, w, 13);
          g.fillStyle = '#ffffff';
          g.fillText(lbl, lx, ly);
        }
      }
      g.restore();
    },

    _legend: function (d, rev) {
      if (!d) {
        var wh = this.wellheads;
        var n = wh ? wh.count : 0;
        var h0 = '<div style="color:#c9d1d9;font-weight:600;margin-bottom:6px">Карта устьев скважин</div>'
          + '<div style="color:#8b949e;font-size:12px;margin-bottom:10px">Скважин с координатами: <b>' + n + '</b></div>'
          + '<div style="font-size:12px;color:#c9d1d9">'
          + '<div style="display:flex;align-items:center;gap:7px;margin:4px 0">'
          + '<span style="width:11px;height:11px;border-radius:50%;background:#fff;border:1px solid #0d1117"></span> устье скважины</div>'
          + '<div style="display:flex;align-items:center;gap:7px;margin:4px 0">'
          + '<span style="width:11px;height:11px;border-radius:50%;background:#484f58"></span> исключена из сетки</div>'
          + '</div>'
          + '<div style="margin-top:10px;font-size:11px;color:#8b949e">'
          + 'Подпись у точки — номер скважины.<br>Клик по скважине в списке слева исключает её из интерполяции.<br>'
          + 'Оси — X/Y в СК-63, м. Масштабная линейка внизу слева.</div>';
        return h0;
      }
      var h = '<div style="color:#c9d1d9;font-weight:600;margin-bottom:6px">' + esc(d.title) + '</div>';
      if (d.horizon) h += '<div style="color:#8b949e;font-size:12px;margin-bottom:8px">Горизонт: ' + esc(d.horizon) + '</div>';
      h += '<div style="display:flex;gap:8px;align-items:stretch">'
        + '<div style="width:26px;height:230px;border:1px solid #30363d;background:linear-gradient(to top,'
        + [0, .15, .32, .5, .66, .82, 1].map(function (t) { return ramp(t, rev); }).join(',') + ')"></div>'
        + '<div style="display:flex;flex-direction:column;justify-content:space-between;font-size:11px;color:#c9d1d9">';
      for (var i = 5; i >= 0; i--) {
        var v = d.vmin + (d.vmax - d.vmin) * i / 5;
        h += '<div>' + v.toFixed(v < 1 ? 3 : 1) + '</div>';
      }
      h += '</div></div>';
      h += '<div style="margin-top:10px;font-size:11px;color:#8b949e">'
        + '<div>● белая — скважина с данными</div>'
        + '<div>● красный контур — нулевая толщина</div>'
        + '<div>● серая — нет данных по горизонту</div>'
        + '<div>◌ полупрозрачная — исключена из интерполяции</div>'
        + '<div style="margin-top:6px">Пустые области — выклинивание коллектора (на половине расстояния до «пустых» скважин).</div>'
        + '</div>';
      return h;
    }
  };
})();
