from __future__ import annotations

from pathlib import Path

TARGET = Path("src/nextgen_memory/execution_ledger.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_in_section(
    text: str,
    start_marker: str,
    end_marker: str,
    old: str,
    new: str,
    label: str,
) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    section = text[start:end]
    updated = replace_once(section, old, new, label)
    return text[:start] + updated + text[end:]


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '_DIGEST_RE = re.compile(r"^[0-9a-f]{16,128}$")\n_FORBIDDEN_METADATA_KEYS',
        '_DIGEST_RE = re.compile(r"^[0-9a-f]{16,128}$")\n'
        '_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")\n'
        '_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")\n'
        '_NON_ALPHANUMERIC = re.compile(r"[^A-Za-z0-9]+")\n'
        '_FORBIDDEN_METADATA_KEYS',
        "metadata regex constants",
    )
    text = replace_once(
        text,
        '        "token",\n    }\n)\n_ALLOWED_ARTIFACT_ROLES',
        '        "token",\n    }\n)\n'
        '_FORBIDDEN_METADATA_COMPACT = frozenset(\n'
        '    key.replace("_", "") for key in _FORBIDDEN_METADATA_KEYS\n'
        ')\n'
        '_ALLOWED_ARTIFACT_ROLES',
        "compact forbidden metadata set",
    )

    event_validation = '''    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExecutionEventKind):
            raise ExecutionLedgerValidationError(
                "kind must be an ExecutionEventKind"
            )
        if not isinstance(self.outcome, ExecutionOutcome):
            raise ExecutionLedgerValidationError(
                "outcome must be an ExecutionOutcome"
            )
        if self.sequence <= 0:
            raise ExecutionLedgerValidationError("sequence must be positive")
        if self.sequence == 1:
            if (
                self.previous_event_id is not None
                or self.kind is not ExecutionEventKind.RUN_STARTED
            ):
                raise ExecutionLedgerValidationError(
                    "first execution event must be run_started without a predecessor"
                )
        elif (
            self.previous_event_id is None
            or self.kind is ExecutionEventKind.RUN_STARTED
        ):
            raise ExecutionLedgerValidationError(
                "non-initial events require a predecessor and cannot be run_started"
            )
        _require_aware("started_at", self.started_at)
        if self.ended_at is not None:
            _require_aware("ended_at", self.ended_at)
            if self.ended_at < self.started_at:
                raise ExecutionLedgerValidationError(
                    "ended_at cannot precede started_at"
                )
        terminal_outcome = _terminal_outcome(self.kind)
        if terminal_outcome is not None:
            if self.outcome is not terminal_outcome:
                raise ExecutionLedgerValidationError(
                    "terminal execution outcome mismatch"
                )
            if self.ended_at is None:
                raise ExecutionLedgerValidationError(
                    "terminal execution events require ended_at"
                )
        if (
            self.kind is ExecutionEventKind.RUN_STARTED
            and self.outcome is not ExecutionOutcome.UNKNOWN
        ):
            raise ExecutionLedgerValidationError(
                "run_started must use unknown outcome"
            )
        if (
            _ACTION_RE.fullmatch(self.action_key) is None
            or not self.idempotency_key.strip()
        ):
            raise ExecutionLedgerValidationError(
                "action_key or event idempotency_key is invalid"
            )
        for name, value in (
            ("command_fingerprint", self.command_fingerprint),
            ("input_hash", self.input_hash),
            ("output_hash", self.output_hash),
            ("content_hash", self.content_hash),
            ("event_hash", self.event_hash),
        ):
            _require_hash(name, value)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))
'''
    text = replace_in_section(
        text,
        "class ExecutionEvent:",
        "class ExecutionArtifact:",
        '    def __post_init__(self) -> None:\n'
        '        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))\n',
        event_validation,
        "ExecutionEvent validation",
    )

    metadata_helpers = '''def _normalize_metadata_key(key: str) -> str:
    with_acronyms = _ACRONYM_BOUNDARY.sub("_", key.strip())
    with_boundaries = _CAMEL_CASE_BOUNDARY.sub("_", with_acronyms)
    return _NON_ALPHANUMERIC.sub("_", with_boundaries).strip("_").lower()


def _metadata_key_is_forbidden(key: str) -> bool:
    normalized = _normalize_metadata_key(key)
    if normalized in _FORBIDDEN_METADATA_KEYS:
        return True
    compact = normalized.replace("_", "")
    if compact in _FORBIDDEN_METADATA_COMPACT:
        return True
    segments = {segment for segment in normalized.split("_") if segment}
    return bool(segments & _FORBIDDEN_METADATA_KEYS)


'''
    text = replace_once(
        text,
        "def _freeze_metadata(",
        metadata_helpers + "def _freeze_metadata(",
        "metadata key helpers",
    )

    freeze_start = text.index("def _freeze_metadata(")
    freeze_end = text.index("def _thaw_json(", freeze_start)
    hardened_freeze = '''def _freeze_metadata(
    metadata: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    source: Any = {} if metadata is None else metadata
    frozen = _freeze_json(source, set(), "metadata")
    if not isinstance(frozen, Mapping):
        raise ExecutionLedgerValidationError("metadata must be a JSON object")
    if len(_canonical_json(frozen).encode("utf-8")) > 8192:
        raise ExecutionLedgerValidationError("metadata exceeds 8192 bytes")
    return frozen


def _freeze_json(value: Any, active_ids: set[int], path: str) -> Any:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active_ids:
            raise ExecutionLedgerValidationError(f"cyclic metadata at {path}")
        active_ids.add(identity)
        try:
            frozen: dict[str, Any] = {}
            normalized_keys: set[str] = set()
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise ExecutionLedgerValidationError(
                        "metadata keys must be strings"
                    )
                stored_key = key.strip()
                if not stored_key:
                    raise ExecutionLedgerValidationError(
                        f"metadata key must not be empty at {path}"
                    )
                normalized_key = _normalize_metadata_key(stored_key)
                if not normalized_key:
                    raise ExecutionLedgerValidationError(
                        f"metadata key normalizes to empty: {path}.{stored_key}"
                    )
                if stored_key in frozen or normalized_key in normalized_keys:
                    raise ExecutionLedgerValidationError(
                        "duplicate metadata key after normalization: "
                        f"{path}.{stored_key}"
                    )
                if _metadata_key_is_forbidden(stored_key):
                    raise ExecutionLedgerValidationError(
                        f"forbidden metadata key: {stored_key}"
                    )
                normalized_keys.add(normalized_key)
                frozen[stored_key] = _freeze_json(
                    nested,
                    active_ids,
                    f"{path}.{stored_key}",
                )
            return MappingProxyType(frozen)
        finally:
            active_ids.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active_ids:
            raise ExecutionLedgerValidationError(f"cyclic metadata at {path}")
        active_ids.add(identity)
        try:
            return tuple(
                _freeze_json(nested, active_ids, f"{path}[{index}]")
                for index, nested in enumerate(value)
            )
        finally:
            active_ids.remove(identity)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ExecutionLedgerValidationError(
                "metadata numbers must be finite JSON numbers"
            )
        return value
    raise ExecutionLedgerValidationError(
        f"unsupported metadata value at {path}: {type(value).__name__}"
    )


'''
    text = text[:freeze_start] + hardened_freeze + text[freeze_end:]

    event_payload = '''def _event_payload(event: ExecutionEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "space_id": str(event.space_id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "previous_event_id": (
            str(event.previous_event_id) if event.previous_event_id else None
        ),
        "kind": event.kind.value,
        "outcome": event.outcome.value,
        "action_key": event.action_key,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        "command_fingerprint": event.command_fingerprint,
        "input_hash": event.input_hash,
        "output_hash": event.output_hash,
        "backend_ref": event.backend_ref,
        "idempotency_key": event.idempotency_key,
        "metadata": event.metadata,
    }


'''
    text = replace_once(
        text,
        "class AppendOnlyExecutionLedger:",
        event_payload + "class AppendOnlyExecutionLedger:",
        "event payload helper",
    )

    text = replace_once(
        text,
        '        if run is None:\n'
        '            raise KeyError(f"unknown run_id {run_id}")\n'
        '        if kind is ExecutionEventKind.RUN_STARTED:\n',
        '        if run is None:\n'
        '            raise KeyError(f"unknown run_id {run_id}")\n'
        '        if not isinstance(kind, ExecutionEventKind):\n'
        '            raise ExecutionLedgerValidationError(\n'
        '                "kind must be an ExecutionEventKind"\n'
        '            )\n'
        '        if not isinstance(outcome, ExecutionOutcome):\n'
        '            raise ExecutionLedgerValidationError(\n'
        '                "outcome must be an ExecutionOutcome"\n'
        '            )\n'
        '        if kind is ExecutionEventKind.RUN_STARTED:\n',
        "append enum validation",
    )

    for start_marker, end_marker, label in (
        ("    def complete(\n", "    def fail(\n", "complete ended_at"),
        ("    def fail(\n", "    def cancel(\n", "fail ended_at"),
        ("    def cancel(\n", "    def attach_artifact(\n", "cancel ended_at"),
    ):
        text = replace_in_section(
            text,
            start_marker,
            end_marker,
            "            started_at=started_at,\n"
            "            idempotency_key=idempotency_key,\n",
            "            started_at=started_at,\n"
            "            ended_at=started_at,\n"
            "            idempotency_key=idempotency_key,\n",
            label,
        )

    verify_chain = '''    def verify_chain(self, run_id: UUID) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id {run_id}")
        previous: ExecutionEvent | None = None
        for expected_sequence, event in enumerate(
            self._events[run_id], start=1
        ):
            if event.sequence != expected_sequence:
                return False
            expected_previous_id = previous.event_id if previous is not None else None
            if event.previous_event_id != expected_previous_id:
                return False
            expected_event_id = uuid5(
                run.run_id,
                f"execution-event:{event.idempotency_key}",
            )
            if event.event_id != expected_event_id:
                return False
            if _hash_payload(_event_payload(event)) != event.content_hash:
                return False
            previous_hash = previous.event_hash if previous is not None else ""
            if _sha256(f"{previous_hash}:{event.content_hash}") != event.event_hash:
                return False
            if previous is not None and event.started_at < previous.started_at:
                return False
            if previous is not None and _terminal_outcome(previous.kind) is not None:
                return False
            previous = event
        return bool(previous)

'''
    text = replace_once(
        text,
        "    def status(self, run_id: UUID) -> ExecutionStatus:\n",
        verify_chain + "    def status(self, run_id: UUID) -> ExecutionStatus:\n",
        "verify_chain method",
    )

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
