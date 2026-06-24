from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

from agent_code_router_codegraph_gateway.budgets import MAX_ACTIVE_SCOPES, MAX_GATEWAY_CALLS_PER_SCOPE, SCOPE_MAX_BYTES, SCOPE_TTL_SECONDS


def new_scope_id() -> str:
    return "cg-" + uuid.uuid4().hex[:10]


def evidence_id(*, path: str, line_start: int, line_end: int, symbol: str) -> str:
    payload = f"{path}:{line_start}:{line_end}:{symbol}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


@dataclass
class ScopeRecord:
    scope_id: str
    scope_key: str | None
    intent: str
    created_monotonic: float
    emitted_bytes: int = 0
    gateway_calls: int = 0
    anchors: dict[str, dict[str, object]] = field(default_factory=dict)


class ScopeBudgetExceeded(ValueError):
    pass


class UnknownScope(ValueError):
    pass


def scope_key(kind: str, payload: dict[str, object]) -> str:
    encoded = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


class EvidenceStore:
    def __init__(self) -> None:
        self._scopes: dict[str, ScopeRecord] = {}
        self._scope_ids_by_key: dict[str, str] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [scope_id for scope_id, scope in self._scopes.items() if now - scope.created_monotonic > SCOPE_TTL_SECONDS]
        for scope_id in expired:
            scope = self._scopes.pop(scope_id, None)
            if scope is not None and scope.scope_key:
                self._scope_ids_by_key.pop(scope.scope_key, None)
        while len(self._scopes) > MAX_ACTIVE_SCOPES:
            oldest = min(self._scopes.items(), key=lambda item: item[1].created_monotonic)[0]
            scope = self._scopes.pop(oldest, None)
            if scope is not None and scope.scope_key:
                self._scope_ids_by_key.pop(scope.scope_key, None)

    def create_scope(self, *, intent: str, scope_key_value: str | None = None) -> ScopeRecord:
        self._cleanup()
        record = ScopeRecord(scope_id=new_scope_id(), scope_key=scope_key_value, intent=intent, created_monotonic=time.monotonic())
        self._scopes[record.scope_id] = record
        if scope_key_value is not None:
            self._scope_ids_by_key[scope_key_value] = record.scope_id
        return record

    def get_or_create_scope(self, *, intent: str, scope_key_value: str) -> ScopeRecord:
        self._cleanup()
        scope_id = self._scope_ids_by_key.get(scope_key_value)
        if scope_id is not None and scope_id in self._scopes:
            return self._scopes[scope_id]
        return self.create_scope(intent=intent, scope_key_value=scope_key_value)

    def get_scope(self, scope_id: str) -> ScopeRecord | None:
        self._cleanup()
        return self._scopes.get(scope_id)

    def ensure_can_call(self, scope_id: str) -> ScopeRecord:
        record = self.get_scope(scope_id)
        if record is None:
            raise UnknownScope("scope_id is unknown or expired")
        if record.gateway_calls >= MAX_GATEWAY_CALLS_PER_SCOPE:
            raise ScopeBudgetExceeded("scope exceeded maximum gateway calls")
        if record.emitted_bytes >= SCOPE_MAX_BYTES:
            raise ScopeBudgetExceeded("scope exceeded total graph output budget")
        return record

    def remaining_bytes(self, scope_id: str, *, tool_max_bytes: int) -> int:
        record = self.ensure_can_call(scope_id)
        return min(tool_max_bytes, max(0, SCOPE_MAX_BYTES - record.emitted_bytes))

    def register_result(self, scope_id: str, *, emitted_bytes: int, anchors: list[dict[str, object]]) -> ScopeRecord:
        record = self.get_scope(scope_id)
        if record is None:
            raise UnknownScope("scope_id is unknown or expired")
        if record.gateway_calls >= MAX_GATEWAY_CALLS_PER_SCOPE:
            raise ScopeBudgetExceeded("scope exceeded maximum gateway calls")
        if record.emitted_bytes + emitted_bytes > SCOPE_MAX_BYTES:
            raise ScopeBudgetExceeded("scope exceeded total graph output budget")
        record.gateway_calls += 1
        record.emitted_bytes += emitted_bytes
        for anchor in anchors:
            record.anchors[str(anchor["id"])] = dict(anchor)
        return record
