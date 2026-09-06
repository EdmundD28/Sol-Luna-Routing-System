from typing import Iterable
import math

from ..errors import WorkbenchError
from .models import CaseResult, Regression, ResultSnapshot


def _err(code, path, message, details=None):
    raise WorkbenchError(code, tuple(path), message, details)


def normalize_result(raw: CaseResult | dict, index: int = 0) -> CaseResult:
    base = ("results", index)
    if isinstance(raw, CaseResult): return CaseResult(raw.case_id, raw.attempt, raw.status, raw.duration_ms, raw.finished_at)
    if not isinstance(raw, dict): _err("INVALID_RESULT", base, "result must be object")
    for key in raw:
        if key not in ("case_id", "attempt", "status", "duration_ms", "finished_at"):
            _err("UNKNOWN_FIELD", base + (key,), "unknown field")
    for key in ("case_id", "attempt", "status", "duration_ms", "finished_at"):
        if key not in raw: _err("MISSING_FIELD", base + (key,), "missing field")
    if not isinstance(raw["case_id"], str) or not raw["case_id"]: _err("INVALID_CASE_ID", base + ("case_id",), "invalid case id")
    if isinstance(raw["attempt"], bool) or not isinstance(raw["attempt"], int) or raw["attempt"] <= 0: _err("INVALID_ATTEMPT", base + ("attempt",), "attempt must be positive integer")
    if raw["status"] not in ("pass", "fail", "error", "skip"): _err("INVALID_STATUS", base + ("status",), "invalid status")
    duration = raw["duration_ms"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0: _err("INVALID_DURATION", base + ("duration_ms",), "invalid duration")
    if not isinstance(raw["finished_at"], str) or not raw["finished_at"]: _err("INVALID_FINISHED_AT", base + ("finished_at",), "invalid timestamp")
    return CaseResult(raw["case_id"], raw["attempt"], raw["status"], duration, raw["finished_at"])


def aggregate_results(raw_results: Iterable[CaseResult | dict]) -> ResultSnapshot:
    try: items = list(raw_results)
    except TypeError: _err("INVALID_RESULTS", ("results",), "results must be iterable")
    selected = {}
    for i, raw in enumerate(items):
        item = normalize_result(raw, i)
        key = (item.case_id, item.attempt, item.finished_at)
        if key in selected:
            if selected[key] != item: _err("DUPLICATE_ATTEMPT", ("results", i), "conflicting attempt")
            continue
        selected[key] = item
    cases_by_id = {}
    for item in selected.values():
        old = cases_by_id.get(item.case_id)
        if old is None or (item.attempt, item.finished_at) > (old.attempt, old.finished_at): cases_by_id[item.case_id] = item
    cases = tuple(cases_by_id[k] for k in sorted(cases_by_id))
    counts = {status: sum(c.status == status for c in cases) for status in ("pass", "fail", "error", "skip")}
    return ResultSnapshot(cases, counts, sum((c.duration_ms for c in cases), 0))


def compare_snapshots(before: ResultSnapshot, after: ResultSnapshot) -> tuple[Regression, ...]:
    rank = {"pass": 0, "skip": 1, "fail": 2, "error": 3}
    old = {c.case_id: c for c in before.cases}
    regressions = []
    for current in after.cases:
        previous = old.get(current.case_id)
        if previous is None:
            if current.status in ("fail", "error"):
                regressions.append(Regression(current.case_id, None, current.status, current.duration_ms))
        elif rank[current.status] > rank[previous.status]:
            regressions.append(Regression(current.case_id, previous.status, current.status, current.duration_ms - previous.duration_ms))
    return tuple(sorted(regressions, key=lambda r: r.case_id))
