# ProjectFlow AgentEval -- Mock Benchmark Run

## Task
Confirm the local benchmark harness still works: `pfae run mock`

## Commands Run

### 1. Check CLI available
```
.venv/bin/pfae --help
```
Result: CLI loaded correctly, subcommands available: case, run, report, diagnose, compare, sync, config.

### 2. Run mock benchmark
```
.venv/bin/pfae run mock
```
Result:
```
Run ID: 20260607T211552-stub-1e7de5
Model: stub
Cases: 49/49 passed
Average score: 0.846
Hard failures: 0
Duration: 0.0s
Reports: output/agent-eval/20260607T211552-stub-1e7de5
```

### 3. Show report details
```
.venv/bin/pfae report latest
```
Result:
```
Run ID: 20260607T211552-stub-1e7de5
Model: stub
Cases: 49/49 passed
Average score: 0.846
Hard failures: 0
Top failure categories: context_missing, weak_actionability, risk_type_mismatch, date_time_error, capacity_ignored
Report directory: output/agent-eval/20260607T211552-stub-1e7de5
```

### 4. Diagnose for failures
```
.venv/bin/pfae diagnose latest
```
Result: `No failed cases in output/agent-eval/20260607T211552-stub-1e7de5`

### 5. List available cases
```
.venv/bin/pfae case list
```
Result: 49 fixture cases available.

## Summary

Benchmark harness is fully functional:
- 49/49 cases passed (mock/stub mode)
- Average score: 0.846
- Hard failures: 0
- Duration: ~0s (stub mode is fast)
- No diagnostic issues found

The "top failure categories" listed (context_missing, weak_actionability, etc.) are soft/judge-level categories that appear in the mock run's scoring but are not actual hard failures -- they represent the stub model's expected limitations.
