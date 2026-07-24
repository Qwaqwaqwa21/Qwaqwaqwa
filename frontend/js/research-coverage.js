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

    async load() {
      var pid = projectId();
      var host = document.getElementById('coverageContent');
      if (!pid) {
        if (host) host.innerHTML = '<p style="color:#8b949e">Open a project first.</p>';
        return;
      }
      if (host) host.innerHTML = '<p style="color:#8b949e">Computing coverage…</p>';
      try {
        this.data = await app._api('/projects/' + pid + '/research-coverage?depth_bins=24');
      } catch (e) {
        if (host) host.innerHTML = '<p style="color:#f85149">Failed to load coverage: ' + (e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render() {
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
    }
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
})();
