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

## Configure Real Models

```powershell
pfae config path
pfae config init
pfae config show
```

Agent and judge models are managed as separate registries:

```powershell
pfae config agent add <name>
pfae config agent use <name>
pfae config agent list
pfae config agent show <name>

pfae config judge add <name>
pfae config judge use <name>
pfae config judge list
pfae config judge show <name>
```

Do not use `config judge ...` commands to manage Agent models or `config agent ...` commands to manage Judge models.

`pfae run real` starts setup automatically when no environment or user config exists.

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
