"""Tests for src/archiver.py."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.airac import cycle_for_date
from src.archiver import (
    ArchiverError,
    _archive_dir_name,
    _collect_files,
    _create_manifest,
    _create_zip,
    _git_stage,
    _sct_basename,
    archive_cycle,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CYCLE_2602 = cycle_for_date(date(2026, 2, 19))   # effective 2026-02-19
CYCLE_2601 = cycle_for_date(date(2026, 1, 22))   # effective 2026-01-22

_ALL_REQUIRED = [
    "Routes.csv",
    "Notes.csv",
    "EG-ENR-3.2-en-GB.html",
    "EG-ENR-3.3-en-GB.html",
    "in.json",
    "out.json",
    "UK_2026_02.sct",
]


def _make_cycle_dir(tmp_path: Path, filenames: list[str]) -> Path:
    """Create a cycle directory in *tmp_path* with the given files present."""
    cycle_dir = tmp_path / "vFPC 2602"
    cycle_dir.mkdir()
    for name in filenames:
        (cycle_dir / name).write_text(f"content of {name}", encoding="utf-8")
    return cycle_dir


# ---------------------------------------------------------------------------
# _archive_dir_name
# ---------------------------------------------------------------------------

class TestArchiveDirName:
    def test_2602(self):
        assert _archive_dir_name(CYCLE_2602) == "vFPC 2602"

    def test_2601(self):
        assert _archive_dir_name(CYCLE_2601) == "vFPC 2601"

    def test_prefix(self):
        assert _archive_dir_name(CYCLE_2602).startswith("vFPC ")


# ---------------------------------------------------------------------------
# _sct_basename
# ---------------------------------------------------------------------------

class TestSctBasename:
    def test_2602(self):
        assert _sct_basename(CYCLE_2602) == "UK_2026_02.sct"

    def test_2601(self):
        assert _sct_basename(CYCLE_2601) == "UK_2026_01.sct"

    def test_zero_padded(self):
        cycle_01 = cycle_for_date(date(2026, 1, 22))
        assert _sct_basename(cycle_01) == "UK_2026_01.sct"


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def test_returns_seven_paths_when_all_present(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        result = _collect_files(cycle_dir, CYCLE_2602)
        assert len(result) == 7

    def test_all_paths_exist(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        result = _collect_files(cycle_dir, CYCLE_2602)
        for p in result:
            assert p.exists()

    def test_all_expected_names_present(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        result = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in result}
        assert names == set(_ALL_REQUIRED)

    def test_raises_on_single_missing_file(self, tmp_path):
        present = [f for f in _ALL_REQUIRED if f != "out.json"]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        with pytest.raises(ArchiverError, match="out.json"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_raises_on_multiple_missing_files(self, tmp_path):
        present = [f for f in _ALL_REQUIRED if f not in ("out.json", "in.json")]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        with pytest.raises(ArchiverError) as exc_info:
            _collect_files(cycle_dir, CYCLE_2602)
        msg = str(exc_info.value)
        assert "out.json" in msg
        assert "in.json" in msg

    def test_error_mentions_cycle_ident(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, [])
        with pytest.raises(ArchiverError, match="2602"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_raises_when_sct_missing(self, tmp_path):
        present = [f for f in _ALL_REQUIRED if not f.endswith(".sct")]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        with pytest.raises(ArchiverError, match="UK_2026_02.sct"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_wrong_cycle_sct_not_accepted(self, tmp_path):
        wrong_sct = _ALL_REQUIRED.copy()
        wrong_sct.remove("UK_2026_02.sct")
        wrong_sct.append("UK_2026_01.sct")
        cycle_dir = _make_cycle_dir(tmp_path, wrong_sct)
        with pytest.raises(ArchiverError, match="UK_2026_02.sct"):
            _collect_files(cycle_dir, CYCLE_2602)


# ---------------------------------------------------------------------------
# _create_zip
# ---------------------------------------------------------------------------

class TestCreateZip:
    def test_creates_zip_file(self, tmp_path):
        src = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        files = [src / name for name in _ALL_REQUIRED]
        zip_path = tmp_path / "out.zip"
        _create_zip(files, zip_path)
        assert zip_path.exists()

    def test_zip_contains_all_files(self, tmp_path):
        src = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        files = [src / name for name in _ALL_REQUIRED]
        zip_path = tmp_path / "out.zip"
        _create_zip(files, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert names == set(_ALL_REQUIRED)

    def test_zip_is_flat_no_subdirectories(self, tmp_path):
        src = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        files = [src / name for name in _ALL_REQUIRED]
        zip_path = tmp_path / "out.zip"
        _create_zip(files, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                assert "/" not in name

    def test_zip_file_contents_preserved(self, tmp_path):
        src = _make_cycle_dir(tmp_path, ["Routes.csv"])
        (src / "Routes.csv").write_bytes(b"col1,col2\n1,2\n")
        zip_path = tmp_path / "out.zip"
        _create_zip([src / "Routes.csv"], zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.read("Routes.csv") == b"col1,col2\n1,2\n"

    def test_zip_uses_deflate_compression(self, tmp_path):
        src = _make_cycle_dir(tmp_path, ["in.json"])
        zip_path = tmp_path / "out.zip"
        _create_zip([src / "in.json"], zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            info = zf.getinfo("in.json")
            assert info.compress_type == zipfile.ZIP_DEFLATED


# ---------------------------------------------------------------------------
# _create_manifest
# ---------------------------------------------------------------------------

class TestCreateManifest:
    def _write_manifest(self, tmp_path: Path) -> str:
        files = [tmp_path / name for name in _ALL_REQUIRED]
        for p in files:
            p.write_text("x", encoding="utf-8")
        manifest_path = tmp_path / "manifest.md"
        with patch("getpass.getuser", return_value="testuser"):
            _create_manifest(CYCLE_2602, files, manifest_path)
        return manifest_path.read_text(encoding="utf-8")

    def test_creates_file(self, tmp_path):
        self._write_manifest(tmp_path)
        assert (tmp_path / "manifest.md").exists()

    def test_contains_cycle_ident(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert "2602" in text

    def test_contains_effective_date(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert "2026-02-19" in text

    def test_contains_expiry_date(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert CYCLE_2602.expiry_date.isoformat() in text

    def test_contains_username(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert "testuser" in text

    def test_lists_all_files(self, tmp_path):
        text = self._write_manifest(tmp_path)
        for name in _ALL_REQUIRED:
            assert name in text

    def test_archived_utc_label_present(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert "UTC" in text

    def test_is_valid_markdown_heading(self, tmp_path):
        text = self._write_manifest(tmp_path)
        assert text.startswith("# Archive manifest")


# ---------------------------------------------------------------------------
# _git_stage
# ---------------------------------------------------------------------------

class TestGitStage:
    def test_calls_git_add_with_paths(self, tmp_path):
        p1 = tmp_path / "a.zip"
        p2 = tmp_path / "manifest.md"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _git_stage(tmp_path, p1, p2)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert cmd[1] == "add"
        assert str(p1) in cmd
        assert str(p2) in cmd

    def test_uses_archive_repo_as_cwd(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _git_stage(tmp_path)
        assert mock_run.call_args[1]["cwd"] == tmp_path

    def test_raises_on_nonzero_exit(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stderr = "not a git repository"
            with pytest.raises(ArchiverError, match="git add failed"):
                _git_stage(tmp_path)

    def test_error_includes_stderr(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "fatal: pathspec did not match"
            with pytest.raises(ArchiverError, match="pathspec did not match"):
                _git_stage(tmp_path)


# ---------------------------------------------------------------------------
# archive_cycle  (integration)
# ---------------------------------------------------------------------------

class TestArchiveCycle:
    def _run(self, tmp_path: Path) -> tuple[Path, Path]:
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            return archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_returns_zip_and_manifest_paths(self, tmp_path):
        zip_path, manifest_path = self._run(tmp_path)
        assert isinstance(zip_path, Path)
        assert isinstance(manifest_path, Path)

    def test_zip_path_is_inside_cycle_subdir(self, tmp_path):
        zip_path, _ = self._run(tmp_path)
        assert zip_path.parent.name == "vFPC 2602"

    def test_manifest_path_is_sibling_of_zip(self, tmp_path):
        zip_path, manifest_path = self._run(tmp_path)
        assert zip_path.parent == manifest_path.parent

    def test_zip_filename_matches_subdir(self, tmp_path):
        zip_path, _ = self._run(tmp_path)
        assert zip_path.name == "vFPC 2602.zip"

    def test_manifest_filename(self, tmp_path):
        _, manifest_path = self._run(tmp_path)
        assert manifest_path.name == "manifest.md"

    def test_zip_file_exists_on_disk(self, tmp_path):
        zip_path, _ = self._run(tmp_path)
        assert zip_path.exists()

    def test_manifest_file_exists_on_disk(self, tmp_path):
        _, manifest_path = self._run(tmp_path)
        assert manifest_path.exists()

    def test_git_add_called_once(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert mock_run.call_count == 1

    def test_git_add_stages_both_files(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            zip_path, manifest_path = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        cmd = mock_run.call_args[0][0]
        assert str(zip_path) in cmd
        assert str(manifest_path) in cmd

    def test_raises_on_missing_file(self, tmp_path):
        partial = [f for f in _ALL_REQUIRED if f != "out.json"]
        cycle_dir = _make_cycle_dir(tmp_path, partial)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with pytest.raises(ArchiverError, match="out.json"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_raises_on_git_failure(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALL_REQUIRED)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stderr = "not a git repository"
            with pytest.raises(ArchiverError, match="git add failed"):
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_zip_contains_all_seven_files(self, tmp_path):
        zip_path, _ = self._run(tmp_path)
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert names == set(_ALL_REQUIRED)

    def test_does_not_call_git_if_files_missing(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, [])
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            with pytest.raises(ArchiverError):
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        mock_run.assert_not_called()
