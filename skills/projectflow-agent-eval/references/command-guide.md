# ProjectFlow AgentEval Command Guide

## Inspect Cases

```powershell
pfae case list
pfae case show <case_id>
```

## Run Benchmark

```powershell
pfae run mock
pfae run real --model deepseek-v4-pro
pfae run resume latest
pfae run retry-failed latest
pfae run retry-errors latest
```

Use `mock` when credentials are unavailable or the user only wants a local sanity check.

## Read Reports

```powershell
pfae report latest
pfae report show <run_dir>
pfae diagnose latest
```

Run `diagnose` before recommending code or prompt changes.

## Compare Runs

```powershell
pfae compare <baseline_run_dir> <candidate_run_dir>
```

A non-zero exit code means the candidate failed the regression gate.
