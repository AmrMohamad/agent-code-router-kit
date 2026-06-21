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
