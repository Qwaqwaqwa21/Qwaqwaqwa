#!/usr/bin/env python3
"""Generate synthetic wells for QA load testing (task #24).

Populates the GeoLog sqlite DB directly (bypassing the LAS-upload HTTP path,
which is already covered by tests/test_parser.py and the real-file checks
earlier in this session) with a large, *varied* synthetic dataset so the
functional/perf pass (#25) and UI walkthrough (#26) exercise real code
paths at scale: coverage maps, duplicate-curve/duplicate-study detection,
the digitization-review workflow (pending/accepted/rejected + redo links),
study-registry completeness, inclinometry, and sign-off gating.

Usage:
    python3 scripts/generate_synthetic_wells.py [--wells 1500] [--runs 3] [--seed 42]
"""
import argparse
import datetime
import json
import os
import random
import sys

_backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.abspath(_backend_dir))

import numpy as np  # noqa: E402
from database import engine, SessionLocal, Base  # noqa: E402
from models import (  # noqa: E402
    Project, Well, LogRun, CurveData, FormationTop, StudyRegistryEntry,
)

CURVES = [
    # mnemonic, unit, description, lo, hi, log_spaced
    ("GR", "GAPI", "Gamma Ray", 20, 150, False),
    ("SP", "MV", "Spontaneous Potential", -80, 20, False),
    ("CALI", "IN", "Caliper", 6, 12, False),
    ("RES", "OHMM", "Deep Resistivity", 0.5, 500, True),
    ("RHOB", "G/C3", "Bulk Density", 1.95, 2.75, False),
    ("NPHI", "V/V", "Neutron Porosity", 0.02, 0.45, False),
    ("DT", "US/F", "Sonic Transit Time", 45, 140, False),
]

FORMATIONS = [
    ("Верхний пласт", "#e74c3c", "Известняк"),
    ("Средний пласт", "#3498db", "Песчаник"),
    ("Продуктивный горизонт", "#2ecc71", "Песчаник глинистый"),
    ("Нижний пласт", "#9b59b6", "Аргиллит"),
    ("Кора выветривания", "#f39c12", "Кора выветривания"),
]

STUDY_TYPES = ["ГИС комплексный", "Инклинометрия", "Кавернометрия", "Плотностной каротаж"]


def make_curve(rng: np.random.Generator, n: int, lo: float, hi: float, log_spaced: bool) -> np.ndarray:
    """Smooth random-walk curve clipped to [lo, hi], with occasional null gaps."""
    steps = rng.normal(0, (hi - lo) * 0.03, n)
    walk = np.cumsum(steps)
    walk -= walk.min()
    span = walk.max() or 1.0
    frac = walk / span  # 0..1
    if log_spaced:
        vals = lo * (hi / lo) ** frac
    else:
        vals = lo + frac * (hi - lo)
    vals = vals.astype(np.float32)
    # occasional short null gaps, like real tool outages
    if n > 200 and rng.random() < 0.3:
        gap_start = rng.integers(0, n - 50)
        gap_len = rng.integers(5, 40)
        vals[gap_start:gap_start + gap_len] = np.nan
    return vals


def build_run(rng, well_total_depth, run_number, digitization_status):
    start = round(rng.uniform(0, max(well_total_depth - 200, 10)), 1)
    length = rng.uniform(150, min(500, well_total_depth - start))
    step = rng.choice([0.1, 0.2])
    n = max(int(length / step), 200)
    stop = round(start + n * step, 1)

    curves_def = [{"mnemonic": m, "unit": u, "description": d} for m, u, d, *_ in CURVES]
    lr = LogRun(
        run_number=run_number,
        filename=f"SYN_{run_number}.las",
        las_version="2.0",
        start_depth=start,
        stop_depth=stop,
        step=step,
        null_value=-999.25,
        depth_unit="M",
        num_points=n,
        curves_json=json.dumps(curves_def, ensure_ascii=False),
        digitization_status=digitization_status,
        digitization_notes="Отклонено QA-синтетикой: несоответствие скану" if digitization_status == "rejected" else "",
        reviewed_by="qa-synth" if digitization_status in ("accepted", "rejected") else "",
        reviewed_at=datetime.datetime.utcnow() if digitization_status in ("accepted", "rejected") else None,
    )
    arrays = {}
    for mnemonic, unit, desc, lo, hi, log_spaced in CURVES:
        arr = make_curve(rng, n, lo, hi, log_spaced)
        arrays[mnemonic] = arr
        valid = arr[~np.isnan(arr)]
        lr.curve_data.append(CurveData(
            mnemonic=mnemonic, unit=unit, description=desc, num_points=n,
            min_value=float(np.min(valid)) if len(valid) else None,
            max_value=float(np.max(valid)) if len(valid) else None,
            data_binary=arr.tobytes(),
        ))
    return lr, arrays


def build_survey_run(rng, well_total_depth):
    step = 25.0
    n = max(int(well_total_depth / step), 10)
    depths = np.arange(n, dtype=np.float32) * step
    max_inc = rng.uniform(15, 65)
    inc = np.clip(np.linspace(0, max_inc, n) + rng.normal(0, 1.0, n), 0, 90).astype(np.float32)
    azi = np.clip(rng.uniform(0, 360) + np.cumsum(rng.normal(0, 2, n)), 0, 360).astype(np.float32)
    curves_def = [
        {"mnemonic": "DEPT", "unit": "M", "description": "Depth"},
        {"mnemonic": "INKL", "unit": "DEG", "description": "Inclination"},
        {"mnemonic": "AZ", "unit": "DEG", "description": "Azimuth"},
    ]
    lr = LogRun(
        run_number=9, filename="SYN_INCL.las", las_version="2.0",
        start_depth=0.0, stop_depth=float(depths[-1]), step=step,
        null_value=-999.25, depth_unit="M", num_points=n,
        curves_json=json.dumps(curves_def, ensure_ascii=False),
        digitization_status="accepted", reviewed_by="qa-synth",
        reviewed_at=datetime.datetime.utcnow(),
    )
    for mnemonic, arr in (("DEPT", depths), ("INKL", inc), ("AZ", azi)):
        lr.curve_data.append(CurveData(
            mnemonic=mnemonic, unit="M" if mnemonic == "DEPT" else "DEG",
            description=mnemonic, num_points=n,
            min_value=float(np.min(arr)), max_value=float(np.max(arr)),
            data_binary=arr.tobytes(),
        ))
    return lr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wells", type=int, default=1500)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--projects", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    pyrand = random.Random(args.seed)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    print(f"Generating {args.wells} wells x {args.runs} runs across {args.projects} projects (seed={args.seed})...")

    projects = []
    for p in range(args.projects):
        lat0 = pyrand.uniform(55, 65)
        lon0 = pyrand.uniform(60, 75)
        proj = Project(
            name=f"QA Synthetic Load Test — Field {p + 1}",
            description="Synthetic dataset generated for task #24/#25 QA load testing.",
            field_name=f"Синтетическое {p + 1}",
            operator="QA-Synth",
            country="RU",
        )
        db.add(proj)
        db.flush()
        projects.append((proj, lat0, lon0))

    wells_per_project = [args.wells // args.projects] * args.projects
    wells_per_project[-1] += args.wells - sum(wells_per_project)

    all_wells = []  # (well, project, total_depth) for duplicate-study seeding
    created = 0

    for (proj, lat0, lon0), n_wells in zip(projects, wells_per_project):
        for i in range(n_wells):
            total_depth = round(pyrand.uniform(800, 3500), 1)
            well = Well(
                project_id=proj.id,
                name=f"СИН-{created + 1:04d}",
                uwi=f"QA-{created + 1:06d}",
                api_number=f"{created + 1:08d}",
                latitude=lat0 + pyrand.uniform(-0.3, 0.3),
                longitude=lon0 + pyrand.uniform(-0.3, 0.3),
                elevation=round(pyrand.uniform(50, 250), 1),
                total_depth=total_depth,
                depth_unit="M",
                operator="QA-Synth",
                field_name=proj.field_name,
                x_coord=round(pyrand.uniform(0, 20000), 1),
                y_coord=round(pyrand.uniform(0, 20000), 1),
            )
            db.add(well)
            db.flush()

            # Digitization status mix: 70% accepted, 15% pending, 15% rejected
            statuses = pyrand.choices(
                ["accepted", "pending_review", "rejected"],
                weights=[70, 15, 15], k=args.runs,
            )
            rejected_run_objs = []
            for run_number, status in enumerate(statuses, start=1):
                lr, _ = build_run(rng, total_depth, run_number, status)
                well.log_runs.append(lr)
                if status == "rejected":
                    rejected_run_objs.append(lr)

            # ~5% exact duplicate curve: copy run 1's GR into run 2 verbatim
            if pyrand.random() < 0.05 and len(well.log_runs) >= 2:
                src_curve = next((c for c in well.log_runs[0].curve_data if c.mnemonic == "GR"), None)
                dst_run = well.log_runs[1]
                dst_curve = next((c for c in dst_run.curve_data if c.mnemonic == "GR"), None)
                if src_curve and dst_curve:
                    dst_curve.data_binary = src_curve.data_binary
                    dst_curve.num_points = src_curve.num_points
                    dst_curve.min_value = src_curve.min_value
                    dst_curve.max_value = src_curve.max_value

            db.flush()

            # Half of rejected runs get a redo (accepted correction) linked back
            for rejected in rejected_run_objs:
                if pyrand.random() < 0.5:
                    redo, _ = build_run(rng, total_depth, rejected.run_number, "accepted")
                    redo.redo_of = rejected.id
                    redo.filename = f"SYN_{rejected.run_number}_redo.las"
                    well.log_runs.append(redo)

            # ~30% deviated wells get an inclinometry survey run
            if pyrand.random() < 0.3:
                well.log_runs.append(build_survey_run(rng, total_depth))

            # Formation tops
            n_tops = pyrand.randint(2, len(FORMATIONS))
            top_depth = pyrand.uniform(50, total_depth * 0.2)
            for name, color, lith in pyrand.sample(FORMATIONS, n_tops):
                top_depth += pyrand.uniform(80, total_depth * 0.15)
                if top_depth >= total_depth:
                    break
                db.add(FormationTop(
                    well_id=well.id, formation_name=name, depth=round(top_depth, 1),
                    color=color, lithology=lith, depth_unit="M",
                ))

            all_wells.append((well, proj, total_depth))
            created += 1

        db.commit()
        print(f"  ...{created}/{args.wells} wells committed")

    # ~3% duplicate-study "twin" wells: near-identical name + overlapping runs,
    # to exercise project-scoped duplicate-study detection at scale.
    twins = pyrand.sample(all_wells, k=max(1, int(len(all_wells) * 0.03)))
    for well, proj, total_depth in twins:
        twin = Well(
            project_id=proj.id,
            name=well.name.replace("СИН-", "СИН -"),  # normalizes to same name, extra space
            uwi=well.uwi + "-B",
            latitude=well.latitude, longitude=well.longitude,
            total_depth=total_depth, depth_unit="M",
            operator="QA-Synth", field_name=proj.field_name,
        )
        db.add(twin)
        db.flush()
        for src_run in well.log_runs[:2]:
            lr, _ = build_run(rng, total_depth, src_run.run_number, "accepted")
            lr.start_depth, lr.stop_depth = src_run.start_depth, src_run.stop_depth
            twin.log_runs.append(lr)
        db.commit()
    print(f"  ...{len(twins)} duplicate-study twin wells added")

    # Study registry: ~70% of wells get a matching entry, plus 10% extra
    # orphan entries (studies nobody has digitized yet) per project.
    for proj, lat0, lon0 in projects:
        proj_wells = [w for w, p, _ in all_wells if p.id == proj.id]
        matched = pyrand.sample(proj_wells, k=int(len(proj_wells) * 0.7))
        for well in matched:
            run = pyrand.choice(well.log_runs) if well.log_runs else None
            db.add(StudyRegistryEntry(
                project_id=proj.id, well_name=well.name, field_name=proj.field_name,
                study_type=pyrand.choice(STUDY_TYPES),
                depth_top=run.start_depth if run else 0,
                depth_bottom=run.stop_depth if run else well.total_depth,
                source_row=f"{well.name};{proj.field_name};ГИС",
            ))
        n_orphans = max(1, int(len(proj_wells) * 0.1))
        for i in range(n_orphans):
            db.add(StudyRegistryEntry(
                project_id=proj.id, well_name=f"СИН-НЕОЦИФР-{i + 1:03d}",
                field_name=proj.field_name, study_type=pyrand.choice(STUDY_TYPES),
                depth_top=0, depth_bottom=500,
                source_row="не оцифровано;опись",
            ))
    db.commit()
    print("  ...study registry entries added")

    # Sign-off locks: mark ~40% of fully-accepted wells (no pending/rejected
    # issues) as locked, so export-readiness has a realistic mix.
    lock_path = os.path.join(_backend_dir, "artifacts", "locks.json")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    locks = {}
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                locks = json.load(f)
        except Exception:
            locks = {}
    locked_count = 0
    for well, proj, total_depth in all_wells:
        clean = all(
            (r.digitization_status or "pending_review") == "accepted"
            for r in well.log_runs
        )
        if clean and pyrand.random() < 0.4:
            locks[str(well.id)] = {
                "locked": True, "actor": "qa-synth", "snapshot_id": f"qa-synth-{well.id}",
                "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            locked_count += 1
    with open(lock_path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(locks, f, indent=2)
    os.replace(lock_path + ".tmp", lock_path)
    print(f"  ...{locked_count} wells signed off (locked)")

    db.close()
    print(f"Done. {created} wells created, {len(twins)} duplicate twins, "
          f"synthetic dataset ready for #25 (functional/perf run).")


if __name__ == "__main__":
    main()
