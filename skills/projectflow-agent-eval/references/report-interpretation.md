# Report Interpretation

Prioritize failures in this order:

1. Deterministic hard failures.
2. Failed hard assertions.
3. Semantic guard hard failures with evidence.
4. Repeated failure categories across cases.
5. Low semantic judge scores.

Do not mark a run healthy because the average score is high if any hard failure exists.

When summarizing failures, include:

- case ID
- module
- hard failures
- failed assertions
- failure categories
- report directory
- the smallest likely repair target

Do not quote secrets or dump full raw model outputs unless the user explicitly asks and the content has been checked for sensitive values.
