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
    aliases: null,
    _showDefaults: false,

    async load() {
      var host = document.getElementById('mnemonicsContent');
      if (host) host.innerHTML = '<p style="color:#8b949e">Loading…</p>';
      try {
        this.aliases = await app._api('/mnemonic-aliases');
      } catch (e) { this.aliases = null; }
      var wid = currentWellId();
      if (wid) {
        try { this.data = await app._api('/wells/' + wid + '/mnemonic-suggestions'); }
        catch (e) { this.data = null; }
      } else {
        this.data = null;
      }
      this.render();
      if (window.lucide) lucide.createIcons();
    },

    render() {
      var host = document.getElementById('mnemonicsContent');
      if (!host) return;
      host.innerHTML = this._aliasSection() + this._scanSection();
      this._bindAliasControls();
    },

    _scanSection() {
      var data = this.data;
      var info = document.getElementById('mnemInfo');
      if (!data) {
        if (info) info.textContent = 'no well selected';
        return '<div style="margin-top:22px"><h4 style="color:#c9d1d9;margin:0 0 6px">Well scan</h4>'
          + '<p style="color:#8b949e">Load a well to scan and normalize its curve mnemonics.</p></div>';
      }
      var minConf = parseFloat((document.getElementById('mnemMinConf') || {}).value || '0.9');
      if (info) info.textContent = data.total + ' curves · ' + data.renamable + ' can be normalized';
      if (!data.curves.length) {
        return '<div style="margin-top:22px"><h4 style="color:#c9d1d9;margin:0 0 6px">Well scan</h4>'
          + '<p style="color:#8b949e">No curves found for this well.</p></div>';
      }

      var rows = data.curves.slice().sort(function (a, b) {
        return (a.already_canonical - b.already_canonical) || (b.confidence - a.confidence);
      });

      var html = '<div style="margin-top:22px"><h4 style="color:#c9d1d9;margin:0 0 8px">Well scan — '
        + escapeHtml(data.well_name || '') + '</h4>';
      html += '<table style="border-collapse:collapse;width:100%;font-size:13px">';
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
           + 'Already-canonical and unknown curves are left untouched.</p></div>';
      return html;
    },

    // ── Alias management (custom mnemonics: Excel/CSV + editable defaults) ──
    _aliasSection() {
      var a = this.aliases;
      if (!a) return '<p style="color:#f85149">Could not load alias table.</p>';
      var canon = a.canonicals || [];
      var opts = canon.map(function (c) { return '<option value="' + c + '">' + c + '</option>'; }).join('');

      var html = '<div style="border:1px solid #30363d;border-radius:10px;padding:12px 14px;background:#0d1117">';
      html += '<h4 style="color:#c9d1d9;margin:0 0 10px">Custom mnemonic aliases <span style="color:#8b949e;font-weight:400">('
        + a.custom_count + ' custom · ' + (a.defaults || []).length + ' built-in)</span></h4>';

      // Add form
      html += '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px">'
        + '<input id="aliasRawInput" placeholder="vendor mnemonic (e.g. ГК, ZDEN)" '
        + 'style="background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:6px 8px;width:220px">'
        + '<span style="color:#8b949e">→</span>'
        + '<select id="aliasCanonSelect" class="depth-select">' + opts + '</select>'
        + '<button class="btn-sm" id="aliasAddBtn"><i data-lucide="plus"></i> Add</button>'
        + '<span style="flex:1"></span>'
        + '<label style="display:flex;align-items:center;gap:6px;color:#8b949e;font-size:12px"><input type="checkbox" id="aliasReplace"> replace all</label>'
        + '<button class="btn-sm" id="aliasImportBtn"><i data-lucide="file-spreadsheet"></i> Import Excel/CSV</button>'
        + '<button class="btn-sm" id="aliasTemplateBtn"><i data-lucide="download"></i> Template</button>'
        + '<input type="file" id="aliasImportInput" accept=".xlsx,.xlsm,.csv,.tsv,.txt" style="display:none">'
        + '</div>';

      // Custom aliases table
      if ((a.custom || []).length) {
        html += '<table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:6px">';
        html += '<tr style="text-align:left;color:#8b949e;border-bottom:1px solid #30363d">'
          + '<th style="padding:5px 8px">Raw</th><th style="padding:5px 8px">→ Canonical</th>'
          + '<th style="padding:5px 8px">Method</th><th style="padding:5px 8px;width:40px"></th></tr>';
        a.custom.forEach(function (c) {
          html += '<tr style="border-bottom:1px solid #21262d">'
            + '<td style="padding:5px 8px;font-family:monospace;color:#c9d1d9">' + escapeHtml(c.raw) + '</td>'
            + '<td style="padding:5px 8px;font-family:monospace;color:#58a6ff">' + escapeHtml(c.canonical) + '</td>'
            + '<td style="padding:5px 8px;color:#8b949e">' + escapeHtml(c.method_name || '—') + '</td>'
            + '<td style="padding:5px 8px"><button class="btn-sm alias-del" data-raw="' + escapeHtml(c.raw)
            + '" title="Remove" style="padding:2px 6px">✕</button></td></tr>';
        });
        html += '</table>';
      } else {
        html += '<p style="color:#6e7681;font-size:12px;margin:4px 0">No custom aliases yet. Add one above or import a table '
          + '(two columns: <code>raw</code>, <code>canonical</code>).</p>';
      }

      // Defaults (collapsible)
      html += '<div style="margin-top:8px"><button class="btn-sm" id="aliasDefaultsToggle">'
        + (this._showDefaults ? 'Hide' : 'Show') + ' built-in defaults</button>';
      if (this._showDefaults) {
        html += '<div style="max-height:220px;overflow:auto;margin-top:8px;border:1px solid #21262d;border-radius:8px">';
        html += '<table style="border-collapse:collapse;width:100%;font-size:12px">';
        (a.defaults || []).forEach(function (d) {
          html += '<tr style="border-bottom:1px solid #161b22">'
            + '<td style="padding:3px 8px;font-family:monospace;color:#c9d1d9">' + escapeHtml(d.raw) + '</td>'
            + '<td style="padding:3px 8px;font-family:monospace;color:#8b949e">→ ' + escapeHtml(d.canonical) + '</td>'
            + '<td style="padding:3px 8px;color:#6e7681">' + escapeHtml(d.method_name || '') + '</td></tr>';
        });
        html += '</table></div>';
      }
      html += '</div></div>';
      return html;
    },

    _bindAliasControls() {
      var self = this;
      var addBtn = document.getElementById('aliasAddBtn');
      if (addBtn) addBtn.onclick = function () { self.addAlias(); };
      var impBtn = document.getElementById('aliasImportBtn');
      var impInput = document.getElementById('aliasImportInput');
      if (impBtn && impInput) impBtn.onclick = function () { impInput.click(); };
      if (impInput) impInput.onchange = function () { self.importAliases(impInput.files[0]); };
      var tplBtn = document.getElementById('aliasTemplateBtn');
      if (tplBtn) tplBtn.onclick = function () { self.downloadTemplate(); };
      var tog = document.getElementById('aliasDefaultsToggle');
      if (tog) tog.onclick = function () { self._showDefaults = !self._showDefaults; self.render(); if (window.lucide) lucide.createIcons(); };
      Array.prototype.forEach.call(document.querySelectorAll('.alias-del'), function (btn) {
        btn.onclick = function () { self.deleteAlias(btn.getAttribute('data-raw')); };
      });
    },

    async addAlias() {
      var raw = (document.getElementById('aliasRawInput') || {}).value;
      var canon = (document.getElementById('aliasCanonSelect') || {}).value;
      if (!raw || !raw.trim()) { GeoToast.warn('Enter a vendor mnemonic'); return; }
      try {
        await app._api('/mnemonic-aliases', { method: 'POST', body: JSON.stringify({ raw: raw.trim(), canonical: canon }) });
        GeoToast.success('Alias added: ' + raw.trim().toUpperCase() + ' → ' + canon);
        await this.load();
      } catch (e) { GeoToast.error('Add failed: ' + (e.message || e)); }
    },

    async deleteAlias(raw) {
      try {
        await app._api('/mnemonic-aliases/' + encodeURIComponent(raw), { method: 'DELETE' });
        GeoToast.info('Removed ' + raw);
        await this.load();
      } catch (e) { GeoToast.error('Remove failed: ' + (e.message || e)); }
    },

    async importAliases(file) {
      if (!file) return;
      var replace = !!(document.getElementById('aliasReplace') || {}).checked;
      try {
        var fd = new FormData();
        fd.append('file', file);
        var resp = await fetch('/api/mnemonic-aliases/import?replace=' + (replace ? 'true' : 'false'), {
          method: 'POST', headers: { 'X-User-Role': app.currentRole || 'viewer' }, body: fd
        });
        var j = await resp.json();
        if (!resp.ok) throw new Error(j.detail || ('HTTP ' + resp.status));
        GeoToast.success('Imported ' + j.added + ' alias(es)' + (j.skipped ? ', ' + j.skipped + ' skipped' : ''));
        await this.load();
      } catch (e) { GeoToast.error('Import failed: ' + (e.message || e)); }
    },

    downloadTemplate() {
      var csv = 'raw,canonical\nZDEN,RHOB\nГК,GR\nMYRES,RT\n';
      var blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      var link = document.createElement('a');
      link.download = 'mnemonic_aliases_template.csv';
      link.href = URL.createObjectURL(blob);
      link.click();
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
