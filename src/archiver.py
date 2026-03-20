"""Collect cycle files and stage them as flat files in the airac-data repo.

Workflow
--------
1. Collect all files from the cycle working directory, excluding known noise
   (IDE artifacts, Excel source, timestamped duplicates).
2. Warn about any expected files that are absent — but proceed regardless.
3. Write a manifest.md recording cycle metadata, file list, and SHA256 checksums.
4. Copy all collected files plus the manifest into the archive repo under
   ``{archive_repo}/vFPC YYNN/``, then run ``git add`` to stage them.

Archive layout in airac-data repo
----------------------------------
``{archive_repo}/vFPC YYNN/<filename>``   — one flat file per collected file
``{archive_repo}/vFPC YYNN/manifest.md``  — cycle metadata + checksums

Expected files (warning if absent)
-----------------------------------
Every archive should contain these files.  Their absence is logged as a warning
but does not prevent archiving:

- Routes.csv          — SRD Parser route input
- Notes.csv           — SRD Parser notes input
- EG-ENR-3.2-en-GB.html — AIP Parser ENR 3.2 input
- EG-ENR-3.3-en-GB.html — AIP Parser ENR 3.3 input
- UK_{YYYY}_{NN}.sct  — VATSIM UK sector file
- in.json             — SRD Parser config input
- out.json            — SRD Parser output
- aip_segments.json   — AIP Parser output (MC resolution input)

Excluded files (never archived)
--------------------------------
- ``*.xlsx`` — NATS source Excel; superseded by Routes.csv / Notes.csv
- ``output_*.json`` — timestamped parser duplicates; out.json is canonical
- ``*.iml``, ``.idea/``, ``__pycache__/`` — IDE and build artefacts
"""

from __future__ import annotations

import getpass
import hashlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.airac import AiracCycle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIR_PREFIX = "vFPC "

# Files we warn about if absent — in the order they should appear in the manifest.
_EXPECTED_FIXED = [
    "Routes.csv",
    "Notes.csv",
    "EG-ENR-3.2-en-GB.html",
    "EG-ENR-3.3-en-GB.html",
    "in.json",
    "out.json",
    "aip_segments.json",
]

# Glob patterns matched against each file's name — matching files are excluded.
_EXCLUDE_PATTERNS = [
    "*.xlsx",           # NATS source Excel
    "output_*.json",    # timestamped parser duplicates
    "*.iml",            # JetBrains module files
    "*.xml",            # JetBrains workspace / inspection XML
    "*.gitignore",      # IDE-generated gitignore
]

# Directory names — any entry whose path component matches is excluded entirely.
_EXCLUDE_DIRS = {".idea", "__pycache__", ".git", "node_modules"}

# Minimum number of expected files that must be present before archiving proceeds.
# Fewer than this indicates a missing or wrong cycle directory, not just an incomplete cycle.
_MIN_EXPECTED_PRESENT = 3


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


def _is_excluded(path: Path, cycle_dir: Path) -> bool:
    """Return True if *path* should be excluded from the archive."""
    # Exclude anything inside a blacklisted directory
    try:
        rel = path.relative_to(cycle_dir)
    except ValueError:
        return True
    for part in rel.parts[:-1]:       # all directory components
        if part in _EXCLUDE_DIRS:
            return True

    # Exclude by filename pattern
    name = path.name
    for pattern in _EXCLUDE_PATTERNS:
        if path.match(pattern):
            return True

    return False


def _collect_files(cycle_dir: Path, cycle: AiracCycle) -> tuple[list[Path], list[str]]:
    """Collect all archivable files from *cycle_dir*.

    Returns a ``(files, warnings)`` tuple where:
    - ``files`` is the list of Paths to archive (sorted by name)
    - ``warnings`` lists the names of expected files that are absent

    Raises:
        ArchiverError: if *cycle_dir* does not exist, or if duplicate basenames
            are found among the collected files (flat copy would silently overwrite),
            or if fewer than ``_MIN_EXPECTED_PRESENT`` expected files are present
            (indicates a wrong or missing cycle directory).
    """
    if not cycle_dir.is_dir():
        raise ArchiverError(
            f"Cycle directory does not exist: {cycle_dir}\n"
            "Check workspace_base in config and the cycle ident."
        )

    all_files = sorted(
        p for p in cycle_dir.rglob("*")
        if p.is_file() and not _is_excluded(p, cycle_dir)
    )

    # Detect duplicate basenames — flat copy would silently overwrite
    seen: dict[str, Path] = {}
    duplicates: list[str] = []
    for p in all_files:
        if p.name in seen:
            duplicates.append(f"  {seen[p.name].relative_to(cycle_dir)}  vs  {p.relative_to(cycle_dir)}")
        else:
            seen[p.name] = p
    if duplicates:
        raise ArchiverError(
            f"Duplicate basenames found in {cycle_dir} — flat archive would overwrite files:\n"
            + "\n".join(duplicates)
            + "\nRename or remove the duplicates before archiving."
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
    """Collect cycle files and stage them as flat files in the airac-data repo.

    Collects all non-excluded files from *cycle_dir*, warns about any expected
    files that are absent, writes a manifest with SHA256 checksums, copies
    everything into ``{archive_repo}/vFPC {ident}/``, and runs ``git add``.

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

    # Remove any previously archived files so a re-run leaves no stale content.
    # This ensures the archive directory always exactly reflects the current cycle_dir.
    if subdir.exists():
        shutil.rmtree(subdir)
    subdir.mkdir(parents=True)

    manifest_path = subdir / "manifest.md"

    # Write manifest alongside the source files so its checksum is not
    # included in the file table (it can't hash itself).
    _create_manifest(cycle, files, warnings, manifest_path)

    # Copy source files into the archive subdir
    copied = _copy_files(files, subdir)

    # Stage everything: copied files + manifest
    all_staged = copied + [manifest_path]
    _git_stage(archive_repo, *all_staged)

    return copied, manifest_path
