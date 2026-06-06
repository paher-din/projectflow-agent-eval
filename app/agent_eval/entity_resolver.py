# -*- coding: utf-8 -*-
"""Deterministic workspace entity resolver for AgentEval.

Resolves entity IDs (task-N, user-N, stage-N, prop-N) against the workspace
state dictionary and returns structured resolution results.  The LLM judge
must never decide whether an ID exists — this module owns that decision.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EntityResolution(BaseModel):
    """Structured result of resolving a single entity ID against workspace state."""

    exists: bool = False
    entity_type: str = ""
    entity_id: str = ""
    state_path: str = ""
    display: str | None = Field(default=None, description="Display name for members, name for projects/stages")
    title: str | None = Field(default=None, description="Title for tasks, name for resources")


_ID_PREFIX_RE = r"\b(?:user|task|stage|prop|resource)-\S+"


def _get_entity_type(entity_id: str) -> str:
    """Extract entity type from a structured ID like 'task-3' -> 'task'."""
    if "-" in entity_id:
        return entity_id.split("-")[0]
    return "unknown"


def build_workspace_entity_index(workspace_state: dict[str, Any]) -> dict[str, EntityResolution]:
    """Scan workspace state and build a flat index of known entity IDs.

    Covers all paths specified by the benchmark contract:
    - workspace_state.tasks[*].id
    - workspace_state.project.tasks[*].id
    - workspace_state.project.task_list[*].id  (if present)
    - workspace_state.members[*].user_id and display_name
    - workspace_state.workspace.members[*].user_id and display_name
    - workspace_state.stages[*].id
    - workspace_state.project.stages[*].id
    - workspace_state.proposals[*].id
    - workspace_state.project.assignment_proposals[*].id
    - workspace_state.resources[*].id and workspace_state.project.resources[*].id
    """
    index: dict[str, EntityResolution] = {}

    # ------------------------------------------------------------------
    # Top-level containers
    # ------------------------------------------------------------------
    for i, member in enumerate(workspace_state.get("members", [])):
        if not isinstance(member, dict):
            continue
        uid = member.get("user_id", "")
        if uid:
            index[uid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(uid) or "user",
                entity_id=uid,
                state_path=f"workspace_state.members[{i}].user_id",
                display=member.get("display_name", ""),
            )
        name = member.get("display_name", "")
        if name:
            index[name] = EntityResolution(
                exists=True,
                entity_type="member",
                entity_id=name,
                state_path=f"workspace_state.members[{i}].display_name",
                display=name,
            )

    for i, task in enumerate(workspace_state.get("tasks", [])):
        if not isinstance(task, dict):
            continue
        tid = task.get("id", "")
        if tid and tid not in index:
            index[tid] = EntityResolution(
                exists=True,
                entity_type="task",
                entity_id=tid,
                state_path=f"workspace_state.tasks[{i}].id",
                title=task.get("title", ""),
            )

    for i, stage in enumerate(workspace_state.get("stages", [])):
        if not isinstance(stage, dict):
            continue
        sid = stage.get("id", "")
        if sid and sid not in index:
            index[sid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(sid) or "stage",
                entity_id=sid,
                state_path=f"workspace_state.stages[{i}].id",
                title=stage.get("name", ""),
            )

    for i, prop in enumerate(workspace_state.get("proposals", [])):
        if not isinstance(prop, dict):
            continue
        pid = prop.get("id", "")
        if pid and pid not in index:
            index[pid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(pid) or "proposal",
                entity_id=pid,
                state_path=f"workspace_state.proposals[{i}].id",
            )

    for i, res in enumerate(workspace_state.get("resources", [])):
        if not isinstance(res, dict):
            continue
        rid = res.get("id", "")
        if rid and rid not in index:
            index[rid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(rid) or "resource",
                entity_id=rid,
                state_path=f"workspace_state.resources[{i}].id",
                title=res.get("name", ""),
            )

    # ------------------------------------------------------------------
    # workspace-level containers
    # ------------------------------------------------------------------
    ws = workspace_state.get("workspace", {})
    if isinstance(ws, dict):
        for i, member in enumerate(ws.get("members", [])):
            if not isinstance(member, dict):
                continue
            uid = member.get("user_id", "")
            if uid and uid not in index:
                index[uid] = EntityResolution(
                    exists=True,
                    entity_type=_get_entity_type(uid) or "user",
                    entity_id=uid,
                    state_path=f"workspace_state.workspace.members[{i}].user_id",
                    display=member.get("display_name", ""),
                )
            name = member.get("display_name", "")
            if name and name not in index:
                index[name] = EntityResolution(
                    exists=True,
                    entity_type="member",
                    entity_id=name,
                    state_path=f"workspace_state.workspace.members[{i}].display_name",
                    display=name,
                )

    # ------------------------------------------------------------------
    # Project-level containers
    # ------------------------------------------------------------------
    project = workspace_state.get("project", {})
    if not isinstance(project, dict):
        return index

    pid = project.get("id", "")
    if pid:
        index[pid] = EntityResolution(
            exists=True,
            entity_type=_get_entity_type(pid) or "project",
            entity_id=pid,
            state_path="workspace_state.project.id",
            title=project.get("name", ""),
        )

    for i, task in enumerate(project.get("tasks", [])):
        if not isinstance(task, dict):
            continue
        tid = task.get("id", "")
        if tid and tid not in index:
            index[tid] = EntityResolution(
                exists=True,
                entity_type="task",
                entity_id=tid,
                state_path=f"workspace_state.project.tasks[{i}].id",
                title=task.get("title", ""),
            )

    for i, task in enumerate(project.get("task_list", [])):
        if not isinstance(task, dict):
            continue
        tid = task.get("id", "")
        if tid and tid not in index:
            index[tid] = EntityResolution(
                exists=True,
                entity_type="task",
                entity_id=tid,
                state_path=f"workspace_state.project.task_list[{i}].id",
                title=task.get("title", ""),
            )

    for i, stage in enumerate(project.get("stages", [])):
        if not isinstance(stage, dict):
            continue
        sid = stage.get("id", "")
        if sid and sid not in index:
            index[sid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(sid) or "stage",
                entity_id=sid,
                state_path=f"workspace_state.project.stages[{i}].id",
                title=stage.get("name", ""),
            )

    for i, prop in enumerate(project.get("assignment_proposals", [])):
        if not isinstance(prop, dict):
            continue
        pid2 = prop.get("id", "")
        if pid2 and pid2 not in index:
            index[pid2] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(pid2) or "proposal",
                entity_id=pid2,
                state_path=f"workspace_state.project.assignment_proposals[{i}].id",
            )

    for i, res in enumerate(project.get("resources", [])):
        if not isinstance(res, dict):
            continue
        rid = res.get("id", "")
        if rid and rid not in index:
            index[rid] = EntityResolution(
                exists=True,
                entity_type=_get_entity_type(rid) or "resource",
                entity_id=rid,
                state_path=f"workspace_state.project.resources[{i}].id",
                title=res.get("name", ""),
            )

    return index


def resolve_workspace_entity(
    entity_id: str,
    index: dict[str, EntityResolution],
) -> EntityResolution:
    """Resolve a single entity ID against a pre-built index.

    Parameters
    ----------
    entity_id
        The ID string to look up (e.g. ``"task-3"``, ``"user-1"``).
    index
        Index returned by :func:`build_workspace_entity_index`.

    Returns
    -------
    EntityResolution
        Resolution result with ``exists``, ``entity_type``, ``state_path``,
        and display/title fields.
    """
    if entity_id in index:
        return index[entity_id]
    entity_type = _get_entity_type(entity_id)
    return EntityResolution(
        exists=False,
        entity_type=entity_type,
        entity_id=entity_id,
        state_path="",
    )
