# coding: utf-8
from io import BytesIO, StringIO

import pandas as pd
import pytest

from zones import (
    load_zones_from_file, validate_zones, build_zone_curve_coverage, zones_to_csv_bytes
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


class TestZonesToCsvBytes:
    def test_produces_valid_csv(self):
        zones = pd.DataFrame({'Зона': ['A'], 'Кровля, м': [1000.0], 'Подошва, м': [1010.0]})
        csv = zones_to_csv_bytes(zones)
        assert 'Зона' in csv
        assert 'A' in csv
