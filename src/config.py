"""Load and validate config.yaml / config.local.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).parent.parent


class ConfigError(ValueError):
    """Raised when config.yaml is missing, unreadable, or fails validation."""


@dataclass(frozen=True)
class Config:
    workspace_base: Path
    archive_repo: Path


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict with *override* recursively merged on top of *base*."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _require_str(raw: dict, key: str) -> str:
    if key not in raw or not raw[key]:
        raise ConfigError(f"Required config key '{key}' is missing or empty.")
    return str(raw[key])


def _parse(raw: dict) -> Config:
    return Config(
        workspace_base=Path(_require_str(raw, "workspace_base")),
        archive_repo=Path(_require_str(raw, "archive_repo")),
    )


def load(config_path: Path | None = None) -> Config:
    """Load and return the merged configuration.

    Reads *config_path* (defaults to ``config.yaml`` in the project root).
    If a sibling ``config.local.yaml`` exists it is deep-merged on top,
    allowing per-machine path overrides without touching the committed file.

    Raises ``ConfigError`` if the file is missing, unparseable, or required
    keys are absent.
    """
    base_path = config_path if config_path is not None else _PROJECT_ROOT / "config.yaml"

    if not base_path.exists():
        raise ConfigError(f"Config file not found: {base_path}")

    try:
        raw: dict = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {base_path}: {exc}") from exc

    local_path = base_path.with_name("config.local.yaml")
    if local_path.exists():
        try:
            local_raw: dict = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse {local_path}: {exc}") from exc
        raw = _deep_merge(raw, local_raw)

    return _parse(raw)
