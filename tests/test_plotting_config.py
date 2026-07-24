# coding: utf-8
import textwrap

from plotting import load_tracks_config, DEFAULT_TRACKS_CONFIG


class TestLoadTracksConfig:
    def test_missing_file_returns_default(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        cfg = load_tracks_config(str(missing))
        assert cfg == DEFAULT_TRACKS_CONFIG

    def test_custom_yaml_is_loaded(self, tmp_path):
        custom = tmp_path / "custom_tracks.yaml"
        custom.write_text(textwrap.dedent("""
            0:
              name: Тестовый трек
              width: 3.0
              curves:
                - {mnemonic: FOO, color: red, linestyle: '-', linewidth: 1.0}
              grid: linear
              limits: [0, 10]
              ylabel: Ед.
        """), encoding='utf-8')

        cfg = load_tracks_config(str(custom))
        assert cfg[0]['name'] == 'Тестовый трек'
        assert cfg[0]['curves'][0]['mnemonic'] == 'FOO'
        assert cfg[0]['limits'] == (0, 10)
        assert isinstance(cfg[0]['limits'], tuple)

    def test_invalid_yaml_falls_back_to_default(self, tmp_path):
        broken = tmp_path / "broken.yaml"
        broken.write_text("not: [a, valid, tracks, config", encoding='utf-8')
        cfg = load_tracks_config(str(broken))
        assert cfg == DEFAULT_TRACKS_CONFIG

    def test_repo_default_yaml_matches_builtin_default(self):
        cfg = load_tracks_config('tracks_config.yaml')
        assert cfg == DEFAULT_TRACKS_CONFIG
