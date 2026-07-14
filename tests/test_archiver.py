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
    _ALLOWED_FIXED,
    _OUT_VERSION_RE,
    _archive_dir_name,
    _collect_files,
    _copy_files,
    _create_manifest,
    _existing_out_versions,
    _git_stage,
    _is_allowed,
    _next_out_version,
    _out_cycle_value,
    _out_version_name,
    _sha256,
    _sct_basename,
    archive_cycle,
    slim_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CYCLE_2602 = cycle_for_date(date(2026, 2, 19))
CYCLE_2601 = cycle_for_date(date(2026, 1, 22))

# The canonical allowlisted files for CYCLE_2602.
_ALLOWED_FILES = [
    "Routes.csv",
    "Notes.csv",
    "in.json",
    "out.json",
    "UK_2026_02.sct",
]

_OPTIONAL_ALLOWED_FILES = [
    "curation_notes.md",
    "aip_airports.json",
    "aip_airspaces.json",
    "aip_navaids.json",
    "aip_restricted_areas.json",
    "aip_segments.json",
    "enr44_points.json",
    "runtime_rules.json",
    "selection_indexes.json",
    "route_network_facts.json",
    "airspace_facts.json",
    "procedure_facts.json",
    "restricted_area_facts.json",
    "manifest.json",
    "RAD_2602_v1_9.xlsx",
    "UK and Ireland SRD 19 February 2026_Excel and Notes.xlsx",
    "EG-ENR-3.2-en-GB.html",
    "EI_ENR_4_4_EN.pdf",
    "FR-ENR-4.4-fr-FR.html",
    "airac_manifest.json",
    "airac_manifest.md",
    "fetcher_log_20260219_090000.txt",
    "in.note516_boundary_fix.20260219-090000.json",
    "in.json.pre-note516-boundary-fix.20260219-090000.bak",
    "Routes.city_pair_cap_edits.20260522-082432.json",
    "Routes.confirmed_rad_denial_curation.20260608-071406.json",
    "Routes.vfp60_eg2444_curation.20260529-163336.md",
    "vfp60_eg2444_route_curation.json",
]

# Files that should be silently ignored (not on the allowlist).
_NON_ALLOWED_FILES = [
    "UK and Ireland SRD_March_2026.xlsx",
    "output_20260219_090000.json",
    "audit_decisions.md",
    "What's changed.csv",
    "log_20260219_0900.txt",
    "discord_announcement.md",
    "RAD_notes.txt",
    "EG-AD-2.EGLL-en-GB.html",
    "full_trace_2602_initial.jsonl",
    "Routes.csv.pre-2605.9-confirmed-rad-denial-curation.20260608-071406.bak",
    "out.json.pre-2605.9-confirmed-rad-denial-curation.20260608-071645.bak",
]


def _make_cycle_dir(tmp_path: Path, filenames: list[str]) -> Path:
    """Create a cycle directory with the given files."""
    cycle_dir = tmp_path / "vFPC 2602"
    cycle_dir.mkdir()
    for name in filenames:
        p = cycle_dir / name
        if name == "out.json":
            p.write_text('{"cycle": "2602.1", "airports": [], "constraints": []}', encoding="utf-8")
        else:
            p.write_text(f"content of {name}", encoding="utf-8")
    return cycle_dir


def _make_full_cycle_dir(tmp_path: Path) -> Path:
    """Create a realistic cycle directory with allowed and non-allowed files."""
    return _make_cycle_dir(tmp_path, _ALLOWED_FILES + _OPTIONAL_ALLOWED_FILES + _NON_ALLOWED_FILES)


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
# Versioned out.json helpers
# ---------------------------------------------------------------------------

class TestOutVersionName:
    def test_format(self):
        assert _out_version_name("2602.1") == "out.2602.1.json"

    def test_double_digit_version(self):
        assert _out_version_name("2602.12") == "out.2602.12.json"

    def test_different_cycle(self):
        assert _out_version_name("2601.3") == "out.2601.3.json"

    def test_base_cycle(self):
        assert _out_version_name("2602") == "out.2602.json"

    def test_rejects_invalid_cycle_value(self):
        with pytest.raises(ArchiverError, match="Invalid out.json cycle value"):
            _out_version_name("2602-beta")


class TestOutVersionRE:
    def test_matches_valid_name(self):
        assert _OUT_VERSION_RE.match("out.2602.1.json")

    def test_captures_ident_and_version(self):
        m = _OUT_VERSION_RE.match("out.2603.5.json")
        assert m.group(1) == "2603"
        assert m.group(2) == "5"

    def test_matches_base_cycle_name(self):
        m = _OUT_VERSION_RE.match("out.2603.json")
        assert m.group(1) == "2603"
        assert m.group(2) is None

    def test_rejects_plain_out_json(self):
        assert not _OUT_VERSION_RE.match("out.json")

    def test_rejects_output_timestamped(self):
        assert not _OUT_VERSION_RE.match("output_20260219_090000.json")

    def test_rejects_wrong_prefix(self):
        assert not _OUT_VERSION_RE.match("data.2602.1.json")


class TestOutCycleValue:
    def test_reads_cycle_from_parser_output(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text('{"cycle": "2602.9"}', encoding="utf-8")
        assert _out_cycle_value(path, CYCLE_2602) == "2602.9"

    def test_rejects_missing_cycle(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(ArchiverError, match="missing string cycle"):
            _out_cycle_value(path, CYCLE_2602)

    def test_rejects_non_string_cycle(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text('{"cycle": 2602}', encoding="utf-8")
        with pytest.raises(ArchiverError, match="missing string cycle"):
            _out_cycle_value(path, CYCLE_2602)

    def test_rejects_invalid_json(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text("not json at all", encoding="utf-8")
        with pytest.raises(ArchiverError, match="not valid JSON"):
            _out_cycle_value(path, CYCLE_2602)

    def test_rejects_mismatched_cycle(self, tmp_path):
        path = tmp_path / "out.json"
        path.write_text('{"cycle": "2601.9"}', encoding="utf-8")
        with pytest.raises(ArchiverError, match="does not match archive cycle"):
            _out_cycle_value(path, CYCLE_2602)


class TestExistingOutVersions:
    def test_empty_dir(self, tmp_path):
        assert _existing_out_versions(tmp_path, CYCLE_2602) == []

    def test_nonexistent_dir(self, tmp_path):
        assert _existing_out_versions(tmp_path / "nope", CYCLE_2602) == []

    def test_finds_matching_versions(self, tmp_path):
        (tmp_path / "out.2602.1.json").write_text("v1")
        (tmp_path / "out.2602.2.json").write_text("v2")
        result = _existing_out_versions(tmp_path, CYCLE_2602)
        assert [p.name for p in result] == ["out.2602.1.json", "out.2602.2.json"]

    def test_ignores_other_cycle(self, tmp_path):
        (tmp_path / "out.2601.1.json").write_text("other cycle")
        (tmp_path / "out.2602.1.json").write_text("this cycle")
        result = _existing_out_versions(tmp_path, CYCLE_2602)
        assert [p.name for p in result] == ["out.2602.1.json"]

    def test_sorted_by_version_number(self, tmp_path):
        (tmp_path / "out.2602.10.json").write_text("v10")
        (tmp_path / "out.2602.2.json").write_text("v2")
        (tmp_path / "out.2602.1.json").write_text("v1")
        result = _existing_out_versions(tmp_path, CYCLE_2602)
        assert [p.name for p in result] == [
            "out.2602.1.json", "out.2602.2.json", "out.2602.10.json"
        ]


class TestNextOutVersion:
    def test_first_version_in_empty_dir(self, tmp_path):
        assert _next_out_version(tmp_path, CYCLE_2602) == 1

    def test_increments_after_existing(self, tmp_path):
        (tmp_path / "out.2602.1.json").write_text("v1")
        assert _next_out_version(tmp_path, CYCLE_2602) == 2

    def test_increments_after_multiple(self, tmp_path):
        (tmp_path / "out.2602.1.json").write_text("v1")
        (tmp_path / "out.2602.2.json").write_text("v2")
        (tmp_path / "out.2602.3.json").write_text("v3")
        assert _next_out_version(tmp_path, CYCLE_2602) == 4

    def test_ignores_other_cycle(self, tmp_path):
        (tmp_path / "out.2601.5.json").write_text("other")
        assert _next_out_version(tmp_path, CYCLE_2602) == 1

    def test_nonexistent_dir_returns_1(self, tmp_path):
        assert _next_out_version(tmp_path / "nope", CYCLE_2602) == 1

    def test_gap_in_versions_uses_max_plus_one(self, tmp_path):
        """Deleted v2 with v3 remaining → next must be 4, never reuse 2."""
        (tmp_path / "out.2602.1.json").write_text("v1")
        # v2 was deleted
        (tmp_path / "out.2602.3.json").write_text("v3")
        assert _next_out_version(tmp_path, CYCLE_2602) == 4


# ---------------------------------------------------------------------------
# _is_allowed
# ---------------------------------------------------------------------------

class TestIsAllowed:
    def test_routes_csv_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("Routes.csv"), allowed)

    def test_out_json_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("out.json"), allowed)

    def test_sct_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("UK_2026_02.sct"), allowed)

    def test_xlsx_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert not _is_allowed(Path("SRD_March.xlsx"), allowed)

    def test_unscoped_aip_html_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert not _is_allowed(Path("EG-AD-2.EGLL-en-GB.html"), allowed)

    def test_aip_segments_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("aip_segments.json"), allowed)

    def test_runtime_rules_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("runtime_rules.json"), allowed)

    def test_enr44_points_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("enr44_points.json"), allowed)

    def test_runtime_bundle_manifest_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("manifest.json"), allowed)

    def test_log_file_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert not _is_allowed(Path("log_20260219_0900.txt"), allowed)

    def test_audit_md_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert not _is_allowed(Path("audit_decisions.md"), allowed)

    def test_route_curation_json_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("Routes.confirmed_rad_denial_curation.20260608-071406.json"), allowed)

    def test_route_edit_json_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("Routes.city_pair_cap_edits.20260522-082432.json"), allowed)

    def test_vfp_curation_json_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("vfp60_eg2444_route_curation.json"), allowed)

    def test_route_backup_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert not _is_allowed(
            Path("Routes.csv.pre-2605.9-confirmed-rad-denial-curation.20260608-071406.bak"),
            allowed,
        )

    def test_rad_workbook_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("RAD_2602_v1_9.xlsx"), allowed)

    def test_airac_manifest_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("airac_manifest.json"), allowed)

    def test_enr_html_allowed_but_ad_html_not_allowed(self):
        allowed = set(_ALLOWED_FIXED) | {"UK_2026_02.sct"}
        assert _is_allowed(Path("EG-ENR-3.2-en-GB.html"), allowed)
        assert not _is_allowed(Path("EG-AD-2.EGLL-en-GB.html"), allowed)


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def test_collects_only_allowlisted_files(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        assert names == set(_ALLOWED_FILES + _OPTIONAL_ALLOWED_FILES)

    def test_ignores_non_allowlisted_files(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        for name in _NON_ALLOWED_FILES:
            assert name not in names

    def test_no_warnings_when_all_expected_present(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert warnings == []

    def test_optional_curation_note_does_not_trigger_warning(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES + _OPTIONAL_ALLOWED_FILES)
        files, warnings = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        assert "curation_notes.md" in names
        assert warnings == []

    def test_optional_rebuild_artifacts_do_not_trigger_warnings(self, tmp_path):
        rebuild_artifacts = [
            name for name in _OPTIONAL_ALLOWED_FILES
            if name != "curation_notes.md"
        ]
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES + rebuild_artifacts)
        files, warnings = _collect_files(cycle_dir, CYCLE_2602)
        names = {p.name for p in files}
        for name in rebuild_artifacts:
            assert name in names
        assert warnings == []

    def test_warns_on_missing_sct(self, tmp_path):
        present = [f for f in _ALLOWED_FILES if f != "UK_2026_02.sct"]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert "UK_2026_02.sct" in warnings

    def test_warns_on_multiple_missing(self, tmp_path):
        present = [f for f in _ALLOWED_FILES if f not in ("out.json", "in.json")]
        cycle_dir = _make_cycle_dir(tmp_path, present)
        _, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert "out.json" in warnings
        assert "in.json" in warnings

    def test_raises_on_empty_dir(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, [])
        with pytest.raises(ArchiverError, match="expected files found"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_returns_only_files_not_dirs(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        files, _ = _collect_files(cycle_dir, CYCLE_2602)
        for p in files:
            assert p.is_file()

    def test_raises_when_cycle_dir_does_not_exist(self, tmp_path):
        missing_dir = tmp_path / "vFPC 9999"
        with pytest.raises(ArchiverError, match="does not exist"):
            _collect_files(missing_dir, CYCLE_2602)

    def test_raises_when_too_few_expected_files(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, ["Routes.csv", "Notes.csv"])
        with pytest.raises(ArchiverError, match="expected files found"):
            _collect_files(cycle_dir, CYCLE_2602)

    def test_does_not_raise_when_min_expected_present(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, ["Routes.csv", "Notes.csv", "out.json"])
        files, warnings = _collect_files(cycle_dir, CYCLE_2602)
        assert len(files) == 3
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# slim retention policy
# ---------------------------------------------------------------------------

class TestSlimPolicy:
    def _make_archive_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "airac-data"
        old_dir = repo / "vFPC 2601"
        current_dir = repo / "vFPC 2602"
        old_dir.mkdir(parents=True)
        current_dir.mkdir(parents=True)

        for directory in (old_dir, current_dir):
            for name in [
                "out.2601.1.json" if directory is old_dir else "out.2602.1.json",
                "manifest.md",
                "curation_notes.md",
                "in.json",
                "Routes.csv",
                "Notes.csv",
                "UK_2026_01.sct" if directory is old_dir else "UK_2026_02.sct",
                "aip_segments.json",
                "runtime_rules.json",
            ]:
                (directory / name).write_text(f"content of {name}", encoding="utf-8")
        return repo

    def test_slim_candidates_only_older_cycles(self, tmp_path):
        repo = self._make_archive_repo(tmp_path)

        names = {p.relative_to(repo).as_posix() for p in slim_candidates(repo, "2602")}

        assert "vFPC 2601/Routes.csv" in names
        assert "vFPC 2601/aip_segments.json" in names
        assert "vFPC 2601/UK_2026_01.sct" in names
        assert "vFPC 2602/Routes.csv" not in names

    def test_slim_candidates_preserve_primary_artifacts(self, tmp_path):
        repo = self._make_archive_repo(tmp_path)

        names = {p.name for p in slim_candidates(repo, "2602")}

        assert "out.2601.1.json" not in names
        assert "manifest.md" not in names
        assert "curation_notes.md" not in names
        assert "in.json" not in names

    def test_slim_candidates_is_report_only(self, tmp_path):
        repo = self._make_archive_repo(tmp_path)

        candidates = slim_candidates(repo, "2602")

        assert candidates
        for path in candidates:
            assert path.exists()


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
        for name in _ALLOWED_FILES:
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
        for name in _ALLOWED_FILES:
            assert name in text

    def test_contains_sha256_checksums(self, tmp_path):
        text = self._write_manifest(tmp_path)
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
        text = self._write_manifest(tmp_path, warnings=["UK_2026_02.sct"])
        assert "Warnings" in text
        assert "UK_2026_02.sct" in text
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

    def test_renames_runtime_bundle_manifest(self, tmp_path):
        src = tmp_path / "manifest.json"
        src.write_text('{"bundle": true}', encoding="utf-8")
        dest_dir = tmp_path / "dest"
        copied = _copy_files([src], dest_dir)
        assert copied == [dest_dir / "runtime_bundle_manifest.json"]
        assert not (dest_dir / "manifest.json").exists()
        assert (dest_dir / "runtime_bundle_manifest.json").read_text(encoding="utf-8") == '{"bundle": true}'


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
        cycle_dir = _make_cycle_dir(tmp_path, filenames or _ALLOWED_FILES)
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

    def test_all_allowed_files_copied(self, tmp_path):
        copied, _ = self._run(tmp_path)
        names = {p.name for p in copied}
        for name in _ALLOWED_FILES:
            if name == "out.json":
                assert "out.2602.1.json" in names, "out.json must be versioned as out.2602.1.json"
            else:
                assert name in names

    def test_runtime_bundle_manifest_renamed_in_archive(self, tmp_path):
        copied, manifest_path = self._run(tmp_path, filenames=_ALLOWED_FILES + ["manifest.json"])
        subdir = manifest_path.parent
        names = {p.name for p in copied}
        assert "runtime_bundle_manifest.json" in names
        assert (subdir / "runtime_bundle_manifest.json").exists()
        assert not (subdir / "manifest.json").exists()
        manifest_text = manifest_path.read_text(encoding="utf-8")
        assert "`runtime_bundle_manifest.json`" in manifest_text
        assert "`manifest.json`" not in manifest_text

    def test_diagnostic_artifacts_preserve_subdirectories(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        diagnostic_dir = tmp_path / "hub" / "data" / "local" / "2602"
        (diagnostic_dir / "bundle").mkdir(parents=True)
        (diagnostic_dir / "rad").mkdir()
        (diagnostic_dir / "routes").mkdir()
        (diagnostic_dir / "tmp").mkdir()
        (diagnostic_dir / "repro_manifest.json").write_text('{"repro": true}', encoding="utf-8")
        (diagnostic_dir / "bundle" / "runtime_rules.json").write_text('{"bundle": true}', encoding="utf-8")
        (diagnostic_dir / "rad" / "runtime_rules.json").write_text('{"rad": true}', encoding="utf-8")
        (diagnostic_dir / "routes" / "out.pre-curation.json").write_text('{"snapshot": true}', encoding="utf-8")
        (diagnostic_dir / "tmp" / "full_trace.summary.json").write_text('{"summary": true}', encoding="utf-8")
        (diagnostic_dir / "tmp" / "full_trace.jsonl").write_text("large trace\n", encoding="utf-8")

        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            copied, manifest_path = archive_cycle(
                CYCLE_2602,
                cycle_dir,
                archive_repo,
                diagnostic_dir=diagnostic_dir,
            )

        subdir = manifest_path.parent
        names = {p.relative_to(subdir).as_posix() for p in copied}
        assert "repro_manifest.json" in names
        assert "bundle/runtime_rules.json" in names
        assert "rad/runtime_rules.json" in names
        assert "routes/out.pre-curation.json" in names
        assert "diagnostics/summaries/full_trace.summary.json" in names
        assert "diagnostics/summaries/full_trace.jsonl" not in names

        manifest_text = manifest_path.read_text(encoding="utf-8")
        assert "`bundle/runtime_rules.json`" in manifest_text
        assert "`rad/runtime_rules.json`" in manifest_text
        assert "`diagnostics/summaries/full_trace.summary.json`" in manifest_text

    def test_ad2_source_pages_preserve_subdirectory(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        ad2_dir = cycle_dir / "ad2"
        ad2_dir.mkdir()
        (ad2_dir / "EG-AD-2.EGLL-en-GB.html").write_text("<html>egll</html>", encoding="utf-8")
        (ad2_dir / "ignore.txt").write_text("no", encoding="utf-8")

        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            copied, manifest_path = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

        subdir = manifest_path.parent
        names = {p.relative_to(subdir).as_posix() for p in copied}
        assert "ad2/EG-AD-2.EGLL-en-GB.html" in names
        assert "ad2/ignore.txt" not in names

        manifest_text = manifest_path.read_text(encoding="utf-8")
        assert "`ad2/EG-AD-2.EGLL-en-GB.html`" in manifest_text

    def test_optional_curation_note_copied_when_present(self, tmp_path):
        copied, _ = self._run(tmp_path, filenames=_ALLOWED_FILES + _OPTIONAL_ALLOWED_FILES)
        names = {p.name for p in copied}
        assert "curation_notes.md" in names

    def test_non_allowed_files_not_copied(self, tmp_path):
        cycle_dir = _make_full_cycle_dir(tmp_path)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            copied, _ = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        names = {p.name for p in copied}
        for name in _NON_ALLOWED_FILES:
            assert name not in names

    def test_raises_when_cycle_dir_missing(self, tmp_path):
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        missing_dir = tmp_path / "vFPC 9999"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with pytest.raises(ArchiverError, match="does not exist"):
                archive_cycle(CYCLE_2602, missing_dir, archive_repo)

    def test_rerun_cleans_stale_non_out_files(self, tmp_path):
        """Re-archiving removes stale non-out files from the archive dir."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        subdir = archive_repo / "vFPC 2602"
        # Manually place a stale file in the archive dir
        (subdir / "stale.txt").write_text("leftover")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert not (subdir / "stale.txt").exists(), (
            "Stale file must be removed on re-archive"
        )

    def test_out_json_renamed_to_versioned(self, tmp_path):
        """out.json from the source dir should be archived as out.{ident}.1.json."""
        copied, _ = self._run(tmp_path)
        subdir = copied[0].parent
        assert not (subdir / "out.json").exists(), "bare out.json must not remain"
        assert (subdir / "out.2602.1.json").exists()

    def test_out_version_uses_parser_cycle_on_rearchive(self, tmp_path):
        """Re-archiving uses the parser output cycle rather than local sequence."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        subdir = archive_repo / "vFPC 2602"
        assert (subdir / "out.2602.1.json").exists()

        (cycle_dir / "out.json").write_text('{"cycle": "2602.7", "constraints": []}', encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert (subdir / "out.2602.1.json").exists(), "version 1 must be preserved"
        assert (subdir / "out.2602.7.json").exists(), "parser release 7 must be created"

    def test_out_version_preserved_contents_across_three_parser_releases(self, tmp_path):
        """Archive runs should preserve each parser release named by out.json."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        subdir = archive_repo / "vFPC 2602"

        for i in (1, 4, 9):
            (cycle_dir / "out.json").write_text(f'{{"cycle": "2602.{i}", "release": {i}}}', encoding="utf-8")
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

        for i in (1, 4, 9):
            p = subdir / f"out.2602.{i}.json"
            assert p.exists(), f"version {i} must exist"
            assert f'"cycle": "2602.{i}"' in p.read_text()

    def test_rearchive_same_parser_release_with_different_content_raises(self, tmp_path):
        """A parser release filename cannot be overwritten with different content."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

        (cycle_dir / "out.json").write_text('{"cycle": "2602.1", "changed": true}', encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with pytest.raises(ArchiverError, match="already exists with different content"):
                archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

    def test_rearchive_same_parser_release_with_same_content_succeeds(self, tmp_path):
        """Re-running the same parser release with identical content is idempotent."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        subdir = archive_repo / "vFPC 2602"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

        first_content = (subdir / "out.2602.1.json").read_text(encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)

        assert not (subdir / "out.json").exists()
        assert (subdir / "out.2602.1.json").read_text(encoding="utf-8") == first_content

    def test_manifest_lists_all_out_versions(self, tmp_path):
        """Manifest after re-archive must list both parser release outputs."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        (cycle_dir / "out.json").write_text('{"cycle": "2602.2"}', encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _, manifest_path = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        text = manifest_path.read_text()
        assert "out.2602.1.json" in text
        assert "out.2602.2.json" in text

    def test_no_out_json_skips_versioning(self, tmp_path):
        """If out.json is absent from the source dir, versioning is a no-op."""
        files_without_out = [f for f in _ALLOWED_FILES if f != "out.json"]
        copied, _ = self._run(tmp_path, filenames=files_without_out)
        subdir = copied[0].parent
        assert not any(_OUT_VERSION_RE.match(p.name) for p in subdir.iterdir())

    def test_rearchive_without_out_preserves_existing_versions(self, tmp_path):
        """Re-archiving when source has no out.json must keep existing versions."""
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        subdir = archive_repo / "vFPC 2602"

        # First run: creates out.2602.1.json
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert (subdir / "out.2602.1.json").exists()

        # Remove out.json from source and re-archive
        (cycle_dir / "out.json").unlink()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert (subdir / "out.2602.1.json").exists(), (
            "Existing versioned out.json must survive re-archive even when source has no out.json"
        )

    def test_succeeds_with_missing_expected_file(self, tmp_path):
        partial = [f for f in _ALLOWED_FILES if f != "UK_2026_02.sct"]
        copied, manifest_path = self._run(tmp_path, filenames=partial)
        assert manifest_path.exists()
        assert "UK_2026_02.sct" not in {p.name for p in copied}

    def test_manifest_records_missing_file_warning(self, tmp_path):
        partial = [f for f in _ALLOWED_FILES if f != "UK_2026_02.sct"]
        _, manifest_path = self._run(tmp_path, filenames=partial)
        text = manifest_path.read_text()
        assert "UK_2026_02.sct" in text
        assert "MISSING" in text

    def test_git_add_called_once(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        assert mock_run.call_count == 1

    def test_git_add_stages_manifest(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
        archive_repo = tmp_path / "airac-data"
        archive_repo.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _, manifest_path = archive_cycle(CYCLE_2602, cycle_dir, archive_repo)
        cmd = mock_run.call_args[0][0]
        assert str(manifest_path) in cmd

    def test_raises_on_git_failure(self, tmp_path):
        cycle_dir = _make_cycle_dir(tmp_path, _ALLOWED_FILES)
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
