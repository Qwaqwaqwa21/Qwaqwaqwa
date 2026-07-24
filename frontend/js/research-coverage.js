/*
 * Research Coverage Map (карта охвата исследованиями)
 * Renders a wells x logging-methods heatmap showing how well each survey type
 * covers each well in the active project. Backed by
 *   GET /api/projects/{pid}/research-coverage
 */
(function () {
  var CATEGORY_LABEL = {
    potential: 'Potential', nuclear: 'Nuclear', mechanical: 'Mechanical',
    electrical: 'Electrical', acoustic: 'Acoustic', auxiliary: 'Auxiliary',
    derived: 'Derived / interpreted'
  };

  function projectId() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && a.projects && a.projects[0]) ? a.projects[0].id : null;
  }

  // Blue → green ramp for a 0..1 score. Absent cells get a neutral slot color.
  function heat(v) {
    if (v == null) return 'transparent';
    var t = Math.max(0, Math.min(1, v));
    var r = Math.round(30 + (46 - 30) * t);
    var g = Math.round(60 + (204 - 60) * t);
    var b = Math.round(90 + (113 - 90) * (1 - t) + 40 * (1 - t));
    var a = 0.18 + 0.72 * t;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(3) + ')';
  }

  window.ResearchCoverageView = {
    data: null,
    logData: null,

    _viewMode() {
      return (document.getElementById('coverageViewMode') || {}).value || 'matrix';
    },

    switchMode() {
      var planshet = this._viewMode() === 'planshet';
      var mc = document.getElementById('coverageMatrixControls');
      if (mc) mc.style.display = planshet ? 'none' : 'contents';
      this.load();
    },

    async load() {
      var pid = projectId();
      var host = document.getElementById('coverageContent');
      if (!pid) {
        if (host) host.innerHTML = '<p style="color:#8b949e">Open a project first.</p>';
        return;
      }
      if (host) host.innerHTML = '<p style="color:#8b949e">Computing coverage…</p>';
      try {
        if (this._viewMode() === 'planshet') {
          this.logData = await app._api('/projects/' + pid + '/coverage-log?bins=200');
        } else {
          this.data = await app._api('/projects/' + pid + '/research-coverage?depth_bins=24');
        }
      } catch (e) {
        if (host) host.innerHTML = '<p style="color:#f85149">Failed to load coverage: ' + (e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render() {
      if (this._viewMode() === 'planshet') return this.renderPlanshet();
      return this.renderMatrix();
    },

    renderMatrix() {
      var host = document.getElementById('coverageContent');
      var data = this.data;
      if (!host || !data) return;
      var mode = (document.getElementById('coverageMode') || {}).value || 'coverage';
      var group = (document.getElementById('coverageGroup') || {}).value || 'category';
      var measuredOnly = !!(document.getElementById('coverageMeasuredOnly') || {}).checked;

      // Only show methods that appear in at least one well.
      var methods = data.methods.filter(function (m) {
        return m.wells_present > 0 && (!measuredOnly || !m.derived);
      });
      var info = document.getElementById('coverageInfo');
      if (info) info.textContent = data.well_count + ' wells · ' + methods.length + ' methods logged';

      if (!methods.length) {
        host.innerHTML = '<p style="color:#8b949e">No recognized logging methods found in this project.</p>';
        return;
      }

      // Optionally order/group columns by category.
      if (group === 'category') {
        methods.sort(function (a, b) {
          if (a.category === b.category) return a.name.localeCompare(b.name);
          return a.category.localeCompare(b.category);
        });
      }

      var valOf = function (cell) {
        if (!cell || !cell.present) return null;
        if (mode === 'presence') return 1;
        if (mode === 'fill') return cell.fill != null ? cell.fill : cell.coverage;
        return cell.coverage;
      };

      var html = '';
      html += '<div style="overflow-x:auto">';
      html += '<table class="coverage-table" style="border-collapse:collapse;font-size:12px;min-width:100%">';

      // Category group header
      if (group === 'category') {
        var spans = [];
        methods.forEach(function (m) {
          var last = spans[spans.length - 1];
          if (last && last.cat === m.category) last.n++;
          else spans.push({ cat: m.category, n: 1 });
        });
        html += '<tr><th style="text-align:left;padding:4px 8px"></th>';
        spans.forEach(function (s) {
          html += '<th colspan="' + s.n + '" style="padding:4px 6px;text-align:center;color:#8b949e;'
               + 'border-bottom:1px solid #30363d;font-weight:600">' + (CATEGORY_LABEL[s.cat] || s.cat) + '</th>';
        });
        html += '</tr>';
      }

      // Method header row
      html += '<tr><th style="text-align:left;padding:6px 8px;position:sticky;left:0;background:#0d1117;z-index:1">Well \\ Method</th>';
      methods.forEach(function (m) {
        html += '<th title="' + m.name + '" style="padding:6px 4px;white-space:nowrap;border-bottom:1px solid #30363d">'
             + '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + m.color + ';margin-right:3px"></span>'
             + m.key + '</th>';
      });
      html += '</tr>';

      // Well rows
      data.wells.forEach(function (w) {
        html += '<tr>';
        html += '<td style="padding:5px 8px;white-space:nowrap;position:sticky;left:0;background:#0d1117;z-index:1">'
             + '<strong>' + escapeHtml(w.well_name) + '</strong>'
             + '<span style="color:#8b949e;margin-left:6px">' + w.methods_present + '</span></td>';
        methods.forEach(function (m) {
          var cell = w.cells[m.key];
          var v = valOf(cell);
          var label = '';
          var title = w.well_name + ' · ' + m.name;
          if (cell && cell.present) {
            var pct = Math.round((mode === 'fill' ? (cell.fill != null ? cell.fill : cell.coverage) : cell.coverage) * 100);
            label = mode === 'presence' ? '●' : pct + '%';
            title += '\ncoverage ' + Math.round(cell.coverage * 100) + '%'
                  + (cell.fill != null ? ' · fill ' + Math.round(cell.fill * 100) + '%' : '')
                  + (cell.depth_top != null ? '\n' + cell.depth_top + '–' + cell.depth_bottom : '')
                  + (cell.mnemonics ? '\n' + cell.mnemonics.join(', ') : '');
          } else {
            label = '·';
            title += '\nnot logged';
          }
          html += '<td title="' + escapeHtml(title) + '" style="text-align:center;padding:5px 4px;'
               + 'background:' + heat(v) + ';color:' + (v != null && v > 0.5 ? '#0d1117' : '#c9d1d9') + ';'
               + 'border:1px solid rgba(48,54,61,0.5)">' + label + '</td>';
        });
        html += '</tr>';
      });
      html += '</table></div>';

      // Method completeness summary
      html += '<div style="margin-top:16px"><h4 style="margin:0 0 8px;color:#c9d1d9">Method completeness across project</h4>';
      methods.slice().sort(function (a, b) { return b.completeness - a.completeness; }).forEach(function (m) {
        var pct = Math.round(m.completeness * 100);
        html += '<div style="display:flex;align-items:center;gap:8px;margin:3px 0">'
             + '<span style="width:150px;color:#c9d1d9">' + m.name + '</span>'
             + '<div style="flex:1;max-width:320px;background:#161b22;border-radius:4px;overflow:hidden;height:14px">'
             + '<div style="width:' + pct + '%;height:100%;background:' + m.color + '"></div></div>'
             + '<span style="color:#8b949e;width:90px">' + m.wells_present + '/' + data.well_count + ' (' + pct + '%)</span>'
             + '</div>';
      });
      html += '</div>';

      host.innerHTML = html;
    },

    // Correlation-style planshet: shared depth axis, one filled column per
    // method per well, coloured where valid data exists at that depth.
    renderPlanshet() {
      var host = document.getElementById('coverageContent');
      var data = this.logData;
      if (!host || !data) return;
      var cols = data.columns || [];
      var wells = data.wells || [];
      var info = document.getElementById('coverageInfo');
      if (info) info.textContent = wells.length + ' wells · ' + cols.length + ' methods · '
        + data.depth_top + '–' + data.depth_bottom;
      if (!cols.length || !wells.length) {
        host.innerHTML = '<p style="color:#8b949e">No recognized method data to plot.</p>';
        return;
      }

      var AXIS_W = 62, COL_W = 13, WELL_PAD = 18, HDR = 96, TOP = 8, BOT = 24;
      var wellW = cols.length * COL_W + WELL_PAD;
      var plotH = 720;
      var totalW = AXIS_W + wells.length * wellW + 16;
      var totalH = HDR + plotH + BOT;

      host.innerHTML = '<div style="overflow-x:auto"><canvas id="coverageLogCanvas"></canvas></div>'
        + this._planshetLegend(cols);
      var canvas = document.getElementById('coverageLogCanvas');
      var dpr = window.devicePixelRatio || 1;
      canvas.style.width = totalW + 'px';
      canvas.style.height = totalH + 'px';
      canvas.width = totalW * dpr;
      canvas.height = totalH * dpr;
      var ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      ctx.textBaseline = 'middle';
      ctx.font = '11px system-ui, sans-serif';

      var top = data.depth_top, bot = data.depth_bottom, span = bot - top || 1;
      var y0 = HDR, y1 = HDR + plotH;
      var depthToY = function (d) { return y0 + (d - top) / span * (y1 - y0); };

      // Depth axis grid + labels
      ctx.strokeStyle = '#30363d';
      ctx.fillStyle = '#8b949e';
      ctx.lineWidth = 1;
      var ticks = 10;
      for (var t = 0; t <= ticks; t++) {
        var d = top + span * t / ticks;
        var y = depthToY(d);
        ctx.beginPath(); ctx.moveTo(AXIS_W, y); ctx.lineTo(totalW - 8, y); ctx.stroke();
        ctx.fillText(Math.round(d).toString(), 6, y);
      }

      // Per-well column groups
      wells.forEach(function (w, wi) {
        var wx = AXIS_W + wi * wellW + WELL_PAD / 2;
        // well name header
        ctx.save();
        ctx.fillStyle = '#c9d1d9';
        ctx.font = '600 12px system-ui, sans-serif';
        ctx.translate(wx + (cols.length * COL_W) / 2, HDR - 8);
        var label = w.well_name || ('Well ' + w.well_id);
        var maxLbl = cols.length * COL_W + 8;
        // rotate long labels
        if (ctx.measureText(label).width > maxLbl) {
          ctx.rotate(-Math.PI / 5);
          ctx.textAlign = 'left';
          ctx.fillText(label, -maxLbl / 2, 0);
        } else {
          ctx.textAlign = 'center';
          ctx.fillText(label, 0, 0);
        }
        ctx.restore();

        // separator between wells
        if (wi > 0) {
          ctx.strokeStyle = '#21262d';
          ctx.beginPath();
          ctx.moveTo(AXIS_W + wi * wellW, y0 - 4);
          ctx.lineTo(AXIS_W + wi * wellW, y1);
          ctx.stroke();
        }

        cols.forEach(function (col, ci) {
          var cx = wx + ci * COL_W;
          // column background
          ctx.fillStyle = '#0d1117';
          ctx.fillRect(cx, y0, COL_W - 2, y1 - y0);
          ctx.strokeStyle = '#161b22';
          ctx.strokeRect(cx + 0.5, y0 + 0.5, COL_W - 3, y1 - y0 - 1);
          // method header tick (small colored square + key rotated)
          ctx.fillStyle = col.color;
          ctx.fillRect(cx, HDR - 4, COL_W - 2, 3);

          var arr = w.present && w.present[col.key];
          if (!arr) return;
          var n = arr.length;
          var binH = (y1 - y0) / n;
          ctx.fillStyle = col.color;
          // draw contiguous filled runs for crisp columns
          var runStart = -1;
          for (var i = 0; i <= n; i++) {
            var on = i < n && arr[i];
            if (on && runStart < 0) runStart = i;
            if (!on && runStart >= 0) {
              var ry = y0 + runStart * binH;
              var rh = (i - runStart) * binH;
              ctx.fillRect(cx, ry, COL_W - 2, Math.max(1, rh));
              runStart = -1;
            }
          }
        });
      });

      // axis title
      ctx.fillStyle = '#8b949e';
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('Depth', 6, HDR - 10);
    },

    _planshetLegend(cols) {
      var items = cols.map(function (c) {
        return '<span style="display:inline-flex;align-items:center;gap:5px;margin:3px 10px 3px 0;color:#c9d1d9">'
          + '<span style="width:11px;height:11px;border-radius:2px;background:' + c.color + '"></span>'
          + c.key + ' — ' + c.name + '</span>';
      }).join('');
      return '<div style="margin-top:12px;font-size:12px;display:flex;flex-wrap:wrap">' + items + '</div>';
    }
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
})();
