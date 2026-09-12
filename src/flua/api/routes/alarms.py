"""Alarm partitions (hc3-rest-api misc.md, alarms section).

The sim auto-creates partition 1 ("Home") like the real HC3 unless the
seed defines partitions. Arm/disarm accepts both shapes fibaro.lua uses:
per-partition (/partitions/{id}/actions/arm) and all-partitions
(/partitions/actions/arm).
"""

from __future__ import annotations

from typing import Any

from ..request import ApiRequest
from ..state import SimState, public


def partitions_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    partitions = sorted(state.alarms.values(), key=lambda p: p["id"])
    return public(partitions), 200


def partitions_breached(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    breached = sorted(
        (p for p in state.alarms.values() if p.get("breached")),
        key=lambda p: p["id"],
    )
    return public(breached), 200


def partition_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    partition = state.partition(req.path_params["id"])
    return (public(partition), 200) if partition is not None else (None, 404)


def partition_arm(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    partition = state.partition(req.path_params["id"])
    if partition is None:
        return None, 404
    partition["armed"] = True
    partition["breached"] = False
    return None, 202


def partition_disarm(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    partition = state.partition(req.path_params["id"])
    if partition is None:
        return None, 404
    partition["armed"] = False
    return None, 202


def partitions_arm_all(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    for partition in state.alarms.values():
        partition["armed"] = True
        partition["breached"] = False
    return None, 202


def partitions_disarm_all(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    for partition in state.alarms.values():
        partition["armed"] = False
    return None, 202
