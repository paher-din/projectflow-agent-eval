from datetime import timedelta
from typing import Any

from app.agent.modules.common import AgentModuleRequest
from app.models.enums import AgentEventType
from app.schemas.workspace_state import CheckInResponseState, TaskState, WorkspaceStateResponse


def build_request(workspace_state: WorkspaceStateResponse) -> AgentModuleRequest:
    fallback_payload = _build_replan_fallback_payload(workspace_state)
    return AgentModuleRequest(
        event_type=AgentEventType.replan,
        user_prompt=(
            "Propose the smallest useful current-stage replan only if WorkspaceState shows blockers, overdue work, unassigned critical tasks, or workload mismatch. "
            "Use concise before/after/impact, cite specific task titles and member names (not IDs) as evidence, and keep requires_confirmation true. "
            "ALL user-facing text (impact, reason, stage_adjustments[*].reason, task_changes[*].reason) MUST be written in Chinese. "
            "Do not change finalized owners unless evidence clearly requires human-confirmed review."
        ),
        fallback_payload=fallback_payload,
    )


def _build_replan_fallback_payload(workspace_state: WorkspaceStateResponse) -> dict[str, Any]:
    if not workspace_state.project:
        return _unchanged_fallback_payload()

    blocker, task = _first_blocked_checkin_task(workspace_state)
    if blocker is None or task is None:
        return _unchanged_fallback_payload()

    stage = next(
        (stage for stage in workspace_state.project.stages if stage.id == task.stage_id),
        None,
    )
    member = next(
        (member for member in workspace_state.members if member.user_id == blocker.user_id),
        None,
    )
    member_name = member.display_name if member else "相关成员"
    blocker_text = blocker.blocker or "未说明具体阻塞"
    task_due_date = task.due_date + timedelta(days=1) if task.due_date else None

    task_change: dict[str, Any] = {
        "task_id": task.id,
        "title": task.title,
        "status": "blocked",
        "reason": (
            f"{member_name} 在 check-in 中反馈「{blocker_text}」，"
            f"需要先把「{task.title}」标记为受阻并集中处理。"
        ),
    }
    if task_due_date:
        task_change["due_date"] = task_due_date.isoformat()

    action_card = _without_none(
        {
            "type": "risk_action",
            "title": f"处理阻塞：{task.title}",
            "content": f"确认阻塞来源并给出解除路径：{blocker_text}",
            "reason": f"{member_name} 已在 check-in 中报告该任务受阻，需要团队主动推进。",
            "goal": "明确阻塞处理人、下一步动作和恢复时间。",
            "start_suggestion": "先在团队内确认阻塞是否需要范围调整、资源支持或任务拆分。",
            "completion_standard": "阻塞解除，任务可以恢复推进，或形成新的人工确认调整方案。",
            "user_id": task.owner_user_id or blocker.user_id,
            "task_id": task.id,
            "stage_id": task.stage_id or None,
            "due_date": task_due_date.isoformat() if task_due_date else None,
        }
    )

    return {
        "before": {
            "task": task.title,
            "status": task.status,
            "due_date": task.due_date.isoformat() if task.due_date else "未设置",
            "blocker": blocker_text,
        },
        "after": {
            "summary": "先处理当前阻塞，不自动更换负责人；确认后同步任务状态并生成行动卡。",
            "task_status": "blocked",
            "due_date": task_due_date.isoformat() if task_due_date else "保持不变",
        },
        "impact": "仅调整 1 个受阻任务并新增 1 张阻塞处理行动卡；不自动变更负责人，等待人工确认后才落库。",
        "stage_adjustments": _stage_adjustments_for_blocker(stage),
        "task_changes": [task_change],
        "action_cards": [action_card],
        "requires_confirmation": True,
        "reason": f"检测到「{task.title}」存在 check-in 阻塞，回退方案给出最小可确认重规划。",
    }


def _unchanged_fallback_payload() -> dict[str, Any]:
    return {
            "before": {"summary": "当前计划保持不变。"},
            "after": {"summary": "不自动应用重规划调整。"},
            "impact": "不做任何进度、负责人或范围的自动变更，等待人工确认。",
            "stage_adjustments": [],
            "task_changes": [],
            "action_cards": [],
            "requires_confirmation": True,
            "reason": "回退方案：没有足够证据支持自动调整计划，保持当前规划不变。",
    }


def _first_blocked_checkin_task(
    workspace_state: WorkspaceStateResponse,
) -> tuple[CheckInResponseState | None, TaskState | None]:
    if not workspace_state.project:
        return None, None
    task_map = {task.id: task for task in workspace_state.project.tasks}
    current_stage_id = workspace_state.project.current_stage_id
    responses = [
        response
        for response in workspace_state.project.checkin_responses
        if response.blocker and response.task_id and response.task_id in task_map
    ]
    current_stage_response = next(
        (
            response
            for response in responses
            if current_stage_id and task_map[response.task_id].stage_id == current_stage_id
        ),
        None,
    )
    response = current_stage_response or (responses[0] if responses else None)
    if response is None or response.task_id is None:
        return None, None
    return response, task_map[response.task_id]


def _stage_adjustments_for_blocker(stage: Any | None) -> list[dict[str, Any]]:
    if stage is None or not stage.end_date:
        return []
    return [
        {
            "stage_id": stage.id,
            "new_end_date": (stage.end_date + timedelta(days=1)).isoformat(),
            "reason": f"阶段「{stage.name}」出现阻塞，建议预留 1 天缓冲等待人工确认。",
        }
    ]


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
