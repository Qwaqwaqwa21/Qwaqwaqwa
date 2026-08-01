/*
 * Full-curve duplicate check (проверка кривых на полное дублирование).
 * Finds pairs of curves whose values match exactly on their shared depth
 * interval — a copy/paste export mistake, not just numerically-similar
 * curves from the same logging family. Backed by
 *   GET /api/wells/{wid}/duplicate-curves
 *   GET /api/projects/{pid}/duplicate-curves
 *
 * Additionally, when scope is "project", also runs the coarser study-level
 * (metadata) duplicate check — same well/площадь + overlapping depth range +
 * overlapping methods, catches a study re-digitized or re-entered under a
 * different well, which the byte-exact curve check above misses. Backed by
 *   GET /api/projects/{pid}/duplicate-studies
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

  function studyLabel(side) {
    var depth = (side.start_depth != null && side.stop_depth != null)
      ? side.start_depth + '–' + side.stop_depth : '?';
    return escapeHtml(side.name)
      + (side.field_name ? ' <span style="color:#6e7681">(' + escapeHtml(side.field_name) + ')</span>' : '')
      + ' <span style="color:#6e7681">/ рейс ' + side.run_number + ' (run ' + side.run_id + ') / '
      + escapeHtml(side.filename || '') + '</span><br><span style="color:#8b949e;font-size:12px">'
      + depth + ' м, ' + escapeHtml(side.digitization_status || '') + '</span>';
  }

  var REASON_LABELS = {
    same_well: 'тот же well, повторная загрузка',
    cross_well_same_name: 'разные скважины, одинаковое имя',
    cross_well_similar_field: 'разные скважины, одна площадь'
  };

  window.DuplicatesView = {
    data: null,
    studyData: null,

    async load() {
      var host = document.getElementById('duplicatesContent');
      var info = document.getElementById('dupInfo');
      var scope = (document.getElementById('dupScope') || {}).value || 'well';
      var studiesSection = document.getElementById('dupStudiesSection');
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

      if (scope === 'project') {
        if (studiesSection) studiesSection.style.display = '';
        await this.loadStudies();
      } else {
        if (studiesSection) studiesSection.style.display = 'none';
        this.studyData = null;
      }
    },

    async loadStudies() {
      var host = document.getElementById('dupStudiesContent');
      var info = document.getElementById('dupStudiesInfo');
      if (host) host.innerHTML = '<p style="color:#8b949e">Проверка…</p>';
      if (info) info.textContent = '';

      var pid = currentProjectId();
      if (!pid) { this.studyData = null; this.renderStudies('Нет проекта'); return; }

      try {
        this.studyData = await app._api('/projects/' + pid + '/duplicate-studies');
      } catch (e) {
        this.studyData = null;
        this.renderStudies('Ошибка: ' + (e.message || e));
        return;
      }
      this.renderStudies();
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
    },

    renderStudies(errorMsg) {
      var host = document.getElementById('dupStudiesContent');
      var info = document.getElementById('dupStudiesInfo');
      if (!host) return;
      if (errorMsg) { host.innerHTML = '<p style="color:#8b949e">' + escapeHtml(errorMsg) + '</p>'; return; }
      var d = this.studyData;
      if (!d) { host.innerHTML = '<p style="color:#8b949e">Нет данных.</p>'; return; }

      var scopeLabel = d.well_count + ' скв. · ' + d.study_count + ' исследований · ' + d.duplicate_count + ' дублей'
        + (d.cross_well_duplicate_count ? ' (' + d.cross_well_duplicate_count + ' между скважинами)' : '');
      if (info) info.textContent = scopeLabel;

      if (!d.duplicates || !d.duplicates.length) {
        host.innerHTML = '<p style="color:#3fb950">Дублей исследований не найдено.</p>';
        return;
      }

      var html = '<table style="border-collapse:collapse;width:100%;font-size:13px">';
      html += '<tr style="text-align:left;color:#8b949e;border-bottom:1px solid #30363d">'
        + '<th style="padding:6px 8px">Скважина А</th><th style="padding:6px 8px">Скважина Б</th>'
        + '<th style="padding:6px 8px">Пересеч. глубин</th><th style="padding:6px 8px">Пересеч. методов</th>'
        + '<th style="padding:6px 8px">Общие методы</th><th style="padding:6px 8px">Причина</th></tr>';
      d.duplicates.forEach(function (dup) {
        html += '<tr style="border-bottom:1px solid #21262d">';
        html += '<td style="padding:6px 8px">' + studyLabel(dup.well_a) + '</td>';
        html += '<td style="padding:6px 8px">' + studyLabel(dup.well_b) + '</td>';
        html += '<td style="padding:6px 8px">' + (dup.depth_overlap_fraction * 100).toFixed(1) + '%</td>';
        html += '<td style="padding:6px 8px">' + (dup.method_overlap_fraction * 100).toFixed(1) + '%</td>';
        html += '<td style="padding:6px 8px;font-family:monospace;color:#58a6ff">' + escapeHtml((dup.shared_methods || []).join(', ')) + '</td>';
        html += '<td style="padding:6px 8px">' + (dup.cross_well ? '<span style="color:#f85149">' : '<span style="color:#d29922">')
          + escapeHtml(REASON_LABELS[dup.reason] || dup.reason) + '</span></td>';
        html += '</tr>';
      });
      html += '</table>';
      html += '<p style="color:#6e7681;margin-top:10px;font-size:12px">Грубая проверка на уровне исследования: '
        + 'совпадение скважины/площади, пересечение интервала глубин и общих методов каротажа — ловит повторную '
        + 'оцифровку того же рейса или скважину, заведённую дважды под разными именами. Не заменяет проверку кривых выше.</p>';
      host.innerHTML = html;
    }
  };
})();
