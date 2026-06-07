# ProjectFlow AgentEval - Mock Mode Run

## Command Executed

```bash
/Users/robertwu/Documents/Projects/projectflow-agent-eval/.venv/bin/pfae run --mode mock
```

## Results Summary

```
============================================================
  Run ID:      20260607T211607-stub-eab5a5
  Model:       stub
  Workers:     4
  Judge Mode:  auto
  Semantic:    auto
  Cache:       0 hit / 0 miss
  Skipped:     0
  Cases:       49/49 passed
  Avg Score:   0.846
  Hard Fails:  0
  Duration:    0.0s
============================================================
```

## Per-Case Results

| Case ID | Score | Status | WS |
|---------|-------|--------|----|
| active_push_all_completed | 0.85 | passed | 1.00 |
| active_push_blocked_member | 0.85 | passed | 1.00 |
| active_push_idle_project | 0.85 | passed | 0.90 |
| active_push_immutable_done | 0.85 | passed | 1.00 |
| active_push_past_deadline | 0.85 | passed | 0.80 |
| assignment_after_previous_accepts | 0.85 | passed | 1.00 |
| assignment_immutable_accepted | 0.85 | passed | 1.00 |
| assignment_member_fit | 0.85 | passed | 1.00 |
| assignment_missing_capacity | 0.85 | passed | 1.00 |
| assignment_single_member | 0.85 | passed | 0.90 |
| assignment_skill_gap | 0.85 | passed | 0.90 |
| breakdown_dependency_gap | 0.85 | passed | 1.00 |
| breakdown_existing_tasks | 0.85 | passed | 1.00 |
| breakdown_large_scope | 0.85 | passed | 1.00 |
| breakdown_no_members_available | 0.85 | passed | 0.90 |
| breakdown_with_existing_tasks | 0.85 | passed | 1.00 |
| checkin_blocker_escalation | 0.85 | passed | 0.80 |
| checkin_empty_cycle | 0.85 | passed | 0.90 |
| checkin_normal_progress | 0.85 | passed | 0.80 |
| clarify_ambiguous_goal | 0.85 | passed | 1.00 |
| clarify_existing_direction | 0.85 | passed | 1.00 |
| clarify_immutable_direction | 0.85 | passed | 1.00 |
| clarify_overconstrained | 0.85 | passed | 0.90 |
| clarify_sparse_project | 0.85 | passed | 1.00 |
| clarify_with_resources | 0.85 | passed | 1.00 |
| fallback_bad_json | 0.85 | passed | 1.00 |
| negotiate_after_rejections | 0.85 | passed | 1.00 |
| negotiate_all_accepted | 0.85 | passed | 1.00 |
| negotiate_immutable_reopen | 0.85 | passed | 1.00 |
| negotiate_multi_member_conflict | 0.85 | passed | 0.90 |
| negotiate_timeline_only | 0.85 | passed | 1.00 |
| plan_no_direction_card | 0.85 | passed | 0.90 |
| plan_overlapping_stages | 0.85 | passed | 1.00 |
| plan_scope_control | 0.85 | passed | 1.00 |
| plan_with_current_date | 0.85 | passed | 1.00 |
| plan_with_existing_stages | 0.85 | passed | 1.00 |
| planning_immutable_done_stages | 0.85 | passed | 1.00 |
| reliability_invalid_date_format | 0.85 | passed | 1.00 |
| reliability_missing_required_field | 0.85 | passed | 1.00 |
| replan_after_prior_cuts | 0.85 | passed | 1.00 |
| replan_before_after | 0.85 | passed | 1.00 |
| replan_immutable_done_stage | 0.85 | passed | 1.00 |
| replan_member_left | 0.85 | passed | 0.90 |
| replan_no_changes | 0.85 | passed | 0.90 |
| replan_scope_increased | 0.85 | passed | 0.90 |
| risk_after_multiple_cycles | 0.85 | passed | 1.00 |
| risk_checkin_blocker | 0.85 | passed | 1.00 |
| risk_multi_dimension | 0.85 | passed | 0.80 |
| risk_simple_project | 0.85 | passed | 1.00 |

## Reports Location

`output/agent-eval/20260607T211607-stub-eab5a5/`

## Conclusion

本地 benchmark harness 正常工作。49 个 fixture 全部通过，0 个 hard fail，平均分 0.846。Mock 模式下所有 case 一致性得分 0.85，WS (weighted score) 范围 0.80-1.00，符合预期。
