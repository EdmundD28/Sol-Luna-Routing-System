---
name: sol-luna
description: "Run an explicit, evidence-driven Sol-Luna delivery workflow that predicts whether bounded Luna execution will reduce accepted-result credits and elapsed time without lowering quality. Use only when the user invokes $sol-luna; SOL_ONLY remains valid."
---

# Sol-Luna Delivery System

Sol is accountable; Luna executes or independently reviews bounded packages. Optimize Luna's **net substitution of expensive Sol work**, not attempts, calls, packages, concurrency, or raw tokens.

Quality and safety are hard gates. Among equally accepted routes, minimize included-plan allowance before elapsed time, counting planning through integration. Purchased-credit estimates never replace matched five-hour readings. Invocation authorizes only task-scoped delegation.

## Decide before dispatch

Choose and record `SOL_ONLY` or `SOL_LUNA` before the first worker. Do not delegate when estimates are missing or coordination and recovery erase the saving.

For a material package, read [references/orchestration-policy.md](references/orchestration-policy.md), create an explicit estimate, and use:

```text
python .agents/skills/sol-luna/scripts/net_substitution.py evaluate --input ALLOCATION.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input ROUTE.json
```

For multi-package work, `scripts/net_substitution.py` enumerates bounded allocations and writer counts, including context reuse and incremental Sol work. Encode its chosen allocation in `ROUTE.json`; the versioned [routing policy](references/routing-policy.v1.json) checks effort, quality, cost, and time. Overlap saves time, not cost. Both are advisory and never prove subscription economics. Unknowns retain work in Sol or justify a read-only `luna_scout` probe.

## Select Luna effort predictively

Choose the initial effort with the lowest expected accepted-delivery credits among candidates that pass every quality, defect, savings, and latency gate. A failed cheaper attempt is not required before selecting a stronger tier.

Start from the lowest effort that concrete task evidence can support. High or above needs an explicit reason that Low or Medium is unlikely to meet the same acceptance contract; do not use High merely because the parent Sol uses High.

- `luna_worker_low`: mechanical and deterministic work with cheap authoritative verification. The user-facing word `light` maps to Codex `low`.
- `luna_worker_medium`: clear bounded implementation with established architecture.
- `luna_worker_high`: complex logic, assumptions, or substantial edge cases.
- `luna_worker_xhigh`: difficult debugging, shared interfaces, ambiguity, or costly failure.
- `luna_worker_max`: exceptional reasoning-heavy work that decomposition cannot simplify.

Use `luna_reviewer` for read-only review and `luna_scout` for bounded feasibility. Do not silently substitute another model family. If a profile is unavailable, request `gpt-5.6-luna` with the exact effort, preserve the sandbox, and disclose the fallback.

## Bound packages and concurrency

Every package binds the repository root, deliverable, dependencies, exclusive relative write paths, Sol-reserved files, acceptance, forbidden actions, and compact handoff. For a stable-domain envelope, Sol freezes those constraints while one Luna decomposes, implements, preflights, and closes out; Sol does not pre-script Luna's internal units. Redact private roots from public receipts. Writers never overlap; handoff freezes ownership until repair.

Before dispatch, run `scripts/ownership_guard.py check-plan`; schema 2 binds executors, units, acceptances, partitions, and digest, while schema 1 is compatibility-only. Before acceptance, compare changed paths with `check-changes`. Violations block acceptance. This is not a filesystem security boundary.

Separate accepted Luna substitution from active concurrency. Calls, packages, actions, and writer count never enter the benefit numerator. Default to **one active Luna writer** and reuse it across adjacent packages only while the domain and assumptions remain stable; switch when the domain, assumptions, or independence need changes. Add a writer only when policy permits it and its marginal net substitution is positive. Freeze one complete allocation with one executor per unit. Sol may advance disjoint valuable work but never shadow-implements Luna work or invents work to create overlap. Waiting is allowed only after the controller queues are explicitly empty.

Give Luna only the context required for its objective, contracts, evidence, and constraints. Luna must not spawn agents. Shared entry points, lockfiles, status files, and common generated outputs stay with Sol or one named integrator.

## Review, repair, and finish

Luna's handoff is a claim. Sol assigns risk-proportional review before acceptance:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py review --input REVIEW.json
```

Use targeted review for clean low-risk work, standard review for ordinary packages, and deep review for shared interfaces, safety impact, discrepancies, failures, nondeterminism, or repair. Run the smallest authoritative checks; do not replay a clean investigation.

Freeze a route-independent repair cap by acceptance claim or baseline weight before dispatch. Splitting work into more packages never creates more repair authority. Permit a focused evidence-backed repair only while that shared cap and positive marginal saving remain; otherwise repartition, escalate once, or let Sol reclaim the affected claim:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py rework --input REWORK.json
```

Never repeat the same correction without new evidence. Stop for user direction when the next action requires new authority, a product or architecture decision, destructive action, or expanded scope. Use `FAILED` for in-scope delivery failure and `BLOCKED` only for a missing external decision, input, permission, authority, or state change.

Before completion, Sol verifies the candidate, host-observed identities, fresh acceptance, ownership, integration, and dispositions. Repeated implementation is shadow work; subtract the whole affected baseline claim. Audit `actual_sol_labor_reduction` and `structural_net_substitution`, using the lower result. A common independent referee runs outside both route intervals, while Luna-specific review, integration, replay, and rework remain inside `SOL_LUNA`. Report both metrics, route costs, acceptance, elapsed time, plan readings, uncertainty, and boundaries.

## Conditional tools

- For runtime identity or boundary compliance, read [references/evidence-and-runtime.md](references/evidence-and-runtime.md) and use `scripts/runtime_receipt.py` against one explicitly identified session. Self-report is not proof.
- For persistent phase evidence or routing comparisons, use `scripts/evidence_ledger.py`; its `feedback` command converts exact task-family cohorts into a fail-closed policy posture. Self-declared `exact` credit is insufficient: the gate also requires an independently supplied claim index bound to each record and receipt. It is advisory and never routes automatically.
- For phase evidence, use schema-2 `scripts/phase_tracker.py` with executor IDs; it reports execution unions and cross-actor overlap, excludes review, and keeps legacy journals read-only.
- For one-envelope Luna delivery, freeze and assess the schema-2 candidate-bound handoff and baseline-weighted Sol replay claims with `scripts/delegation_contract.py`; these estimates measure structural substitution, not actual plan allowance, and never replace independent acceptance.
- For predictive net substitution, use `scripts/net_substitution.py`; participation counts never create benefit, and the tool never launches work or authorizes routing automatically.
- For matched Sol-only versus Sol-Luna evaluation, use `scripts/matched_eval.py` with the same starting commit, task digest, policy fingerprint, and independent acceptance-suite digest.
- For a subscription-allowance benchmark, read [references/allowance-benchmark.md](references/allowance-benchmark.md), record route-only intervals with `scripts/allowance_campaign.py`, bind host receipts with `scripts/benchmark_identity.py`, and assess the retained dashboard readings with `scripts/allowance_meter.py`. Five-hour percentage points are primary; weekly percentage points are separate corroboration.
- After a completed allowance campaign has a verified identity index and frozen benchmark contract, use `scripts/benchmark_attestation.py` to emit one deterministic, redacted structural attestation; it does not decide the economic threshold.
- For a secondary purchased-credit estimate only, use `scripts/credit_model.py` with a current fingerprinted rate card and complete classified phase usage. It cannot convert included plan percentages or authorize routing.
- For package state transitions or stale-evidence checks, use `scripts/lifecycle_contract.py`; simulated transitions are not native runtime proof.
- For opt-in native lifecycle acceptance, validate a host-produced receipt with `scripts/native_lifecycle_receipt.py`; requested settings or worker prose without matching host-observed identity, boundary, profile, and child continuity fail proof.
- For detailed ownership, rolling-pipeline, review, and evidence contracts, read [references/orchestration-policy.md](references/orchestration-policy.md).

Do not commit, push, deploy, install dependencies, delete data, or contact external systems unless the underlying user request separately authorizes that exact action.
