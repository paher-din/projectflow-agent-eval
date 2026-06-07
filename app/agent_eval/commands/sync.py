"""Sync agent code from a ProjectFlow checkout into the benchmark repo."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.agent_eval.commands.common import CommandError

# Files to sync from ProjectFlow's agent directory.
# coordinator.py and workflow.py are NOT synced — the benchmark keeps its own
# lightweight versions that don't depend on sqlmodel/database.
_SYNC_AGENT_FILES = [
    "llm_client.py",
    "output_schemas.py",
    "prompts.py",
]
_SYNC_AGENT_DIRS = [
    "modules",
]

# Where to write sync metadata
_META_FILENAME = ".sync_meta.json"


def _find_projectflow_root(explicit: str = "") -> Path:
    """Resolve the ProjectFlow root from explicit arg or env var."""
    raw = explicit or os.getenv("PROJECTFLOW_ROOT", "")
    if not raw:
        raise CommandError(
            "ProjectFlow root not specified. "
            "Use --projectflow-root <path> or set PROJECTFLOW_ROOT env var."
        )
    root = Path(raw).resolve()
    backend_app = root / "backend" / "app"
    if backend_app.is_dir():
        return root
    flat_app = root / "app"
    if flat_app.is_dir():
        return root
    raise CommandError(
        f"Cannot find ProjectFlow app directory at {backend_app} or {flat_app}. "
        f"Check the path: {raw}"
    )


def _resolve_app_dir(projectflow_root: Path) -> Path:
    """Return the app/ directory inside the ProjectFlow checkout."""
    backend_app = projectflow_root / "backend" / "app"
    if backend_app.is_dir():
        return backend_app
    flat_app = projectflow_root / "app"
    if flat_app.is_dir():
        return flat_app
    raise CommandError(f"No app/ directory found under {projectflow_root}")


def _git_info(projectflow_root: Path) -> dict[str, str]:
    """Read git commit info from the ProjectFlow repo."""
    info: dict[str, str] = {"commit": "", "message": "", "dirty": "false", "dirty_summary": ""}

    def _run(cmd: list[str]) -> str:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(projectflow_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    info["commit"] = _run(["git", "rev-parse", "HEAD"])
    info["message"] = _run(["git", "log", "--oneline", "-1"])

    dirty_stat = _run(["git", "diff", "--stat", "HEAD"])
    if dirty_stat:
        info["dirty"] = "true"
        lines = dirty_stat.strip().splitlines()
        info["dirty_summary"] = lines[-1] if lines else "uncommitted changes"

    return info


def _sync_file(src: Path, dst: Path) -> None:
    """Copy a single file, creating parent dirs as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _sync_dir(src: Path, dst: Path) -> None:
    """Copy src directory to dst, clearing dst first."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _clean_agent_dir(agent_dir: Path) -> None:
    """Remove synced files from the agent directory, preserving benchmark-owned files."""
    # Remove previously synced files
    for name in _SYNC_AGENT_FILES:
        p = agent_dir / name
        if p.exists():
            p.unlink()
    for name in _SYNC_AGENT_DIRS:
        p = agent_dir / name
        if p.is_dir():
            shutil.rmtree(p)
    # Remove .sync_meta.json if it exists
    meta = agent_dir / _META_FILENAME
    if meta.exists():
        meta.unlink()


def sync_agent_code(projectflow_root: str = "") -> dict[str, str]:
    """Sync agent code from ProjectFlow into the benchmark repo.

    Only syncs the files that contain agent logic (modules, output schemas,
    prompts). Does NOT sync coordinator.py or workflow.py — the benchmark
    keeps its own lightweight versions without database dependencies.

    Returns the sync metadata dict.
    """
    root = _find_projectflow_root(projectflow_root)
    app_dir = _resolve_app_dir(root)

    benchmark_root = Path(__file__).resolve().parents[3]
    benchmark_agent = benchmark_root / "app" / "agent"

    src_agent = app_dir / "agent"
    if not src_agent.is_dir():
        raise CommandError(f"Agent directory not found: {src_agent}")

    # Clean previously synced files
    _clean_agent_dir(benchmark_agent)

    # Sync individual agent files
    missing = []
    for name in _SYNC_AGENT_FILES:
        src = src_agent / name
        if src.is_file():
            _sync_file(src, benchmark_agent / name)
        else:
            missing.append(name)

    # Sync agent subdirectories
    for name in _SYNC_AGENT_DIRS:
        src = src_agent / name
        if src.is_dir():
            _sync_dir(src, benchmark_agent / name)
        else:
            missing.append(name)

    if missing:
        raise CommandError(f"Missing expected files in ProjectFlow: {', '.join(missing)}")

    # Gather git info
    git = _git_info(root)

    meta = {
        "commit": git["commit"],
        "message": git["message"],
        "dirty": git["dirty"],
        "dirty_summary": git["dirty_summary"],
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(root),
    }
    meta_path = benchmark_agent / _META_FILENAME
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    return meta


def print_sync_result(meta: dict[str, str]) -> None:
    """Print a human-readable sync summary."""
    commit_short = meta["commit"][:12] if meta["commit"] else "unknown"
    dirty_flag = " (dirty)" if meta.get("dirty") == "true" else ""
    print(f"Synced from: {meta.get('source_path', '?')}")
    print(f"Commit:      {commit_short}{dirty_flag}")
    if meta.get("message"):
        print(f"Message:     {meta['message']}")
    if meta.get("dirty") == "true" and meta.get("dirty_summary"):
        print(f"Changes:     {meta['dirty_summary']}")
    print(f"Synced at:   {meta.get('synced_at', '?')}")
