/*
 * ЦЕНТР ИМПОРТА — одно окно на все виды данных.
 *
 * Каждая строка: что импортируем → выбрать файл(ы) → «Выполнить» → отчёт.
 * ГИС берётся папкой целиком (вместе с подпапками): скважина определяется из
 * шапки LAS, имя рейса — из папки, инклинометрия уходит в замеры, а не в рейс.
 */
(function () {
  function app() { return (typeof window.app !== 'undefined') ? window.app : null; }
  function pid() {
    var a = app();
    return (a && a.projects && a.projects[0]) ? a.projects[0].id : null;
  }
  function role() {
    var a = app();
    return (a && a.currentRole) || 'viewer';
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function toast(kind, msg) {
    if (typeof GeoToast !== 'undefined' && GeoToast[kind]) GeoToast[kind](msg);
  }

  // Разделы окна. accept/dir задают поведение выбора файлов.
  var SECTIONS = [
    {
      key: 'las', title: 'ГИС / РИГИС — каротаж (LAS)',
      hint: 'Папка обходится рекурсивно вместе с подпапками; можно выбрать и отдельные файлы. '
          + 'Скважина берётся из шапки LAS, имя рейса — из папки (для отдельных файлов — из имени файла).',
      accept: '.las,.LAS', dir: true, multiple: true, alsoFiles: true,
    },
    {
      key: 'tops', title: 'Отбивки (горизонты)',
      hint: 'Excel или CSV на весь проект: скважина | горизонт | кровля | подошва.',
      accept: '.xlsx,.xlsm,.csv', dir: false, multiple: false,
    },
    {
      key: 'coords', title: 'Координаты и альтитуды',
      hint: 'Excel или CSV: скважина | X | Y | альтитуда. Если координат нет в шапке LAS.',
      accept: '.xlsx,.xlsm,.csv', dir: false, multiple: false,
    },
    {
      key: 'mnemonics', title: 'Пользовательские мнемоники',
      hint: 'Excel или CSV: мнемоника | метод. Дополняет встроенный справочник.',
      accept: '.xlsx,.xlsm,.csv', dir: false, multiple: false,
    },
  ];

  window.ImportCenter = {
    files: {},        // key -> FileList
    busy: false,

    open: async function () {
      var a = app();
      if (!a) return;
      if (!pid() && a._ensureDefaultProject) { try { await a._ensureDefaultProject(); } catch (e) {} }
      var m = document.getElementById('importCenterModal');
      if (!m) return;
      m.style.display = 'flex';
      this.render();
    },

    close: function (ev) {
      if (ev && ev.target !== ev.currentTarget) return;
      var m = document.getElementById('importCenterModal');
      if (m) m.style.display = 'none';
    },

    render: function () {
      var host = document.getElementById('importCenterBody');
      if (!host) return;
      var self = this;
      var h = '';
      SECTIONS.forEach(function (s) {
        var picked = self.files[s.key];
        var label = !picked || !picked.length
          ? 'файл не выбран'
          : (picked.length === 1 ? picked[0].name : picked.length + ' файл(ов)');
        h += '<div class="imp-row" data-key="' + s.key + '">'
          + '<div class="imp-main">'
          + '<div class="imp-title">' + esc(s.title) + '</div>'
          + '<div class="imp-hint">' + esc(s.hint) + '</div>'
          + '<div class="imp-file" id="impFile_' + s.key + '">' + esc(label) + '</div>'
          + '</div>'
          + '<div class="imp-actions">'
          + (s.alsoFiles
              ? '<button class="btn-sm" data-pickdir="' + s.key + '">Папку…</button>'
                + '<button class="btn-sm" data-pick="' + s.key + '">Файлы…</button>'
              : '<button class="btn-sm" data-pick="' + s.key + '">Выбрать…</button>')
          + '<button class="btn-sm btn-primary-action" data-run="' + s.key + '">Выполнить</button>'
          + '</div>'
          + '<div class="imp-result" id="impRes_' + s.key + '"></div>'
          + '</div>';
      });
      host.innerHTML = h;

      host.querySelectorAll('[data-pick]').forEach(function (b) {
        b.onclick = function () { self.pick(b.getAttribute('data-pick'), false); };
      });
      host.querySelectorAll('[data-pickdir]').forEach(function (b) {
        b.onclick = function () { self.pick(b.getAttribute('data-pickdir'), true); };
      });
      host.querySelectorAll('[data-run]').forEach(function (b) {
        b.onclick = function () { self.run(b.getAttribute('data-run')); };
      });
    },

    /* Диалог выбора обязан открываться синхронно внутри обработчика клика,
       иначе браузер считает жест пользователя потерянным и молча его игнорирует. */
    pick: function (key, asDirectory) {
      var s = SECTIONS.filter(function (x) { return x.key === key; })[0];
      if (!s) return;
      var self = this;
      var input = document.createElement('input');
      input.type = 'file';
      if (s.multiple) input.multiple = true;
      // Раздел ГИС умеет и папку, и отдельные файлы: раньше выбор папки был
      // единственным вариантом и загрузить один LAS было нельзя.
      var wantDir = (asDirectory === undefined) ? s.dir : !!asDirectory;
      if (wantDir) { input.webkitdirectory = true; input.directory = true; }
      else if (s.accept) input.accept = s.accept;
      input.style.display = 'none';
      document.body.appendChild(input);
      input.onchange = function () {
        self.files[key] = input.files;
        var el = document.getElementById('impFile_' + key);
        if (el) {
          el.textContent = !input.files.length ? 'файл не выбран'
            : (input.files.length === 1 ? input.files[0].name : input.files.length + ' файл(ов)');
        }
        document.body.removeChild(input);
      };
      input.click();
    },

    _result: function (key, html, cls) {
      var el = document.getElementById('impRes_' + key);
      if (el) el.innerHTML = '<div class="imp-res ' + (cls || '') + '">' + html + '</div>';
    },

    run: async function (key) {
      if (this.busy) { toast('warn', 'Импорт уже идёт'); return; }
      var p = pid();
      if (!p) { toast('warn', 'Сначала создайте проект'); return; }
      var picked = this.files[key];
      if (!picked || !picked.length) { toast('warn', 'Не выбран файл'); return; }

      this.busy = true;
      this._result(key, 'импорт…', '');
      try {
        if (key === 'las') await this._runLas(p, picked);
        else if (key === 'tops') await this._runSimple(p, picked[0], key,
          '/api/projects/' + p + '/tops/import', function (r) {
            return 'загружено отбивок: <b>' + r.tops_added + '</b>, скважин: <b>'
              + r.wells_updated + '</b>, горизонтов: <b>' + (r.horizons || []).length + '</b>'
              + ((r.unknown_wells || []).length
                ? '<br><span class="imp-warn">нет в проекте: ' + esc(r.unknown_wells.join(', ')) + '</span>' : '');
          });
        else if (key === 'coords') await this._runSimple(p, picked[0], key,
          '/api/projects/' + p + '/wells/coordinates/import', function (r) {
            return 'обновлено скважин: <b>' + (r.updated != null ? r.updated : '—') + '</b>'
              + ((r.missing || []).length
                ? '<br><span class="imp-warn">не найдены: ' + esc(r.missing.join(', ')) + '</span>' : '');
          });
        else if (key === 'mnemonics') await this._runSimple(p, picked[0], key,
          '/api/mnemonic-aliases/import', function (r) {
            return 'добавлено алиасов: <b>' + (r.added != null ? r.added : '—') + '</b>';
          });
      } catch (e) {
        this._result(key, 'ошибка: ' + esc(e.message || e), 'imp-err');
      } finally {
        this.busy = false;
      }
    },

    _post: async function (url, body) {
      var resp = await fetch(url, { method: 'POST', headers: { 'X-User-Role': role() }, body: body });
      if (!resp.ok) {
        var detail = 'HTTP ' + resp.status;
        try { var j = await resp.json(); detail = j.detail || detail; } catch (e) {}
        throw new Error(detail);
      }
      return resp.json();
    },

    _runSimple: async function (p, file, key, url, fmt) {
      var fd = new FormData();
      fd.append('file', file);
      var r = await this._post(url, fd);
      this._result(key, fmt(r), 'imp-ok');
      toast('success', 'Импорт выполнен');
      var a = app();
      if (a && a.projects && a.projects.length) await a.loadWells(p);
    },

    _runLas: async function (p, list) {
      var files = Array.prototype.filter.call(list, function (f) {
        return /\.las$/i.test(f.name || '');
      });
      if (!files.length) throw new Error('в выбранном месте нет .las файлов');

      // Крупные выгрузки режем на пачки — иначе один запрос на сотни мегабайт.
      var BATCH = 25;
      var total = { imported: 0, failed: 0, wells: 0, errors: [], runs: {}, dups: [], marked: [] };
      for (var i = 0; i < files.length; i += BATCH) {
        var chunk = files.slice(i, i + BATCH);
        var fd = new FormData();
        var paths = [];
        chunk.forEach(function (f) {
          fd.append('files', f, f.name);
          paths.push(f.webkitRelativePath || f.name);
        });
        fd.append('paths', JSON.stringify(paths));
        fd.append('run_name_mode', 'folder');
        fd.append('on_duplicate', this._dupPolicy || 'load');
        this._result('las', 'импорт ' + Math.min(i + BATCH, files.length) + ' из ' + files.length + '…', '');
        var r = await this._post('/api/projects/' + p + '/bulk-import', fd);
        total.imported += r.imported;
        total.failed += r.failed;
        total.wells += r.wells_created;
        (r.results || []).forEach(function (row) {
          if (row.status === 'ok') {
            total.runs[row.run] = (total.runs[row.run] || 0) + 1;
            if (row.duplicate_of) total.marked.push(row);
          }
          else if (row.status === 'duplicate') total.dups.push(row);
          else if (total.errors.length < 8) total.errors.push(row.file + ' — ' + row.error);
        });
      }

      var runsTxt = Object.keys(total.runs).sort().map(function (k) {
        return esc(k) + ' (' + total.runs[k] + ')';
      }).join(', ');
      var html = 'файлов загружено: <b>' + total.imported + '</b>'
        + (total.failed ? ', с ошибкой: <b>' + total.failed + '</b>' : '')
        + '<br>создано скважин: <b>' + total.wells + '</b>'
        + (runsTxt ? '<br>рейсы: ' + runsTxt : '');
      if (total.dups.length) {
        html += '<br><span class="imp-warn">пропущено как повтор: <b>' + total.dups.length + '</b></span>'
          + '<div class="imp-dups">' + total.dups.slice(0, 10).map(function (d) {
              return esc(d.well) + ' · ' + esc(d.run) + ' повторяет «' + esc(d.duplicate_of)
                + '» (' + d.overlap + ' % интервала, методы ' + esc((d.methods || []).join(', ')) + ')';
            }).join('<br>') + '</div>'
          + '<button class="btn-sm" id="impForceDup">Всё равно загрузить повторы</button>';
      }
      if (total.marked.length) {
        // Повтор того же исследования в том же интервале — сообщаем, но грузим:
        // молча терять данные нельзя.
        html += '<br><span class="imp-warn">похожи на повтор уже загруженного (<b>'
          + total.marked.length + '</b>) — проверьте и при необходимости удалите рейс:</span>'
          + '<div class="imp-dups">' + total.marked.slice(0, 10).map(function (d) {
              return esc(d.well) + ' · ' + esc(d.run) + ' ≈ «' + esc(d.duplicate_of) + '»';
            }).join('<br>') + '</div>';
      }
      if (total.errors.length) {
        html += '<br><span class="imp-warn">' + esc(total.errors.join('; ')) + '</span>';
      }
      this._result('las', html, total.failed ? '' : 'imp-ok');
      toast('success', 'Загружено файлов: ' + total.imported
        + (total.dups.length ? ', пропущено повторов: ' + total.dups.length : ''));

      var self = this;
      var force = document.getElementById('impForceDup');
      if (force) {
        force.onclick = async function () {
          self._dupPolicy = 'load';
          try { await self.run('las'); } finally { self._dupPolicy = 'ask'; }
        };
      }

      var a = app();
      if (a) {
        await a.loadProjects();
        if (a.projects && a.projects.length) await a.loadWells(a.projects[0].id);
      }
    },
  };
})();
