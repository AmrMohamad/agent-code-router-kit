# Android LSP vs Default Search Benchmark - 2026-05-24

Generated benchmark report for Android/Kotlin routing over the configured Android repos.

Raw outputs are intentionally kept under ignored `results/` and should not be published without sanitizing.

## Scope

- Default search benchmark: manifest-driven `fd` / `rg` / `ast-grep` cases.
- Android Studio semantic probe: manifest-driven `android studio` readiness and symbol probes.
- Serena source-symbol probe: manifest-driven `serena project index-file` checks on real `.kt` files.
- Serena ProjectServer probe: manifest-driven `find_symbol`, `find_referencing_symbols`, `get_symbols_overview`, and `get_diagnostics_for_file` semantic checks.
- Serena/Android process-state probe: live MCP/LSP/JDTLS process counts for LSP stability.
- Android project-model probe: Gradle/local-config preflight before trusting semantic lookup.
- No emulator, device, app install, UI, or runtime behavior proof is claimed.

## Source Artifacts

| Layer | Summary | Assertions |
| --- | --- | --- |
| Default search | `/path/to/user/Developer/agent-code-router-kit/results/android/default-search/summary-2026-05-24-073711.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/default-search/policy-assertions-2026-05-24-073711.json` |
| Android Studio semantic | `/path/to/user/Developer/agent-code-router-kit/results/android/android-studio-semantic/android-studio-semantic-summary-2026-05-24-073718.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/android-studio-semantic/android-studio-semantic-assertions-2026-05-24-073718.json` |
| Serena source-symbol | `/path/to/user/Developer/agent-code-router-kit/results/android/serena-source-symbol/serena-source-symbol-summary-2026-05-24-073804.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/serena-source-symbol/serena-source-symbol-assertions-2026-05-24-073804.json` |
| Serena ProjectServer | `/path/to/user/Developer/agent-code-router-kit/results/android/serena-project-server/serena-project-server-summary-2026-05-24-073829.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/serena-project-server/serena-project-server-assertions-2026-05-24-073829.json` |
| Process state | `/path/to/user/Developer/agent-code-router-kit/results/android/process-state/android-process-state-summary-2026-05-24-073905.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/process-state/android-process-state-assertions-2026-05-24-073905.json` |
| Project model | `/path/to/user/Developer/agent-code-router-kit/results/android/project-model/android-project-model-summary-2026-05-24-073905.json` | `/path/to/user/Developer/agent-code-router-kit/results/android/project-model/android-project-model-assertions-2026-05-24-073905.json` |

## Assertion Summary

| Layer | Pass | Warn | Fail |
| --- | --- | --- | --- |
| Default search | 495 | 48 | 0 |
| Android Studio semantic | 51 | 39 | 0 |
| Serena source-symbol | 3 | 0 | 0 |
| Serena ProjectServer | 105 | 0 | 0 |
| Process state | 4 | 0 | 0 |
| Project model | 2 | 2 | 0 |

## Warning / Blocker Breakdown

Warnings are not benchmark failures. They mark capability boundaries or intentionally large baseline outputs that should not be used as live-agent context dumps.

| Layer | Warning | Count | Message | Repos | Cases |
| --- | --- | --- | --- | --- | --- |
| Default search | high_fanout_raw_or_json_is_benchmark_only | 18 | live agent work should request grouped semantic counts first | `sample_b2b_android`, `sample_retail_android` | `high_fanout_usecase_json`, `high_fanout_usecase_raw`, `high_fanout_viewmodel_raw` |
| Default search | large_output_requires_summary_first | 3 | bytes=122930 | `sample_b2b_android` | `inventory_kotlin_files` |
| Default search | large_output_requires_summary_first | 3 | bytes=152416 | `sample_retail_android` | `structural_koin_module` |
| Default search | large_output_requires_summary_first | 3 | bytes=185071 | `sample_retail_android` | `structural_flow_collect` |
| Default search | large_output_requires_summary_first | 3 | bytes=197203 | `sample_retail_android` | `inventory_kotlin_files` |
| Default search | large_output_requires_summary_first | 3 | bytes=205412 | `sample_retail_android` | `structural_composable` |
| Default search | large_output_requires_summary_first | 3 | bytes=209502 | `sample_b2b_android` | `high_fanout_usecase_raw` |
| Default search | large_output_requires_summary_first | 3 | bytes=467335 | `sample_retail_android` | `high_fanout_usecase_raw` |
| Default search | large_output_requires_summary_first | 3 | bytes=490240 | `sample_b2b_android` | `structural_function_shape` |
| Default search | large_output_requires_summary_first | 1 | bytes=1127500 | `sample_retail_android` | `high_fanout_usecase_json` |
| Default search | large_output_requires_summary_first | 1 | bytes=1127530 | `sample_retail_android` | `high_fanout_usecase_json` |
| Default search | large_output_requires_summary_first | 1 | bytes=1127545 | `sample_retail_android` | `high_fanout_usecase_json` |
| Default search | large_output_requires_summary_first | 1 | bytes=599986 | `sample_b2b_android` | `high_fanout_usecase_json` |
| Default search | large_output_requires_summary_first | 1 | bytes=599988 | `sample_b2b_android` | `high_fanout_usecase_json` |
| Default search | large_output_requires_summary_first | 1 | bytes=599999 | `sample_b2b_android` | `high_fanout_usecase_json` |
| Android Studio semantic | semantic_probe_not_ready | 39 | actual=no-result | `sample_b2b_android`, `sample_retail_android` | `studio_declaration_app_update_manager`, `studio_declaration_base_viewmodel`, `studio_declaration_base_viewmodel_fqn`, `studio_declaration_main_activity`, +9 more |
| Project model | project_model_not_ready | 1 | status=missing-local-properties; missing=sample_analytics_id | `sample_b2b_android` | `project_model_sample_b2b` |
| Project model | project_model_not_ready | 1 | status=missing-local-properties; missing=production.sample.map.api.key,staging.sample.map.api.key | `sample_retail_android` | `project_model_sample_retail` |

## Android Semantic Capability Matrix

| Layer | Current proof | Boundary |
| --- | --- | --- |
| Default `fd` / `rg` / `ast-grep` | 495 assertion passes with expected high-output warnings | Discovery and structural evidence only; not symbol identity proof. |
| Android Studio Preview / Quail CLI | 4 readiness/file-analysis passes; 13 declaration/usages probes still no-result | Use for readiness and diagnostics until declaration/usages smoke tests pass. |
| Serena source-symbol | 3 real `.kt` source-symbol passes | Proves Kotlin symbol extraction, not full runtime/project-model correctness. |
| Serena ProjectServer | 19 functional semantic cases across 57 measured passes; 2 expected implementation-boundary cases | Best current Android semantic proof layer outside the broken Codex MCP transport; implementation lookup is an explicit unsupported boundary. |
| Serena/Android process state | 4 clean-process assertions passed | Keeps stale LSP/JDTLS sessions from being mistaken for semantic failures. |
| Gradle / Android runtime | Preflight only; missing local keys: `sample_analytics_id`, `production.sample.map.api.key`, `staging.sample.map.api.key` | No build, install, emulator, device, or runtime proof is claimed. |

## Direct Search vs LSP Comparison

These rows compare the normal-search baseline with the closest semantic Serena ProjectServer probe for the same Android symbol family.

| Symbol family | Search case | Search tokens | Search seconds | LSP case | LSP tokens | LSP seconds | Interpretation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sample B2B SampleFeatureViewModel | `known_symbol_notifications_viewmodel_files` | 57 | 0.0181 | `serena_project_find_sample_b2b_notifications_viewmodel` | 545 | 0.1092 | Text search is tiny, but LSP returns owning class structure and child symbol ranges. |
| Sample B2B SampleFeatureViewModel references | `known_symbol_notifications_viewmodel_files` | 57 | 0.0181 | `serena_project_refs_sample_b2b_notifications_viewmodel` | 260 | 0.5149 | LSP proves semantic references instead of only matching the ViewModel name text. |
| Sample B2B SampleContentViewModel | `known_symbol_dynamic_content_viewmodel_files` | 55 | 0.0163 | `serena_project_find_sample_b2b_dynamic_content_viewmodel` | 256 | 0.1096 | Both are small; LSP adds symbol kind, owning file, and body range. |
| Sample B2B SampleContentViewModel references | `known_symbol_dynamic_content_viewmodel_files` | 55 | 0.0163 | `serena_project_refs_sample_b2b_dynamic_content_viewmodel` | 241 | 0.4153 | Reference lookup stays bounded and proves semantic callers/owners. |
| Sample B2B SamplePushService | `known_symbol_push_service_files` | 36 | 0.0210 | `serena_project_find_sample_b2b_push_service` | 348 | 0.1101 | Text search discovers service files; LSP proves the Android service symbol. |
| Sample B2B IUseCase | `known_symbol_iusecase_files` | 499 | 0.0170 | `serena_project_find_sample_b2b_iusecase` | 72 | 0.1050 | A high-fanout base interface should be identified semantically before broad reference expansion. |
| Sample Retail BaseViewModel definition | `known_symbol_base_viewmodel_files` | 1,268 | 0.0213 | `serena_project_find_sample_retail_base_viewmodel` | 771 | 0.1037 | LSP is smaller than the text file list and returns the exact class body range plus members. |
| Sample Retail BaseViewModel references | `known_symbol_base_viewmodel_files` | 1,268 | 0.0213 | `serena_project_refs_sample_retail_base_viewmodel` | 1,018 | 0.6678 | LSP returns semantic referencing symbols with a bounded high-fanout response. |
| Sample Retail MainActivity | `known_symbol_main_activity_files` | 223 | 0.0222 | `serena_project_find_sample_retail_main_activity` | 264 | 0.1062 | Text search is faster; LSP proves the class identity and child structure. |
| Sample Retail MainNavHost | `known_symbol_main_nav_host_files` | 39 | 0.0208 | `serena_project_find_sample_retail_main_nav_host` | 54 | 0.1107 | Compose function lookup can be tiny through either route; LSP proves the function body range. |
| Sample Retail CartItemsDao definition | `known_symbol_cart_items_dao_files` | 126 | 0.0206 | `serena_project_find_sample_retail_cart_items_dao` | 152 | 0.1039 | DAO text hits are not enough to distinguish generated/cache roles; LSP identifies the source symbol. |
| Sample Retail CartItemsDao references | `known_symbol_cart_items_dao_files` | 126 | 0.0206 | `serena_project_refs_sample_retail_cart_items_dao` | 236 | 0.1525 | LSP returns semantic referencing symbols for the DAO without reading every text hit. |
| Sample Retail SamplePushService | `known_symbol_push_service_files` | 36 | 0.0210 | `serena_project_find_sample_retail_push_service` | 341 | 0.1040 | Text search is smallest; LSP adds service symbol identity and range. |

Direct comparison rule: `rg/fd` often wins on raw speed and sometimes on size, but only the LSP layer proves Kotlin symbol identity, owning ranges, members, and semantic references.

## sample_b2b_android Default Search Highlights

| Case | Command | Bytes | Token proxy | Lines | Files | Median seconds |
| --- | --- | --- | --- | --- | --- | --- |
| `high_fanout_usecase_json` | `json_UseCase` | 599,988 | 149,997 | 2,090 | 262 | 0.0184 |
| `structural_function_shape` | `function_shapes` | 490,240 | 122,560 | 4,141 | 92 | 0.1116 |
| `high_fanout_usecase_raw` | `raw_UseCase` | 209,502 | 52,376 | 1,565 | 262 | 0.0177 |
| `inventory_kotlin_files` | `fd_kotlin_files` | 122,930 | 30,733 | 1,525 | 1,525 | 0.0189 |
| `structural_composable` | `composable_functions` | 68,662 | 17,166 | 650 | 363 | 0.1007 |
| `high_fanout_viewmodel_raw` | `raw_ViewModel` | 41,750 | 10,438 | 317 | 101 | 0.0169 |
| `high_fanout_usecase_count` | `count_UseCase` | 23,107 | 5,777 | 262 | 262 | 0.0173 |
| `high_fanout_usecase_files` | `files_UseCase` | 22,557 | 5,640 | 262 | 262 | 0.0172 |
| `inventory_xml_files` | `fd_xml_files` | 11,966 | 2,992 | 245 | 245 | 0.0158 |
| `high_fanout_viewmodel_files` | `files_ViewModel` | 8,030 | 2,008 | 101 | 101 | 0.0181 |

Known-symbol text baselines:

| Case | Bytes | Token proxy | Files | Matches | Median seconds |
| --- | --- | --- | --- | --- | --- |
| `known_symbol_dynamic_content_viewmodel_files` | 219 | 55 | 3 | 3 | 0.0163 |
| `known_symbol_iusecase_files` | 1,993 | 499 | 26 | 26 | 0.0170 |
| `known_symbol_notifications_viewmodel_count` | 231 | 58 | 3 | 4 | 0.0174 |
| `known_symbol_notifications_viewmodel_files` | 225 | 57 | 3 | 3 | 0.0181 |
| `known_symbol_product_details_request_files` | 157 | 40 | 2 | 2 | 0.0156 |
| `known_symbol_push_service_files` | 262 | 66 | 4 | 4 | 0.0156 |
| `known_symbol_session_service_impl_files` | 169 | 43 | 2 | 2 | 0.0173 |
| `known_symbol_store_config_raw` | 7,567 | 1,892 | 18 | 62 | 0.0176 |

## sample_retail_android Default Search Highlights

| Case | Command | Bytes | Token proxy | Lines | Files | Median seconds |
| --- | --- | --- | --- | --- | --- | --- |
| `high_fanout_usecase_json` | `json_UseCase` | 1,127,500 | 281,875 | 3,480 | 323 | 0.0215 |
| `high_fanout_usecase_raw` | `raw_UseCase` | 467,335 | 116,834 | 2,833 | 323 | 0.0219 |
| `structural_composable` | `composable_functions` | 205,412 | 51,353 | 1,823 | 752 | 0.1483 |
| `inventory_kotlin_files` | `fd_kotlin_files` | 197,203 | 49,301 | 2,167 | 2,167 | 0.0183 |
| `structural_flow_collect` | `flow_collect` | 185,071 | 46,268 | 1,438 | 50 | 0.1464 |
| `structural_koin_module` | `koin_modules` | 152,416 | 38,104 | 1,172 | 37 | 0.1437 |
| `high_fanout_viewmodel_raw` | `raw_ViewModel` | 95,423 | 23,856 | 645 | 152 | 0.0221 |
| `inventory_xml_files` | `fd_xml_files` | 35,614 | 8,904 | 501 | 501 | 0.0172 |
| `high_fanout_usecase_count` | `count_UseCase` | 33,708 | 8,427 | 323 | 323 | 0.0212 |
| `high_fanout_usecase_files` | `files_UseCase` | 33,009 | 8,253 | 323 | 323 | 0.0214 |

Known-symbol text baselines:

| Case | Bytes | Token proxy | Files | Matches | Median seconds |
| --- | --- | --- | --- | --- | --- |
| `known_symbol_app_update_manager_raw` | 1,751 | 438 | 6 | 14 | 0.0200 |
| `known_symbol_base_viewmodel_files` | 5,071 | 1,268 | 51 | 51 | 0.0213 |
| `known_symbol_cart_items_dao_files` | 501 | 126 | 6 | 6 | 0.0206 |
| `known_symbol_main_activity_count` | 914 | 229 | 11 | 22 | 0.0213 |
| `known_symbol_main_activity_files` | 892 | 223 | 11 | 11 | 0.0222 |
| `known_symbol_main_nav_host_files` | 156 | 39 | 2 | 2 | 0.0208 |
| `known_symbol_push_service_files` | 141 | 36 | 2 | 2 | 0.0210 |

## Android Studio Semantic Probe

| Repo | Case | Command | Symbol | Status | Bytes | Token proxy | Median seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sample_b2b_android` | `studio_analyze_notifications_fragment` | `analyze-file` | `-` | `pass` | 180 | 45 | 0.8926 |
| `sample_b2b_android` | `studio_check_sample_b2b` | `check` | `-` | `pass` | 276 | 69 | 0.8711 |
| `sample_b2b_android` | `studio_declaration_notifications_viewmodel` | `find-declaration` | `SampleFeatureViewModel` | `no-result` | 76 | 19 | 0.8744 |
| `sample_b2b_android` | `studio_declaration_notifications_viewmodel_fqn` | `find-declaration` | `com.app.features.notifications.SampleFeatureViewModel` | `no-result` | 107 | 27 | 0.8646 |
| `sample_b2b_android` | `studio_declaration_product_details_request` | `find-declaration` | `ProductDetailsRequest` | `no-result` | 75 | 19 | 0.8617 |
| `sample_b2b_android` | `studio_declaration_session_service_impl` | `find-declaration` | `SessionServiceImp` | `no-result` | 71 | 18 | 0.8864 |
| `sample_b2b_android` | `studio_usages_notifications_viewmodel` | `find-usages` | `SampleFeatureViewModel` | `no-result` | 99 | 25 | 0.9154 |
| `sample_b2b_android` | `studio_usages_session_service_impl` | `find-usages` | `SessionServiceImp` | `no-result` | 94 | 24 | 0.8781 |
| `sample_retail_android` | `studio_analyze_main_activity` | `analyze-file` | `-` | `pass` | 160 | 40 | 0.8889 |
| `sample_retail_android` | `studio_check_sample_retail` | `check` | `-` | `pass` | 276 | 69 | 0.8807 |
| `sample_retail_android` | `studio_declaration_app_update_manager` | `find-declaration` | `AppUpdateManager` | `no-result` | 70 | 18 | 0.8834 |
| `sample_retail_android` | `studio_declaration_base_viewmodel` | `find-declaration` | `BaseViewModel` | `no-result` | 67 | 17 | 0.8742 |
| `sample_retail_android` | `studio_declaration_base_viewmodel_fqn` | `find-declaration` | `com.core.base.mvi.BaseViewModel` | `no-result` | 85 | 22 | 0.8616 |
| `sample_retail_android` | `studio_declaration_main_activity` | `find-declaration` | `MainActivity` | `no-result` | 66 | 17 | 0.8805 |
| `sample_retail_android` | `studio_declaration_main_activity_fqn` | `find-declaration` | `com.app.features.main.MainActivity` | `no-result` | 88 | 22 | 0.8862 |
| `sample_retail_android` | `studio_usages_base_viewmodel` | `find-usages` | `BaseViewModel` | `no-result` | 90 | 23 | 0.8757 |
| `sample_retail_android` | `studio_usages_main_activity` | `find-usages` | `MainActivity` | `no-result` | 89 | 23 | 0.8767 |

## Serena / Kotlin LSP Source-Symbol Probe

| Repo | Case | Source file | Status | Symbols | Bytes | Token proxy | Median seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sample_b2b_android` | `serena_sample_b2b_notifications_fragment` | `feature-notifications/src/main/java/com/example/sample/features/notifications/SampleFeatureFragment.kt` | `pass` | 13 | 1,350 | 337 | 7.0638 |
| `sample_retail_android` | `serena_sample_retail_base_viewmodel` | `core/base/src/commonMain/kotlin/com/core/base/mvi/BaseViewModel.kt` | `pass` | 36 | 2,129 | 532 | 7.2294 |
| `sample_retail_android` | `serena_sample_retail_main_activity` | `android/app/src/main/java/com/app/features/main/MainActivity.kt` | `pass` | 12 | 1,155 | 288 | 11.1391 |

## Serena / ProjectServer Semantic Probe

This layer exercises read-only Serena semantic tools through the local ProjectServer, outside the Codex MCP transport.

| Repo | Case | Tool | Status | Measured passes | Bytes | Token proxy | Median seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sample_b2b_android` | `serena_project_diagnostics_sample_b2b_iusecase` | `get_diagnostics_for_file` | `pass` | 3 | 290 | 73 | 0.1563 |
| `sample_b2b_android` | `serena_project_find_sample_b2b_dynamic_content_viewmodel` | `find_symbol` | `pass` | 3 | 1,021 | 256 | 0.1096 |
| `sample_b2b_android` | `serena_project_find_sample_b2b_iusecase` | `find_symbol` | `pass` | 3 | 288 | 72 | 0.1050 |
| `sample_b2b_android` | `serena_project_find_sample_b2b_notifications_viewmodel` | `find_symbol` | `pass` | 3 | 2,178 | 545 | 0.1092 |
| `sample_b2b_android` | `serena_project_find_sample_b2b_push_service` | `find_symbol` | `pass` | 3 | 1,391 | 348 | 0.1101 |
| `sample_b2b_android` | `serena_project_implementations_sample_b2b_iusecase_boundary` | `find_implementations` | `error` | 3 | 394 | 99 | 0.1172 |
| `sample_b2b_android` | `serena_project_overview_sample_b2b_notifications_fragment` | `get_symbols_overview` | `pass` | 3 | 36 | 9 | 0.1104 |
| `sample_b2b_android` | `serena_project_overview_sample_b2b_notifications_viewmodel` | `get_symbols_overview` | `pass` | 3 | 37 | 10 | 0.1068 |
| `sample_b2b_android` | `serena_project_refs_sample_b2b_dynamic_content_viewmodel` | `find_referencing_symbols` | `pass` | 3 | 963 | 241 | 0.4153 |
| `sample_b2b_android` | `serena_project_refs_sample_b2b_notifications_viewmodel` | `find_referencing_symbols` | `pass` | 3 | 1,037 | 260 | 0.5149 |
| `sample_retail_android` | `serena_project_diagnostics_sample_retail_cart_items_dao` | `get_diagnostics_for_file` | `pass` | 3 | 2,548 | 637 | 0.1886 |
| `sample_retail_android` | `serena_project_find_sample_retail_base_viewmodel` | `find_symbol` | `pass` | 3 | 3,082 | 771 | 0.1037 |
| `sample_retail_android` | `serena_project_find_sample_retail_cart_items_dao` | `find_symbol` | `pass` | 3 | 606 | 152 | 0.1039 |
| `sample_retail_android` | `serena_project_find_sample_retail_main_activity` | `find_symbol` | `pass` | 3 | 1,055 | 264 | 0.1062 |
| `sample_retail_android` | `serena_project_find_sample_retail_main_nav_host` | `find_symbol` | `pass` | 3 | 215 | 54 | 0.1107 |
| `sample_retail_android` | `serena_project_find_sample_retail_push_service` | `find_symbol` | `pass` | 3 | 1,361 | 341 | 0.1040 |
| `sample_retail_android` | `serena_project_implementations_sample_retail_cart_items_dao_boundary` | `find_implementations` | `error` | 3 | 403 | 101 | 0.1082 |
| `sample_retail_android` | `serena_project_overview_sample_retail_base_viewmodel` | `get_symbols_overview` | `pass` | 3 | 28 | 7 | 0.1104 |
| `sample_retail_android` | `serena_project_overview_sample_retail_main_activity` | `get_symbols_overview` | `pass` | 3 | 27 | 7 | 0.1107 |
| `sample_retail_android` | `serena_project_refs_sample_retail_base_viewmodel` | `find_referencing_symbols` | `pass` | 3 | 4,070 | 1,018 | 0.6678 |
| `sample_retail_android` | `serena_project_refs_sample_retail_cart_items_dao` | `find_referencing_symbols` | `pass` | 3 | 942 | 236 | 0.1525 |

## Serena / Android Process State

| Process kind | Count |
| --- | --- |
| Serena MCP | 0 |
| Kotlin LSP | 0 |
| JSON LSP | 0 |
| Java/JDTLS | 0 |

Status: `clean`

Cleanup commands:

```bash
scripts/setup/repair-serena-android-sessions.sh --dry-run
scripts/setup/repair-serena-android-sessions.sh --kill
```

## Android Project-Model Readiness

| Repo | Status | Gradle distribution | Wrapper status | Command source | Missing local keys | Ran Gradle |
| --- | --- | --- | --- | --- | --- | --- |
| `sample_b2b_android` | `missing-local-properties` | `gradle-8.13-bin` | `wrapper-script-missing` | `cached-wrapper-distribution` | `sample_analytics_id` | false |
| `sample_retail_android` | `missing-local-properties` | `gradle-9.1.0-bin` | `wrapper-executable` | `wrapper` | `production.sample.map.api.key`, `staging.sample.map.api.key` | false |

## Current Interpretation

The current Android result is operational for the requested routing benchmark, with explicit boundaries where Android Studio or Gradle cannot yet be used as proof.

- `rg` / `fd` / `ast-grep` are stable and fast for discovery, literal/resource lookup, and structural patterns.
- Android Studio Preview/Quail is connected and `analyze-file` works on real Kotlin files.
- `find-declaration` and `find-usages` are still not usable as proof because they return `no-result` on the tested simple and fully qualified symbols.
- Serena/Kotlin LSP source-symbol extraction works in both ExampleCo Android repos after stale sessions are cleaned.
- Serena ProjectServer semantic queries can find Kotlin symbols, references, file-level symbol overviews, and diagnostics through read-only LSP tools outside the broken Codex MCP transport, with one warmup plus repeated measured passes per case.
- Serena ProjectServer `find_implementations` is recorded as an expected unsupported boundary for the current Kotlin LSP handler, not as a live proof tool.
- Process-state evidence must stay clean before treating future Kotlin LSP failures as semantic failures.
- The project-model probe records the runtime/build boundary: both repos are missing required machine-local `local.properties` keys, and Sample B2B also has wrapper metadata without a checked-in `gradlew` script.
- Because no build/runtime parity is claimed, those machine-local Gradle inputs are recorded as boundaries, not as LSP/search benchmark failures.

## Routing Policy

```text
Known Kotlin/Java symbol:
  Use a proven semantic layer only after source-symbol smoke tests pass.

High-fanout symbol:
  Summary/counts first; never raw dump.

Literal/resource/XML/GraphQL/generated:
  rg/fd and GraphQL tools first.

Structural Kotlin/Gradle pattern:
  ast-grep first.

Build/runtime truth:
  Gradle, Android Studio, emulator/device, adb, or CI only.
```

## Next Gate

First clean stale Serena/LSP sessions only when it is safe to reconnect active agents, then prove process state:

```bash
scripts/setup/repair-serena-android-sessions.sh --dry-run
scripts/setup/repair-serena-android-sessions.sh --kill
python3 scripts/benchmarks/android/process_state_probe.py --validate --run \
  --require-clean --enforce-assertions \
  --output results/android/process-state
```

Only when you need build/runtime proof, add the real team-approved `local.properties` values, repair or restore Sample B2B's `gradlew` script, rerun Gradle sync, and rerun:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --require-clean-process-state --enforce-assertions \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

For focused layer debugging, rerun the individual probes:

```bash
python3 scripts/benchmarks/android/project_model_probe.py --validate --run \
  --cases benchmarks/android/project-model-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/project-model

python3 scripts/benchmarks/android/studio_semantic_probe.py --validate --run \
  --cases benchmarks/android/studio-semantic-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/android-studio-semantic

python3 scripts/benchmarks/android/serena_source_symbol_probe.py --validate --run \
  --cases benchmarks/android/serena-source-symbol-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/serena-source-symbol
```
