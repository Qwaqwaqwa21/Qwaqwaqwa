# coding: utf-8
from io import BytesIO, StringIO

import pandas as pd
import pytest

from zones import (
    load_zones_from_file, validate_zones, build_zone_curve_coverage, zones_to_csv_bytes,
    clean_zones_df
)


def make_interval_table():
    return [
        {'Метод': 'GK', 'Кровля, м': '1000.0', 'Подошва, м': '1050.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'a.las'},
        {'Метод': 'RS', 'Кровля, м': '1020.0', 'Подошва, м': '1030.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'b.las'},
    ]


class TestLoadZonesFromFile:
    def test_loads_csv_with_russian_headers(self):
        csv = "Зона,Кровля,Подошва\nПласт А,1000,1010\nПласт Б,1015,1025\n"
        df, warnings = load_zones_from_file(StringIO(csv), filename='zones.csv')
        assert list(df['Зона']) == ['Пласт А', 'Пласт Б']
        assert list(df['Кровля, м']) == [1000.0, 1015.0]
        assert list(df['Подошва, м']) == [1010.0, 1025.0]
        assert warnings == []

    def test_loads_csv_with_english_headers(self):
        csv = "Name,Top,Bottom\nZone1,1000,1010\n"
        df, warnings = load_zones_from_file(StringIO(csv), filename='zones.csv')
        assert df.iloc[0]['Зона'] == 'Zone1'
        assert df.iloc[0]['Кровля, м'] == 1000.0

    def test_loads_xlsx(self, tmp_path):
        path = tmp_path / "zones.xlsx"
        pd.DataFrame({'Зона': ['A'], 'Кровля': [1000.0], 'Подошва': [1010.0]}).to_excel(path, index=False)
        df, warnings = load_zones_from_file(str(path))
        assert df.iloc[0]['Зона'] == 'A'

    def test_optional_well_column_detected(self):
        csv = "Скважина,Зона,Кровля,Подошва\nWELL-1,A,1000,1010\nWELL-2,B,2000,2010\n"
        df, warnings = load_zones_from_file(StringIO(csv), filename='zones.csv')
        assert 'Скважина' in df.columns
        assert list(df['Скважина']) == ['WELL-1', 'WELL-2']

    def test_missing_required_column_raises(self):
        csv = "Зона,Кровля\nA,1000\n"
        with pytest.raises(ValueError, match="подошва"):
            load_zones_from_file(StringIO(csv), filename='zones.csv')

    def test_non_numeric_depth_rows_dropped_with_warning(self):
        csv = "Зона,Кровля,Подошва\nA,1000,1010\nB,oops,1020\n"
        df, warnings = load_zones_from_file(StringIO(csv), filename='zones.csv')
        assert len(df) == 1
        assert any('Пропущено' in w for w in warnings)

    def test_empty_file_raises(self):
        csv = "Зона,Кровля,Подошва\n"
        with pytest.raises(ValueError):
            load_zones_from_file(StringIO(csv), filename='zones.csv')


class TestValidateZones:
    def test_no_warnings_for_clean_zones(self):
        df = pd.DataFrame({'Зона': ['A', 'B'], 'Кровля, м': [1000.0, 1020.0], 'Подошва, м': [1010.0, 1030.0]})
        assert validate_zones(df) == []

    def test_inverted_zone_flagged(self):
        df = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1010.0], 'Подошва, м': [1000.0]})
        warnings = validate_zones(df)
        assert any('не меньше подошвы' in w for w in warnings)

    def test_duplicate_names_flagged(self):
        df = pd.DataFrame({'Зона': ['A', 'A'], 'Кровля, м': [1000.0, 1020.0], 'Подошва, м': [1010.0, 1030.0]})
        warnings = validate_zones(df)
        assert any('Повторяющееся' in w for w in warnings)

    def test_overlapping_zones_flagged(self):
        df = pd.DataFrame({'Зона': ['A', 'B'], 'Кровля, м': [1000.0, 1005.0], 'Подошва, м': [1010.0, 1020.0]})
        warnings = validate_zones(df)
        assert any('пересекаются' in w for w in warnings)

    def test_empty_df_no_warnings(self):
        assert validate_zones(pd.DataFrame()) == []

    def test_nested_non_adjacent_overlap_flagged(self):
        # B is fully nested inside A, but C sits in between them by depth
        # sort order — an adjacent-only pairwise check would miss A/B.
        df = pd.DataFrame({
            'Зона': ['A', 'C', 'B'],
            'Кровля, м': [1000.0, 1005.0, 1010.0],
            'Подошва, м': [1100.0, 1006.0, 1020.0],
        })
        warnings = validate_zones(df)
        assert any('«A»' in w and '«B»' in w for w in warnings)


class TestBuildZoneCurveCoverage:
    def test_full_coverage(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1005.0], 'Подошва, м': [1015.0]})
        df = build_zone_curve_coverage(zones, make_interval_table())
        assert df.iloc[0]['GK'] == 'полностью'

    def test_partial_coverage(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1015.0], 'Подошва, м': [1035.0]})
        df = build_zone_curve_coverage(zones, make_interval_table())
        assert df.iloc[0]['RS'] == 'частично'

    def test_no_coverage(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1100.0], 'Подошва, м': [1110.0]})
        df = build_zone_curve_coverage(zones, make_interval_table())
        assert df.iloc[0]['GK'] == 'нет'
        assert df.iloc[0]['RS'] == 'нет'

    def test_empty_zones_returns_empty_df(self):
        df = build_zone_curve_coverage(pd.DataFrame(), make_interval_table())
        assert df.empty

    def test_empty_interval_table_all_zones_have_no_curve_columns(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1000.0], 'Подошва, м': [1010.0]})
        df = build_zone_curve_coverage(zones, [])
        assert list(df.columns) == ['Зона', 'Кровля, м', 'Подошва, м']

    def test_overlapping_records_for_same_method_are_not_double_counted(self):
        # Two GK records for the same method overlap each other by 20m
        # (990-1030 and 1010-1050). Their union only covers 990-1050 (60m),
        # not the 40+40=80m a naive sum would produce — so a zone with a
        # real 10m gap (1050-1060) must NOT be reported as fully covered.
        table = [
            {'Метод': 'GK', 'Кровля, м': '990.0', 'Подошва, м': '1030.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'a.las'},
            {'Метод': 'GK', 'Кровля, м': '1010.0', 'Подошва, м': '1050.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'b.las'},
        ]
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [990.0], 'Подошва, м': [1060.0]})
        df = build_zone_curve_coverage(zones, table)
        assert df.iloc[0]['GK'] == 'частично'


class TestCleanZonesDf:
    def test_drops_rows_with_missing_depth(self):
        df = pd.DataFrame({'Зона': ['A', 'B'], 'Кровля, м': [1000.0, None], 'Подошва, м': [1010.0, 1020.0]})
        cleaned, dropped = clean_zones_df(df)
        assert dropped == 1
        assert list(cleaned['Зона']) == ['A']

    def test_coerces_string_depth_columns(self):
        df = pd.DataFrame({'Зона': ['A'], 'Кровля, м': ['1000'], 'Подошва, м': ['1010']})
        cleaned, dropped = clean_zones_df(df)
        assert dropped == 0
        assert cleaned.iloc[0]['Кровля, м'] == 1000.0

    def test_none_and_empty_pass_through(self):
        assert clean_zones_df(None) == (None, 0)
        empty = pd.DataFrame()
        cleaned, dropped = clean_zones_df(empty)
        assert cleaned.empty and dropped == 0


class TestZonesToCsvBytes:
    def test_produces_valid_csv(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1000.0], 'Подошва, м': [1010.0]})
        csv = zones_to_csv_bytes(zones)
        assert 'Зона' in csv
        assert 'A' in csv
