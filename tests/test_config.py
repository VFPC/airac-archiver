"""Tests for src/config.py."""

from pathlib import Path

import pytest

from src.config import Config, ConfigError, load

MINIMAL_YAML = """\
workspace_base: /work
archive_repo: /archive
"""


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    f = tmp_path / "config.yaml"
    f.write_text(MINIMAL_YAML, encoding="utf-8")
    return f


class TestLoad:
    def test_returns_config(self, cfg_file):
        assert isinstance(load(cfg_file), Config)

    def test_workspace_base_is_path(self, cfg_file):
        assert load(cfg_file).workspace_base == Path("/work")

    def test_archive_repo_is_path(self, cfg_file):
        assert load(cfg_file).archive_repo == Path("/archive")

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("{ bad yaml: [", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load(f)

    def test_missing_workspace_base_raises(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("archive_repo: /archive\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="workspace_base"):
            load(f)

    def test_empty_workspace_base_raises(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("workspace_base: ''\narchive_repo: /archive\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="workspace_base"):
            load(f)

    def test_missing_archive_repo_raises(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("workspace_base: /work\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="archive_repo"):
            load(f)

    def test_empty_archive_repo_raises(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("workspace_base: /work\narchive_repo: ''\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="archive_repo"):
            load(f)


class TestLocalOverride:
    def test_local_overrides_workspace_base(self, cfg_file):
        cfg_file.with_name("config.local.yaml").write_text(
            "workspace_base: /local/work\n", encoding="utf-8"
        )
        assert load(cfg_file).workspace_base == Path("/local/work")

    def test_local_overrides_archive_repo(self, cfg_file):
        cfg_file.with_name("config.local.yaml").write_text(
            "archive_repo: /local/archive\n", encoding="utf-8"
        )
        assert load(cfg_file).archive_repo == Path("/local/archive")

    def test_missing_local_file_is_ignored(self, cfg_file):
        assert load(cfg_file).workspace_base == Path("/work")

    def test_invalid_local_yaml_raises(self, cfg_file):
        cfg_file.with_name("config.local.yaml").write_text(
            "{ bad: [", encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="Failed to parse"):
            load(cfg_file)


class TestImmutability:
    def test_config_is_frozen(self, cfg_file):
        cfg = load(cfg_file)
        with pytest.raises((AttributeError, TypeError)):
            cfg.workspace_base = Path("/other")  # type: ignore[misc]
