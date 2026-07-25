"""Пакетный импорт: скважина из шапки, рейс из папки, инклинометрия отдельно."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.las_parser import LASParser
from backend.routers.ingest import _classify, _run_name_from_path, _minimum_curvature


GIS_LAS = (
    "~VERSION\nVERS. 2 :\nWRAP. NO :\n"
    "~WELL\n"
    "WELL        .          444                     :WELL\n"
    "STRT        .m         20.0000                 :First index value\n"
    "STOP        .m         1200.0000               :Last index value\n"
    "X           .m         -17302.000              :X-coordinate of Well Head\n"
    "Y           .m         71819.000               :Y-coordinate of Well Head\n"
    "RKB         .m         194.8000                :RKB\n"
    "~CURVE\nMD .m :\nGK . :\nGZ1 . :\nKS_500 . :\n"
    "~ASCII\n20.0 5.1 12.0 3.0\n20.1 5.4 12.5 3.2\n20.2 5.9 13.0 3.4\n"
)

INKL_LAS = (
    "~Version\nVERS. 2.0 :\nWRAP. NO :\n"
    "~Well\nSTRT .m 0.0 :\nSTOP .m 100.0 :\nWELL . 444 : Well\n"
    "~Curve\nMD .m :\nINCL .deg :\nAZ .deg :\n"
    "~ASCII\n0 0 0\n50 0 0\n100 0 0\n"
)


def test_well_name_comes_from_header_not_description():
    """`WELL . 444 :WELL` — номер стоит ДО двоеточия, после него описание."""
    las = LASParser.parse_bytes(GIS_LAS.encode())
    assert las.well.well_name == "444"


def test_header_gives_units_coordinates_and_altitude():
    las = LASParser.parse_bytes(GIS_LAS.encode())
    assert las.well.depth_unit == "M"
    assert las.well.x == -17302.0
    assert las.well.y == 71819.0
    assert las.well.rkb == 194.8


def test_field_mnemonics_are_kept_as_written():
    """GZ1 и KS_500 не переписываются, но опознаются как БКЗ и КС."""
    las = LASParser.parse_bytes(GIS_LAS.encode())
    names = [c.mnemonic for c in las.curves]
    canon = {c.mnemonic: c.canonical for c in las.curves}
    assert "GZ1" in names and "KS_500" in names
    assert canon["GZ1"] == "BKZ"


def test_run_name_taken_from_folder():
    assert _run_name_from_path("rd/2/C1/444.las", "444.las") == "C1"
    assert _run_name_from_path("rd/2/ГИС_С1/444.las", "444.las") == "ГИС_С1"
    # файл без папки — имя рейса из имени файла
    assert _run_name_from_path("444.las", "444.las") == "444"


def test_inclinometry_detected_by_curves_and_by_folder():
    assert _classify("C1", ["MD", "INCL", "AZ"]) == "inkl"
    assert _classify("INKL", ["MD", "GK"]) == "inkl"
    assert _classify("ИНКЛ", ["MD", "GK"]) == "inkl"
    assert _classify("C1", ["GK", "NGK"]) == "gis"


def test_rigis_detected_by_interpreted_curves():
    assert _classify("C1", ["LITH", "COLL", "SAT"]) == "rigis"
    assert _classify("РИГИС", ["GK"]) == "rigis"


def test_inkl_las_parses_into_md_incl_az():
    las = LASParser.parse_bytes(INKL_LAS.encode())
    names = [c.mnemonic for c in las.curves]
    assert names == ["MD", "INCL", "AZ"]
    assert _classify("INKL", names[1:]) == "inkl"


def test_minimum_curvature_vertical_well_gives_tvd_equal_md():
    md = [0.0, 100.0, 200.0]
    tvd, north, east = _minimum_curvature(md, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    assert abs(tvd[-1] - 200.0) < 1e-6
    assert abs(north[-1]) < 1e-9 and abs(east[-1]) < 1e-9


def test_minimum_curvature_deviated_well_shortens_tvd():
    md = [0.0, 100.0, 200.0]
    tvd, _, east = _minimum_curvature(md, [0.0, 30.0, 30.0], [90.0, 90.0, 90.0])
    assert tvd[-1] < 200.0            # наклон укорачивает вертикаль
    assert east[-1] > 0.0             # смещение на восток при азимуте 90°
