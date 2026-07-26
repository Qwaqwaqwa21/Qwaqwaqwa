/*
 * Карта охвата ГИС (research coverage)
 *   • Матрица   — скважина × метод
 *   • Планшет   — закрашенные столбцы по глубине + горизонты
 *   • Горизонты — таблица охвата по горизонтам + экспорт CSV/XLSX
 */
(function () {
  var CATEGORY_LABEL = {
    potential: 'ПС', electrical: 'Электрические', nuclear: 'Радиоактивные',
    acoustic: 'Акустические', mechanical: 'Механические', geochem: 'Газовый',
    auxiliary: 'Вспомогательные', interpretation: 'Интерпретация (РИГИС)'
  };

  function projectId() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && typeof a._pid === 'function') ? a._pid()
         : ((a && a.projects && a.projects[0]) ? a.projects[0].id : null);
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function heat(v) {
    if (v == null) return 'transparent';
    var t = Math.max(0, Math.min(1, v));
    return 'rgba(' + Math.round(30 + 16 * t) + ',' + Math.round(60 + 144 * t) + ','
      + Math.round(90 + 23 * t) + ',' + (0.18 + 0.72 * t).toFixed(3) + ')';
  }

  window.ResearchCoverageView = {
    data: null, logData: null, horizonData: null,

    _mode: function () {
      return (document.getElementById('coverageViewMode') || {}).value || 'matrix';
    },

    switchMode: function () {
      var m = this._mode();
      var mc = document.getElementById('coverageMatrixControls');
      if (mc) mc.style.display = (m === 'matrix') ? 'contents' : 'none';
      var hx = document.getElementById('coverageHorizonControls');
      if (hx) hx.style.display = (m === 'horizon') ? 'contents' : 'none';
      this.load();
    },

    load: async function () {
      var pid = projectId();
      var host = document.getElementById('coverageContent');
      if (!pid) { if (host) host.innerHTML = '<p style="color:#8b949e">Откройте проект.</p>'; return; }
      if (host) host.innerHTML = '<p style="color:#8b949e">Расчёт охвата…</p>';
      var m = this._mode();
      try {
        if (m === 'planshet') this.logData = await app._api('/projects/' + pid + '/coverage-log?bins=300');
        else if (m === 'horizon') this.horizonData = await app._api('/projects/' + pid + '/coverage-by-horizon');
        else this.data = await app._api('/projects/' + pid + '/research-coverage?depth_bins=24');
      } catch (e) {
        if (host) host.innerHTML = '<p style="color:#f85149">Ошибка: ' + esc(e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render: function () {
      var m = this._mode();
      if (m === 'planshet') return this.renderPlanshet();
      if (m === 'horizon') return this.renderHorizons();
      return this.renderMatrix();
    },

    // ── Матрица скважина × метод ──────────────────────────────────────────
    renderMatrix: function () {
      var host = document.getElementById('coverageContent'), d = this.data;
      if (!host || !d) return;
      var mode = (document.getElementById('coverageMode') || {}).value || 'coverage';
      var measuredOnly = !!(document.getElementById('coverageMeasuredOnly') || {}).checked;
      var methods = d.methods.filter(function (x) {
        return x.wells_present > 0 && (!measuredOnly || !x.derived);
      });
      var info = document.getElementById('coverageInfo');
      if (info) info.textContent = d.well_count + ' скв. · ' + methods.length + ' методов';
      if (!methods.length) { host.innerHTML = '<p style="color:#8b949e">Нет распознанных методов.</p>'; return; }
      methods.sort(function (a, b) {
        return a.category === b.category ? a.name.localeCompare(b.name) : a.category.localeCompare(b.category);
      });

      var h = '<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:12px">';
      var spans = [];
      methods.forEach(function (x) {
        var l = spans[spans.length - 1];
        if (l && l.c === x.category) l.n++; else spans.push({ c: x.category, n: 1 });
      });
      h += '<tr><th></th>';
      spans.forEach(function (s) {
        h += '<th colspan="' + s.n + '" style="padding:4px 6px;text-align:center;color:#8b949e;border-bottom:1px solid #30363d">'
          + esc(CATEGORY_LABEL[s.c] || s.c) + '</th>';
      });
      h += '</tr><tr><th style="text-align:left;padding:6px 8px;position:sticky;left:0;background:#0d1117">Скважина \\ Метод</th>';
      methods.forEach(function (x) {
        h += '<th title="' + esc(x.name) + '" style="padding:6px 5px;white-space:nowrap;border-bottom:1px solid #30363d">'
          + '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + x.color + ';margin-right:3px"></span>'
          + esc(x.key) + '</th>';
      });
      h += '</tr>';
      d.wells.forEach(function (w) {
        h += '<tr><td style="padding:5px 8px;white-space:nowrap;position:sticky;left:0;background:#0d1117"><strong>'
          + esc(w.well_name) + '</strong> <span style="color:#8b949e">' + w.methods_present + '</span></td>';
        methods.forEach(function (x) {
          var c = w.cells[x.key], v = null, lbl = '·', t = w.well_name + ' · ' + x.name;
          if (c && c.present) {
            v = (mode === 'presence') ? 1 : (mode === 'fill' ? (c.fill != null ? c.fill : c.coverage) : c.coverage);
            lbl = (mode === 'presence') ? '●' : Math.round(v * 100) + '%';
            t += '\nохват ' + Math.round(c.coverage * 100) + '%'
              + (c.depth_top != null ? '\n' + c.depth_top + '–' + c.depth_bottom + ' м' : '')
              + (c.mnemonics ? '\n' + c.mnemonics.join(', ') : '');
          } else t += '\nнет данных';
          h += '<td title="' + esc(t) + '" style="text-align:center;padding:5px 4px;background:' + heat(v)
            + ';color:' + (v != null && v > 0.5 ? '#0d1117' : '#c9d1d9') + ';border:1px solid rgba(48,54,61,.5)">' + lbl + '</td>';
        });
        h += '</tr>';
      });
      h += '</table></div>';
      host.innerHTML = h;
    },

    // ── Планшет охвата по глубине (+ горизонты, дубли методов) ────────────
    renderPlanshet: function () {
      var host = document.getElementById('coverageContent'), d = this.logData;
      if (!host || !d) return;
      var cols = d.columns || [], wells = d.wells || [];
      var info = document.getElementById('coverageInfo');
      if (info) info.textContent = wells.length + ' скв. · ' + cols.length + ' методов · '
        + d.depth_top + '–' + d.depth_bottom + ' м';
      if (!cols.length) { host.innerHTML = '<p style="color:#8b949e">Нет данных.</p>'; return; }

      var AXIS = 64, COLW = 15, PAD = 26, HDR = 118, BOT = 12;
      var wellW = cols.length * COLW + PAD;
      var plotH = 660, W = AXIS + wells.length * wellW + 150, H = HDR + plotH + BOT;

      host.innerHTML = '<div style="overflow-x:auto"><canvas id="coverageLogCanvas"></canvas></div>'
        + this._legend(cols);
      var cv = document.getElementById('coverageLogCanvas'), dpr = window.devicePixelRatio || 1;
      cv.style.width = W + 'px'; cv.style.height = H + 'px';
      cv.width = W * dpr; cv.height = H * dpr;
      var x = cv.getContext('2d'); x.scale(dpr, dpr);
      x.textBaseline = 'middle'; x.font = '11px system-ui,sans-serif';

      var top = d.depth_top, bot = d.depth_bottom, span = (bot - top) || 1;
      var y0 = HDR, y1 = HDR + plotH;
      var Y = function (dep) { return y0 + (dep - top) / span * (y1 - y0); };

      // сетка глубин
      x.strokeStyle = '#30363d'; x.fillStyle = '#8b949e'; x.lineWidth = 1;
      for (var t = 0; t <= 10; t++) {
        var dep = top + span * t / 10, yy = Y(dep);
        x.beginPath(); x.moveTo(AXIS, yy); x.lineTo(W - 150, yy); x.stroke();
        x.fillText(Math.round(dep), 6, yy);
      }
      x.fillStyle = '#8b949e'; x.fillText('Глубина, м', 6, HDR - 12);

      // горизонты (по первой скважине, где они есть) — линии на всю ширину
      var tops = null;
      for (var i = 0; i < wells.length; i++) { if (wells[i].tops && wells[i].tops.length) { tops = wells[i].tops; break; } }
      if (tops) {
        var lastLabelY = -1e9;
        tops.forEach(function (tp) {
          var yy = Y(tp.top);
          if (yy < y0 || yy > y1) return;
          x.save();
          x.strokeStyle = tp.color || '#d29922';
          x.setLineDash([6, 4]); x.lineWidth = 1.2;
          x.beginPath(); x.moveTo(AXIS, yy); x.lineTo(W - 152, yy); x.stroke();
          x.setLineDash([]);
          // подпись со сдвигом, чтобы близкие горизонты не накладывались
          var ly = Math.max(yy, lastLabelY + 13);
          lastLabelY = ly;
          if (ly !== yy) {   // выноска от линии к сдвинутой подписи
            x.strokeStyle = 'rgba(139,148,158,.6)'; x.lineWidth = 1;
            x.beginPath(); x.moveTo(W - 152, yy); x.lineTo(W - 148, ly); x.stroke();
          }
          x.fillStyle = tp.color || '#d29922';
          x.textAlign = 'left'; x.font = '11px system-ui,sans-serif';
          x.fillText(tp.name, W - 146, ly);
          x.restore();
        });
      }

      wells.forEach(function (w, wi) {
        var wx = AXIS + wi * wellW + PAD / 2;
        // имя скважины
        x.save(); x.fillStyle = '#c9d1d9'; x.font = '600 13px system-ui,sans-serif';
        x.textAlign = 'center'; x.fillText(w.well_name, wx + cols.length * COLW / 2, 20); x.restore();
        // сокращения методов (вертикально над столбцами)
        cols.forEach(function (col, ci) {
          var cx = wx + ci * COLW;
          x.save();
          x.translate(cx + (COLW - 2) / 2, HDR - 10);
          x.rotate(-Math.PI / 2);
          x.textAlign = 'left';
          var has = w.present && w.present[col.key] && w.present[col.key].some(function (v) { return v > 0; });
          x.fillStyle = has ? col.color : '#484f58';
          x.font = (has ? '600 ' : '') + '11px system-ui,sans-serif';
          x.fillText(col.abbr || col.key, 0, 0);
          x.restore();
        });
        if (wi > 0) {
          x.strokeStyle = '#21262d';
          x.beginPath(); x.moveTo(AXIS + wi * wellW, HDR - 96); x.lineTo(AXIS + wi * wellW, y1); x.stroke();
        }
        cols.forEach(function (col, ci) {
          var cx = wx + ci * COLW;
          x.fillStyle = '#0d1117'; x.fillRect(cx, y0, COLW - 2, y1 - y0);
          x.strokeStyle = '#161b22'; x.strokeRect(cx + .5, y0 + .5, COLW - 3, y1 - y0 - 1);
          var arr = w.present && w.present[col.key];
          if (!arr) return;
          var n = arr.length, bh = (y1 - y0) / n;
          // 1 кривая — цвет метода; ≥2 кривых в интервале — другой цвет (штриховка)
          var run = -1, runVal = 0;
          for (var k = 0; k <= n; k++) {
            var v = k < n ? arr[k] : 0;
            if (v > 0 && run < 0) { run = k; runVal = v; }
            else if (run >= 0 && (v === 0 || (v > 1) !== (runVal > 1))) {
              var ry = y0 + run * bh, rh = Math.max(1, (k - run) * bh);
              if (runVal > 1) {
                x.fillStyle = '#f0b429';
                x.fillRect(cx, ry, COLW - 2, rh);
                x.strokeStyle = 'rgba(0,0,0,.45)'; x.lineWidth = 1;
                for (var yy2 = ry; yy2 < ry + rh; yy2 += 4) {
                  x.beginPath(); x.moveTo(cx, yy2); x.lineTo(cx + COLW - 2, yy2); x.stroke();
                }
              } else { x.fillStyle = col.color; x.fillRect(cx, ry, COLW - 2, rh); }
              run = (v > 0) ? k : -1; runVal = v;
            }
          }
        });
      });
    },

    _legend: function (cols) {
      var s = cols.map(function (c) {
        return '<span style="display:inline-flex;align-items:center;gap:5px;margin:3px 12px 3px 0;color:#c9d1d9">'
          + '<span style="width:11px;height:11px;border-radius:2px;background:' + c.color + '"></span>'
          + '<b>' + esc(c.abbr || c.key) + '</b> — ' + esc(c.name) + '</span>';
      }).join('');
      s += '<span style="display:inline-flex;align-items:center;gap:5px;margin:3px 12px 3px 0;color:#c9d1d9">'
        + '<span style="width:11px;height:11px;border-radius:2px;background:#f0b429;'
        + 'background-image:repeating-linear-gradient(0deg,rgba(0,0,0,.5) 0 1px,transparent 1px 4px)"></span>'
        + '≥2 кривых одного метода в интервале</span>';
      return '<div style="margin-top:12px;font-size:12px;display:flex;flex-wrap:wrap">' + s + '</div>';
    },

    // ── Охват по горизонтам (таблица + экспорт) ───────────────────────────
    renderHorizons: function () {
      var host = document.getElementById('coverageContent'), d = this.horizonData;
      if (!host || !d) return;
      var info = document.getElementById('coverageInfo');
      if (info) info.textContent = d.rows.length + ' строк · ' + d.horizons.length + ' горизонтов · '
        + d.methods.length + ' методов';
      if (!d.rows.length) {
        host.innerHTML = '<p style="color:#8b949e">Нет горизонтов. Загрузите отбивки (Tops), чтобы построить охват по горизонтам.</p>';
        return;
      }
      var h = '<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:12px;white-space:nowrap">';
      h += '<tr style="color:#8b949e;border-bottom:1px solid #30363d">'
        + '<th style="text-align:left;padding:6px 8px">Скважина</th>'
        + '<th style="text-align:left;padding:6px 8px">Горизонт</th>'
        + '<th style="padding:6px 8px">Кровля</th><th style="padding:6px 8px">Подошва</th>'
        + '<th style="padding:6px 8px">Мощн.</th><th style="padding:6px 8px">Методов</th>';
      d.methods.forEach(function (m) {
        h += '<th title="' + esc(m.name) + '" style="padding:6px 6px">' + esc(m.abbr) + '</th>';
      });
      h += '</tr>';
      d.rows.forEach(function (r) {
        h += '<tr style="border-bottom:1px solid #21262d">'
          + '<td style="padding:5px 8px;color:#c9d1d9">' + esc(r.well_name) + '</td>'
          + '<td style="padding:5px 8px;color:#c9d1d9">' + esc(r.horizon) + '</td>'
          + '<td style="padding:5px 8px;text-align:right;color:#8b949e">' + r.top + '</td>'
          + '<td style="padding:5px 8px;text-align:right;color:#8b949e">' + r.base + '</td>'
          + '<td style="padding:5px 8px;text-align:right;color:#8b949e">' + r.thickness + '</td>'
          + '<td style="padding:5px 8px;text-align:center;color:#58a6ff">' + r.methods_count + '</td>';
        d.methods.forEach(function (m) {
          var c = r.methods[m.key];
          if (!c) { h += '<td style="text-align:center;color:#30363d">·</td>'; return; }
          var pct = Math.round(c.coverage * 100);
          var multi = c.curves > 1;
          h += '<td title="' + esc(c.mnemonics.join(', ')) + '" style="text-align:center;padding:4px 6px;'
            + 'background:' + (multi ? 'rgba(240,180,41,.30)' : 'rgba(46,204,113,.20)') + ';color:#c9d1d9">'
            + (multi ? '+' + c.curves : '+') + ' <span style="color:#8b949e">' + pct + '%</span></td>';
        });
        h += '</tr>';
      });
      h += '</table></div>';
      h += '<p style="color:#6e7681;font-size:12px;margin-top:8px">'
        + '«+» — метод есть в интервале горизонта, «+N» — N кривых этого метода (жёлтый), % — доля мощности горизонта, покрытая записью.</p>';
      host.innerHTML = h;
    },

    exportHorizons: function (fmt) {
      var pid = projectId();
      if (!pid) { GeoToast.warn('Откройте проект'); return; }
      var url = '/api/projects/' + pid + '/coverage-by-horizon/export?fmt=' + (fmt || 'csv');
      var a = document.createElement('a');
      a.href = url; a.download = '';
      document.body.appendChild(a); a.click(); a.remove();
      GeoToast.success('Экспорт охвата по горизонтам (' + (fmt || 'csv').toUpperCase() + ')');
    }
  };
})();
