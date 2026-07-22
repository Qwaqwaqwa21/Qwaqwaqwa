# coding: utf-8
import numpy as np

from las_io import merge_curves_by_mnemonic


def make_file_data(file_name, depth, curves):
    depth = np.array(depth, dtype=float)
    return {
        'file_name': file_name,
        'well_name': 'WELL-1',
        'depth': depth,
        'curves': {k: np.array(v, dtype=float) for k, v in curves.items()},
        'curve_descriptions': {k: '' for k in curves},
        'depth_range': (np.nanmin(depth), np.nanmax(depth)),
    }


class TestMergeCurvesByMnemonic:
    def test_merges_curves_across_files(self):
        f1 = make_file_data('a.las', [1000, 1001, 1002], {'GK': [10, 11, 12]})
        f2 = make_file_data('b.las', [1000, 1001, 1002], {'GK': [20, 21, 22], 'NGK': [1, 2, 3]})
        merged, gmin, gmax = merge_curves_by_mnemonic([f1, f2], overlap_m=0)

        assert set(merged.keys()) == {'GK', 'NGK'}
        assert len(merged['GK']) == 2  # два экземпляра GK, из a.las и b.las
        assert len(merged['NGK']) == 1
        assert gmin == 1000
        assert gmax == 1002

    def test_overlap_padding_extends_global_range(self):
        f1 = make_file_data('a.las', [1000, 1001], {'GK': [1, 2]})
        merged, gmin, gmax = merge_curves_by_mnemonic([f1], overlap_m=50)
        assert gmin == 1000 - 50
        assert gmax == 1001 + 50

    def test_instance_preserves_source_file_name(self):
        f1 = make_file_data('run1.las', [1000, 1001], {'GK': [1, 2]})
        f2 = make_file_data('run2.las', [1000, 1001], {'GK': [3, 4]})
        merged, _, _ = merge_curves_by_mnemonic([f1, f2], overlap_m=0)
        file_names = {inst['file_name'] for inst in merged['GK']}
        assert file_names == {'run1.las', 'run2.las'}

    def test_curve_missing_from_one_file_only_has_one_instance(self):
        f1 = make_file_data('a.las', [1000, 1001], {'GK': [1, 2], 'SP': [5, 6]})
        f2 = make_file_data('b.las', [1000, 1001], {'GK': [3, 4]})
        merged, _, _ = merge_curves_by_mnemonic([f1, f2], overlap_m=0)
        assert len(merged['SP']) == 1
        assert merged['SP'][0]['file_name'] == 'a.las'
