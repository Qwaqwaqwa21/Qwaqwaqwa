/*
 * CLIPBOARD — библиотека построенных карт в сайдбаре.
 * Папки: Пористость / Нефтенасыщенность / Толщины / Прочее.
 * Позиция хранит НАСТРОЙКИ построения (параметр, горизонт, IDW, палитра),
 * карта пересчитывается при клике — так она всегда актуальна.
 */
(function () {
  var FOLDERS = [
    { key: 'porosity',  name: 'Пористость',        icon: '◍' },
    { key: 'oil_thick', name: 'Нефтенасыщенность', icon: '◆' },
    { key: 'thickness', name: 'Толщины',           icon: '▤' },
    { key: 'other',     name: 'Прочее',            icon: '○' }
  ];
  var PARAM_FOLDER = {
    porosity: 'porosity', oil_thick: 'oil_thick', thickness: 'thickness',
    altitude: 'other', wellheads: 'other'
  };
  var PARAM_TITLE = {
    porosity: 'Пористость', oil_thick: 'Нефтенас. толщина', thickness: 'Толщина коллектора',
    altitude: 'Альтитуды устьев', wellheads: 'Карта устьев'
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function pid() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && a.projects && a.projects[0]) ? a.projects[0].id : null;
  }

  window.ClipboardPanel = {
    items: [],
    open: { porosity: true, oil_thick: true, thickness: true, other: false },

    load: async function () {
      var p = pid();
      if (!p) return;
      try {
        var r = await app._api('/projects/' + p + '/clipboard');
        this.items = r.items || [];
      } catch (e) { this.items = []; }
      this.render();
    },

    render: function () {
      var host = document.getElementById('clipboardContent');
      if (!host) return;
      var self = this;
      var byFolder = {};
      this.items.forEach(function (it) {
        var f = PARAM_FOLDER[it.param] || 'other';
        (byFolder[f] = byFolder[f] || []).push(it);
      });

      var h = '';
      FOLDERS.forEach(function (f) {
        var list = byFolder[f.key] || [];
        var isOpen = self.open[f.key];
        h += '<div class="clip-folder">'
          + '<div class="clip-folder-hd" data-folder="' + f.key + '">'
          + '<span style="width:12px;display:inline-block">' + (isOpen ? '▾' : '▸') + '</span>'
          + '<span style="opacity:.75">' + f.icon + '</span> ' + esc(f.name)
          + '<span class="clip-count">' + list.length + '</span></div>';
        if (isOpen) {
          if (!list.length) {
            h += '<div class="clip-empty">пусто — постройте карту и нажмите «В clipboard»</div>';
          }
          list.forEach(function (it) {
            h += '<div class="clip-item" data-id="' + it.id + '" title="Открыть карту">'
              + '<span class="clip-item-name">' + esc(it.horizon || PARAM_TITLE[it.param] || it.param) + '</span>'
              + (it.frozen ? '<span class="clip-frozen" title="заморожено">❄</span>' : '')
              + '<button class="clip-del" data-del="' + it.id + '" title="Удалить">✕</button>'
              + '</div>';
          });
        }
        h += '</div>';
      });
      host.innerHTML = h;

      host.querySelectorAll('.clip-folder-hd').forEach(function (el) {
        el.onclick = function () {
          var k = el.getAttribute('data-folder');
          self.open[k] = !self.open[k];
          self.render();
        };
      });
      host.querySelectorAll('.clip-item').forEach(function (el) {
        el.onclick = function (e) {
          if (e.target.classList.contains('clip-del')) return;
          self.openItem(parseInt(el.getAttribute('data-id'), 10));
        };
      });
      host.querySelectorAll('.clip-del').forEach(function (b) {
        b.onclick = function (e) {
          e.stopPropagation();
          self.remove(parseInt(b.getAttribute('data-del'), 10));
        };
      });
    },

    openItem: function (id) {
      var it = this.items.filter(function (x) { return x.id === id; })[0];
      if (!it) return;
      if (typeof app !== 'undefined') app.switchView('maps');
      var set = function (elId, v) { var e = document.getElementById(elId); if (e) e.value = v; };
      set('mapParam', it.param);
      if (it.horizon) set('mapHorizon', it.horizon);
      set('mapPower', it.power);
      set('mapLevels', it.levels);
      var rev = document.getElementById('mapReverse');
      if (rev) rev.checked = !!it.reverse;
      if (typeof MapsView !== 'undefined') MapsView.load();
    },

    addCurrent: async function () {
      var p = pid();
      if (!p) { GeoToast.warn('Откройте проект'); return; }
      var g = function (id) { var e = document.getElementById(id); return e ? e.value : ''; };
      var body = {
        param: g('mapParam') || 'thickness',
        horizon: g('mapHorizon') || '',
        power: parseFloat(g('mapPower') || '2') || 2,
        levels: parseInt(g('mapLevels') || '8', 10) || 8,
        reverse: !!(document.getElementById('mapReverse') || {}).checked,
        title: ''
      };
      try {
        await app._api('/projects/' + p + '/clipboard', { method: 'POST', body: JSON.stringify(body) });
        GeoToast.success('Карта добавлена в clipboard');
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    },

    remove: async function (id) {
      try {
        await app._api('/projects/' + pid() + '/clipboard/' + id, { method: 'DELETE' });
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    }
  };

  // Самоинициализация: ждём, пока приложение загрузит проекты.
  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    if (pid()) { clearInterval(timer); ClipboardPanel.load(); }
    else if (tries > 40) clearInterval(timer);
  }, 250);
})();
