# coding: utf-8
"""
Тесты на корректность обработки кодировок при чтении/сохранении LAS-файлов —
это самое чувствительное место приложения, т.к. большинство исходных файлов
приходят в однобайтовых кириллических кодировках (cp1251/ibm866), которые
никогда не дают ошибку декодирования при неверном выборе, а просто дают
другой (неверный) текст.
"""
import pytest

from las_io import read_las_robust, write_las_file

LAS_TEMPLATE = """~VERSION INFORMATION
VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0
WRAP.   NO  : ONE LINE PER DEPTH STEP
~WELL INFORMATION
STRT.M  1000.0 : START DEPTH
STOP.M  1001.0 : STOP DEPTH
STEP.M  0.5    : STEP
NULL.   -999.25 : NULL VALUE
WELL.   Скважина №1 : WELL NAME
~CURVE INFORMATION
DEPT.M       : DEPTH
GK  .GAPI    : Гамма-каротаж
~ASCII
   1000.0    10.0
   1000.5    11.0
   1001.0    12.0
"""


def write_las_bytes(path, encoding):
    path.write_bytes(LAS_TEMPLATE.encode(encoding))


class TestReadLasRobustEncoding:
    def test_correct_encoding_decodes_cleanly(self, tmp_path):
        path = tmp_path / "test.las"
        write_las_bytes(path, 'cp1251')

        las = read_las_robust(path, encoding='cp1251')

        assert las.well.WELL.value == 'Скважина №1'
        assert las.curves['GK'].descr == 'Гамма-каротаж'
        assert getattr(las, '_encoding_warning', 'MISSING') is None

    def test_correct_ibm866_decodes_cleanly(self, tmp_path):
        path = tmp_path / "test_ibm866.las"
        write_las_bytes(path, 'ibm866')

        las = read_las_robust(path, encoding='ibm866')

        assert las.well.WELL.value == 'Скважина №1'
        assert getattr(las, '_encoding_warning', 'MISSING') is None

    def test_wrong_utf8_family_encoding_is_flagged_not_silent(self, tmp_path):
        path = tmp_path / "test.las"
        write_las_bytes(path, 'cp1251')

        # cp1251-байты почти всегда невалидны как utf-8 -> должно быть явно
        # помечено предупреждением, а не тихо выдано как будто всё в порядке.
        las = read_las_robust(path, encoding='utf-8')

        assert las.well.WELL.value != 'Скважина №1'
        assert getattr(las, '_encoding_warning', None) is not None
        assert 'utf-8' in las._encoding_warning

    def test_bom_overrides_user_choice_and_is_flagged(self, tmp_path):
        path = tmp_path / "bom.las"
        path.write_bytes(LAS_TEMPLATE.encode('utf-8-sig'))

        # Пользователь по ошибке выбрал cp1251, но в файле BOM utf-8-sig —
        # BOM должен победить, а пользователь должен быть об этом предупреждён.
        las = read_las_robust(path, encoding='cp1251')

        assert las.well.WELL.value == 'Скважина №1'
        assert las._effective_encoding == 'utf-8-sig'
        assert 'BOM' in las._encoding_warning

    def test_bom_matching_user_choice_has_no_warning(self, tmp_path):
        path = tmp_path / "bom_ok.las"
        path.write_bytes(LAS_TEMPLATE.encode('utf-8-sig'))

        las = read_las_robust(path, encoding='utf-8-sig')

        assert las.well.WELL.value == 'Скважина №1'
        assert getattr(las, '_encoding_warning', 'MISSING') is None

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_las_robust(tmp_path / "does_not_exist.las", encoding='cp1251')

    def test_unknown_encoding_raises_clear_error(self, tmp_path):
        path = tmp_path / "test.las"
        write_las_bytes(path, 'cp1251')

        with pytest.raises(RuntimeError, match="Неизвестная кодировка"):
            read_las_robust(path, encoding='not-a-real-encoding')


class TestWriteLasFileRoundTrip:
    def test_cyrillic_survives_cp1251_to_utf8sig_round_trip(self, tmp_path):
        src = tmp_path / "src.las"
        write_las_bytes(src, 'cp1251')
        las = read_las_robust(src, encoding='cp1251')

        out_path = tmp_path / "out.las"
        write_las_file(las, out_path, encoding='utf-8-sig')

        reloaded = read_las_robust(out_path, encoding='utf-8-sig')
        assert reloaded.well.WELL.value == 'Скважина №1'
        assert reloaded.curves['GK'].descr == 'Гамма-каротаж'
        assert getattr(reloaded, '_encoding_warning', 'MISSING') is None

    def test_output_file_has_utf8_bom(self, tmp_path):
        src = tmp_path / "src.las"
        write_las_bytes(src, 'cp1251')
        las = read_las_robust(src, encoding='cp1251')

        out_path = tmp_path / "out.las"
        write_las_file(las, out_path, encoding='utf-8-sig')

        assert out_path.read_bytes().startswith(b'\xef\xbb\xbf')
