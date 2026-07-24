/*
 * Колонки РИГИС: Литология / Коллектор / Насыщение
 *
 * Рисуются как категориальные колонки: заливка по коду + условная штриховка
 * литологии (известняк — «кирпич», песчаник — точки, глина — линии …).
 * При наведении курсора рядом показывается расшифровка кода по-русски.
 */
(function () {
  var CODES = null;                 // справочники с бэкенда
  var PATTERNS = {};                // кэш CanvasPattern

  function loadCodes() {
    if (CODES) return Promise.resolve(CODES);
    return app._api('/rigis-codes').then(function (d) { CODES = d; return d; })
      .catch(function () { CODES = {}; return CODES; });
  }

  function lookup(book, code) {
    var t = CODES && CODES[book];
    if (!t) return null;
    var k = String(Math.round(Number(code)));
    return t[k] || { code: k, ru: 'код ' + k, pattern: 'none', color: '#30363d' };
  }

  // ── условные обозначения литологии (штриховка 12×12) ──────────────────
  function makePattern(ctx, kind, color) {
    var key = kind + '|' + color;
    if (PATTERNS[key]) return PATTERNS[key];
    var c = document.createElement('canvas');
    c.width = 12; c.height = 12;
    var g = c.getContext('2d');
    g.fillStyle = color; g.fillRect(0, 0, 12, 12);
    g.strokeStyle = 'rgba(15,20,25,.75)'; g.fillStyle = 'rgba(15,20,25,.75)';
    g.lineWidth = 1;
    function brick(off) {           // известняк — кирпичная кладка
      g.beginPath();
      g.moveTo(0, 4 + off); g.lineTo(12, 4 + off);
      g.moveTo(0, 10 + off); g.lineTo(12, 10 + off);
      g.moveTo(6, 4 + off); g.lineTo(6, 10 + off);
      g.moveTo(0, 10 + off); g.lineTo(0, 12 + off);
      g.stroke();
    }
    function dots(n) {              // песчаник — точки
      for (var i = 0; i < n; i++) {
        var x = (i * 5 + 2) % 11, y = (i * 7 + 3) % 11;
        g.beginPath(); g.arc(x, y, 1.05, 0, 6.283); g.fill();
      }
    }
    function hlines(step) {         // глина/аргиллит — горизонтальные линии
      g.beginPath();
      for (var y = 2; y < 12; y += step) { g.moveTo(0, y); g.lineTo(12, y); }
      g.stroke();
    }
    function rhomb() {              // доломит — ромбы
      g.beginPath();
      g.moveTo(6, 1); g.lineTo(11, 6); g.lineTo(6, 11); g.lineTo(1, 6); g.closePath();
      g.stroke();
    }
    function dashes() {             // алевролит — штрихи
      g.beginPath();
      g.moveTo(1, 3); g.lineTo(5, 3); g.moveTo(7, 8); g.lineTo(11, 8);
      g.stroke();
    }
    function cross() {              // ангидрит/гипс — косая сетка
      g.beginPath();
      g.moveTo(0, 0); g.lineTo(12, 12); g.moveTo(12, 0); g.lineTo(0, 12);
      g.stroke();
    }
    switch (kind) {
      case 'limestone': brick(0); break;
      case 'limestone_dol': brick(0); rhomb(); break;
      case 'limestone_clay': brick(0); hlines(6); break;
      case 'carbonate': brick(0); break;
      case 'dolomite': rhomb(); break;
      case 'dolomite_clay': rhomb(); hlines(6); break;
      case 'sand': dots(7); break;
      case 'sand_clay': dots(5); hlines(6); break;
      case 'sand_silt': dots(5); dashes(); break;
      case 'sand_carb': dots(5); brick(0); break;
      case 'silt': dashes(); break;
      case 'silt_clay': dashes(); hlines(6); break;
      case 'clay': case 'shale': hlines(3); break;
      case 'marl': hlines(4); brick(0); break;
      case 'gypsum': case 'anhydrite': cross(); break;
      case 'coal': g.fillStyle = '#12161c'; g.fillRect(0, 0, 12, 12); break;
      case 'salt': cross(); dots(3); break;
      case 'crystalline': cross(); rhomb(); break;
      case 'conglomerate':
        g.beginPath(); g.arc(4, 4, 2.4, 0, 6.283); g.stroke();
        g.beginPath(); g.arc(9, 9, 2, 0, 6.283); g.stroke(); break;
      case 'weathered': dashes(); dots(3); break;
      case 'bitumen': hlines(3); g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(0, 0, 12, 12); break;
      default: break;
    }
    var p = ctx.createPattern(c, 'repeat');
    PATTERNS[key] = p;
    return p;
  }

  window.RigisTracks = {
    ensureCodes: loadCodes,
    lookup: lookup,

    /** Категориальная кривая? */
    isCategorical: function (mnemonic) {
      var m = (mnemonic || '').toUpperCase();
      return m === 'LITH' || m === 'COLL' || m === 'SAT';
    },
    bookFor: function (mnemonic) {
      var m = (mnemonic || '').toUpperCase();
      return m === 'LITH' ? 'lithology' : (m === 'COLL' ? 'collector' : (m === 'SAT' ? 'saturation' : null));
    },

    /** Отрисовать колонку кодов в прямоугольнике трека. */
    draw: function (ctx, mnemonic, values, depths, x0, w, yTop, yBot, viewStart, viewStop) {
      var book = this.bookFor(mnemonic);
      if (!book || !values || !depths || !values.length) return;
      var span = (viewStop - viewStart) || 1;
      var Y = function (d) { return yTop + (d - viewStart) / span * (yBot - yTop); };
      var runStart = -1, runCode = null;
      for (var i = 0; i <= values.length; i++) {
        var v = (i < values.length) ? values[i] : null;
        var code = (v == null || !isFinite(v)) ? null : Math.round(v);
        if (code !== runCode) {
          if (runCode != null && runStart >= 0) {
            var d1 = depths[runStart], d2 = depths[Math.min(i, depths.length - 1)];
            var y1 = Y(d1), y2 = Y(d2);
            if (y2 > yTop && y1 < yBot) {
              var info = lookup(book, runCode);
              var yy = Math.max(yTop, y1), hh = Math.min(yBot, y2) - yy;
              if (hh > 0) {
                ctx.fillStyle = info.color || '#30363d';
                ctx.fillRect(x0, yy, w, hh);
                if (book === 'lithology' && info.pattern && info.pattern !== 'none') {
                  var pat = makePattern(ctx, info.pattern, info.color || '#30363d');
                  if (pat) { ctx.fillStyle = pat; ctx.fillRect(x0, yy, w, hh); }
                }
                ctx.strokeStyle = 'rgba(13,17,23,.55)'; ctx.lineWidth = 0.5;
                ctx.strokeRect(x0 + 0.25, yy + 0.25, w - 0.5, hh - 0.5);
              }
            }
          }
          runStart = i; runCode = code;
        }
      }
    },

    /** Расшифровка кода на данной глубине (для подсказки у курсора). */
    valueAt: function (mnemonic, values, depths, depth) {
      var book = this.bookFor(mnemonic);
      if (!book || !values || !depths) return null;
      var lo = 0, hi = depths.length - 1, best = -1, bestd = Infinity;
      for (var i = lo; i <= hi; i++) {
        var d = Math.abs(depths[i] - depth);
        if (d < bestd) { bestd = d; best = i; }
      }
      if (best < 0) return null;
      var v = values[best];
      if (v == null || !isFinite(v)) return null;
      var info = lookup(book, v);
      return info ? { code: info.code, label: info.ru, color: info.color } : null;
    },

    /** Легенда встреченных кодов (для панели под планшетом). */
    legendHtml: function (curveData) {
      if (!CODES) return '';
      var books = [['LITH', 'lithology', 'Литология'],
                   ['COLL', 'collector', 'Коллектор'],
                   ['SAT', 'saturation', 'Насыщение']];
      var out = '';
      books.forEach(function (b) {
        var vals = curveData && curveData[b[0]];
        if (!vals || !vals.length) return;
        var seen = {};
        for (var i = 0; i < vals.length; i++) {
          var v = vals[i];
          if (v == null || !isFinite(v)) continue;
          seen[Math.round(v)] = true;
        }
        var keys = Object.keys(seen);
        if (!keys.length) return;
        out += '<div style="margin:6px 0"><b style="color:#c9d1d9">' + b[2] + '</b> ';
        keys.sort(function (a, c) { return a - c; }).forEach(function (k) {
          var info = lookup(b[1], k);
          out += '<span style="display:inline-flex;align-items:center;gap:4px;margin:2px 10px 2px 0;color:#8b949e;font-size:12px">'
            + '<span style="width:12px;height:12px;border:1px solid #30363d;background:' + (info.color || '#30363d') + '"></span>'
            + (info.ru || k) + '</span>';
        });
        out += '</div>';
      });
      return out;
    }
  };
})();
