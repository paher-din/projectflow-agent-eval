# Benchmark Run History

| Run ID | Mode | Cases | Score | HF | Time | PF Commit | Top Failures |
|--------|------|-------|-------|----|------|-----------|-------------|
| 20260607T183648-stub-acb396 | mock | 49/49 | 0.846 | 0 | 0s | - | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T185611-real-c11b34 | real | 18/49 | 0.351 | 77 | 364s | - | schema_failure, weak_actionability, scope_creep |
| 20260607T194156-stub-704a55 | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T194202-real-d14d4a | real | 0/49 | 0.000 | 156 | 0s | 052395a00fb0 | schema_failure, scope_creep, weak_actionability |
| 20260607T194757-real-aea7f6 | real | 17/49 | 0.333 | 79 | 337s | 052395a00fb0 | schema_failure, scope_creep, weak_actionability |
| 20260607T195559-real-4f1064 | real | 17/49 | 0.333 | 79 | 7s | 052395a00fb0 | schema_failure, scope_creep, weak_actionability |
| 20260607T200809-stub-9066cb | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T200816-real-6fc2da | real | 42/49 | 0.818 | 10 | 304s | 052395a00fb0 | date_time_error, weak_actionability, context_missing |
| 20260607T211552-stub-1e7de5 | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T211607-stub-eab5a5 | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T211921-real-e6edeb | real | 1/1 | 1.000 | 0 | 30s | 052395a00fb0 | - |
| 20260607T211947-stub-1483b0 | mock | 1/1 | 0.850 | 0 | 0s | 052395a00fb0 | - |
| 20260607T212453-real-f193c2 | real | 1/1 | 1.000 | 0 | 0s | 052395a00fb0 | - |
| 20260607T213241-stub-a027fc | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T220043-stub-1b57bf | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T220814-real-cb0be9 | real | 2/7 | 0.271 | 7 | 190s | 052395a00fb0 | dependency_inconsistency, no_op_replan, date_time_error |
| 20260607T222715-real-ebbf41 | real | 4/7 | 0.557 | 3 | 182s | 052395a00fb0 | dependency_inconsistency, date_time_error, no_op_replan |
| 20260607T223400-real-b24adc | real | 0/3 | 0.000 | 3 | 0s | 052395a00fb0 | dependency_inconsistency, no_op_replan |
| 20260607T223420-real-a0fcbc | real | 1/3 | 0.333 | 2 | 108s | 052395a00fb0 | dependency_inconsistency, no_op_replan |
| 20260607T223758-real-48b829 | real | 1/3 | 0.333 | 16 | 128s | 052395a00fb0 | dependency_inconsistency, schema_failure, weak_actionability |
| 20260607T224103-real-6c7a91 | real | 1/2 | 0.500 | 2 | 92s | 052395a00fb0 | dependency_inconsistency, hallucinated_entity |
| 20260607T224308-real-204035 | real | 0/1 | 0.000 | 2 | 87s | 052395a00fb0 | dependency_inconsistency, hallucinated_entity |
| 20260607T230111-real-4847a6 | real | 0/1 | 0.000 | 1 | 63s | 052395a00fb0 | hallucinated_entity |
| 20260607T230525-stub-8e6ba3 | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T230530-real-0c51cd | real | 5/7 | 0.700 | 2 | 200s | 052395a00fb0 | no_op_replan, date_time_error |
| 20260607T231104-real-195f60 | real | 1/2 | 0.500 | 1 | 110s | 052395a00fb0 | no_op_replan |
| 20260607T231340-real-e06c33 | real | 1/1 | 1.000 | 0 | 86s | 052395a00fb0 | - |
| 20260607T231512-real-04f51d | real | 47/49 | 0.914 | 4 | 574s | 052395a00fb0 | date_time_error, context_missing, weak_actionability |
| 20260607T232836-stub-f4d303 | mock | 49/49 | 0.846 | 0 | 0s | 052395a00fb0 | context_missing, weak_actionability, risk_type_mismatch |
| 20260607T233453-real-a2bb2b | real | 2/2 | 0.950 | 0 | 109s | 58ad2304c2eb | date_time_error |
| 20260607T233647-real-a4f43e | real | 46/49 | 0.900 | 4 | 567s | 58ad2304c2eb | date_time_error, context_missing, weak_actionability |
| 20260607T234631-real-fd51b2 | real | 45/49 | 0.880 | 5 | 517s | 58ad2304c2eb | date_time_error, context_missing, weak_actionability |
| 20260608T000550-real-cf720f | real | 4/4 | 0.925 | 0 | 48s | 193d9a70aed6 | date_time_error, state_blindness |
| 20260608T000642-real-1e7658 | real | 3/4 | 0.700 | 1 | 87s | 193d9a70aed6 | date_time_error, hallucinated_entity, state_blindness |
| 20260608T001032-real-695f62 | real | 4/4 | 0.925 | 0 | 41s | 193d9a70aed6 | date_time_error, state_blindness |
| 20260608T001123-real-f36992 | real | 4/4 | 0.925 | 0 | 47s | 193d9a70aed6 | date_time_error, state_blindness |
| 20260608T001852-stub-ed8bf0 | mock | 49/49 | 0.846 | 0 | 0s | 51afb9831ef4 | context_missing, weak_actionability, risk_type_mismatch |
