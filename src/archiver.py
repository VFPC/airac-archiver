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
``{archive_repo}/vFPC YYNN/out.YYNN.{n}.json``      — versioned parser output
``{archive_repo}/vFPC YYNN/manifest.md``             — cycle metadata + checksums

Versioned out.json
-------------------
The parser writes ``out.json`` into the working directory.  During archival
this file is renamed to ``out.{ident}.{n}.json`` (e.g. ``out.2603.1.json``).
Re-archiving the same cycle increments *n*, and all previous versions are
preserved.  The manifest lists every version.

Allowlisted files
------------------
Only files matching these names are archived.  All other files in the working
directory are silently ignored:

- Routes.csv          — SRD route data (hard to re-obtain)
- Notes.csv           — SRD notes data (hard to re-obtain)
- UK_{YYYY}_{NN}.sct  — VATSIM UK sector file (hard to re-obtain)
- in.json             — SRD Parser config input
- out.json            — SRD Parser output (archived as out.YYNN.n.json)
- curation_notes.md   — optional cycle-specific manual curation note

Only the required files are logged as warnings when absent; the curation note
is archived when present and ignored when absent.

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
]

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

# Versioned out.json: out.{ident}.{n}.json — e.g. out.2603.1.json
_OUT_VERSION_RE = re.compile(r"^out\.(\d{4})\.(\d+)\.json$")


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


def _out_version_name(cycle: AiracCycle, n: int) -> str:
    """Return the versioned filename for out.json: ``out.{ident}.{n}.json``."""
    return f"out.{cycle.ident}.{n}.json"


def _existing_out_versions(directory: Path, cycle: AiracCycle) -> list[Path]:
    """Return all ``out.{ident}.{n}.json`` files in *directory*, sorted by version."""
    results = []
    if not directory.is_dir():
        return results
    for p in directory.iterdir():
        m = _OUT_VERSION_RE.match(p.name)
        if m and m.group(1) == cycle.ident:
            results.append(p)
    return sorted(results, key=lambda p: int(_OUT_VERSION_RE.match(p.name).group(2)))


def _next_out_version(directory: Path, cycle: AiracCycle) -> int:
    """Return the next version number for ``out.{ident}.{n}.json`` in *directory*."""
    existing = _existing_out_versions(directory, cycle)
    if not existing:
        return 1
    last_n = int(_OUT_VERSION_RE.match(existing[-1].name).group(2))
    return last_n + 1


def _is_allowed(path: Path, allowed_names: set[str]) -> bool:
    """Return True if *path*'s filename is in the allowlist."""
    return path.name in allowed_names


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
    for file_path in sorted(files, key=lambda p: p.name):
        checksum = _sha256(file_path)
        lines.append(f"| `{file_path.name}` | `{checksum}` |")
    lines.append("")

    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def _copy_files(files: list[Path], dest_dir: Path) -> list[Path]:
    """Copy *files* into *dest_dir*, returning the list of destination paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in files:
        dst = dest_dir / src.name
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def archive_cycle(
    cycle: AiracCycle,
    cycle_dir: Path,
    archive_repo: Path,
) -> tuple[list[Path], Path]:
    """Collect allowlisted cycle files and stage them in the airac-data repo.

    Collects only allowlisted files from *cycle_dir*, warns about any expected
    files that are absent, writes a manifest with SHA256 checksums, copies
    everything into ``{archive_repo}/vFPC {ident}/``, and runs ``git add``.

    ``out.json`` is renamed to ``out.{ident}.{n}.json`` where *n* increments
    on each archive run.  Previous versions are preserved across re-archives.

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

    subdir = archive_repo / _archive_dir_name(cycle)

    # Preserve previously-archived out.{ident}.{n}.json versions by moving
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

    # Determine the next version number for out.json and prepare the rename.
    # _copy_files copies everything flat, so we handle the rename afterwards.
    has_out = any(p.name == "out.json" for p in files)
    out_version_path: Path | None = None
    if has_out:
        version_n = _next_out_version(subdir, cycle)
        out_version_name = _out_version_name(cycle, version_n)

    manifest_path = subdir / "manifest.md"

    # Copy source files into the archive subdir
    copied = _copy_files(files, subdir)

    # Rename out.json → out.{ident}.{n}.json
    if has_out:
        old_out = subdir / "out.json"
        out_version_path = subdir / out_version_name
        old_out.rename(out_version_path)
        copied = [out_version_path if p.name == "out.json" else p for p in copied]

    # Collect all out versions (preserved + new) for the manifest
    all_out_versions = _existing_out_versions(subdir, cycle)

    # Build the full file list for the manifest: non-out copied files + all out versions
    manifest_files = [p for p in copied if not _OUT_VERSION_RE.match(p.name)]
    manifest_files.extend(all_out_versions)

    # Write manifest alongside the source files so its checksum is not
    # included in the file table (it can't hash itself).
    _create_manifest(cycle, manifest_files, warnings, manifest_path)

    # Stage everything: copied files + preserved out versions + manifest
    all_staged = copied + [p for p in all_out_versions if p not in copied] + [manifest_path]
    _git_stage(archive_repo, *all_staged)

    return copied, manifest_path
