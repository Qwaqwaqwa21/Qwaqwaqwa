"""Tests for Cyrillic/UTF-8 curve support and custom mnemonic aliases."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import methods  # noqa: E402
from methods import suggest_mnemonic  # noqa: E402
from las_parser import LASParser  # noqa: E402


# ── Cyrillic mnemonic mapping ────────────────────────────────────────────────
def test_cyrillic_aliases_map_to_canonical():
    cases = {"ГК": "GR", "ПС": "SP", "НГК": "NPHI", "БК": "RT",
             "ГГКП": "RHOB", "АК": "DT", "ДС": "CAL", "МК": "MINV"}
    for raw, canon in cases.items():
        s = suggest_mnemonic(raw)
        assert s.canonical == canon, (raw, s.canonical)
        assert s.confidence == 1.0


# ── Encoding detection ───────────────────────────────────────────────────────
def test_decode_cp1251_bytes():
    text = "WELL. Скважина-7 : имя"
    assert LASParser.decode_bytes(text.encode("cp1251")) == text
    assert LASParser.decode_bytes(text.encode("utf-8")) == text


def test_latin_transliterated_russian_gis_codes():
    """Real Russian LAS use Latin-transliterated method codes."""
    cases = {"GK": "GR", "PS": "SP", "KS": "RT", "NGK": "NPHI", "BK": "RT",
             "IK": "RT", "DS": "CAL", "GZ1": "RT", "MPZ": "MINV", "MGZ": "MINV",
             "INCL": "INCL", "AZ": "INCL"}
    for raw, canon in cases.items():
        s = suggest_mnemonic(raw)
        assert s.canonical == canon, (raw, s.canonical)
        assert s.confidence >= 0.6


def test_scale_suffix_variants_strip_to_family():
    for raw, canon in [("GK_500", "GR"), ("GK_500_2", "GR"), ("NGK_500", "NPHI"),
                       ("GZ4_500_3", "RT"), ("PS_1", "SP")]:
        s = suggest_mnemonic(raw)
        assert s.canonical == canon, (raw, s.canonical)


def test_no_false_positive_uranium():
    # U1/U2 must NOT map to spectral uranium (was a keyword false positive)
    for raw in ("U1", "U2"):
        assert suggest_mnemonic(raw).confidence == 0.0


def test_russian_interpreted_curves():
    for raw, canon in [("КГЛ", "VSH"), ("КП", "PHIE"), ("ЛИТОЛОГИЯ", "LITH"),
                       ("НАСЫЩЕНИЕ", "SAT")]:
        assert suggest_mnemonic(raw).canonical == canon, raw


def test_parse_cyrillic_las_cp1251():
    las_txt = (
        "~Version\nVERS. 2.0 :\nWRAP. NO :\n"
        "~Well\nSTRT.M 100 :\nSTOP.M 103 :\nSTEP.M 1 :\nNULL. -999.25 :\n"
        "WELL. Скважина-7 : name\n"
        "~Curve\nDEPT.M :\nГК.мкР/ч :\nПС.мВ :\nНЕЧТО.xx :\n"
        "~ASCII\n100 55 -12 1\n101 60 -13 2\n102 58 -11 3\n"
    )
    parsed = LASParser.parse_bytes(las_txt.encode("cp1251"))
    assert parsed.well.well_name == "Скважина-7"
    mnems = [c.mnemonic for c in parsed.curves]
    assert "GR" in mnems and "SP" in mnems      # ГК/ПС normalized
    assert "НЕЧТО" in mnems                       # unknown Cyrillic preserved
    assert len(parsed.depth) == 3


# ── Custom aliases ───────────────────────────────────────────────────────────
def _isolate(tmp_path):
    methods._CUSTOM_PATH = str(tmp_path / "custom.json")
    methods.CUSTOM_ALIASES = {}


def test_custom_alias_overrides_suggestion(tmp_path):
    _isolate(tmp_path)
    methods.set_custom_alias("XZY", "GR")
    s = suggest_mnemonic("XZY")
    assert s.canonical == "GR"
    assert s.reason == "custom"
    assert s.method_key == "GR"


def test_custom_alias_remove(tmp_path):
    _isolate(tmp_path)
    methods.set_custom_alias("WEIRD", "RHOB")
    assert methods.remove_custom_alias("weird") is True
    assert suggest_mnemonic("WEIRD").confidence == 0.0
    assert methods.remove_custom_alias("WEIRD") is False


def test_custom_alias_import_pairs(tmp_path):
    _isolate(tmp_path)
    res = methods.import_custom_aliases([("AA1", "GR"), ("BB2", "RT"), ("", "GR")])
    assert res["added"] == 2 and res["skipped"] == 1
    assert suggest_mnemonic("AA1").canonical == "GR"
    assert suggest_mnemonic("BB2").canonical == "RT"


def test_custom_alias_persists_to_disk(tmp_path):
    _isolate(tmp_path)
    methods.set_custom_alias("PERSIST1", "NPHI")
    methods.CUSTOM_ALIASES = {}
    methods.load_custom_aliases()
    assert methods.CUSTOM_ALIASES.get("PERSIST1") == "NPHI"
