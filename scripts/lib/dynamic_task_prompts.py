from __future__ import annotations

import random
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from scripts.lib.serena_readiness import extract_source_symbol


SOURCE_GLOBS = ["*.kt", "*.java", "*.swift", "*.ts", "*.tsx", "*.js", "*.jsx"]
BROAD_DECLARATION_RE = r"\b(class|interface|object|struct|enum|protocol|actor|function|const|let|var)\s+[A-Z][A-Za-z0-9_]{3,}\b"
DECLARATION_PATTERNS = [
    re.compile(
        r"^\s*(?:(?:public|internal|private|protected)\s+)*"
        r"(?:(?:data|sealed|annotation|value)\s+)?"
        r"(class|interface|object|enum)\s+([A-Z][A-Za-z0-9_]{3,})\b"
    ),
    re.compile(
        r"^\s*(?:(?:public|internal|private|fileprivate|open|final)\s+)*"
        r"(class|struct|enum|protocol|actor)\s+([A-Z][A-Za-z0-9_]{3,})\b"
    ),
    re.compile(r"^\s*(?:export\s+default\s+|export\s+)?(?:async\s+)?(function)\s+([A-Z][A-Za-z0-9_]{3,})\b"),
    re.compile(r"^\s*(?:export\s+)?(const|let|var)\s+([A-Z][A-Za-z0-9_]{3,})\s*[:=]"),
]
EXCLUDED_PARTS = {
    ".gradle",
    ".idea",
    ".serena",
    "build",
    "generated",
    "intermediates",
    "tmp",
}


@dataclass(frozen=True)
class CodeSymbolTarget:
    symbol: str
    source_file: str
    line: int
    language: str
    declaration_kind: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _allowed_source_path(path: str) -> bool:
    parts = set(Path(path).parts)
    return not bool(parts.intersection(EXCLUDED_PARTS))


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".kt": "kotlin",
        ".java": "java",
        ".swift": "swift",
        ".ts": "typescript",
        ".tsx": "typescriptreact",
        ".js": "javascript",
        ".jsx": "javascriptreact",
    }.get(suffix, "unknown")


def _declaration_match(code: str) -> tuple[str, str] | None:
    for pattern in DECLARATION_PATTERNS:
        match = pattern.search(code)
        if match:
            return match.group(1), match.group(2)
    return None


def discover_code_symbol_targets(repo: str | Path, *, limit: int = 2000) -> list[CodeSymbolTarget]:
    repo_path = Path(repo).expanduser().resolve()
    command = [
        "rg",
        "--no-config",
        "-n",
        "--no-heading",
    ]
    for glob in SOURCE_GLOBS:
        command.extend(["-g", glob])
    command.extend([BROAD_DECLARATION_RE, "."])
    completed = subprocess.run(
        command,
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    targets: list[CodeSymbolTarget] = []
    for raw_line in completed.stdout.splitlines():
        path, line_text, code = raw_line.split(":", 2) if raw_line.count(":") >= 2 else ("", "", "")
        if not path or not line_text.isdigit() or not _allowed_source_path(path):
            continue
        declaration = _declaration_match(code)
        if not declaration:
            continue
        declaration_kind, symbol = declaration
        targets.append(
            CodeSymbolTarget(
                symbol=symbol,
                source_file=path,
                line=int(line_text),
                language=_language_for_path(path),
                declaration_kind=declaration_kind,
            )
        )
        if len(targets) >= limit:
            break
    return targets


def select_code_symbol_target(repo: str | Path, *, rng: random.Random) -> CodeSymbolTarget | None:
    targets = discover_code_symbol_targets(repo)
    if not targets:
        return None
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.symbol] = counts.get(target.symbol, 0) + 1
    unique_targets = [target for target in targets if counts[target.symbol] == 1]
    return rng.choice(unique_targets or targets)


def materialize_task_for_symbol(task, target: CodeSymbolTarget):
    old_symbol = extract_source_symbol(task.prompt)
    prompt = task.prompt
    expected_success_signal = task.expected_success_signal
    if old_symbol:
        prompt = prompt.replace(old_symbol, target.symbol)
        expected_success_signal = expected_success_signal.replace(old_symbol, target.symbol)
    else:
        prompt = f"{prompt.rstrip()} Use the sampled real source symbol {target.symbol}."
        expected_success_signal = f"{expected_success_signal}; {target.symbol} reported"
    return replace(task, prompt=prompt, expected_success_signal=expected_success_signal)
