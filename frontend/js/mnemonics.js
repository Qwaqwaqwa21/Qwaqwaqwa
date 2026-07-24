/*
 * Auto-Mnemonics (авто применение мнемоник)
 * Scans the active well's curves, proposes canonical mnemonics with a
 * confidence score, and applies the normalization in one click. Backed by
 *   GET  /api/wells/{wid}/mnemonic-suggestions
 *   POST /api/wells/{wid}/apply-mnemonics
 */
(function () {
  function currentWellId() {
    var a = (typeof app !== 'undefined') ? app : window.app;
    return (a && a.currentWell) ? a.currentWell.id : null;
  }

  function confBadge(c) {
    var color = c >= 1 ? '#3fb950' : (c >= 0.9 ? '#58a6ff' : (c >= 0.6 ? '#d29922' : '#8b949e'));
    return '<span style="background:' + color + '22;color:' + color
      + ';padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600">' + c.toFixed(2) + '</span>';
  }

  window.MnemonicsView = {
    data: null,

    async load() {
      var wid = currentWellId();
      var host = document.getElementById('mnemonicsContent');
      if (!wid) {
        if (host) host.innerHTML = '<p style="color:#8b949e">Load a well first, then scan its curve mnemonics.</p>';
        return;
      }
      if (host) host.innerHTML = '<p style="color:#8b949e">Scanning curves…</p>';
      try {
        this.data = await app._api('/wells/' + wid + '/mnemonic-suggestions');
      } catch (e) {
        if (host) host.innerHTML = '<p style="color:#f85149">Failed to scan: ' + (e.message || e) + '</p>';
        return;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render() {
      var host = document.getElementById('mnemonicsContent');
      var data = this.data;
      if (!host || !data) return;
      var minConf = parseFloat((document.getElementById('mnemMinConf') || {}).value || '0.9');

      var info = document.getElementById('mnemInfo');
      if (info) info.textContent = data.total + ' curves · ' + data.renamable + ' can be normalized';

      if (!data.curves.length) {
        host.innerHTML = '<p style="color:#8b949e">No curves found for this well.</p>';
        return;
      }

      var rows = data.curves.slice().sort(function (a, b) {
        return (a.already_canonical - b.already_canonical) || (b.confidence - a.confidence);
      });

      var html = '<table style="border-collapse:collapse;width:100%;font-size:13px">';
      html += '<tr style="text-align:left;color:#8b949e;border-bottom:1px solid #30363d">'
           + '<th style="padding:6px 8px;width:36px"></th><th style="padding:6px 8px">Raw</th>'
           + '<th style="padding:6px 8px">→ Canonical</th><th style="padding:6px 8px">Method</th>'
           + '<th style="padding:6px 8px">Confidence</th><th style="padding:6px 8px">Basis</th></tr>';

      rows.forEach(function (c) {
        var eligible = !c.already_canonical && c.confidence >= minConf;
        var status, statusColor;
        if (c.already_canonical) { status = 'canonical'; statusColor = '#3fb950'; }
        else if (c.confidence >= 0.6) { status = 'remap'; statusColor = '#d29922'; }
        else { status = 'unknown'; statusColor = '#8b949e'; }

        html += '<tr style="border-bottom:1px solid #21262d">';
        html += '<td style="padding:6px 8px">'
             + (eligible
                ? '<input type="checkbox" class="mnem-pick" data-raw="' + escapeHtml(c.raw) + '" checked>'
                : '<span title="' + status + '" style="color:' + statusColor + '">●</span>')
             + '</td>';
        html += '<td style="padding:6px 8px;font-family:monospace;color:#c9d1d9">' + escapeHtml(c.raw)
             + (c.unit ? ' <span style="color:#6e7681">[' + escapeHtml(c.unit) + ']</span>' : '') + '</td>';
        html += '<td style="padding:6px 8px;font-family:monospace">'
             + (c.already_canonical
                ? '<span style="color:#3fb950">' + escapeHtml(c.canonical) + '</span>'
                : (c.confidence >= 0.6
                   ? '<span style="color:#58a6ff">' + escapeHtml(c.canonical) + '</span>'
                   : '<span style="color:#6e7681">—</span>')) + '</td>';
        html += '<td style="padding:6px 8px;color:#8b949e">' + escapeHtml(c.method_name || '—') + '</td>';
        html += '<td style="padding:6px 8px">' + confBadge(c.confidence) + '</td>';
        html += '<td style="padding:6px 8px;color:#6e7681">' + escapeHtml(c.reason) + '</td>';
        html += '</tr>';
      });
      html += '</table>';
      html += '<p style="color:#6e7681;margin-top:10px;font-size:12px">'
           + 'Checked rows meet the selected confidence threshold and will be renamed to their canonical family. '
           + 'Already-canonical and unknown curves are left untouched.</p>';
      host.innerHTML = html;
    },

    _selectedRaws() {
      return Array.prototype.map.call(
        document.querySelectorAll('.mnem-pick:checked'),
        function (el) { return el.getAttribute('data-raw'); });
    },

    async applySelected() {
      var only = this._selectedRaws();
      if (!only.length) { GeoToast.warn('No curves selected'); return; }
      await this._apply({ min_confidence: 0.6, only: only });
    },

    async applyAll() {
      var minConf = parseFloat((document.getElementById('mnemMinConf') || {}).value || '0.9');
      await this._apply({ min_confidence: minConf });
    },

    async _apply(body) {
      var wid = currentWellId();
      if (!wid) { GeoToast.warn('Load a well first'); return; }
      try {
        var res = await app._api('/wells/' + wid + '/apply-mnemonics', {
          method: 'POST', body: JSON.stringify(body)
        });
        GeoToast.success('Normalized ' + res.applied + ' curve(s)'
          + (res.skipped && res.skipped.length ? ' · ' + res.skipped.length + ' skipped' : ''));
        // Refresh well data so the viewer/other panels pick up canonical names.
        if (app.currentWell && typeof app.selectWell === 'function') {
          try { await app.selectWell(app.currentWell.id); } catch (e) { /* noop */ }
        }
        await this.load();
      } catch (e) {
        GeoToast.error('Apply failed: ' + (e.message || e));
      }
    }
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
})();
