"""Zip prepared cycle files and stage in the airac-data repo with a manifest.

Workflow
--------
1. Verify all seven required files are present in the cycle working directory.
2. Create a zip containing those files (flat layout, no sub-directories).
3. Write a manifest.md alongside the zip.
4. Run ``git add`` on both files so they are staged for the user's review
   before committing.

Archive layout in airac-data repo
----------------------------------
``{archive_repo}/vFPC YYNN/vFPC YYNN.zip``
``{archive_repo}/vFPC YYNN/manifest.md``

Required files
--------------
Every archive must contain exactly these seven files:

- Routes.csv          — SRD Parser route input
- Notes.csv           — SRD Parser notes input
- EG-ENR-3.2-en-GB.html — AIP Parser ENR 3.2 input
- EG-ENR-3.3-en-GB.html — AIP Parser ENR 3.3 input
- UK_{YYYY}_{NN}.sct  — VATSIM UK sector file
- in.json             — SRD Parser config input (copied forward)
- out.json            — SRD Parser output (written after a successful parser run)
"""

from __future__ import annotations

import getpass
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.airac import AiracCycle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIR_PREFIX = "vFPC "

_FIXED_REQUIRED = [
    "Routes.csv",
    "Notes.csv",
    "EG-ENR-3.2-en-GB.html",
    "EG-ENR-3.3-en-GB.html",
    "in.json",
    "out.json",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ArchiverError(Exception):
    """Raised when archiving fails due to missing files or a git error."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _archive_dir_name(cycle: AiracCycle) -> str:
    """Return the subdirectory name for *cycle* in the airac-data repo."""
    return f"{_DIR_PREFIX}{cycle.ident}"


def _sct_basename(cycle: AiracCycle) -> str:
    """Return the expected SCT filename for *cycle*."""
    return f"UK_{cycle.year}_{cycle.number:02d}.sct"


def _collect_files(cycle_dir: Path, cycle: AiracCycle) -> list[Path]:
    """Collect and validate all required files from *cycle_dir*.

    Returns a list of Paths for all seven required files in a stable order.
    Raises ArchiverError listing every missing file if any are absent.
    """
    required_names = _FIXED_REQUIRED + [_sct_basename(cycle)]
    missing: list[str] = []
    paths: list[Path] = []

    for name in required_names:
        p = cycle_dir / name
        if not p.exists():
            missing.append(name)
        else:
            paths.append(p)

    if missing:
        raise ArchiverError(
            f"Cannot archive cycle {cycle.ident} — the following required files "
            f"are missing from {cycle_dir}:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    return paths


def _create_zip(files: list[Path], zip_path: Path) -> None:
    """Create a zip archive at *zip_path* containing *files* in a flat layout."""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            zf.write(file_path, arcname=file_path.name)


def _create_manifest(
    cycle: AiracCycle,
    files: list[Path],
    manifest_path: Path,
) -> None:
    """Write a manifest.md recording the archive metadata."""
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
        "## Files",
        "",
    ]
    for file_path in sorted(files, key=lambda p: p.name):
        lines.append(f"- `{file_path.name}`")
    lines.append("")

    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def _git_stage(archive_repo: Path, *paths: Path) -> None:
    """Run ``git add`` for *paths* inside *archive_repo*.

    Raises ArchiverError if git returns a non-zero exit code.
    """
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
) -> tuple[Path, Path]:
    """Zip the prepared cycle files and stage them in the airac-data repo.

    Collects the seven required files from *cycle_dir*, creates
    ``{archive_repo}/vFPC {ident}/vFPC {ident}.zip`` and a sibling
    ``manifest.md``, then runs ``git add`` so both are staged for review
    before committing.

    Args:
        cycle:        The target AIRAC cycle.
        cycle_dir:    Local working directory containing the prepared files.
        archive_repo: Local clone of the airac-data repository.

    Returns:
        A ``(zip_path, manifest_path)`` tuple for the two files written.

    Raises:
        ArchiverError: if any required file is missing, or if ``git add`` fails.
    """
    files = _collect_files(cycle_dir, cycle)

    subdir_name = _archive_dir_name(cycle)
    subdir = archive_repo / subdir_name
    subdir.mkdir(parents=True, exist_ok=True)

    zip_path = subdir / f"{subdir_name}.zip"
    manifest_path = subdir / "manifest.md"

    _create_zip(files, zip_path)
    _create_manifest(cycle, files, manifest_path)
    _git_stage(archive_repo, zip_path, manifest_path)

    return zip_path, manifest_path
