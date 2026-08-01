/*
 * Full-curve duplicate check (проверка кривых на полное дублирование).
 * Finds pairs of curves whose values match exactly on their shared depth
 * interval — a copy/paste export mistake, not just numerically-similar
 * curves from the same logging family. Backed by
 *   GET /api/wells/{wid}/duplicate-curves
 *   GET /api/projects/{pid}/duplicate-curves
 */
(function () {
  function currentWellId() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && a.currentWell) ? a.currentWell.id : null;
  }

  function currentProjectId() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && a.projects && a.projects.length) ? a.projects[0].id : null;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function curveLabel(side) {
    return escapeHtml(side.name) + ' <span style="color:#6e7681">/ run ' + side.run_id + ' / '
      + escapeHtml(side.filename || '') + '</span> — <span style="color:#58a6ff;font-family:monospace">'
      + escapeHtml(side.mnemonic) + '</span>' + (side.unit ? ' <span style="color:#6e7681">[' + escapeHtml(side.unit) + ']</span>' : '');
  }

  window.DuplicatesView = {
    data: null,

    async load() {
      var host = document.getElementById('duplicatesContent');
      var info = document.getElementById('dupInfo');
      var scope = (document.getElementById('dupScope') || {}).value || 'well';
      if (host) host.innerHTML = '<p style="color:#8b949e">Проверка…</p>';
      if (info) info.textContent = '';

      try {
        if (scope === 'project') {
          var pid = currentProjectId();
          if (!pid) { this.data = null; this.render('Нет проекта'); return; }
          this.data = await app._api('/projects/' + pid + '/duplicate-curves');
        } else {
          var wid = currentWellId();
          if (!wid) { this.data = null; this.render('Выберите скважину'); return; }
          this.data = await app._api('/wells/' + wid + '/duplicate-curves');
        }
      } catch (e) {
        this.data = null;
        this.render('Ошибка: ' + (e.message || e));
        return;
      }
      this.render();
    },

    render(errorMsg) {
      var host = document.getElementById('duplicatesContent');
      var info = document.getElementById('dupInfo');
      if (!host) return;
      if (errorMsg) { host.innerHTML = '<p style="color:#8b949e">' + escapeHtml(errorMsg) + '</p>'; return; }
      var d = this.data;
      if (!d) { host.innerHTML = '<p style="color:#8b949e">Нет данных.</p>'; return; }

      var scopeLabel = d.project_id != null
        ? (d.well_count + ' скв. · ' + d.curve_count + ' кривых · ' + d.duplicate_count + ' дублей'
           + (d.cross_well_duplicate_count ? ' (' + d.cross_well_duplicate_count + ' между скважинами)' : ''))
        : (d.curve_count + ' кривых · ' + d.duplicate_count + ' дублей');
      if (info) info.textContent = scopeLabel;

      if (!d.duplicates || !d.duplicates.length) {
        host.innerHTML = '<p style="color:#3fb950">Дублей не найдено'
          + (d.well_name ? ' (скважина ' + escapeHtml(d.well_name) + ')' : '') + '.</p>';
        return;
      }

      var html = '<table style="border-collapse:collapse;width:100%;font-size:13px">';
      html += '<tr style="text-align:left;color:#8b949e;border-bottom:1px solid #30363d">'
        + '<th style="padding:6px 8px">Кривая А</th><th style="padding:6px 8px">Кривая Б</th>'
        + '<th style="padding:6px 8px">Совпало точек</th><th style="padding:6px 8px">Покрытие</th>'
        + '<th style="padding:6px 8px">Между скважинами</th></tr>';
      d.duplicates.forEach(function (dup) {
        html += '<tr style="border-bottom:1px solid #21262d">';
        html += '<td style="padding:6px 8px">' + curveLabel(dup.well_a) + '</td>';
        html += '<td style="padding:6px 8px">' + curveLabel(dup.well_b) + '</td>';
        html += '<td style="padding:6px 8px">' + dup.overlap_points + '</td>';
        html += '<td style="padding:6px 8px">' + (dup.coverage * 100).toFixed(1) + '%</td>';
        html += '<td style="padding:6px 8px">' + (dup.cross_well
          ? '<span style="color:#f85149">да</span>' : '<span style="color:#6e7681">нет</span>') + '</td>';
        html += '</tr>';
      });
      html += '</table>';
      html += '<p style="color:#6e7681;margin-top:10px;font-size:12px">Совпадение фиксируется только там, где '
        + 'обе кривые имеют реальные (не NULL) значения на общем интервале глубин — случайные совпадения на '
        + 'пустых участках не считаются.</p>';
      host.innerHTML = html;
    }
  };
})();
