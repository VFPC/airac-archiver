"""CLI entry point for the AIRAC Archiver.

Usage
-----
Run via the module entry point::

    python -m src archive [--cycle YYNN]

The ``archive`` command:

1. Resolves the target AIRAC cycle (defaults to the current cycle).
2. Locates the cycle working directory under ``workspace_base``
   (``vFPC YYNN/`` — e.g. ``vFPC 2603/``).
3. Collects all seven required files from that directory.
4. Creates ``{archive_repo}/vFPC YYNN/vFPC YYNN.zip`` and ``manifest.md``.
5. Runs ``git add`` to stage both files for review before committing.

Run this command after the SRD Parser has written ``out.json`` into
the cycle working directory.
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import click

from src.airac import AiracCycle, current_cycle, cycle_for_date
from src.archiver import ArchiverError, _collect_files, archive_cycle
from src.config import ConfigError, load

_IDENT_RE = re.compile(r"^\d{4}$")


def _resolve_cycle(ident: str | None) -> AiracCycle:
    """Return the AiracCycle for *ident* (YYNN), or the current cycle if None."""
    if ident is None:
        return current_cycle()

    if not _IDENT_RE.match(ident):
        raise click.BadParameter(
            f"'{ident}' is not a valid cycle ident — expected 4 digits, e.g. '2603'.",
            param_hint="'--cycle'",
        )

    year = 2000 + int(ident[:2])
    number = int(ident[2:])

    if number < 1 or number > 13:
        raise click.BadParameter(
            f"Cycle number {number} is out of range (1–13).",
            param_hint="'--cycle'",
        )

    c = cycle_for_date(date(year, 1, 1))
    if c.year < year:
        c = c.next
    target = cycle_for_date(c.effective_date + timedelta(days=(number - 1) * 28))

    if target.ident != ident:
        raise click.BadParameter(
            f"Could not resolve cycle ident '{ident}'. "
            "Check that the year and number are correct.",
            param_hint="'--cycle'",
        )
    return target


def _abort(message: str) -> None:
    click.echo(f"\nError: {message}", err=True)
    sys.exit(1)


@click.group()
def cli() -> None:
    """AIRAC Archiver — zip and stage prepared cycle files for airac-data."""


@cli.command()
@click.option(
    "--cycle", "-c",
    default=None,
    metavar="YYNN",
    help="AIRAC cycle ident to archive (e.g. 2603). Defaults to the current cycle.",
)
def archive(cycle: str | None) -> None:
    """Zip prepared cycle files and stage them in the airac-data repo.

    Requires that the SRD Parser has been run so that out.json is present
    in the cycle working directory.
    """
    try:
        cfg = load()
    except ConfigError as exc:
        _abort(str(exc))

    try:
        target = _resolve_cycle(cycle)
    except click.BadParameter as exc:
        _abort(str(exc))

    cycle_dir = cfg.workspace_base / f"vFPC {target.ident}"

    click.echo(f"\nCycle:        {target}")
    click.echo(f"Working dir:  {cycle_dir}")
    click.echo(f"Archive repo: {cfg.archive_repo}\n")

    # Surface warnings before archiving so the operator can see them clearly
    _, warnings = _collect_files(cycle_dir, target)
    if warnings:
        click.echo("  Warnings — expected files not found:", err=True)
        for name in warnings:
            click.echo(f"    MISSING: {name}", err=True)
        click.echo("  Proceeding with incomplete archive.\n", err=True)

    click.echo("  Collecting files, writing manifest, copying, staging...", nl=False)
    try:
        copied, manifest_path = archive_cycle(target, cycle_dir, cfg.archive_repo)
    except ArchiverError as exc:
        click.echo("")
        _abort(str(exc))

    click.echo(" done")
    click.echo(f"\n  {len(copied)} file(s) + manifest staged in:")
    click.echo(f"  {manifest_path.parent}")
    click.echo("\nReview and commit when ready.")


if __name__ == "__main__":
    cli()
