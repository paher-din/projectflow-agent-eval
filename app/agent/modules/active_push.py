from app.agent.modules.common import AgentModuleRequest, first_member_id, first_stage_id, first_task_id
from app.models.enums import AgentEventType
from app.schemas.workspace_state import WorkspaceStateResponse


def build_request(workspace_state: WorkspaceStateResponse) -> AgentModuleRequest:
    fallback_task_title = "下一步任务"
    if workspace_state.project and workspace_state.project.tasks:
        for t in workspace_state.project.tasks:
            if t.status != "done":
                fallback_task_title = t.title
                break

    member_id = first_member_id(workspace_state)
    stage_id = first_stage_id(workspace_state)
    task_id = first_task_id(workspace_state)

    if member_id is None or stage_id is None or task_id is None:
        return AgentModuleRequest(
            event_type=AgentEventType.push,
            user_prompt=(
                "Create exactly 1 action card for the most important next step. "
                "Prefer blocked, overdue, unassigned, or high-priority tasks. "
                "Each card needs goal, start_suggestion, completion_standard, and a reason citing task status, deadline, or member capacity."
            ),
            fallback_payload={
                "action_cards": [],
                "reason": "当前没有可用的成员、阶段或任务，无法生成主动推进建议。",
            },
        )

    return AgentModuleRequest(
        event_type=AgentEventType.push,
        user_prompt=(
            "Create exactly 1 action card for the most important next step. "
            "Scan the active stage: if all tasks in it are done, suggest advancing to the next stage. "
            "If tasks are overdue or blocked, suggest unblocking actions. "
            "If no tasks exist for the active stage, suggest running task breakdown. "
            "Prefer blocked, overdue, unassigned, or high-priority tasks. "
            "Each card needs goal, start_suggestion, completion_standard, and a reason citing task status, deadline, or member capacity. "
            "ALL text fields (title, content, reason, goal, start_suggestion, completion_standard) MUST be written in Chinese. "
            "In text fields, use member display names (e.g. '小林') and task titles (e.g. '后端 API') — never use raw IDs."
        ),
        fallback_payload={
            "action_cards": [
                {
                    "type": "team_next_step",
                    "title": f"确认下一步：{fallback_task_title}",
                    "content": "为当前阶段选择最小可执行的下一个步骤。",
                    "reason": f"回退方案：建议优先推进「{fallback_task_title}」。",
                    "goal": f"推进「{fallback_task_title}」至进行中",
                    "start_suggestion": f"开始处理「{fallback_task_title}」",
                    "completion_standard": f"「{fallback_task_title}」状态更新为进行中或已完成",
                    "stage_id": stage_id,
                    "task_id": task_id,
                }
            ],
            "reason": "主动推进回退方案：聚焦一个核心行动，等待人工确认。",
        },
    )
