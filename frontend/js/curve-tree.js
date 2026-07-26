/*
 * ДЕРЕВО КРИВЫХ выбранной скважины: рейс → кривые с интервалом глубин.
 *
 * Здесь же — переименование рейса, удаление рейса и удаление отдельной кривой
 * из проекта, а также выбор рейсов, которые показываются на планшете
 * одновременно (галочки).
 */
(function () {
  function app() { return (typeof window.app !== 'undefined') ? window.app : null; }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function toast(kind, msg) {
    if (typeof GeoToast !== 'undefined' && GeoToast[kind]) GeoToast[kind](msg);
  }
  function fmt(v) {
    return (v == null || !isFinite(v)) ? '—' : Math.round(v);
  }

  var KIND_LABEL = { gis: 'ГИС', rigis: 'РИГИС', inkl: 'ИНКЛ', other: 'прочее' };

  window.CurveTree = {
    data: null,
    wellId: null,
    open: {},          // id рейса -> развёрнут
    shown: {},         // id рейса -> показывать на планшете

    load: async function (wellId) {
      var a = app();
      if (!a || !wellId) return;
      this.wellId = wellId;
      try {
        this.data = await a._api('/wells/' + wellId + '/curve-tree');
      } catch (e) {
        this.data = null;
      }
      var self = this;
      if (this.data) {
        // По умолчанию на планшет выводятся ВСЕ рейсы скважины: иначе виден
        // только первый, и кажется, что остальной каротаж не загрузился.
        var known = {};
        this.data.runs.forEach(function (r) {
          known[r.id] = true;
          if (self.shown[r.id] === undefined) self.shown[r.id] = true;
        });
        Object.keys(this.shown).forEach(function (k) { if (!known[k]) delete self.shown[k]; });
      }
      this.render();
    },

    shownRunIds: function () {
      var self = this;
      if (!this.data) return [];
      return this.data.runs.filter(function (r) { return self.shown[r.id]; })
        .map(function (r) { return r.id; });
    },

    render: function () {
      var host = document.getElementById('curveTreeContent');
      if (!host) return;
      var d = this.data;
      if (!d) { host.innerHTML = '<div class="ct-empty">Выберите скважину</div>'; return; }

      var self = this;
      var h = '<div class="ct-well">' + esc(d.well)
        + ' <span class="ct-dim">' + esc(d.depth_unit) + '</span>'
        + (d.elevation != null ? ' <span class="ct-dim">альт. ' + fmt(d.elevation) + '</span>' : '')
        + '</div>';
      h += '<div class="ct-inkl' + (d.has_inclinometry ? '' : ' ct-inkl-off') + '">'
        + (d.has_inclinometry
          ? 'ИНКЛ: ' + d.inclinometry_points + ' замеров → TVD'
          : 'ИНКЛ нет — скважина считается вертикальной')
        + '</div>';

      if (!d.runs.length) {
        h += '<div class="ct-empty">Нет загруженного каротажа</div>';
      } else {
        h += '<div class="ct-bulk">На планшет: '
          + '<a href="#" data-all="1">все</a> · <a href="#" data-none="1">ни одного</a>'
          + '<div class="ct-hint">Активный рейс рисуется сплошной линией, остальные — '
          + 'пунктиром (у каждого свой рисунок штриха). Цвет всегда цвет метода.</div></div>';
      }
      d.runs.forEach(function (r) {
        var isOpen = !!self.open[r.id];
        h += '<div class="ct-run">'
          + '<div class="ct-run-hd">'
          + '<input type="checkbox" class="ct-show" data-show="' + r.id + '"'
          + (self.shown[r.id] ? ' checked' : '') + ' title="Показывать на планшете">'
          + '<span class="ct-caret" data-toggle="' + r.id + '">' + (isOpen ? '▾' : '▸') + '</span>'
          + '<span class="ct-run-name" data-toggle="' + r.id + '">' + esc(r.name) + '</span>'
          + '<span class="ct-kind">' + esc(KIND_LABEL[r.kind] || r.kind) + '</span>'
          + '<span class="ct-count">' + r.curves.length + '</span>'
          + '<button class="ct-btn" data-rename="' + r.id + '" title="Переименовать рейс">✎</button>'
          + '<button class="ct-btn ct-btn-del" data-delrun="' + r.id + '" title="Удалить рейс">✕</button>'
          + '</div>';
        if (isOpen) {
          h += '<div class="ct-range">' + fmt(r.start_depth) + '–' + fmt(r.stop_depth) + ' ' + esc(r.depth_unit) + '</div>';
          if (!r.curves.length) h += '<div class="ct-empty">нет кривых</div>';
          r.curves.forEach(function (c) {
            h += '<div class="ct-curve' + (c.empty ? ' ct-curve-empty' : '') + '" title="'
              + esc(c.method_name || c.description || c.mnemonic) + '">'
              + '<span class="ct-dot" style="background:' + esc(c.color || '#8b949e') + '"></span>'
              + '<span class="ct-mnem">' + esc(c.mnemonic) + '</span>'
              + '<span class="ct-meth">' + esc(c.method || '—') + '</span>'
              + '<span class="ct-depth">' + (c.empty ? 'пусто' : fmt(c.top) + '–' + fmt(c.base)) + '</span>'
              + '<button class="ct-btn ct-btn-del" data-delcurve="' + r.id + '|' + encodeURIComponent(c.mnemonic)
              + '" title="Удалить кривую из проекта">✕</button>'
              + '</div>';
          });
        }
        h += '</div>';
      });
      host.innerHTML = h;

      host.querySelectorAll('[data-toggle]').forEach(function (el) {
        el.onclick = function () {
          var id = el.getAttribute('data-toggle');
          self.open[id] = !self.open[id];
          self.render();
        };
      });
      var setAll = function (v) {
        return function (e) {
          e.preventDefault();
          self.data.runs.forEach(function (r) { self.shown[r.id] = v; });
          self.render();
          if (app() && app().renderShownRuns) app().renderShownRuns();
        };
      };
      var allEl = host.querySelector('[data-all]');
      if (allEl) allEl.onclick = setAll(true);
      var noneEl = host.querySelector('[data-none]');
      if (noneEl) noneEl.onclick = setAll(false);

      host.querySelectorAll('[data-show]').forEach(function (el) {
        el.onchange = function () {
          self.shown[el.getAttribute('data-show')] = el.checked;
          if (app() && app().renderShownRuns) app().renderShownRuns();
        };
      });
      host.querySelectorAll('[data-rename]').forEach(function (b) {
        b.onclick = function (e) { e.stopPropagation(); self.rename(parseInt(b.getAttribute('data-rename'), 10)); };
      });
      host.querySelectorAll('[data-delrun]').forEach(function (b) {
        b.onclick = function (e) { e.stopPropagation(); self.deleteRun(parseInt(b.getAttribute('data-delrun'), 10)); };
      });
      host.querySelectorAll('[data-delcurve]').forEach(function (b) {
        b.onclick = function (e) {
          e.stopPropagation();
          var parts = b.getAttribute('data-delcurve').split('|');
          self.deleteCurve(parseInt(parts[0], 10), decodeURIComponent(parts[1]));
        };
      });
    },

    rename: async function (runId) {
      var run = (this.data.runs || []).filter(function (r) { return r.id === runId; })[0];
      if (!run) return;
      var name = window.prompt('Имя рейса (например ГИС_С1, РИГИС, ИНКЛ):', run.name);
      if (name == null) return;
      name = name.trim();
      if (!name) return;
      try {
        await app()._api('/runs/' + runId, { method: 'PATCH', body: JSON.stringify({ name: name }) });
        toast('success', 'Рейс переименован');
        await this.load(this.wellId);
        var a = app();
        if (a && a.currentWell) await a.selectWell(a.currentWell.id);
      } catch (e) { toast('error', 'Не удалось переименовать: ' + (e.message || e)); }
    },

    deleteRun: async function (runId) {
      var run = (this.data.runs || []).filter(function (r) { return r.id === runId; })[0];
      if (!run) return;
      if (!window.confirm('Удалить рейс «' + run.name + '» со всеми кривыми?')) return;
      try {
        await app()._api('/runs/' + runId, { method: 'DELETE' });
        toast('success', 'Рейс удалён');
        await this.load(this.wellId);
        var a = app();
        if (a && a.currentWell) await a.selectWell(a.currentWell.id);
      } catch (e) { toast('error', 'Не удалось удалить: ' + (e.message || e)); }
    },

    deleteCurve: async function (runId, mnemonic) {
      if (!window.confirm('Удалить кривую ' + mnemonic + ' из проекта?')) return;
      try {
        await app()._api('/runs/' + runId + '/curves/' + encodeURIComponent(mnemonic), { method: 'DELETE' });
        toast('success', 'Кривая удалена');
        await this.load(this.wellId);
        var a = app();
        if (a && a.currentWell) await a.selectWell(a.currentWell.id);
      } catch (e) { toast('error', 'Не удалось удалить: ' + (e.message || e)); }
    },
  };
})();
