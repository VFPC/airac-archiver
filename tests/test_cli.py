"""Tests for src/cli.py."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from src.airac import cycle_for_date
from src.archiver import ArchiverError
from src.cli import _resolve_cycle, cli
from src.config import Config, ConfigError

CYCLE_2602 = cycle_for_date(date(2026, 2, 19))
CYCLE_2603 = cycle_for_date(date(2026, 3, 19))


def _make_config(tmp_path: Path) -> Config:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    archive = tmp_path / "airac-data"
    archive.mkdir(exist_ok=True)
    return Config(workspace_base=workspace, archive_repo=archive)


# ---------------------------------------------------------------------------
# _resolve_cycle
# ---------------------------------------------------------------------------

class TestResolveCycle:
    def test_none_returns_current_cycle(self):
        with patch("src.cli.current_cycle", return_value=CYCLE_2602):
            assert _resolve_cycle(None) == CYCLE_2602

    def test_valid_ident_returns_correct_cycle(self):
        assert _resolve_cycle("2602").ident == "2602"

    def test_valid_ident_2603(self):
        assert _resolve_cycle("2603").ident == "2603"

    def test_non_numeric_raises(self):
        import click
        with pytest.raises(click.BadParameter):
            _resolve_cycle("ABCD")

    def test_wrong_length_raises(self):
        import click
        with pytest.raises(click.BadParameter):
            _resolve_cycle("260")

    def test_cycle_number_zero_raises(self):
        import click
        with pytest.raises(click.BadParameter):
            _resolve_cycle("2600")

    def test_cycle_number_14_raises(self):
        import click
        with pytest.raises(click.BadParameter):
            _resolve_cycle("2614")


# ---------------------------------------------------------------------------
# archive command
# ---------------------------------------------------------------------------

def _make_archive_result(cfg: "Config", ident: str) -> tuple[list[Path], Path]:
    """Build a realistic archive_cycle return value for the given cycle ident."""
    subdir = cfg.archive_repo / f"vFPC {ident}"
    copied = [
        subdir / "Routes.csv",
        subdir / "out.json",
    ]
    manifest_p = subdir / "manifest.md"
    return (copied, manifest_p)


class TestArchiveCommand:
    def _invoke(self, tmp_path: Path, archive_result=None):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        if archive_result is None:
            archive_result = _make_archive_result(cfg, "2603")
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", return_value=archive_result),
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            return runner.invoke(cli, ["archive", "--cycle", "2603"])

    def test_exits_zero_on_success(self, tmp_path):
        assert self._invoke(tmp_path).exit_code == 0

    def test_output_mentions_cycle_ident(self, tmp_path):
        assert "2603" in self._invoke(tmp_path).output

    def test_output_mentions_staged(self, tmp_path):
        assert "staged" in self._invoke(tmp_path).output.lower()

    def test_output_mentions_commit(self, tmp_path):
        assert "commit" in self._invoke(tmp_path).output.lower()

    def test_shows_archive_subdir(self, tmp_path):
        result = self._invoke(tmp_path)
        assert "vFPC 2603" in result.output

    def test_shows_file_count(self, tmp_path):
        result = self._invoke(tmp_path)
        # "2 file(s)" from the mock archive_result
        assert "2" in result.output

    def test_warnings_shown_when_files_missing(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        archive_result = _make_archive_result(cfg, "2603")
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", return_value=archive_result),
            patch("src.cli._collect_files", return_value=([], ["EG-ENR-3.2-en-GB.html"])),
        ):
            result = runner.invoke(cli, ["archive", "--cycle", "2603"])
        assert "EG-ENR-3.2-en-GB.html" in result.output

    def test_archiver_error_exits_nonzero(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", side_effect=ArchiverError("git add failed")),
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            result = runner.invoke(cli, ["archive", "--cycle", "2603"])
        assert result.exit_code != 0

    def test_archiver_error_message_shown(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", side_effect=ArchiverError("git add failed")),
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            result = runner.invoke(cli, ["archive", "--cycle", "2603"])
        assert "git add failed" in result.output

    def test_config_error_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        with patch("src.cli.load", side_effect=ConfigError("missing workspace_base")):
            result = runner.invoke(cli, ["archive", "--cycle", "2603"])
        assert result.exit_code != 0

    def test_default_cycle_used_when_no_option(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        archive_result = _make_archive_result(cfg, "2602")
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.current_cycle", return_value=CYCLE_2602),
            patch("src.cli.archive_cycle", return_value=archive_result),
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            result = runner.invoke(cli, ["archive"])
        assert "2602" in result.output

    def test_archive_cycle_called_with_correct_args(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        archive_result = _make_archive_result(cfg, "2603")
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", return_value=archive_result) as mock_archive,
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            runner.invoke(cli, ["archive", "--cycle", "2603"])
        args = mock_archive.call_args[0]
        assert args[0].ident == "2603"
        assert args[2] == cfg.archive_repo

    def test_cycle_dir_is_vfpc_subdir_of_workspace(self, tmp_path):
        cfg = _make_config(tmp_path)
        runner = CliRunner()
        archive_result = _make_archive_result(cfg, "2603")
        with (
            patch("src.cli.load", return_value=cfg),
            patch("src.cli.archive_cycle", return_value=archive_result) as mock_archive,
            patch("src.cli._collect_files", return_value=([], [])),
        ):
            runner.invoke(cli, ["archive", "--cycle", "2603"])
        cycle_dir_arg = mock_archive.call_args[0][1]
        assert cycle_dir_arg == cfg.workspace_base / "vFPC 2603"


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

class TestHelp:
    def test_help_exits_zero(self):
        assert CliRunner().invoke(cli, ["--help"]).exit_code == 0

    def test_archive_help_exits_zero(self):
        assert CliRunner().invoke(cli, ["archive", "--help"]).exit_code == 0

    def test_archive_in_help_output(self):
        assert "archive" in CliRunner().invoke(cli, ["--help"]).output
