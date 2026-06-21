from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OracleResult:
    task_id: str
    oracle_id: str
    oracle_type: str
    status: str
    checks: list[dict[str, object]]
    reason: str


FAMILY_ORACLE_TYPES = {
    "known_symbol_definition": "semantic_identity",
    "high_fanout_symbol": "high_fanout_reference",
    "literal_resource": "literal_resource",
    "structural_pattern": "structural_pattern",
    "build_runtime_boundary": "build_runtime_boundary",
}


def load_task_oracles(path: str | Path | None) -> dict[str, dict[str, object]]:
    if not path:
        return {}
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"task oracle file does not exist: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    rows = data.get("oracles", data if isinstance(data, list) else [])
    if not isinstance(rows, list):
        raise ValueError("task oracle file must contain a list or an object with an 'oracles' list")
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or (not row.get("task_id") and not row.get("task_family")):
            raise ValueError("every oracle row must include task_id or task_family")
        if row.get("task_id"):
            result[str(row["task_id"])] = row
        if row.get("task_family"):
            result[f"family:{row['task_family']}"] = row
    return result


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def _regex(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) is not None


def _row_value(row: dict[str, object], dotted_key: str) -> object:
    value: object = row
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _oracle_has_external_checks(oracle: dict[str, object]) -> bool:
    check_fields = [
        "required_terms",
        "required_regexes",
        "forbidden_terms",
        "required_row_values",
        "required_row_fields",
        "min_numeric_fields",
        "max_numeric_fields",
    ]
    return any(bool(oracle.get(field)) for field in check_fields)


def validate_task_oracle_plan(
    *,
    tasks: list[object],
    oracles: dict[str, dict[str, object]],
    require_task_specific: bool = False,
) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    for task in tasks:
        task_id = str(getattr(task, "task_id", ""))
        task_family = str(getattr(task, "task_family", ""))
        task_oracle = oracles.get(task_id)
        family_oracle = oracles.get(f"family:{task_family}")
        oracle = task_oracle or family_oracle
        if oracle is None:
            issues.append({"severity": "fail", "code": "oracle_missing", "task_id": task_id, "message": "task has no external oracle"})
            continue
        if require_task_specific and task_oracle is None:
            issues.append(
                {
                    "severity": "fail",
                    "code": "oracle_not_task_specific",
                    "task_id": task_id,
                    "message": "confirmatory tasks require task-specific oracles, not family fallbacks",
                }
            )
        expected_type = FAMILY_ORACLE_TYPES.get(task_family)
        if expected_type and oracle.get("type") not in {expected_type, "text_checks"}:
            issues.append(
                {
                    "severity": "fail",
                    "code": "oracle_type",
                    "task_id": task_id,
                    "message": f"oracle type must be {expected_type} or text_checks for {task_family}",
                }
            )
        if oracle.get("requires_policy_pass") is not True:
            issues.append(
                {
                    "severity": "fail",
                    "code": "oracle_policy_gate",
                    "task_id": task_id,
                    "message": "confirmatory oracle must require policy_adherence=pass",
                }
            )
        if not _oracle_has_external_checks(oracle):
            issues.append(
                {
                    "severity": "fail",
                    "code": "oracle_has_no_checks",
                    "task_id": task_id,
                    "message": "oracle must contain at least one transcript or run-row check",
                }
            )
        if task_family == "build_runtime_boundary" and not oracle.get("forbidden_terms"):
            issues.append(
                {
                    "severity": "fail",
                    "code": "oracle_missing_overclaim_guard",
                    "task_id": task_id,
                    "message": "build/runtime boundary oracles must include forbidden overclaim terms",
                }
            )
    status = "pass" if not any(issue["severity"] == "fail" for issue in issues) else "fail"
    return {
        "status": status,
        "task_count": len(tasks),
        "oracle_count": len([key for key in oracles if not key.startswith("family:")]),
        "require_task_specific": require_task_specific,
        "issues": issues,
    }


def verify_oracle(
    *,
    task_id: str,
    oracle: dict[str, object] | None,
    transcript_text: str,
    run_row: dict[str, object] | None = None,
) -> OracleResult:
    if not oracle:
        return OracleResult(
            task_id=task_id,
            oracle_id="",
            oracle_type="not_configured",
            status="not_configured",
            checks=[],
            reason="no external oracle configured for task",
        )
    checks: list[dict[str, object]] = []
    passed = True
    for term in [str(item) for item in oracle.get("required_terms", [])]:
        ok = _contains(transcript_text, term)
        checks.append({"kind": "required_term", "value": term, "passed": ok})
        passed = passed and ok
    for pattern in [str(item) for item in oracle.get("required_regexes", [])]:
        ok = _regex(transcript_text, pattern)
        checks.append({"kind": "required_regex", "value": pattern, "passed": ok})
        passed = passed and ok
    for term in [str(item) for item in oracle.get("forbidden_terms", [])]:
        ok = not _contains(transcript_text, term)
        checks.append({"kind": "forbidden_term", "value": term, "passed": ok})
        passed = passed and ok
    for field, expected in dict(oracle.get("required_row_values", {})).items():
        actual = _row_value(run_row or {}, str(field))
        ok = actual == expected
        checks.append({"kind": "required_row_value", "field": str(field), "expected": expected, "actual": actual, "passed": ok})
        passed = passed and ok
    for field in [str(item) for item in oracle.get("required_row_fields", [])]:
        actual = _row_value(run_row or {}, field)
        ok = actual not in {"", None, []}
        checks.append({"kind": "required_row_field", "field": field, "passed": ok})
        passed = passed and ok
    for field, minimum in dict(oracle.get("min_numeric_fields", {})).items():
        actual = _row_value(run_row or {}, str(field))
        ok = isinstance(actual, int | float) and actual >= float(minimum)
        checks.append({"kind": "min_numeric_field", "field": str(field), "minimum": minimum, "actual": actual, "passed": ok})
        passed = passed and ok
    for field, maximum in dict(oracle.get("max_numeric_fields", {})).items():
        actual = _row_value(run_row or {}, str(field))
        ok = isinstance(actual, int | float) and actual <= float(maximum)
        checks.append({"kind": "max_numeric_field", "field": str(field), "maximum": maximum, "actual": actual, "passed": ok})
        passed = passed and ok
    if run_row and oracle.get("requires_policy_pass", True):
        ok = run_row.get("policy_adherence") == "pass"
        checks.append({"kind": "policy_adherence", "value": "pass", "passed": ok})
        passed = passed and ok
    return OracleResult(
        task_id=task_id,
        oracle_id=str(oracle.get("oracle_id", task_id)),
        oracle_type=str(oracle.get("type", "text_checks")),
        status="pass" if passed else "fail",
        checks=checks,
        reason="all oracle checks passed" if passed else "one or more oracle checks failed",
    )


def verify_transcript_file(
    *,
    task_id: str,
    oracle: dict[str, object] | None,
    transcript_path: str | Path,
    run_row: dict[str, object] | None = None,
) -> OracleResult:
    text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    return verify_oracle(task_id=task_id, oracle=oracle, transcript_text=text, run_row=run_row)
