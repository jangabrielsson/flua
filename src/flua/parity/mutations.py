"""Tier-2 mutation sequences: controlled create/update/delete cycles whose
artifacts are namespaced ``flua_p_<uuid8>`` and cleaned up LIFO after the
capture.

A sequence is a list of steps. Step paths and bodies template ``{prefix}``
(the session namespace) and ``{step.field}`` (values extracted from an
earlier step's response, e.g. ``{create.id}``). The capture records each
step's status + normalized shape; the offline replay executes the same
sequence against the sim and compares — statuses and shapes, never the
artifacts' concrete ids.

One honest asymmetry is modeled explicitly: the HC3's ``POST /quickApp``
takes a real .fqa, while the sim's takes ``{name, ...}``. Such steps carry
a ``sim_body`` variant (or ``live_fqa`` for the QA create) so both sides
perform the *same operation* with their own wire format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from flua.parity.normalize import shape

_TEMPLATE = re.compile(r"\{([a-z_]+)(?:\.([a-z_]+))?\}")


class Backend(Protocol):
    """One side of a parity run: the live HC3 or the offline sim."""

    is_sim: bool

    def call(self, method: str, path: str, body: Any = None) -> tuple[Any, int]: ...


class SimBackend:
    is_sim = True

    def __init__(self, api: Any) -> None:
        self._api = api

    def call(self, method: str, path: str, body: Any = None) -> tuple[Any, int]:
        return self._api.dispatch(method, path, body)


class LiveBackend:
    is_sim = False

    def __init__(self, client: Any) -> None:
        self._client = client

    def call(self, method: str, path: str, body: Any = None) -> tuple[Any, int]:
        return self._client.request(method, path, body=body)


@dataclass(frozen=True)
class Step:
    id: str
    method: str
    path: str  # {prefix} and {step.field} templates
    body: Any = None  # templated too; the HC3's wire body by default
    sim_body: Any = None  # sim-side body for the same operation (HC3 asymmetry)
    live_fqa: bool = False  # live body is a built .fqa (the QA create)
    extract: dict[str, str] = field(default_factory=dict)  # response field -> binding


@dataclass(frozen=True)
class Sequence:
    id: str
    note: str
    steps: list[Step]


SEQUENCES: list[Sequence] = [
    Sequence(
        "customEvents",
        "create, update, fire, publish, delete — one namespaced event",
        [
            Step(
                "create",
                "POST",
                "/customEvents",
                {"name": "{prefix}_evt", "userDescription": "flua parity probe"},
            ),
            Step(
                "update",
                "PUT",
                "/customEvents/{prefix}_evt",
                {"userDescription": "flua parity probe, updated"},
            ),
            Step("fire", "POST", "/customEvents/{prefix}_evt"),
            Step("publish", "GET", "/customEvents/{prefix}_evt/publish"),
            Step("delete", "DELETE", "/customEvents/{prefix}_evt"),
        ],
    ),
    Sequence(
        "globalVariables",
        "add, change, read, delete — one namespaced variable (the final read "
        "pins the post-delete 404 contract)",
        [
            Step("create", "POST", "/globalVariables", {"name": "{prefix}_gv", "value": "1"}),
            Step("update", "PUT", "/globalVariables/{prefix}_gv", {"value": "2"}),
            Step("read", "GET", "/globalVariables/{prefix}_gv"),
            Step("delete", "DELETE", "/globalVariables/{prefix}_gv"),
            Step("read_deleted", "GET", "/globalVariables/{prefix}_gv"),
        ],
    ),
    Sequence(
        "qaLifecycle",
        "create QA, read it, updateProperty, read the property, delete — "
        "read goes through /devices/{id} (external-visible; /plugins/{id} is "
        "the HC3's local-only family, covered by the helper-backed shape probes)",
        [
            Step(
                "create",
                "POST",
                "/quickApp/",
                sim_body={"name": "{prefix}_qa", "type": "com.fibaro.binarySwitch"},
                live_fqa=True,
                extract={"id": "id"},
            ),
            Step("read", "GET", "/devices/{create.id}"),
            Step(
                "updateProperty",
                "POST",
                "/plugins/updateProperty",
                {
                    "deviceId": "{create.id}",
                    "propertyName": "userDescription",
                    "value": "flua parity probe",
                },
            ),
            Step("read_property", "GET", "/devices/{create.id}/properties/userDescription"),
            Step("delete", "DELETE", "/devices/{create.id}"),
        ],
    ),
]


SEQUENCES_BY_ID: dict[str, Sequence] = {sequence.id: sequence for sequence in SEQUENCES}


def _substitute(match: re.Match[str], bindings: dict[str, Any], prefix: str) -> str:
    key, field = match.group(1), match.group(2)
    if key == "prefix":
        return prefix
    if field is None:
        return str(bindings.get(key, match.group(0)))
    return str(bindings.get(f"{key}.{field}", match.group(0)))


def _resolve(value: Any, bindings: dict[str, Any], prefix: str) -> Any:
    if isinstance(value, str):
        return _TEMPLATE.sub(lambda m: _substitute(m, bindings, prefix), value)
    if isinstance(value, dict):
        return {key: _resolve(val, bindings, prefix) for key, val in value.items()}
    if isinstance(value, list):
        return [_resolve(val, bindings, prefix) for val in value]
    return value


def run_sequence(
    backend: Backend,
    sequence: Sequence,
    prefix: str,
    fqa_builder: Any = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Execute a sequence against one side. Returns (records, bindings);
    records are the capture/replay unit: per step {step, path, status,
    shape} with concrete paths and normalized shapes (no ids)."""
    bindings: dict[str, Any] = {}
    records: list[dict] = []
    for step in sequence.steps:
        path = _resolve(step.path, bindings, prefix)
        if "{" in path:
            raise ValueError(
                f"{sequence.id}/{step.id}: unresolved template in path {path!r} "
                f"(bindings: {sorted(bindings)})"
            )
        if step.live_fqa and not backend.is_sim:
            if fqa_builder is None:
                raise ValueError(f"{sequence.id}/{step.id}: live_fqa step needs a fqa builder")
            body = fqa_builder(prefix)
        else:
            body = step.sim_body if (backend.is_sim and step.sim_body is not None) else step.body
            body = _resolve(body, bindings, prefix)
        data, status = backend.call(step.method, path, body)
        record: dict = {"step": step.id, "path": path, "status": status, "shape": None}
        if 200 <= status < 300 and data is not None:
            record["shape"] = shape(data)
        records.append(record)
        if step.extract:
            if isinstance(data, dict):
                for field, binding in step.extract.items():
                    value = data.get(field)
                    if value is not None:
                        bindings[f"{step.id}.{binding}"] = value
            elif isinstance(data, int) and len(step.extract) == 1:
                # the HC3's POST /quickApp can answer with a bare id
                binding = next(iter(step.extract.values()))
                bindings[f"{step.id}.{binding}"] = data
    return records, bindings


@dataclass(frozen=True)
class Artifact:
    kind: str  # device | customEvent | globalVariable
    ref: str  # device id or event/variable name
    seq: int  # creation order


class ArtifactTracker:
    """Session-scoped registry of created artifacts; teardown deletes them
    LIFO. 404 during teardown counts as already-gone (idempotent)."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self._artifacts: list[Artifact] = []

    def add(self, kind: str, ref: Any) -> None:
        self._artifacts.append(Artifact(kind, str(ref), len(self._artifacts)))

    def teardown(self, backend: Backend) -> tuple[list[str], list[str]]:
        deleted: list[str] = []
        failed: list[str] = []
        for artifact in reversed(self._artifacts):
            path = {
                "device": f"/devices/{artifact.ref}",
                "customEvent": f"/customEvents/{artifact.ref}",
                "globalVariable": f"/globalVariables/{artifact.ref}",
            }[artifact.kind]
            _data, status = backend.call("DELETE", path)
            if status in (200, 202, 204, 404):
                deleted.append(f"{artifact.kind} {artifact.ref}")
            else:
                failed.append(f"{artifact.kind} {artifact.ref} (HTTP {status})")
        return deleted, failed
