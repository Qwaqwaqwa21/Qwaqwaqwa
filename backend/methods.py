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
    # --- Potential / spontaneous ---
    LogMethod("SP", "Spontaneous Potential", "potential", "SP",
              ("SP", "SPC", "SPCG", "SPRL", "ПС", "СП"), unit="MV",
              color="#9b59b6", track=0, keywords=("SP", "SPONT", "SELFP", "ПС")),

    # --- Natural radioactivity ---
    LogMethod("GR", "Gamma Ray", "nuclear", "GR",
              ("GR", "CGR", "SGR", "GRGC", "GRD", "GRR", "ГК"), unit="GAPI",
              color="#2ecc71", track=0, keywords=("GR", "GAMMA", "GAPI", "ГК")),
    LogMethod("KTH", "Spectral Gamma (K/Th/U)", "nuclear", "POTA",
              ("POTA", "THOR", "URAN", "K", "TH", "U"), unit="",
              color="#27ae60", track=0, derived=False,
              keywords=("POTA", "THOR", "URAN", "SPECTR")),

    # --- Mechanical ---
    LogMethod("CAL", "Caliper", "mechanical", "CAL",
              ("CAL", "CALI", "HCAL", "DCAL", "CLDC", "BS", "LCAL",
               "ДС", "КВ", "КАВ"), unit="IN",
              color="#95a5a6", track=0,
              keywords=("CAL", "CALIP", "BIT", "BS", "ДС", "КАВ")),

    # --- Electrical / resistivity ---
    LogMethod("RES", "Deep Resistivity", "electrical", "RT",
              ("RT", "RESD", "RES", "ILD", "RILD", "LLD", "RLA5", "RD", "AT90",
               "CILD", "БК", "БКЗ", "ИК", "КС", "ПЗ", "ГЗ"),
              unit="OHMM", color="#e74c3c", track=1, log_scale=True,
              keywords=("RDEEP", "RDEP", "RLLD", "RT", "RES", "ILD", "LLD",
                        "DEEP", "AT90", "RLA", "БК", "ИК")),
    LogMethod("RESM", "Medium Resistivity", "electrical", "RILM",
              ("RILM", "ILM", "LLM", "RLA3", "RM", "AT60", "CILM"), unit="OHMM",
              color="#e67e22", track=1, log_scale=True,
              keywords=("RMEDIUM", "RMED", "RLLM", "ILM", "MEDIUM", "AT60",
                        "RLA3", "RILM")),
    LogMethod("RESS", "Shallow / Flushed Resistivity", "electrical", "RXO",
              ("RXO", "MSFL", "RLL3", "LL3", "SFL", "RXORT", "AT10", "RS", "БМК"),
              unit="OHMM", color="#f39c12", track=1, log_scale=True,
              keywords=("RSHALLOW", "RSHAL", "RSHL", "RLLS", "RXO", "MSFL",
                        "SFL", "SHALLOW", "FLUSH", "AT10", "БМК")),
    LogMethod("MICRO", "Microresistivity", "electrical", "MINV",
              ("MINV", "MNOR", "MI", "MN", "MLL", "RMLL", "МК"), unit="OHMM",
              color="#d35400", track=1, log_scale=True,
              keywords=("MICRO", "RMLL", "MLL", "MINV", "MNOR", "МК")),

    # --- Density (gamma-gamma) ---
    LogMethod("DEN", "Bulk Density", "nuclear", "RHOB",
              ("RHOB", "RHOZ", "DEN", "RHOC", "ZDEN", "DGA", "ГГК", "ГГКП"),
              unit="G/CC", color="#c0392b", track=2,
              keywords=("RHOB", "RHOZ", "DENS", "ZDEN", "ГГК")),
    LogMethod("DRHO", "Density Correction", "nuclear", "DRHO",
              ("DRHO", "DCOR", "HDRA"), unit="G/CC", color="#7f8c8d", track=2,
              keywords=("DRHO", "DCOR", "HDRA", "CORR")),
    LogMethod("PE", "Photoelectric Factor", "nuclear", "PE",
              ("PE", "PEF", "PDPE", "FEFE", "PEFZ"), unit="B/E", color="#8e44ad",
              track=2, keywords=("PE", "PEF", "PHOTO")),

    # --- Neutron ---
    LogMethod("NEU", "Neutron Porosity", "nuclear", "NPHI",
              ("NPHI", "TNPH", "CNLS", "NPRL", "NEUT", "CNC", "APLC",
               "НГК", "ННК", "ННКТ", "НКТ"), unit="V/V",
              color="#3498db", track=2,
              keywords=("NPHI", "NEUT", "TNPH", "CN", "НГК", "ННК")),

    # --- Acoustic ---
    LogMethod("SON", "Compressional Sonic", "acoustic", "DT",
              ("DT", "DTC", "DTP", "DT35", "AC", "DTCO", "АК", "ДТ", "ИНК"),
              unit="US/F", color="#1abc9c", track=2,
              keywords=("DT", "SON", "ACOUS", "SLOW", "АК", "ДТ")),
    LogMethod("SONS", "Shear Sonic", "acoustic", "DTS",
              ("DTS", "DTSM", "DTSH"), unit="US/F", color="#16a085", track=2,
              keywords=("DTS", "SHEAR")),

    # --- Auxiliary measured ---
    LogMethod("TEMP", "Borehole Temperature", "auxiliary", "TEMP",
              ("TEMP", "DTEM", "TEMPC", "ТМ", "ТЕМ"), unit="DEGC",
              color="#e84393", track=0, keywords=("TEMP", "DTEM", "ТМ")),

    # --- Derived / interpreted results ---
    LogMethod("DPOR", "Density Porosity", "derived", "DPOR",
              ("DPOR", "PHID"), unit="V/V", color="#d68910", track=2,
              derived=True, keywords=("DPOR", "PHID")),
    LogMethod("PHIE", "Effective Porosity", "derived", "PHIE",
              ("PHIE", "PHIT"), unit="V/V", color="#f1c40f", track=2,
              derived=True, keywords=("PHIE", "PHIT", "PORO")),
    LogMethod("VSH", "Shale Volume", "derived", "VSH",
              ("VSH", "VCL", "VSHALE"), unit="V/V", color="#7f8c8d", track=3,
              derived=True, keywords=("VSH", "VCL", "SHALE")),
    LogMethod("SW", "Water Saturation", "derived", "SW",
              ("SW", "SWT", "SWE"), unit="V/V", color="#2980b9", track=3,
              derived=True, keywords=("SW", "SATUR")),
    LogMethod("BVW", "Bulk Volume Water", "derived", "BVW",
              ("BVW",), unit="V/V", color="#3498db", track=3, derived=True,
              keywords=("BVW",)),
    LogMethod("PERM", "Permeability", "derived", "PERM",
              ("PERM", "KINT", "KLOGH"), unit="MD", color="#af7ac5", track=3,
              log_scale=True, derived=True, keywords=("PERM", "KINT", "KLOG")),
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
    """Reduce a vendor mnemonic to a comparable core token."""
    m = (raw or "").strip().upper()
    m = _TRAILING_JUNK.sub("", m)
    prev = None
    while prev != m:
        prev = m
        m = _TOOL_SUFFIX.sub("", m)
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

    # 3) keyword / substring heuristic — pick the longest keyword that matches
    best: Optional[Tuple[int, LogMethod]] = None
    for meth in METHODS:
        for kw in meth.keywords:
            if kw and (up.startswith(kw) or core.startswith(kw) or kw in up):
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
