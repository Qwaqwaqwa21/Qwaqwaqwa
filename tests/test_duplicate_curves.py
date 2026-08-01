"""Tests for the full-curve-duplication QC check (backend/routers/duplicates.py)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from routers.duplicates import _well_curves, _find_duplicates  # noqa: E402


class FakeCurve:
    def __init__(self, mnemonic, values, unit=""):
        self.mnemonic = mnemonic
        self.unit = unit
        self.data_binary = np.asarray(values, dtype=np.float64).tobytes()


class FakeRun:
    def __init__(self, run_id, filename, curves, depth=None, start_depth=0.0, step=1.0, num_points=None):
        self.id = run_id
        self.filename = filename
        self.curve_data = list(curves)
        self.start_depth = start_depth
        self.step = step
        self.num_points = num_points or (len(depth) if depth is not None else 0)
        if depth is not None:
            self.curve_data = [FakeCurve("MD", depth)] + self.curve_data


class FakeWell:
    def __init__(self, well_id, name, runs):
        self.id = well_id
        self.name = name
        self.log_runs = list(runs)


def test_no_false_positive_between_distinct_curves():
    depth = np.arange(0, 100, 1.0)
    gr = np.sin(depth / 10.0) * 50 + 75
    ngk = np.cos(depth / 7.0) * 3 + 1
    run = FakeRun(1, "well.las", [FakeCurve("GR", gr), FakeCurve("NGK", ngk)], depth=depth)
    well = FakeWell(1, "A", [run])

    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tol=1e-6, min_points=20, min_coverage=0.9)
    assert dupes == []


def test_exact_duplicate_within_same_run_is_flagged():
    depth = np.arange(0, 100, 1.0)
    gr = np.sin(depth / 10.0) * 50 + 75
    run = FakeRun(1, "well.las", [FakeCurve("GR", gr), FakeCurve("GR_COPY", gr.copy())], depth=depth)
    well = FakeWell(1, "A", [run])

    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tol=1e-6, min_points=20, min_coverage=0.9)
    assert len(dupes) == 1
    mnems = {dupes[0]["well_a"]["mnemonic"], dupes[0]["well_b"]["mnemonic"]}
    assert mnems == {"GR", "GR_COPY"}
    assert dupes[0]["coverage"] == 1.0


def test_duplicate_across_runs_joined_on_depth():
    depth1 = np.arange(0, 100, 1.0)
    depth2 = np.arange(0, 100, 1.0) + 0.0002  # sub-tolerance jitter, still joins after rounding
    val = np.sin(depth1 / 5.0) * 20
    run1 = FakeRun(1, "run1.las", [FakeCurve("GK", val)], depth=depth1)
    run2 = FakeRun(2, "run2.las", [FakeCurve("GAMMA", val.copy())], depth=depth2)
    well = FakeWell(1, "A", [run1, run2])

    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tol=1e-6, min_points=20, min_coverage=0.9)
    assert len(dupes) == 1
    assert dupes[0]["well_a"]["run_id"] != dupes[0]["well_b"]["run_id"]


def test_sparse_overlap_below_min_points_not_flagged():
    depth = np.arange(0, 1000, 1.0)
    a = np.full(len(depth), np.nan)
    b = np.full(len(depth), np.nan)
    a[:5] = 1.0
    b[:5] = 1.0  # only 5 shared valid points, below default min_points
    run = FakeRun(1, "well.las", [FakeCurve("A", a), FakeCurve("B", b)], depth=depth)
    well = FakeWell(1, "A", [run])

    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tol=1e-6, min_points=20, min_coverage=0.9)
    assert dupes == []


def test_gradient_probe_family_not_falsely_flagged():
    """GZ1..GZ5 (BKZ lateral-sounding gradient probes) are genuinely different
    curves even though they belong to one logging method family — they must
    never be reported as duplicates just because they're numerically close."""
    depth = np.arange(0, 200, 1.0)
    rng = np.random.default_rng(0)
    gz = {f"GZ{i}": 5 + i + rng.normal(0, 0.01, len(depth)) for i in range(1, 6)}
    run = FakeRun(1, "well.las", [FakeCurve(k, v) for k, v in gz.items()], depth=depth)
    well = FakeWell(1, "A", [run])

    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tol=1e-6, min_points=20, min_coverage=0.9)
    assert dupes == []
