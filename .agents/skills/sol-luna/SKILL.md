---
name: sol-luna
description: "Run an explicit, evidence-driven Sol-Luna delivery workflow that predicts whether bounded Luna execution will reduce accepted-result credits and elapsed time without lowering quality. Use only when the user invokes $sol-luna; SOL_ONLY remains valid."
---

# Sol-Luna Delivery System

Sol is accountable; Luna executes or reviews bounded work. Optimize Luna's **net substitution of expensive Sol work**, not activity counts or raw tokens.

Quality and safety are hard gates. Among accepted routes, minimize included-plan allowance before elapsed time, counting planning through integration. Purchased-credit estimates never replace matched five-hour readings. Invocation authorizes only task-scoped delegation.

## Decide before dispatch

Choose and record `SOL_ONLY` or `SOL_LUNA` before the first worker. Do not delegate when estimates are missing or coordination and recovery erase the saving.

For a material package, read [references/orchestration-policy.md](references/orchestration-policy.md), create an explicit estimate, and use:

```text
python .agents/skills/sol-luna/scripts/net_substitution.py evaluate --input ALLOCATION.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input ROUTE.json
```

For multi-package work, `net_substitution.py` enumerates bounded allocations, context reuse, and incremental Sol work. Encode its allocation in `ROUTE.json`; the [routing policy](references/routing-policy.v1.json) checks effort, quality, cost, and time. Advisory only. Unknowns retain work in Sol or justify a read-only scout. Schema 7 enforces a task-coupling effort floor; schema 6 keeps external quality binding, and schema 5 is compatibility-only.

## Select Luna effort predictively

Choose the lowest expected accepted-delivery cost among efforts passing every quality, defect, savings, and latency gate; a failed cheap attempt is not required first.

Start with the lowest evidence-supported effort. High+ Luna critical-path work needs a same-allocation Low/Medium candidate rejected by a quality or defect gate; prose is insufficient.

- `luna_worker_low`: mechanical work with cheap authoritative verification (`light` maps to `low`).
- `luna_worker_medium`: bounded implementation with settled architecture.
- `luna_worker_high`: complex logic or substantial edge cases.
- `luna_worker_xhigh`: difficult debugging, shared interfaces, or costly failure.
- `luna_worker_max`: exceptional reasoning that decomposition cannot simplify.

Use `luna_reviewer` for read-only review and `luna_scout` for feasibility. Never silently substitute another model family; disclose an exact-effort `gpt-5.6-luna` fallback.

## Bound packages and concurrency

Packages bind root, dependencies, exclusive paths, Sol-reserved files, acceptance, forbidden actions, and handoff. Prefer ready Luna leaves with deterministic checks; keep coupled cores in Sol. One stable-domain envelope freezes boundaries while Luna closes out; Sol does not pre-script Luna's internal units. Writers never overlap.
For material work, freeze a few acceptance-bound Luna responsibility units. They are accounting boundaries inside one retained context, not extra workers or handoffs. Use one only when indivisible; replay shadows only the affected unit.

Before dispatch, run `scripts/ownership_guard.py check-plan`; schema 2 binds executors, units, acceptances, partitions, and digest, while schema 1 is compatibility-only. Before acceptance, compare changed paths with `check-changes`. Violations block acceptance. This is not a filesystem security boundary.

Calls, packages, actions, and writer count never enter the benefit numerator. Default to **one active Luna writer**; reuse it until the domain, assumptions, or independence need changes. Add a writer only when its marginal net substitution is positive. Freeze one executor per unit. Reserve a disjoint Sol acceptance/integration lane. Sol never shadow-implements Luna work; wait only when controller queues are empty.

Give Luna only the context required for its objective, contracts, evidence, and constraints. Luna must not spawn agents. Before the first material handoff, Luna runs acceptance and relevant schema, boundary, capacity, derived-value, immutability, and error probes bound to the candidate; structured handoffs use `scripts/handoff_preflight.py`. `HOLD` is incomplete, not permission for Sol replay. Sol reviews from this evidence and returns only exact new failures to the same Luna. Shared entry points, lock/status files, and common outputs stay with Sol or one integrator.

## Review, repair, and finish

Luna's handoff is a claim. Sol assigns risk-proportional review before acceptance:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py review --input REVIEW.json
```

Use targeted review for clean low-risk work, standard review normally, and deep review for shared interfaces, risk, discrepancies, failures, or repair. Run the smallest authoritative checks.

Freeze a route-independent repair cap by acceptance claim or baseline weight. Return failures to the same Luna with new evidence while the shared cost cap, three-attempt ceiling, and positive marginal net substitution remain. Do not use a one-repair cutoff. Sol acceptance is read-only; its Luna-scope edit is an explicit replay or reclaim. Otherwise repartition, escalate once, or reclaim the affected unit:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py rework --input REWORK.json
```

Never repeat the same correction without new evidence. Stop for user direction when the next action requires new authority, a product or architecture decision, destructive action, or expanded scope. Use `FAILED` for in-scope delivery failure and `BLOCKED` only for a missing external decision, input, permission, authority, or state change.

Before completion, Sol verifies the candidate, identities, fresh acceptance, ownership, and dispositions. Repeated implementation shadows the affected responsibility unit. Use the lower of `actual_sol_labor_reduction` and `structural_net_substitution`. A common independent referee runs outside both route intervals; Luna-specific review, integration, replay, and rework remain inside `SOL_LUNA`. Report costs, quality, elapsed time, plan readings, and uncertainty.

## Conditional tools
- For runtime identity or boundary compliance, read [references/evidence-and-runtime.md](references/evidence-and-runtime.md) and use `scripts/runtime_receipt.py` against one explicitly identified session. Self-report is not proof.
- For persistent phase evidence or routing comparisons, use `scripts/evidence_ledger.py`; its `feedback` command converts exact task-family cohorts into a fail-closed policy posture. Self-declared `exact` credit is insufficient: the gate also requires an independently supplied claim index bound to each record and receipt. It is advisory and never routes automatically.
- For phase evidence, use schema-2 `scripts/phase_tracker.py` with executor IDs; it reports execution unions and cross-actor overlap, excludes review, and keeps legacy journals read-only.
- For one-envelope Luna delivery, freeze and assess the schema-2 candidate-bound handoff and baseline-weighted Sol replay claims with `scripts/delegation_contract.py`; these estimates measure structural substitution, not actual plan allowance, and never replace independent acceptance.
- For a same-Luna implementation and repair loop with a non-overlapping Sol acceptance lane, use `scripts/closure_contract.py`; `project` returns the next legal event and exact repair targets. For a validated multi-package snapshot, `scripts/frontier_cli.py` projects sorted queues and one repair-first retained-domain Luna envelope. Both are replay-only and never dispatch work.
- For predictive net substitution, use `scripts/net_substitution.py`; participation counts never create benefit, and the tool never launches work or authorizes routing automatically.
- For matched Sol-only versus Sol-Luna evaluation, use `scripts/matched_eval.py` with the same starting commit, task digest, policy fingerprint, and independent acceptance-suite digest.
- For a subscription-allowance benchmark, read [references/allowance-benchmark.md](references/allowance-benchmark.md), record route-only intervals with `scripts/allowance_campaign.py`, bind host receipts with `scripts/benchmark_identity.py`, and assess the retained dashboard readings with `scripts/allowance_meter.py`. Five-hour percentage points are primary; weekly percentage points are separate corroboration.
- After a completed allowance campaign has a verified identity index and frozen benchmark contract, use `scripts/benchmark_attestation.py` to emit one deterministic, redacted structural attestation; it does not decide the economic threshold.
- For a secondary purchased-credit estimate only, use `scripts/credit_model.py` with a current fingerprinted rate card and complete classified phase usage. It cannot convert included plan percentages or authorize routing.
- For package state transitions or stale-evidence checks, use `scripts/lifecycle_contract.py`; simulated transitions are not native runtime proof.
- For opt-in native lifecycle acceptance, validate a host-produced receipt with `scripts/native_lifecycle_receipt.py`; requested settings or worker prose without matching host-observed identity, boundary, profile, and child continuity fail proof.
- For detailed ownership, rolling-pipeline, review, and evidence contracts, read [references/orchestration-policy.md](references/orchestration-policy.md).

Do not commit, push, deploy, install dependencies, delete data, or contact external systems unless the underlying user request separately authorizes that exact action.
