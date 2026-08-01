"""Tests for study-level (metadata) duplicate-study detection
(backend/routers/duplicates.py, added in commit 1971ba3)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from routers.duplicates import (  # noqa: E402
    _normalize_well_name,
    _run_methods,
    _depth_overlap_fraction,
    _run_side,
    _compare_study_pair,
    _find_duplicate_studies,
)


class FakeRun:
    def __init__(self, run_id, run_number, filename, start_depth, stop_depth, methods,
                 digitization_status="pending_review"):
        self.id = run_id
        self.run_number = run_number
        self.filename = filename
        self.start_depth = start_depth
        self.stop_depth = stop_depth
        self.curves_json = json.dumps([{"mnemonic": m} for m in methods])
        self.digitization_status = digitization_status


class FakeWell:
    def __init__(self, well_id, name, field_name, runs):
        self.id = well_id
        self.name = name
        self.field_name = field_name
        self.log_runs = list(runs)


# ─── _normalize_well_name ────────────────────────────────────────

def test_normalize_well_name_strips_ru_en_noise():
    assert _normalize_well_name("Скв. 105") == _normalize_well_name("105")
    assert _normalize_well_name("well-105") == _normalize_well_name("105")


# ─── _run_methods ─────────────────────────────────────────────────

def test_run_methods_excludes_depth_mnemonics():
    run = FakeRun(1, 1, "a.las", 1000.0, 1100.0, ["MD", "GR", "NGK"])
    assert _run_methods(run) == {"GR", "NGK"}


def test_run_methods_handles_bad_json():
    run = FakeRun(1, 1, "a.las", 1000.0, 1100.0, [])
    run.curves_json = "not json"
    assert _run_methods(run) == set()


# ─── _depth_overlap_fraction ──────────────────────────────────────

def test_depth_overlap_fraction_full_overlap():
    a = FakeRun(1, 1, "a.las", 1000.0, 1100.0, ["GR"])
    b = FakeRun(2, 1, "b.las", 1000.0, 1100.0, ["GR"])
    assert _depth_overlap_fraction(a, b) == 1.0


def test_depth_overlap_fraction_no_overlap():
    a = FakeRun(1, 1, "a.las", 1000.0, 1100.0, ["GR"])
    b = FakeRun(2, 1, "b.las", 2000.0, 2100.0, ["GR"])
    assert _depth_overlap_fraction(a, b) == 0.0


def test_depth_overlap_fraction_missing_depth_is_none():
    a = FakeRun(1, 1, "a.las", None, None, ["GR"])
    b = FakeRun(2, 1, "b.las", 1000.0, 1100.0, ["GR"])
    assert _depth_overlap_fraction(a, b) is None


# ─── _compare_study_pair / _find_duplicate_studies ────────────────

def test_same_well_overlapping_runs_flagged_same_well():
    well = FakeWell(1, "105", "FieldA",
                     [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"]),
                      FakeRun(2, 2, "b.las", 1050.0, 1250.0, ["GR", "NGK"])])
    match = _compare_study_pair(well, well.log_runs[0], well, well.log_runs[1], 0.5, 0.5)
    assert match is not None
    assert match["reason"] == "same_well"
    assert match["cross_well"] is False


def test_cross_well_same_normalized_name_flagged():
    # Same (non-blank, matching) field_name is required to even consider a
    # cross-well pair — the name match is what tips the reason to
    # cross_well_same_name rather than cross_well_similar_field.
    well_a = FakeWell(1, "105", "FieldA", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"])])
    well_b = FakeWell(2, "Скв. 105", "FieldA", [FakeRun(2, 1, "b.las", 1050.0, 1250.0, ["GR", "NGK"])])
    match = _compare_study_pair(well_a, well_a.log_runs[0], well_b, well_b.log_runs[0], 0.5, 0.5)
    assert match is not None
    assert match["reason"] == "cross_well_same_name"
    assert match["cross_well"] is True


def test_cross_well_different_names_same_field_flagged_similar_field():
    well_a = FakeWell(1, "105", "Priobskoye", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"])])
    well_b = FakeWell(2, "210", "Priobskoye", [FakeRun(2, 1, "b.las", 1050.0, 1250.0, ["GR", "NGK"])])
    match = _compare_study_pair(well_a, well_a.log_runs[0], well_b, well_b.log_runs[0], 0.5, 0.5)
    assert match is not None
    assert match["reason"] == "cross_well_similar_field"
    assert match["cross_well"] is True


def test_cross_well_blank_field_names_not_flagged():
    """Blank field_name on both sides means 'unknown', not 'same field' —
    must not be flagged as cross_well_similar_field."""
    well_a = FakeWell(1, "105", "", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"])])
    well_b = FakeWell(2, "210", "", [FakeRun(2, 1, "b.las", 1050.0, 1250.0, ["GR", "NGK"])])
    match = _compare_study_pair(well_a, well_a.log_runs[0], well_b, well_b.log_runs[0], 0.5, 0.5)
    assert match is None


def test_depth_overlap_below_threshold_not_flagged():
    well_a = FakeWell(1, "105", "FieldA", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"])])
    well_b = FakeWell(2, "105", "FieldA", [FakeRun(2, 1, "b.las", 1190.0, 1400.0, ["GR", "NGK"])])
    # overlap = 10 / 200 = 0.05, well below default 0.5 threshold
    match = _compare_study_pair(well_a, well_a.log_runs[0], well_b, well_b.log_runs[0], 0.5, 0.5)
    assert match is None


def test_method_overlap_below_threshold_not_flagged():
    well_a = FakeWell(1, "105", "FieldA", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK", "DT", "SP"])])
    well_b = FakeWell(2, "105", "FieldA", [FakeRun(2, 1, "b.las", 1000.0, 1200.0, ["GR", "XYZ", "ABC"])])
    # shared={GR} → overlap = 1/min(4,3) = 0.333, below default 0.5 threshold
    match = _compare_study_pair(well_a, well_a.log_runs[0], well_b, well_b.log_runs[0], 0.5, 0.5)
    assert match is None


def test_find_duplicate_studies_across_multiple_wells():
    well_a = FakeWell(1, "105", "FieldA", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR", "NGK"])])
    well_b = FakeWell(2, "Скв. 105", "FieldA", [FakeRun(2, 1, "b.las", 1050.0, 1250.0, ["GR", "NGK"])])
    well_c = FakeWell(3, "999", "FieldZ", [FakeRun(3, 1, "c.las", 5000.0, 5200.0, ["GR", "NGK"])])
    dupes = _find_duplicate_studies([well_a, well_b, well_c], 0.5, 0.5)
    assert len(dupes) == 1
    assert dupes[0]["cross_well"] is True


def test_run_side_shape():
    well = FakeWell(1, "105", "FieldA", [FakeRun(1, 1, "a.las", 1000.0, 1200.0, ["GR"], "accepted")])
    side = _run_side(well, well.log_runs[0])
    assert side["id"] == 1
    assert side["name"] == "105"
    assert side["run_id"] == 1
    assert side["digitization_status"] == "accepted"
