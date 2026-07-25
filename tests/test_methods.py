"""Tests for the logging-method registry and mnemonic auto-mapper."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from methods import (  # noqa: E402
    METHODS,
    methods_catalog,
    method_for_mnemonic,
    suggest_mnemonic,
)


def test_catalog_is_populated_and_serializable():
    cat = methods_catalog()
    assert len(cat) == len(METHODS)
    assert all({"key", "name", "category", "canonical", "curves"} <= set(m) for m in cat)
    # keys are unique
    keys = [m["key"] for m in cat]
    assert len(keys) == len(set(keys))


def test_exact_alias_high_confidence():
    for raw, canon in [("ILD", "IK"), ("ZDEN", "GGKP"), ("APLC", "NGK"),
                       ("DTCO", "AK"), ("KLOGH", "KPR"), ("MLL", "MKZ")]:
        s = suggest_mnemonic(raw)
        assert s.canonical == canon, (raw, s.canonical)
        assert s.confidence == 1.0
        assert s.method_key is not None


def test_canonical_is_flagged_and_not_renamable():
    s = suggest_mnemonic("GK")
    assert s.already_canonical is True
    assert s.canonical == "GK"


def test_variant_stripping():
    s = suggest_mnemonic("GGKP_HRT")
    assert s.canonical == "GGKP"
    assert s.confidence >= 0.9


def test_fuzzy_keyword_matches():
    for raw, canon in [("GAMMA1", "GK"), ("NEUTRON", "NGK"),
                       ("ACOUS1", "AK"), ("INDUCX", "IK")]:
        s = suggest_mnemonic(raw)
        assert s.canonical == canon, (raw, s.canonical)
        assert 0.5 <= s.confidence < 1.0


def test_unknown_mnemonic_is_left_alone():
    s = suggest_mnemonic("CGXT")
    assert s.confidence == 0.0
    assert s.method_key is None
    assert s.canonical == "CGXT"


def test_method_for_mnemonic_family_grouping():
    assert method_for_mnemonic("KS").key == "KS"
    assert method_for_mnemonic("GZ1").key == "BKZ"
    assert method_for_mnemonic("NGK").key == "NGK"
    assert method_for_mnemonic("UNKNOWNX") is None
