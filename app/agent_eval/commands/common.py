from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("output") / "agent-eval"


class CommandError(Exception):
    """User-facing CLI error with a clear message."""


def resolve_run_dir(raw: str, *, output_base: Path = DEFAULT_OUTPUT_BASE) -> Path:
    """Resolve a run directory path or the special `latest` reference."""
    if raw != "latest":
        path = Path(raw)
        if not path.is_dir():
            raise CommandError(f"Run directory not found: {path}")
        return path

    if not output_base.exists():
        raise CommandError(f"No benchmark run directories found in {output_base}")

    candidates = [
        path
        for path in output_base.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    if not candidates:
        raise CommandError(f"No benchmark run directories found in {output_base}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_json_file(path: Path) -> Any:
    """Read JSON and raise CommandError with the failing path."""
    if not path.exists():
        raise CommandError(f"JSON file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Malformed JSON file: {path}: {exc}") from exc
