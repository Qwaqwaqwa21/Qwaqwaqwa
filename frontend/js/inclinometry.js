/*
 * Инклинометрия: контроль качества + проекции траектории.
 *   • вертикальная проекция  (отход ↔ TVD)
 *   • план (вид сверху)      (восток ↔ север)
 *   • профиль DLS по глубине с порогом (по умолчанию 20 °/10 м)
 * Участки с DLS > порога подсвечиваются красным на обеих проекциях.
 */
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  window.InclinometryView = {
    data: null, notes: null,

    load: async function () {
      var host = document.getElementById('inklContent');
      var a = (typeof app !== 'undefined') ? app : window.app;
      if (!a || !a.currentWell) {
        if (host) host.innerHTML = '<p style="color:#8b949e">Выберите скважину.</p>';
        return;
      }
      var lim = parseFloat((document.getElementById('inklDlsLimit') || {}).value || '20');
      if (host) host.innerHTML = '<p style="color:#8b949e">Расчёт траектории…</p>';
      try {
        this.data = await a._api('/wells/' + a.currentWell.id + '/inclinometry?dls_limit=' + lim);
      } catch (e) {
        this.data = null;
        if (host) host.innerHTML = '<p style="color:#f85149">' + esc(e.message || e) + '</p>';
      }
      try { this.notes = await a._api('/wells/' + a.currentWell.id + '/notes'); } catch (e) { this.notes = null; }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render: function () {
      var host = document.getElementById('inklContent');
      if (!host) return;
      var d = this.data;
      var html = '';
      if (d) {
        var badge = function (label, val, color) {
          return '<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 12px;min-width:120px">'
            + '<div style="color:#8b949e;font-size:11px">' + label + '</div>'
            + '<div style="color:' + (color || '#c9d1d9') + ';font-size:17px;font-weight:600">' + val + '</div></div>';
        };
        var dlsCol = d.max_dls > d.dls_limit ? '#f85149' : '#3fb950';
        html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">'
          + badge('Замеров', d.count)
          + badge('Забой MD', d.td_md + ' м')
          + badge('Забой TVD', d.td_tvd + ' м')
          + badge('Отход', d.displacement + ' м')
          + badge('Макс. зенит', d.max_incl + '°')
          + badge('Макс. DLS', d.max_dls + ' °/10м', dlsCol)
          + badge('Дубли', (d.duplicates.exact + d.duplicates.conflicting),
                  (d.duplicates.exact + d.duplicates.conflicting) ? '#d29922' : '#3fb950')
          + '</div>';
        html += '<div style="display:flex;gap:14px;flex-wrap:wrap">'
          + '<div><div style="color:#8b949e;font-size:12px;margin-bottom:4px">Вертикальная проекция (отход — TVD)</div>'
          + '<canvas id="inklVert"></canvas></div>'
          + '<div><div style="color:#8b949e;font-size:12px;margin-bottom:4px">План (вид сверху: восток — север)</div>'
          + '<canvas id="inklPlan"></canvas></div>'
          + '<div><div style="color:#8b949e;font-size:12px;margin-bottom:4px">DLS по глубине, °/10 м</div>'
          + '<canvas id="inklDls"></canvas></div></div>';
        html += '<div style="margin-top:14px"><h4 style="color:#c9d1d9;margin:0 0 6px">Выявленные проблемы ('
          + d.problem_count + ')</h4>';
        if (!d.problems.length) {
          html += '<p style="color:#3fb950;font-size:13px">Проблем не выявлено — DLS в пределах нормы, дублей нет.</p>';
        } else {
          html += '<ul style="margin:0;padding-left:18px;font-size:13px">';
          d.problems.slice(0, 40).forEach(function (p) {
            var c = p.severity === 'high' ? '#f85149' : '#d29922';
            html += '<li style="color:' + c + ';margin:2px 0">' + esc(p.message) + '</li>';
          });
          html += '</ul>';
        }
        html += '</div>';
      }
      // заметки по качеству
      html += this._notesHtml();
      host.innerHTML = html;
      if (d) { this._drawVert(); this._drawPlan(); this._drawDls(); }
      this._bindNotes();
    },

    _notesHtml: function () {
      var n = (this.notes && this.notes.notes) || [];
      var h = '<div style="margin-top:18px;border-top:1px solid #21262d;padding-top:12px">'
        + '<h4 style="color:#c9d1d9;margin:0 0 8px">Заметки по качеству (' + n.length + ')</h4>'
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">'
        + '<input id="noteText" placeholder="Опишите проблему с кривой/данными…" '
        + 'style="flex:1;min-width:280px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:6px 9px">'
        + '<input id="noteCurve" placeholder="кривая" style="width:110px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:6px 9px">'
        + '<select id="noteSeverity" class="depth-select"><option value="low">низкая</option>'
        + '<option value="medium" selected>средняя</option><option value="high">высокая</option></select>'
        + '<button class="btn-sm" id="noteAddBtn"><i data-lucide="plus"></i> Добавить</button>'
        + '<button class="btn-sm" id="noteAutoBtn"><i data-lucide="wand-sparkles"></i> Авто-заметки по QC</button>'
        + '</div>';
      if (!n.length) {
        h += '<p style="color:#6e7681;font-size:12px">Заметок нет. Авто-заметки создаются по результатам QC, ручные — через форму выше.</p>';
      } else {
        h += '<table style="border-collapse:collapse;width:100%;font-size:12px">';
        n.slice().reverse().forEach(function (x) {
          var c = x.severity === 'high' ? '#f85149' : (x.severity === 'medium' ? '#d29922' : '#8b949e');
          h += '<tr style="border-bottom:1px solid #21262d">'
            + '<td style="padding:4px 8px;color:' + c + ';white-space:nowrap">●</td>'
            + '<td style="padding:4px 8px;color:#c9d1d9">' + esc(x.text) + '</td>'
            + '<td style="padding:4px 8px;color:#8b949e;white-space:nowrap">' + esc(x.curve || '') + '</td>'
            + '<td style="padding:4px 8px;color:#6e7681;white-space:nowrap">'
            + (x.source === 'auto' ? 'авто' : 'вручную') + '</td>'
            + '<td style="padding:4px 8px"><button class="btn-sm note-del" data-id="' + x.id
            + '" style="padding:1px 6px">✕</button></td></tr>';
        });
        h += '</table>';
      }
      return h + '</div>';
    },

    _bindNotes: function () {
      var self = this;
      var add = document.getElementById('noteAddBtn');
      if (add) add.onclick = function () { self.addNote(); };
      var auto = document.getElementById('noteAutoBtn');
      if (auto) auto.onclick = function () { self.autoNotes(); };
      Array.prototype.forEach.call(document.querySelectorAll('.note-del'), function (b) {
        b.onclick = function () { self.delNote(b.getAttribute('data-id')); };
      });
    },

    addNote: async function () {
      var t = (document.getElementById('noteText') || {}).value || '';
      if (!t.trim()) { GeoToast.warn('Введите текст заметки'); return; }
      try {
        await app._api('/wells/' + app.currentWell.id + '/notes', {
          method: 'POST', body: JSON.stringify({
            text: t.trim(),
            curve: (document.getElementById('noteCurve') || {}).value || null,
            severity: (document.getElementById('noteSeverity') || {}).value || 'medium'
          })
        });
        GeoToast.success('Заметка добавлена');
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    },

    autoNotes: async function () {
      try {
        var r = await app._api('/wells/' + app.currentWell.id + '/notes/auto', { method: 'POST' });
        GeoToast.success('Добавлено авто-заметок: ' + r.added);
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    },

    delNote: async function (id) {
      try {
        await app._api('/wells/' + app.currentWell.id + '/notes/' + id, { method: 'DELETE' });
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    },

    dedupe: async function () {
      try {
        var r = await app._api('/wells/' + app.currentWell.id + '/inclinometry/dedupe', { method: 'POST' });
        GeoToast.success(r.message);
        await this.load();
      } catch (e) { GeoToast.error('Ошибка: ' + (e.message || e)); }
    },

    // ── проекции ────────────────────────────────────────────────────────
    _setup: function (id, w, h) {
      var c = document.getElementById(id);
      if (!c) return null;
      var dpr = window.devicePixelRatio || 1;
      c.style.width = w + 'px'; c.style.height = h + 'px';
      c.width = w * dpr; c.height = h * dpr;
      var g = c.getContext('2d'); g.scale(dpr, dpr);
      g.fillStyle = '#0d1117'; g.fillRect(0, 0, w, h);
      g.strokeStyle = '#30363d'; g.strokeRect(.5, .5, w - 1, h - 1);
      g.font = '10px system-ui,sans-serif'; g.textBaseline = 'middle';
      return g;
    },

    _polyline: function (g, xs, ys, dls, limit, X, Y) {
      // обычный ход — синий; участки с DLS выше порога — красным и толще
      for (var i = 1; i < xs.length; i++) {
        var bad = dls[i] > limit;
        g.beginPath();
        g.strokeStyle = bad ? '#f85149' : '#58a6ff';
        g.lineWidth = bad ? 3 : 1.6;
        g.moveTo(X(xs[i - 1]), Y(ys[i - 1]));
        g.lineTo(X(xs[i]), Y(ys[i]));
        g.stroke();
        if (bad) {
          g.fillStyle = 'rgba(248,81,73,.9)';
          g.beginPath(); g.arc(X(xs[i]), Y(ys[i]), 3.2, 0, 6.283); g.fill();
        }
      }
    },

    _drawVert: function () {
      var d = this.data, W = 430, H = 430;
      var g = this._setup('inklVert', W, H); if (!g) return;
      var s = d.survey;
      var disp = s.north.map(function (n, i) { return Math.hypot(n, s.east[i]); });
      var maxX = Math.max(10, Math.max.apply(null, disp)) * 1.15;
      var maxY = Math.max(10, s.tvd[s.tvd.length - 1]) * 1.05;
      var m = { l: 52, r: 12, t: 16, b: 26 };
      var X = function (v) { return m.l + v / maxX * (W - m.l - m.r); };
      var Y = function (v) { return m.t + v / maxY * (H - m.t - m.b); };
      g.strokeStyle = '#21262d';
      for (var i = 0; i <= 5; i++) {
        var yy = m.t + i / 5 * (H - m.t - m.b);
        g.beginPath(); g.moveTo(m.l, yy); g.lineTo(W - m.r, yy); g.stroke();
        g.fillStyle = '#6e7681'; g.textAlign = 'right';
        g.fillText(Math.round(maxY * i / 5), m.l - 6, yy);
        var xx = m.l + i / 5 * (W - m.l - m.r);
        g.beginPath(); g.moveTo(xx, m.t); g.lineTo(xx, H - m.b); g.stroke();
        g.textAlign = 'center'; g.fillText(Math.round(maxX * i / 5), xx, H - m.b + 12);
      }
      this._polyline(g, disp, s.tvd, s.dls, d.dls_limit, X, Y);
      g.fillStyle = '#8b949e'; g.textAlign = 'left';
      g.fillText('отход, м', W - 70, H - m.b + 12);
      g.save(); g.translate(12, H / 2); g.rotate(-Math.PI / 2);
      g.textAlign = 'center'; g.fillText('TVD, м', 0, 0); g.restore();
    },

    _drawPlan: function () {
      var d = this.data, W = 430, H = 430;
      var g = this._setup('inklPlan', W, H); if (!g) return;
      var s = d.survey;
      var lim = Math.max(10, Math.max(
        Math.max.apply(null, s.north.map(Math.abs)),
        Math.max.apply(null, s.east.map(Math.abs)))) * 1.2;
      var m = 40;
      var X = function (v) { return m + (v + lim) / (2 * lim) * (W - 2 * m); };
      var Y = function (v) { return H - m - (v + lim) / (2 * lim) * (H - 2 * m); };
      g.strokeStyle = '#21262d';
      g.beginPath(); g.moveTo(X(-lim), Y(0)); g.lineTo(X(lim), Y(0)); g.stroke();
      g.beginPath(); g.moveTo(X(0), Y(-lim)); g.lineTo(X(0), Y(lim)); g.stroke();
      g.fillStyle = '#6e7681'; g.textAlign = 'center';
      g.fillText('С', X(0), Y(lim) - 8); g.fillText('Ю', X(0), Y(-lim) + 10);
      g.fillText('В', X(lim) - 8, Y(0) - 8); g.fillText('З', X(-lim) + 10, Y(0) - 8);
      this._polyline(g, s.east, s.north, s.dls, d.dls_limit, X, Y);
      g.fillStyle = '#3fb950';
      g.beginPath(); g.arc(X(0), Y(0), 4, 0, 6.283); g.fill();
      g.fillStyle = '#8b949e'; g.textAlign = 'left';
      g.fillText('устье', X(0) + 7, Y(0) - 8);
    },

    _drawDls: function () {
      var d = this.data, W = 300, H = 430;
      var g = this._setup('inklDls', W, H); if (!g) return;
      var s = d.survey;
      var maxD = Math.max.apply(null, s.md) || 1;
      var maxV = Math.max(d.dls_limit * 1.4, Math.max.apply(null, s.dls) * 1.15, 5);
      var m = { l: 44, r: 12, t: 16, b: 26 };
      var X = function (v) { return m.l + v / maxV * (W - m.l - m.r); };
      var Y = function (v) { return m.t + v / maxD * (H - m.t - m.b); };
      g.strokeStyle = '#21262d';
      for (var i = 0; i <= 5; i++) {
        var yy = m.t + i / 5 * (H - m.t - m.b);
        g.beginPath(); g.moveTo(m.l, yy); g.lineTo(W - m.r, yy); g.stroke();
        g.fillStyle = '#6e7681'; g.textAlign = 'right'; g.fillText(Math.round(maxD * i / 5), m.l - 6, yy);
      }
      // порог
      g.strokeStyle = '#f85149'; g.setLineDash([5, 4]); g.lineWidth = 1.4;
      g.beginPath(); g.moveTo(X(d.dls_limit), m.t); g.lineTo(X(d.dls_limit), H - m.b); g.stroke();
      g.setLineDash([]);
      g.fillStyle = '#f85149'; g.textAlign = 'left';
      g.fillText('порог ' + d.dls_limit, X(d.dls_limit) + 4, m.t + 8);
      // профиль
      for (var k = 1; k < s.dls.length; k++) {
        var bad = s.dls[k] > d.dls_limit;
        g.beginPath();
        g.strokeStyle = bad ? '#f85149' : '#58a6ff';
        g.lineWidth = bad ? 2.6 : 1.2;
        g.moveTo(X(s.dls[k - 1]), Y(s.md[k - 1]));
        g.lineTo(X(s.dls[k]), Y(s.md[k]));
        g.stroke();
      }
      g.fillStyle = '#8b949e'; g.textAlign = 'center';
      g.fillText('DLS, °/10м', W / 2, H - m.b + 12);
    }
  };
})();
