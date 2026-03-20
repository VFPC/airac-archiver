"""Tests for src/archiver.py."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.airac import cycle_for_date
from src.archiver import (
    ArchiverError,
    _archive_dir_name,
    _collect_files,
    _copy_files,
    _create_manifest,
    _git_stage,
    _is_excluded,
    _sha256,
    _sct_basename,
    archive_cycle,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CYCLE_2602 = cycle_for_date(date(2026, 2, 19))
CYCLE_2601 = cycle_for_date(date(2026, 1, 22))

_EXPECTED_FILES = [
    "Routes.csv",
    "Notes.csv",
    "EG-ENR-3.2-en-GB.html",
    "EG-ENR-3.3-en-GB.html",
    "in.json",
    "out.json",
    "aip_segments.json",
    "UK_2026_02.sct",
]

_EXTRA_FILES = [
    "What's changed.csv",
    "audit_decisions.md",
    "discord_announcement.md",
    "logs/log_20260219_0900.txt",
]

_EXCLUDED_FILES = [
    "UK and Ireland SRD_March_2026.xlsx",
    "output_20260219_090000.json",
    "vFPC 2602.iml",
    "workspace.xml",
    ".gitignore",
]


def _make_cycle_dir(tmp_path: Path, filenames: list[str]) -> Path:
    """Create a cycle directory with the given files (supports subdirectories)."""
    cycle_dir = tmp_path / "vFPC 2602"
    cycle_dir.mkdir()
    for name in filenames:
        p = cycle_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"content of {name}", encoding="utf-8")
    return cycle_dir


def _make_full_cycle_dir(tmp_path: Path) -> Path:
    """Create a realistic cycle directory with expected, extra, and excluded files."""
    return _make_cycle_dir(tmp_path, _EXPECTED_FILES + _EXTRA_FILES + _EXCLUDED_FILES)


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
        assert _sct_basename(cycle_for_date(date(2026, 1, 22))) == "UK_2026_01.sct"


# ---------------------------------------------------------------------------
# _is_excluded
# ---------------------------------------------------------------------------

class TestIsExcluded:
    def test_xlsx_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "SRD_March.xlsx"
        assert _is_excluded(p, cycle_dir)

    def test_timestamped_json_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "output_20260219_090000.json"
        assert _is_excluded(p, cycle_dir)

    def test_iml_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "vFPC 2602.iml"
        assert _is_excluded(p, cycle_dir)

    def test_xml_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "workspace.xml"
        assert _is_excluded(p, cycle_dir)

    def test_idea_dir_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / ".idea" / "misc.xml"
        assert _is_excluded(p, cycle_dir)

    def test_routes_csv_not_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "Routes.csv"
        assert not _is_excluded(p, cycle_dir)

    def test_out_json_not_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "out.json"
        assert not _is_excluded(p, cycle_dir)

    def test_log_file_not_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "logs" / "log_20260219_0900.txt"
        assert not _is_excluded(p, cycle_dir)

    def test_audit_md_not_excluded(self, tmp_path):
        cycle_dir = tmp_path / "vFPC 2602"
        cycle_dir.mkdir()
        p = cycle_dir / "audit_decisions.md"
        assert not _is_excluded(p, cycle_dir)


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def test_collects_expected_and_extra_files(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        for name in _EXPECTED_FILES + ["What's changed.csv", "audit_decisions.md"]:
            assert name in names

    def test_excludes_xlsx(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        assert not any(n.endswith(".xlsx") for n in names)

    def test_excludes_timestamped_json(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        assert not any(n.startswith("output_") for n in names)

    def test_excludes_idea_dir(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        (cycle_dir / ".idea").mkdir()
        (cycle_dir / ".idea" / "misc.xml").write_text("x")
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        assert not any(".idea" in str(p) for p in files)

    def test_no_warnings_when_all_expected_present(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert warnings == []

    def test_warns_on_missing_enr32(self, tmp_path):
        present = [f for f in _EXPECTED_FILES if f != "EG-ENR-3.2-en-GB.html"]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert "EG-ENR-3.2-en-GB.html" in warnings

    def test_warns_on_multiple_missing(self, tmp_path):
        present = [f for f in _EXPECTED_FILES if f not in ("out.json", "in.json")]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert "out.json" in warnings
        assert "in.json" in warnings

    def test_raises_on_empty_dir(self, tmp_path):
        # An empty cycle dir is almost certainly wrong — must fail, not silently archive nothing
        cycle_dir = _make_cycle_dir(tmp_path, [])
        with pytest.raises(ArchiverError, match="expected files found"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_returns_only_files_not_dirs(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        for p in files:
            assert p.is_file()

    def test_raises_when_cycle_dir_does_not_exist(self, tmp_path):
        missing_dir = tmp_path / "vFPC 9999"
        with pytest.raises(ArchiverError, match="does not exist"):
            _collect_files(missing_dir, CYCLE_2602)

    def test_raises_on_duplicate_basenames(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        # Create a subdirectory with a file whose basename clashes with a root file
        (cycle_dir / "subdir").mkdir()
        (cycle_dir / "subdir" / "out.json").write_text("duplicate", encoding="utf-8")
        with pytest.raises(ArchiverError, match="Duplicate basenames"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_raises_when_too_few_expected_files(self, tmp_path):
        # Only 2 expected files present — below MIN_EXPECTED_PRESENT (3)
        cycle_dir = _make_cycle_dir(tmp_path, ["Routes.csv", "Notes.csv"])
        with pytest.raises(ArchiverError, match="expected files found"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_does_not_raise_when_min_expected_present(self, tmp_path):
        # Exactly 3 expected files — should warn but not raise
        cycle_dir = _make_cycle_dir(tmp_path, ["Routes.csv", "Notes.csv", "out.json"])
        files, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert len(files) == 3
        assert len(warnings) > 0  # missing files are warned about


# ---------------------------------------------------------------------------
# _sha256
# ---------------------------------------------------------------------------

class TestSha256:
    def test_known_content(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert _sha256(p) == expected

    def test_different_files_different_hashes(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"aaa")
        b.write_bytes(b"bbb")
        assert _sha256(a) != _sha256(b)

    def test_returns_64_char_hex(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_bytes(b"x")
        result = _sha256(p)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# _create_manifest
# ---------------------------------------------------------------------------

class TestCreateManifest:
    def _write_manifest(self, tmp_path: Path, warnings: list[str] = None) -> str:
        files = []
        for name in _EXPECTED_FILES:
            p = tmp_path / name
            p.write_text("x", encoding="utf-8")
            files.append(p)
        manifest_path = tmp_path / "manifest.md"
        with patch("getpass.getuser", return_value="testuser"):
            _create_manifest(CYCLE_2602, files, warnings or [], manifest_path)
        return manifest_path.read_text(encoding="utf-8")

    def test_creates_file(self, tmp_path):
        self._write_manifest(tmp_path)
        assert (tmp_path / "manifest.md").exists()

    def test_contains_cycle_ident(self, tmp_path):
        assert "2602" in self._write_manifest(tmp_path)

    def test_contains_effective_date(self, tmp_path):
        assert "2026-02-19" in self._write_manifest(tmp_path)

    def test_contains_expiry_date(self, tmp_path):
        assert CYCLE_2602.expiry_date.isoformat() in self._write_manifest(tmp_path)

    def test_contains_username(self, tmp_path):
        assert "testuser" in self._write_manifest(tmp_path)

    def test_lists_all_files(self, tmp_path):
        text = self._write_manifest(tmp_path)
        for name in _EXPECTED_FILES:
            assert name in text

    def test_contains_sha256_checksums(self, tmp_path):
        text = self._write_manifest(tmp_path)
        # SHA256 hashes are 64 hex chars
        import re
        assert re.search(r"[0-9a-f]{64}", text)

    def test_contains_utc_label(self, tmp_path):
        assert "UTC" in self._write_manifest(tmp_path)

    def test_is_valid_markdown_heading(self, tmp_path):
        assert self._write_manifest(tmp_path).startswith("# Archive manifest")

    def test_no_warnings_section_when_none(self, tmp_path):
        text = self._write_manifest(tmp_path, warnings=[])
        assert "Warnings" not in text

    def test_warnings_section_present_when_missing(self, tmp_path):
        text = self._write_manifest(tmp_path, warnings=["EG-ENR-3.2-en-GB.html"])
        assert "Warnings" in text
        assert "EG-ENR-3.2-en-GB.html" in text
        assert "MISSING" in text


# ---------------------------------------------------------------------------
# _copy_files
# ---------------------------------------------------------------------------

class TestCopyFiles:
    def test_copies_all_files(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        files = []
        for name in ["a.txt", "b.txt"]:
            p = src_dir / name
            p.write_text(name)
            files.append(p)
        copied = _copy_files(files, dest_dir)
        assert all(p.exists() for p in copied)
        assert {p.name for p in copied} == {"a.txt", "b.txt"}

    def test_creates_dest_dir_if_missing(self, tmp_path):
        src = tmp_path / "f.txt"
        src.write_text("x")
        dest_dir = tmp_path / "new" / "subdir"
        _copy_files([src], dest_dir)
        assert dest_dir.is_dir()

    def test_preserves_file_contents(self, tmp_path):
        src = tmp_path / "data.json"
        src.write_bytes(b'{"key": "value"}')
        dest_dir = tmp_path / "dest"
        _copy_files([src], dest_dir)
        assert (dest_dir / "data.json").read_bytes() == b'{"key": "value"}'


# ---------------------------------------------------------------------------
# _git_stage
# ---------------------------------------------------------------------------

class TestGitStage:
    def test_calls_git_add_with_paths(self, tmp_path):
        p1 = tmp_path / "a.txt"
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
    def _run(self, tmp_path: Path, filenames: list[str] = None) -> tuple[list[Path], Path]:
        cycle_dir = _make_cycle_dir(tmp_path, filenames or _EXPECTED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            return archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_returns_copied_paths_and_manifest(self, tmp_path):
        copied, manifest_path = self._run(tmp_path)
        assert isinstance(copied, list)
        assert isinstance(manifest_path, Path)

    def test_files_staged_in_cycle_subdir(self, tmp_path):
        copied, manifest_path = self._run(tmp_path)
        for p in copied:
            assert p.parent.name == "vFPC 2602"
        assert manifest_path.parent.name == "vFPC 2602"

    def test_manifest_filename(self, tmp_path):
        _, manifest_path = self._run(tmp_path)
        assert manifest_path.name == "manifest.md"

    def test_copied_files_exist_on_disk(self, tmp_path):
        copied, _ = self._run(tmp_path)
        for p in copied:
            assert p.exists()

    def test_manifest_exists_on_disk(self, tmp_path):
        _, manifest_path = self._run(tmp_path)
        assert manifest_path.exists()

    def test_all_expected_files_copied(self, tmp_path):
        copied, _ = self._run(tmp_path)
        names = {p.name for p in copied}
        for name in _EXPECTED_FILES:
            assert name in names

    def test_excluded_files_not_copied(self, tmp_path):
        all_files = _EXPECTED_FILES + _EXCLUDED_FILES
        cycle_dir = _make_cycle_dir(tmp_path, all_files)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            copied, _ = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        names = {p.name for p in copied}
        for name in _EXCLUDED_FILES:
            assert name not in names

    def test_extra_files_are_included(self, tmp_path):
        all_files = _EXPECTED_FILES + ["audit_decisions.md", "What's changed.csv"]
        cycle_dir = _make_cycle_dir(tmp_path, all_files)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            copied, _ = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        names = {p.name for p in copied}
        assert "audit_decisions.md" in names
        assert "What's changed.csv" in names

    def test_raises_when_cycle_dir_missing(self, tmp_path):
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        missing_dir = tmp_path / "vFPC 9999"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with pytest.raises(ArchiverError, match="does not exist"):
                archive_cycle(CYCLE_2602, missing_dir, archive_repo)

    def test_raises_on_duplicate_basenames(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        (cycle_dir / "subdir").mkdir()
        (cycle_dir / "subdir" / "out.json").write_text("dup", encoding="utf-8")
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with pytest.raises(ArchiverError, match="Duplicate basenames"):
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_rerun_removes_stale_files(self, tmp_path):
        """Re-archiving a cycle must not leave files from the previous run."""
        # First run: full set including an extra file
        first_files = _EXPECTED_FILES + ["stale_extra.txt"]
        cycle_dir = _make_cycle_dir(tmp_path, first_files)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        subdir = archive_repo / "vFPC 2602"
        assert (subdir / "stale_extra.txt").exists()

        # Second run: stale_extra.txt removed from cycle_dir
        (cycle_dir / "stale_extra.txt").unlink()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert not (subdir / "stale_extra.txt").exists(), (
            "Stale file from previous archive run was not removed on re-archive"
        )

    def test_succeeds_with_missing_expected_file(self, tmp_path):
        # Missing ENR 3.2 — should NOT raise, just warn
        partial = [f for f in _EXPECTED_FILES if f != "EG-ENR-3.2-en-GB.html"]
        copied, manifest_path = self._run(tmp_path, filenames=partial)
        assert manifest_path.exists()
        assert "EG-ENR-3.2-en-GB.html" not in {p.name for p in copied}

    def test_manifest_records_missing_file_warning(self, tmp_path):
        partial = [f for f in _EXPECTED_FILES if f != "EG-ENR-3.2-en-GB.html"]
        _, manifest_path = self._run(tmp_path, filenames=partial)
        text = manifest_path.read_text()
        assert "EG-ENR-3.2-en-GB.html" in text
        assert "MISSING" in text

    def test_git_add_called_once(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert mock_run.call_count == 1

    def test_git_add_stages_manifest(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _, manifest_path = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        cmd = mock_run.call_args[0][0]
        assert str(manifest_path) in cmd

    def test_raises_on_git_failure(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _EXPECTED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stderr = "not a git repository"
            with pytest.raises(ArchiverError, match="git add failed"):
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_no_zip_file_created(self, tmp_path):
        copied, manifest_path = self._run(tmp_path)
        subdir = manifest_path.parent
        assert not any(p.suffix == ".zip" for p in subdir.iterdir())
