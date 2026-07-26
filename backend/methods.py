"""
Logging-method registry and mnemonic auto-mapping.

This module is the single source of truth for the *logging methods* (well-log
survey types / "методы ГИС") that GeoLog understands. Each method groups a
family of canonical curve mnemonics and carries display metadata used by the
viewer, the research-coverage map, and the auto-mnemonic mapper.

It is intentionally dependency-free (stdlib only) so it can be imported by the
parser, the API layer, and tests without side effects.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LogMethod:
    """A logging method (survey type) and the curve family that carries it."""
    key: str                     # short stable code, e.g. "GR"
    name: str                    # human name, e.g. "Gamma Ray"
    category: str                # physics group: nuclear/acoustic/electrical/...
    canonical: str               # canonical mnemonic used across the app
    curves: Tuple[str, ...]      # all canonical/aliased mnemonics in this family
    unit: str = ""
    color: str = "#8b949e"
    track: int = 0               # preferred viewer track (0=GR,1=RES,2=POR,3=SAT)
    log_scale: bool = False
    derived: bool = False        # True = computed result, not a measured survey
    keywords: Tuple[str, ...] = field(default_factory=tuple)  # fuzzy-match hints


# ── Method catalogue ────────────────────────────────────────────────────────
# Ordered roughly the way an interpreter reads a log header.
METHODS: List[LogMethod] = [
    # ═══ Российский стандарт ГИС — канонические мнемоники русские ═══
    # --- Электрические / Electrical ---
    LogMethod("PS", "ПС — потенциал собственной поляризации", "electrical", "PS",
              ("PS", "ПС", "СП", "SP", "SPC", "SPCG", "SPRL"), unit="мВ",
              color="#9b59b6", track=0, keywords=("PS", "ПС", "SP", "SPONT")),
    LogMethod("KS", "КС — каротаж сопротивления", "electrical", "KS",
              ("KS", "КС", "RT", "RESD", "RES", "R"), unit="Ом·м",
              color="#e74c3c", track=1, log_scale=True,
              keywords=("KS", "КС", "RT", "RESD")),
    LogMethod("IK", "ИК — индукционный каротаж", "electrical", "IK",
              ("IK", "ИК", "RIK", "РИК", "ILD", "RILD", "ILM", "RILM",
               "CILD", "CILM", "AT90", "AT60"),
              unit="мСм/м", color="#e67e22", track=1, log_scale=True,
              keywords=("IK", "ИК", "ILD", "INDUC")),
    LogMethod("BK", "БК — боковой каротаж", "electrical", "BK",
              ("BK", "БК", "LLD", "LLS", "RLA5", "RLA3"), unit="Ом·м",
              color="#c0392b", track=1, log_scale=True,
              keywords=("BK", "БК", "LLD", "LATER")),
    LogMethod("BKZ", "БКЗ — боковое каротажное зондирование (градиент-зонды)",
              "electrical", "BKZ",
              ("BKZ", "БКЗ", "GZ", "ГЗ", "GZ1", "GZ2", "GZ3", "GZ4", "GZ5",
               "GZ6", "GZ7", "GZ4K", "PZ", "ПЗ"), unit="Ом·м",
              color="#f39c12", track=1, log_scale=True,
              keywords=("BKZ", "БКЗ", "GZ", "ПЗ")),
    LogMethod("MKZ", "МКЗ — микрозонды", "electrical", "MKZ",
              ("MKZ", "МКЗ", "MPZ", "MGZ", "МПЗ", "МГЗ", "BMK", "БМК",
               "MINV", "MNOR", "MLL", "MSFL", "RXO"), unit="Ом·м",
              color="#d35400", track=1, log_scale=True,
              keywords=("MKZ", "МКЗ", "MPZ", "MGZ", "BMK", "MICRO")),
    LogMethod("RS", "РС — резистивиметрия", "electrical", "RS",
              ("RS", "РС", "REZ", "RESIST"), unit="Ом·м",
              color="#16a085", track=1, keywords=("REZIST", "RESIST")),

    # --- Радиоактивные / Nuclear ---
    LogMethod("GK", "ГК — гамма-каротаж", "nuclear", "GK",
              ("GK", "ГК", "GR", "CGR", "SGR", "GRGC", "GRD", "GRR"), unit="мкР/ч",
              color="#2ecc71", track=0, keywords=("GK", "ГК", "GR", "GAMMA")),
    LogMethod("NGK", "НГК — нейтронный гамма-каротаж", "nuclear", "NGK",
              ("NGK", "НГК", "NNK", "ННК", "ННКТ", "NNKT", "NKT", "NNKB",
               "NPHI", "TNPH", "CNLS", "NPRL", "NEUT", "APLC",
               "NKTS", "NKTD", "WNK", "ВНК"), unit="усл.ед.",
              color="#3498db", track=2, keywords=("NGK", "НГК", "NNK", "NPHI", "NEUT")),
    LogMethod("GGKP", "ГГКп — гамма-гамма плотностной каротаж", "nuclear", "GGKP",
              ("GGKP", "ГГКП", "GGK", "ГГК", "RHOB", "RHOZ", "DEN", "RHOC", "ZDEN"),
              unit="г/см³", color="#c0392b", track=2,
              keywords=("GGKP", "ГГК", "RHOB", "DENS")),
    LogMethod("PE", "ФЭП — фотоэлектрический фактор", "nuclear", "PE",
              ("PE", "PEF", "PDPE", "PEFZ", "ФЭП"), unit="б/э", color="#8e44ad",
              track=2, keywords=("PEF", "PHOTO")),
    LogMethod("DRHO", "Поправка плотности", "nuclear", "DRHO",
              ("DRHO", "DCOR", "HDRA"), unit="г/см³", color="#7f8c8d", track=2,
              keywords=("DRHO", "DCOR", "HDRA")),
    LogMethod("YMK", "ЯМК — ядерно-магнитный каротаж", "nuclear", "U1",
              ("U1", "U2", "U3", "ЯМК", "YMK", "NMR",
               "NML1", "NML2", "NML3", "NML"), unit="усл.ед.",
              color="#af7ac5", track=2, keywords=("ЯМК", "YMK")),

    # --- Акустические / Acoustic ---
    LogMethod("AK", "АК — акустический каротаж", "acoustic", "AK",
              ("AK", "АК", "DT", "DTC", "DTP", "DTCO", "AC", "ДТ"), unit="мкс/м",
              color="#1abc9c", track=2, keywords=("AK", "АК", "DT", "ACOUS")),
    LogMethod("AKS", "АК — поперечная волна", "acoustic", "DTS",
              ("DTS", "DTSM", "DTSH"), unit="мкс/м", color="#16a085", track=2,
              keywords=("DTS", "SHEAR")),

    # --- Механические / Mechanical ---
    LogMethod("DS", "ДС — кавернометрия", "mechanical", "DS",
              ("DS", "ДС", "CAL", "CALI", "HCAL", "DCAL", "CLDC", "КВ", "KV",
               "КАВ", "KAV", "DM"), unit="мм",
              color="#95a5a6", track=0, keywords=("DS", "ДС", "CAL", "KAV")),
    LogMethod("BS", "Диаметр долота", "mechanical", "BS",
              ("BS", "BIT", "DN"), unit="мм", color="#7f8c8d", track=0,
              keywords=("BIT",)),

    # --- Газовый и вспомогательные ---
    LogMethod("GAZ", "Газовый каротаж", "geochem", "GAZ",
              ("GAZ", "ГАЗ", "GAS", "SUMGAS"), unit="усл.ед.",
              color="#e84393", track=3, keywords=("GAZ", "ГАЗ", "GAS")),
    LogMethod("TEMP", "Термометрия", "auxiliary", "TEMP",
              ("TEMP", "DTEM", "TEMPC", "ТМ", "ТЕМ"), unit="°C",
              color="#fd79a8", track=0, keywords=("TEMP", "DTEM", "ТМ")),
    # Зенитный угол и азимут — РАЗНЫЕ каналы инклинометрии. Пока они лежали в
    # одном семействе, обе кривые приводились к INKL: первая выигрывала,
    # вторая отбрасывалась как дубль, азимут читался как зенит — траектория
    # и TVD получались бессмысленными.
    LogMethod("INKL", "Инклинометрия — зенитный угол", "auxiliary", "INKL",
              ("INKL", "INCL", "ИНКЛ", "ZENIT", "ZENITH", "DEVI", "INK",
               "ЗЕНИТ", "ЗЕН", "УГОЛ", "UGOL", "ANGLE"),
              unit="град", color="#636e72", track=0,
              keywords=("INCL", "INKL", "ZENIT", "ЗЕНИТ", "УГОЛ")),
    LogMethod("AZIM", "Инклинометрия — азимут", "auxiliary", "AZ",
              ("AZ", "AZIM", "AZIMUTH", "АЗИМУТ", "АЗ", "AZI"),
              unit="град", color="#7f8fa6", track=0,
              keywords=("AZIM", "АЗИМУТ", "AZIMUTH")),

    # --- Результаты интерпретации (РИГИС) ---
    LogMethod("KP", "Кп — пористость", "interpretation", "KP",
              ("KP", "КП", "КП_W", "KP_W", "PHIE", "PHIT", "КПЭФ"), unit="д.ед.",
              color="#f1c40f", track=2, derived=True, keywords=("КП", "PHIE", "PORO")),
    LogMethod("KGL", "Кгл — глинистость", "interpretation", "KGL",
              ("KGL", "КГЛ", "КГЛ_ГК", "KGL_GK", "VSH", "VCL", "VSHALE"),
              unit="д.ед.", color="#7f8c8d", track=3, derived=True,
              keywords=("КГЛ", "VSH", "VCL")),
    # Кнг и Кв — ДОПОЛНЯЮЩИЕ величины (Кв = 1 − Кнг), поэтому это разные
    # методы: пока SW/SWE лежали в семействе КНГ, водонасыщенность
    # подменялась нефтегазонасыщенностью и отбор коллектора инвертировался.
    LogMethod("KNG", "Кнг — нефтегазонасыщенность", "interpretation", "KNG",
              ("KNG", "КНГ", "КНГ_W", "KNG_W", "КН", "SO", "SOIL", "SHC"),
              unit="д.ед.", color="#2980b9", track=3, derived=True,
              keywords=("КНГ", "НЕФТЕНАС", "ГАЗОНАС")),
    LogMethod("KV", "Кв — водонасыщенность", "interpretation", "SW",
              ("SW", "SWT", "SWE", "КВ_W", "KV_W", "SW_W", "SWA"),
              unit="д.ед.", color="#3498db", track=3, derived=True,
              keywords=("КВ", "ВОДОНАС", "WATER SAT")),
    LogMethod("KPR", "Кпр — проницаемость", "interpretation", "KPR",
              ("KPR", "КПР", "ПРОН", "PERM", "KINT", "KLOGH"), unit="мД",
              color="#af7ac5", track=3, log_scale=True, derived=True,
              keywords=("КПР", "ПРОН", "PERM")),
    LogMethod("LITH", "Литология", "interpretation", "LITH",
              ("LITH", "ЛИТОЛОГИЯ", "ЛИТ", "LITOLOG", "FACIES"), unit="код",
              color="#a0522d", track=4, derived=True, keywords=("ЛИТОЛ", "LITHOL")),
    LogMethod("COLL", "Коллектор", "interpretation", "COLL",
              ("COLL", "КОЛЛЕКТОР", "КОЛЛ", "KOLLEKTOR"), unit="код",
              color="#3fb950", track=4, derived=True, keywords=("КОЛЛЕКТ",)),
    LogMethod("SAT", "Насыщение", "interpretation", "SAT",
              ("SAT", "НАСЫЩЕНИЕ", "НАСЫЩ", "NASYSH"), unit="код",
              color="#8b5a2b", track=4, derived=True, keywords=("НАСЫЩ",)),
]

# Fast lookups -----------------------------------------------------------------
METHOD_BY_KEY: Dict[str, LogMethod] = {m.key: m for m in METHODS}

# canonical/aliased mnemonic -> method
_MNEMONIC_TO_METHOD: Dict[str, LogMethod] = {}
for _m in METHODS:
    for _c in _m.curves:
        _MNEMONIC_TO_METHOD.setdefault(_c.upper(), _m)

# canonical mnemonic each raw alias should normalize to (family canonical)
ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _m in METHODS:
    for _c in _m.curves:
        ALIAS_TO_CANONICAL.setdefault(_c.upper(), _m.canonical)


def method_for_mnemonic(mnemonic: str) -> Optional[LogMethod]:
    """Return the LogMethod a (possibly aliased) mnemonic belongs to, or None."""
    if not mnemonic:
        return None
    up = mnemonic.strip().upper()
    meth = _MNEMONIC_TO_METHOD.get(up)
    if meth is not None:
        return meth
    # honour user-defined custom aliases (raw -> canonical)
    canon = CUSTOM_ALIASES.get(up)
    if canon:
        return _MNEMONIC_TO_METHOD.get(canon.upper())
    # variant fallback: KS_500, GK_500_2, GZ4_500_3 … belong to their family,
    # so coverage/analytics must see them as that method too.
    core = _strip_variants(up)
    if core != up:
        meth = _MNEMONIC_TO_METHOD.get(core)
        if meth is not None:
            return meth
        canon = CUSTOM_ALIASES.get(core)
        if canon:
            return _MNEMONIC_TO_METHOD.get(canon.upper())
    return None


# ── User-defined custom aliases (editable defaults + Excel/CSV import) ────────
# Persisted as a flat {RAW: CANONICAL} JSON map so operators can teach GeoLog
# their own vendor mnemonics without code changes. Overrides the built-in table.
CUSTOM_ALIASES: Dict[str, str] = {}

_CUSTOM_PATH = os.environ.get(
    "GEOLOG_CUSTOM_MNEMONICS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_mnemonics.json"),
)


def load_custom_aliases() -> Dict[str, str]:
    """(Re)load the custom-alias map from disk into CUSTOM_ALIASES."""
    global CUSTOM_ALIASES
    data: Dict[str, str] = {}
    try:
        with open(_CUSTOM_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            for k, v in raw.items():
                rk, rv = str(k).strip().upper(), str(v).strip().upper()
                if rk and rv:
                    data[rk] = rv
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    CUSTOM_ALIASES = data
    return CUSTOM_ALIASES


def save_custom_aliases() -> None:
    try:
        with open(_CUSTOM_PATH, "w", encoding="utf-8") as fh:
            json.dump(CUSTOM_ALIASES, fh, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        pass


def set_custom_alias(raw: str, canonical: str) -> Dict[str, str]:
    rk, rv = str(raw or "").strip().upper(), str(canonical or "").strip().upper()
    if not rk or not rv:
        raise ValueError("raw and canonical are required")
    CUSTOM_ALIASES[rk] = rv
    save_custom_aliases()
    return {"raw": rk, "canonical": rv}


def remove_custom_alias(raw: str) -> bool:
    rk = str(raw or "").strip().upper()
    if rk in CUSTOM_ALIASES:
        del CUSTOM_ALIASES[rk]
        save_custom_aliases()
        return True
    return False


def import_custom_aliases(pairs, replace: bool = False) -> Dict[str, int]:
    """Merge (raw, canonical) pairs into the custom map. Returns counts."""
    global CUSTOM_ALIASES
    if replace:
        CUSTOM_ALIASES = {}
    added = 0
    skipped = 0
    for raw, canon in pairs:
        rk, rv = str(raw or "").strip().upper(), str(canon or "").strip().upper()
        if not rk or not rv:
            skipped += 1
            continue
        CUSTOM_ALIASES[rk] = rv
        added += 1
    save_custom_aliases()
    return {"added": added, "skipped": skipped, "total": len(CUSTOM_ALIASES)}


# load persisted custom aliases at import time
load_custom_aliases()


# ── Mnemonic auto-mapping ────────────────────────────────────────────────────
_TRAILING_JUNK = re.compile(r"[\s_\-]*\d+$")           # GR_1, RHOB-2
_TOOL_SUFFIX = re.compile(r"(_[A-Z]{1,4})$")           # GR_EDTC, RHOB_HRT


def _strip_variants(raw: str) -> str:
    """Reduce a vendor mnemonic to a comparable core token.

    Strips repeated trailing numeric/scale suffixes and short tool suffixes so
    e.g. GK_500_2 -> GK, NGK_500 -> NGK, GZ4_500_3 -> GZ4 (then GZ via alias).
    """
    m = (raw or "").strip().upper()
    prev = None
    while prev != m:
        prev = m
        m = _TRAILING_JUNK.sub("", m)   # drop trailing _500, _2, -1 …
        m = _TOOL_SUFFIX.sub("", m)     # drop trailing _EDTC, _HRT …
    return m


@dataclass
class MnemonicSuggestion:
    raw: str
    canonical: str
    method_key: Optional[str]
    method_name: Optional[str]
    confidence: float            # 0..1
    reason: str
    already_canonical: bool

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "canonical": self.canonical,
            "method_key": self.method_key,
            "method_name": self.method_name,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "already_canonical": self.already_canonical,
        }


def suggest_mnemonic(raw: str) -> MnemonicSuggestion:
    """
    Best-effort normalization of an arbitrary vendor mnemonic to a canonical
    family mnemonic, with a confidence score and a human-readable reason.

    Resolution order (highest confidence first):
      1. exact alias/canonical hit           → 1.0
      2. stripped-variant alias hit          → 0.9
      3. keyword / substring heuristic       → 0.6
      4. no match                            → 0.0 (canonical == raw)
    """
    up = (raw or "").strip().upper()
    if not up:
        return MnemonicSuggestion(raw, raw, None, None, 0.0, "empty", False)

    # 0) user-defined custom alias — highest priority
    if up in CUSTOM_ALIASES:
        canon = CUSTOM_ALIASES[up]
        meth = _MNEMONIC_TO_METHOD.get(canon.upper())
        already = up == canon
        return MnemonicSuggestion(
            raw, canon, meth.key if meth else None,
            meth.name if meth else None, 1.0,
            "canonical" if already else "custom", already)

    # 1) exact
    if up in ALIAS_TO_CANONICAL:
        canon = ALIAS_TO_CANONICAL[up]
        meth = _MNEMONIC_TO_METHOD.get(up)
        already = up == canon
        return MnemonicSuggestion(
            raw, canon, meth.key if meth else None,
            meth.name if meth else None, 1.0,
            "canonical" if already else "exact-alias", already)

    # 2) stripped variant
    core = _strip_variants(up)
    if core in ALIAS_TO_CANONICAL:
        canon = ALIAS_TO_CANONICAL[core]
        meth = _MNEMONIC_TO_METHOD.get(core)
        return MnemonicSuggestion(
            raw, canon, meth.key if meth else None,
            meth.name if meth else None, 0.9,
            f"variant-of {core}", False)

    # 3) keyword heuristic — pick the longest keyword that matches. Short
    # keywords (≤2 chars) match by prefix only; substring matching is reserved
    # for longer keywords so tokens like TOPS/ROCKS don't map via PS/KS.
    best: Optional[Tuple[int, LogMethod]] = None
    for meth in METHODS:
        for kw in meth.keywords:
            if not kw:
                continue
            hit = up.startswith(kw) or core.startswith(kw)
            if not hit and len(kw) >= 3:
                hit = kw in up
            if hit:
                score = len(kw) + (2 if up.startswith(kw) else 0)
                if best is None or score > best[0]:
                    best = (score, meth)
    if best is not None:
        meth = best[1]
        return MnemonicSuggestion(
            raw, meth.canonical, meth.key, meth.name, 0.6,
            f"keyword~{meth.key}", False)

    # 4) unknown
    return MnemonicSuggestion(raw, up, None, None, 0.0, "unknown", False)


def methods_catalog() -> List[dict]:
    """Serializable catalogue of all supported logging methods."""
    return [
        {
            "key": m.key,
            "name": m.name,
            "category": m.category,
            "canonical": m.canonical,
            "curves": list(m.curves),
            "unit": m.unit,
            "color": m.color,
            "track": m.track,
            "log_scale": m.log_scale,
            "derived": m.derived,
        }
        for m in METHODS
    ]
