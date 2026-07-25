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
    return (a && a.projects && a.projects[0]) ? a.projects[0].id : null;
  }

  window.MapsView = {
    data: null, wellheads: null, shapes: null, horizons: [],

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
          var pw = (document.getElementById('mapPower') || {}).value || '2';
          this.data = await app._api('/projects/' + p + '/map/grid?param=' + param
            + '&horizon=' + encodeURIComponent(h) + '&power=' + pw + '&nx=150&ny=150');
          this.wellheads = null;
        }
      } catch (e) {
        if (host) host.innerHTML = '<p style="color:#f85149">' + esc(e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    importDemoCoords: async function () {
      try {
        var r = await app._api('/projects/' + pid() + '/wells/demo-coords', { method: 'POST' });
        GeoToast.success('Вымышленные координаты заданы для ' + r.wells + ' скв.');
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
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
      // равный масштаб по осям
      var availW = W - m.l - m.r, availH = H - m.t - m.b;
      var sc = Math.min(availW / (x1 - x0), availH / (y1 - y0));
      var offX = m.l + (availW - (x1 - x0) * sc) / 2;
      var offY = m.t + (availH - (y1 - y0) * sc) / 2;
      var X = function (v) { return offX + (v - x0) * sc; };
      var Y = function (v) { return offY + (y1 - v) * sc; };   // север вверх

      var rev = !!(document.getElementById('mapReverse') || {}).checked;

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
      pts.forEach(function (p) {
        var px = X(p.x), py = Y(p.y);
        var noData = d && (p.value == null);
        var zero = d && (p.value != null && p.value <= 1e-9);
        g.beginPath(); g.arc(px, py, 4.5, 0, 6.283);
        g.fillStyle = noData ? '#484f58' : (zero ? '#0d1117' : '#ffffff');
        g.fill();
        g.lineWidth = 1.4; g.strokeStyle = zero ? '#f85149' : '#0d1117'; g.stroke();
        g.fillStyle = '#ffffff'; g.font = '11px system-ui,sans-serif'; g.textAlign = 'left';
        g.fillText(p.name, px + 7, py - 5);
        if (d && p.value != null) {
          g.fillStyle = '#c9d1d9'; g.font = '10px system-ui,sans-serif';
          g.fillText(p.value.toFixed(p.value < 1 ? 3 : 1), px + 7, py + 8);
        }
      });

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
        return '<div style="color:#8b949e;font-size:12px">Карта устьев.<br>Точки — скважины с координатами.</div>';
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
        + '<div style="margin-top:6px">Пустые области — выклинивание коллектора (на половине расстояния до «пустых» скважин).</div>'
        + '</div>';
      return h;
    }
  };
})();
