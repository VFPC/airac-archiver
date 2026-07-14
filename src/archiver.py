"""Collect cycle files and stage them as flat files in the airac-data repo.

Workflow
--------
1. Collect only allowlisted files from the cycle working directory.
   Everything else is silently ignored.
2. Warn about any expected files that are absent — but proceed regardless.
3. Write a manifest.md recording cycle metadata, file list, and SHA256 checksums.
4. Copy all collected files plus the manifest into the archive repo under
   ``{archive_repo}/vFPC YYNN/``, then run ``git add`` to stage them.

Archive layout in airac-data repo
----------------------------------
``{archive_repo}/vFPC YYNN/<filename>``             — one flat file per collected file
``{archive_repo}/vFPC YYNN/out.<cycle>.json``       - parser output named from out.json
``{archive_repo}/vFPC YYNN/manifest.md``             — cycle metadata + checksums

Versioned out.json
-------------------
The parser writes ``out.json`` into the working directory.  During archival
this file is renamed from its embedded ``cycle`` value (e.g. ``2605.9`` becomes
``out.2605.9.json``). Not every parser dot release is moved to production, so
archive filenames follow the parser output instead of local archive sequence.

Allowlisted files
------------------
Only files matching these names are archived.  All other files in the working
directory are silently ignored:

- Routes.csv          — SRD route data (hard to re-obtain)
- Notes.csv           — SRD notes data (hard to re-obtain)
- UK_{YYYY}_{NN}.sct  — VATSIM UK sector file (hard to re-obtain)
- in.json             — SRD Parser config input
- out.json            - SRD Parser output (archived as out.<cycle>.json)
- curation_notes.md   - optional cycle-specific manual curation note
- Routes.*curation/edits*.json|md and vfp*_curation*.json|md
                       - optional route patch reconstruction evidence
- aip_*.json / enr44_points.json — optional AIP rebuild artifacts
- runtime_rules.json and bundle fact/index files — optional RAD runtime artifacts
- manifest.json      — optional runtime bundle manifest, archived as
                       runtime_bundle_manifest.json

Only the required files are logged as warnings when absent; optional files are
archived when present and ignored when absent.

Concurrency
-----------
This tool assumes **single-writer, manual invocation** — only one process
archives a given cycle at a time.  There is no file lock or atomic-swap
mechanism.  If two processes archive the same cycle concurrently, they may
pick the same out.json version number or race on the rmtree/restore
sequence, losing one run's output.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.airac import AiracCycle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIR_PREFIX = "vFPC "

# Allowlisted filenames (exact match). Only these — plus the cycle-specific
# .sct file — are collected from the working directory. Everything else is
# silently ignored.
_ALLOWED_FIXED = [
    "Routes.csv",
    "Notes.csv",
    "in.json",
    "out.json",
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
]

_ARCHIVE_RENAMES = {
    "manifest.json": "runtime_bundle_manifest.json",
}

# Required files that should normally be present for a valid cycle archive.
# Their absence is recorded as a warning in the manifest. Optional allowlisted
# files such as curation_notes.md are archived when present but do not warn
# when absent.
_EXPECTED_FIXED = [
    "Routes.csv",
    "Notes.csv",
    "in.json",
    "out.json",
]

# Minimum number of expected files that must be present before archiving proceeds.
# Fewer than this indicates a missing or wrong cycle directory, not just an incomplete cycle.
_MIN_EXPECTED_PRESENT = 3

# Versioned out.json: out.{cycle}.json — e.g. out.2605.9.json
_OUT_VERSION_RE = re.compile(r"^out\.(\d{4})(?:\.(\d+))?\.json$")
_OUT_CYCLE_RE = re.compile(r"^\d{4}(?:\.\d+)?$")
_ARCHIVE_DIR_RE = re.compile(r"^vFPC (\d{4})$")
_SCT_RE = re.compile(r"^UK_\d{4}_\d{2}\.sct$")
_CURATION_AUDIT_RE = re.compile(
    r"^(?:Routes\..*(?:curation|edits).*|vfp\d+_.*curation.*)\.(?:json|md)$",
    re.IGNORECASE,
)
_SOURCE_PROVENANCE_RE = re.compile(
    r"^(?:"
    r"RAD_\d{4}_v\d+_\d+\.xlsx|"
    r"UK and Ireland SRD .+\.xlsx|"
    r"EG-ENR-[\d.]+-en-GB\.html|"
    r"EI[-_].*\.(?:html|pdf)|"
    r"FR-ENR-[\d.]+-fr-FR\.html|"
    r"airac_manifest\.(?:json|md)|"
    r"fetcher_log_\d+_\d+\.txt|"
    r"in\..*\.json|"
    r"in\.json\.pre-.*\.bak"
    r")$",
    re.IGNORECASE,
)
_DIAGNOSTIC_ARCHIVE_PATTERNS = (
    "repro_manifest.json",
    "bundle/*.json",
    "rad/*.json",
    "routes/out.pre-*.json",
    "tmp/*.summary.json",
    "tmp/*_summary.json",
    "tmp/ifpuv_probe_plan_*.md",
)
_SOURCE_TREE_ARCHIVE_PATTERNS = (
    "ad2/EG-AD-2.*-en-GB.html",
)

_SLIM_DROP_FIXED = {
    "Routes.csv",
    "Notes.csv",
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
}
# runtime_bundle_manifest.json is intentionally preserved as provenance for
# archived runtime bundles, even though the source manifest.json is allowlisted.


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ArchiverError(Exception):
    """Raised when archiving fails due to a git error or unrecoverable I/O problem."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _archive_dir_name(cycle: AiracCycle) -> str:
    return f"{_DIR_PREFIX}{cycle.ident}"


def _sct_basename(cycle: AiracCycle) -> str:
    return f"UK_{cycle.year}_{cycle.number:02d}.sct"


def _out_version_name(cycle_value: str) -> str:
    """Return the archived filename for an out.json cycle value."""
    if not _OUT_CYCLE_RE.match(cycle_value):
        raise ArchiverError(f"Invalid out.json cycle value: {cycle_value!r}")
    return f"out.{cycle_value}.json"


def _existing_out_versions(directory: Path, cycle: AiracCycle) -> list[Path]:
    """Return all ``out.{ident}[.{release}].json`` files in *directory*."""
    results = []
    if not directory.is_dir():
        return results
    for p in directory.iterdir():
        m = _OUT_VERSION_RE.match(p.name)
        if m and m.group(1) == cycle.ident:
            results.append(p)
    return sorted(
        results,
        key=lambda p: (
            -1 if _OUT_VERSION_RE.match(p.name).group(2) is None
            else int(_OUT_VERSION_RE.match(p.name).group(2))
        ),
    )


def _next_out_version(directory: Path, cycle: AiracCycle) -> int:
    """Return the next legacy archive sequence number for compatibility callers."""
    existing = _existing_out_versions(directory, cycle)
    numbered = [p for p in existing if _OUT_VERSION_RE.match(p.name).group(2)]
    if not numbered:
        return 1
    last_n = int(_OUT_VERSION_RE.match(numbered[-1].name).group(2))
    return last_n + 1


def _out_cycle_value(path: Path, cycle: AiracCycle) -> str:
    """Read and validate the parser cycle value from *path*."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArchiverError(f"out.json is not valid JSON: {path}") from exc

    cycle_value = payload.get("cycle")
    if not isinstance(cycle_value, str):
        raise ArchiverError(f"out.json is missing string cycle field: {path}")
    if not _OUT_CYCLE_RE.match(cycle_value):
        raise ArchiverError(f"Invalid out.json cycle value: {cycle_value!r}")
    if cycle_value.split(".", 1)[0] != cycle.ident:
        raise ArchiverError(
            f"out.json cycle {cycle_value!r} does not match archive cycle {cycle.ident!r}"
        )
    return cycle_value


def _is_allowed(path: Path, allowed_names: set[str]) -> bool:
    """Return True if *path*'s filename is in the allowlist."""
    return (
        path.name in allowed_names
        or bool(_CURATION_AUDIT_RE.match(path.name))
        or bool(_SOURCE_PROVENANCE_RE.match(path.name))
    )


def _collect_diagnostic_files(diagnostic_dir: Path | None) -> list[Path]:
    """Collect optional Hub diagnostic artifacts for reproducibility.

    The diagnostic directory is normally ``vFPC-Hub/data/local/YYNN``.  Missing
    directories are treated as an absent optional input so older SRD-only
    archive runs remain valid.
    """
    if diagnostic_dir is None or not diagnostic_dir.is_dir():
        return []

    files: set[Path] = set()
    for pattern in _DIAGNOSTIC_ARCHIVE_PATTERNS:
        files.update(
            path for path in diagnostic_dir.glob(pattern)
            if path.is_file()
        )
    return sorted(files, key=lambda p: p.relative_to(diagnostic_dir).as_posix())


def _collect_source_tree_files(cycle_dir: Path) -> list[Path]:
    """Collect source artifacts that must preserve subdirectory layout."""
    files: set[Path] = set()
    for pattern in _SOURCE_TREE_ARCHIVE_PATTERNS:
        files.update(
            path for path in cycle_dir.glob(pattern)
            if path.is_file()
        )
    return sorted(files, key=lambda p: p.relative_to(cycle_dir).as_posix())


def _collect_files(cycle_dir: Path, cycle: AiracCycle) -> tuple[list[Path], list[str]]:
    """Collect only allowlisted files from *cycle_dir*.

    Returns a ``(files, warnings)`` tuple where:
    - ``files`` is the list of Paths to archive (sorted by name)
    - ``warnings`` lists the names of expected files that are absent

    Raises:
        ArchiverError: if *cycle_dir* does not exist, or if fewer than
            ``_MIN_EXPECTED_PRESENT`` expected files are present (indicates a
            wrong or missing cycle directory).
    """
    if not cycle_dir.is_dir():
        raise ArchiverError(
            f"Cycle directory does not exist: {cycle_dir}\n"
            "Check workspace_base in config and the cycle ident."
        )

    allowed = set(_ALLOWED_FIXED) | {_sct_basename(cycle)}

    all_files = sorted(
        p for p in cycle_dir.iterdir()
        if p.is_file() and _is_allowed(p, allowed)
    )

    # Check for expected files and build warnings
    present_names = {p.name for p in all_files}
    expected = _EXPECTED_FIXED + [_sct_basename(cycle)]
    warnings = [name for name in expected if name not in present_names]

    # Guard against archiving a wrong or empty directory
    expected_present = len(expected) - len(warnings)
    if expected_present < _MIN_EXPECTED_PRESENT:
        raise ArchiverError(
            f"Only {expected_present} of {len(expected)} expected files found in {cycle_dir}. "
            f"At least {_MIN_EXPECTED_PRESENT} must be present. "
            "Check that this is the correct cycle directory."
        )

    return all_files, warnings


def _sha256(path: Path) -> str:
    """Return the hex SHA256 digest of *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _create_manifest(
    cycle: AiracCycle,
    files: list[Path],
    warnings: list[str],
    manifest_path: Path,
    *,
    root_path: Path | None = None,
) -> None:
    """Write a manifest.md recording cycle metadata, file list, and checksums."""
    now = datetime.now(tz=timezone.utc)
    user = getpass.getuser()
    dir_name = _archive_dir_name(cycle)

    lines = [
        f"# Archive manifest — {dir_name}",
        "",
        f"**Cycle:** {cycle.ident}  ",
        f"**Effective:** {cycle.effective_date.isoformat()}  ",
        f"**Expires:** {cycle.expiry_date.isoformat()}  ",
        f"**Archived:** {now.strftime('%Y-%m-%d %H:%M:%S')} UTC  ",
        f"**Archived by:** {user}  ",
        "",
    ]

    if warnings:
        lines += [
            "## Warnings",
            "",
        ]
        for name in warnings:
            lines.append(f"- `{name}` — **MISSING** from cycle directory")
        lines.append("")

    lines += [
        "## Files",
        "",
        "| File | SHA256 |",
        "|------|--------|",
    ]
    def display_name(path: Path) -> str:
        if root_path is None:
            return path.name
        try:
            return path.relative_to(root_path).as_posix()
        except ValueError:
            return path.name

    for file_path in sorted(files, key=display_name):
        checksum = _sha256(file_path)
        lines.append(f"| `{display_name(file_path)}` | `{checksum}` |")
    lines.append("")

    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def _copy_files(files: list[Path], dest_dir: Path) -> list[Path]:
    """Copy *files* into *dest_dir*, returning the list of destination paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in files:
        dst = dest_dir / _ARCHIVE_RENAMES.get(src.name, src.name)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def _copy_relative_files(
    files: list[Path],
    source_root: Path,
    dest_dir: Path,
    *,
    map_relative_path=None,
) -> list[Path]:
    """Copy *files* preserving paths relative to *source_root*."""
    copied = []
    for src in files:
        rel = src.relative_to(source_root)
        if map_relative_path is not None:
            rel = map_relative_path(rel)
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def _diagnostic_archive_relative_path(rel: Path) -> Path:
    """Return the archive path for a diagnostic relative path.

    ``tmp/`` is ignored by the airac-data repo at any depth, so selected
    summary artifacts from Hub's temporary work directory are archived under
    ``diagnostics/summaries/``.
    """
    parts = rel.parts
    if parts and parts[0].lower() == "tmp":
        return Path("diagnostics", "summaries", *parts[1:])
    return rel


def _git_stage(archive_repo: Path, *paths: Path) -> None:
    """Run ``git add`` for *paths* inside *archive_repo*."""
    result = subprocess.run(
        ["git", "add", "--"] + [str(p) for p in paths],
        cwd=archive_repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ArchiverError(
            f"git add failed in {archive_repo}:\n{result.stderr.strip()}"
        )


def _archive_cycle_dirs_before(archive_repo: Path, before_ident: str) -> list[Path]:
    """Return archived cycle directories whose YYNN ident is earlier than *before_ident*."""
    dirs: list[Path] = []
    if not archive_repo.is_dir():
        raise ArchiverError(f"Archive repo does not exist: {archive_repo}")
    for path in archive_repo.iterdir():
        if not path.is_dir():
            continue
        match = _ARCHIVE_DIR_RE.match(path.name)
        if match and match.group(1) < before_ident:
            dirs.append(path)
    return sorted(dirs, key=lambda p: p.name)


def _is_slim_drop_file(path: Path) -> bool:
    """Return True when *path* is removed by the archive slim policy."""
    return path.name in _SLIM_DROP_FIXED or bool(_SCT_RE.match(path.name))


def slim_candidates(archive_repo: Path, before_ident: str) -> list[Path]:
    """Return files that would be removed by the retention slim policy.

    The slim policy preserves ``out.YYNN.N.json``, ``manifest.md``,
    ``curation_notes.md``, and ``in.json``. It removes large source/rebuild
    artifacts from archived cycles older than *before_ident*.
    """
    candidates: list[Path] = []
    for cycle_dir in _archive_cycle_dirs_before(archive_repo, before_ident):
        candidates.extend(
            path for path in sorted(cycle_dir.iterdir(), key=lambda p: p.name)
            if path.is_file() and _is_slim_drop_file(path)
        )
    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def archive_cycle(
    cycle: AiracCycle,
    cycle_dir: Path,
    archive_repo: Path,
    diagnostic_dir: Path | None = None,
) -> tuple[list[Path], Path]:
    """Collect allowlisted cycle files and stage them in the airac-data repo.

    Collects only allowlisted files from *cycle_dir*, warns about any expected
    files that are absent, writes a manifest with SHA256 checksums, copies
    everything into ``{archive_repo}/vFPC {ident}/``, and runs ``git add``.

    ``out.json`` is renamed to match its embedded parser cycle value, for
    example ``out.2605.9.json``. Previous versions are preserved across
    re-archives.

    Args:
        cycle:        The target AIRAC cycle.
        cycle_dir:    Local working directory containing the prepared files.
        archive_repo: Local clone of the airac-data repository.

    Returns:
        A ``(copied_paths, manifest_path)`` tuple.

    Raises:
        ArchiverError: if *cycle_dir* does not exist, if duplicate basenames are
            found, if fewer than ``_MIN_EXPECTED_PRESENT`` expected files are present,
            or if ``git add`` fails.
    """
    files, warnings = _collect_files(cycle_dir, cycle)
    source_tree_files = _collect_source_tree_files(cycle_dir)
    diagnostic_files = _collect_diagnostic_files(diagnostic_dir)

    source_out = next((p for p in files if p.name == "out.json"), None)
    has_out = source_out is not None
    out_version_name: str | None = None
    if has_out:
        out_version_name = _out_version_name(_out_cycle_value(source_out, cycle))

    subdir = archive_repo / _archive_dir_name(cycle)
    if out_version_name is not None:
        existing_out = subdir / out_version_name
        if existing_out.exists() and _sha256(source_out) != _sha256(existing_out):
            raise ArchiverError(
                f"Archived parser output already exists with different content: {existing_out}"
            )

    # Preserve previously-archived out.{ident}[.{release}].json versions by moving
    # them to a temp directory on the same filesystem, then restoring after
    # rmtree.  This avoids holding file contents in RAM and minimises the
    # window where data is absent from both locations.
    tmp_hold: Path | None = None
    if subdir.exists():
        existing_versions = _existing_out_versions(subdir, cycle)
        if existing_versions:
            tmp_hold = Path(tempfile.mkdtemp(
                dir=archive_repo, prefix=".out-preserve-",
            ))
            for p in existing_versions:
                shutil.move(str(p), str(tmp_hold / p.name))
        shutil.rmtree(subdir)
    subdir.mkdir(parents=True)

    # Restore preserved out versions from the temp directory
    if tmp_hold is not None:
        for p in tmp_hold.iterdir():
            shutil.move(str(p), str(subdir / p.name))
        tmp_hold.rmdir()

    out_version_path: Path | None = None

    manifest_path = subdir / "manifest.md"

    # Copy source files into the archive subdir
    copied = _copy_files(files, subdir)
    source_tree_copied = _copy_relative_files(source_tree_files, cycle_dir, subdir)
    diagnostic_copied = (
        _copy_relative_files(
            diagnostic_files,
            diagnostic_dir,
            subdir,
            map_relative_path=_diagnostic_archive_relative_path,
        )
        if diagnostic_dir is not None
        else []
    )

    # Rename out.json to the parser cycle release filename.
    if has_out:
        old_out = subdir / "out.json"
        out_version_path = subdir / out_version_name
        if out_version_path.exists():
            old_out.unlink()
        else:
            old_out.rename(out_version_path)
        copied = [out_version_path if p.name == "out.json" else p for p in copied]

    # Collect all out versions (preserved + new) for the manifest
    all_out_versions = _existing_out_versions(subdir, cycle)

    # Build the full file list for the manifest: non-out copied files + all out versions
    manifest_files = [p for p in copied if not _OUT_VERSION_RE.match(p.name)]
    manifest_files.extend(source_tree_copied)
    manifest_files.extend(all_out_versions)
    manifest_files.extend(diagnostic_copied)

    # Write manifest alongside the source files so its checksum is not
    # included in the file table (it can't hash itself).
    _create_manifest(cycle, manifest_files, warnings, manifest_path, root_path=subdir)

    # Stage everything: copied files + preserved out versions + manifest
    all_staged = (
        copied
        + source_tree_copied
        + [p for p in all_out_versions if p not in copied]
        + diagnostic_copied
        + [manifest_path]
    )
    _git_stage(archive_repo, *all_staged)

    return copied + source_tree_copied + diagnostic_copied, manifest_path
