---
name: sol-luna
description: "Run an explicit, evidence-driven Sol-Luna delivery workflow that predicts whether bounded Luna execution will reduce accepted-result credits and elapsed time without lowering quality. Use only when the user invokes $sol-luna; SOL_ONLY remains valid."
---

# Sol-Luna Delivery System

Sol is accountable; Luna executes bounded work. Optimize Luna's **net substitution of expensive Sol work**, not activity, calls, workers, or raw tokens. Quality and safety are hard gates; among accepted routes, minimize included-plan allowance before elapsed time. Purchased-credit estimates never replace matched five-hour readings.

## Route before dispatch

Record `SOL_ONLY` or `SOL_LUNA` before the first worker. For material work, read [references/orchestration-policy.md](references/orchestration-policy.md), estimate the complete task, and run:

```text
python .agents/skills/sol-luna/scripts/net_substitution.py evaluate --input ALLOCATION.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input ROUTE.json
```

The versioned [routing policy](references/routing-policy.v1.json) checks effort, quality, cost, and time but never dispatches automatically. Unknowns retain work in Sol or justify a bounded read-only scout.

Always evaluate one complete-Luna envelope when ownership, authority, and deterministic acceptance allow it. Compare that candidate with mixed allocations and `SOL_ONLY`; do not retain Sol implementation merely to keep Sol busy or manufacture overlap. Sol implementation is justified only when the complete-Luna candidate fails a concrete quality, defect, authority, cost, or time gate. Calibrate Sol planning, coordination, review, integration, and replay from observed controller evidence when available, not optimistic prose.

## Select Luna effort

Choose the lowest expected accepted-delivery cost among efforts passing every gate; a failed cheap attempt is not required first. Start at the lowest evidence-supported effort. High+ critical-path work needs a same-allocation lower-effort candidate rejected by a quality or defect gate.

- `luna_worker_low`: mechanical work with cheap authoritative verification (`light` maps to `low`).
- `luna_worker_medium`: bounded implementation with settled architecture.
- `luna_worker_high`: complex logic or substantial edge cases.
- `luna_worker_xhigh`: difficult debugging, shared interfaces, or costly failure.
- `luna_worker_max`: exceptional reasoning that decomposition cannot simplify.

Use `luna_reviewer` for independent review and `luna_scout` for feasibility. Never silently substitute another model family; disclose an exact-effort `gpt-5.6-luna` fallback.

## Freeze one economical envelope

Bind repository root, dependencies, exclusive paths, acceptance IDs, forbidden actions, stop conditions, and one executor per responsibility unit. Production ownership is schema 2; schema 1 is compatibility-only. Validate material plans and changed paths with `scripts/ownership_guard.py`. Writers never overlap.

Default to one active Luna writer and reuse it until the domain, assumptions, or independence need changes. Add a writer only when its marginal net substitution is positive. Calls, packages, actions, and writer count never enter the benefit numerator. Sol does not pre-script Luna's internal units and never shadow-implements Luna work.

For a complete-Luna envelope, Luna owns implementation, integration edits, tests, documentation, and its repair loop. Sol has a read-only acceptance lane: prepare the smallest risk checklist while Luna works, then check ownership, exact changed paths, specified acceptance, and focused diff risk. Waiting is cheaper than inventing Sol implementation when no useful acceptance work remains.

Give Luna only the objective, required interfaces, ownership, acceptance, forbidden actions, and evidence it actually needs. Reference frozen material instead of repeating it. Luna must not spawn agents. A structured first handoff may use `scripts/handoff_preflight.py`; `HOLD` remains incomplete. Normal success returns a compact receipt, while failures, conflicts, or material semantic uncertainty may expand.

## Review, repair, and finish

Use targeted review for clean low-risk work, standard review for ordinary bounded work, and deep review only for shared interfaces, high risk, discrepancy, nondeterminism, failure, or repair. Run the smallest authoritative checks; do not reread or rederive the whole task by default.

Freeze a route-independent repair cap by acceptance claim or baseline weight. Return only exact new failures and changed boundaries to the same Luna while the cap and positive net substitution remain. Sol acceptance is read-only; its Luna-scope edit is a declared replay or reclaim. Repeated implementation shadows the affected responsibility unit. Otherwise repartition, escalate once, or reclaim only the affected unit.

Before completion, Sol verifies the final candidate, identities, fresh acceptance, ownership, and dispositions. A common independent referee runs outside both route intervals; Luna-specific review, integration, replay, and rework remain inside `SOL_LUNA`. Report quality, included-plan readings, elapsed time, Sol rewrites/reclaims, and uncertainty; keep legacy journals read-only.

For a complete-Luna package, the same Luna runs targeted checks during implementation and one full authoritative suite on the final candidate; Sol verifies the candidate snapshot and causal coverage instead of repeating the full suite by default.
Sol reruns only the smallest triggered check for candidate drift, incomplete evidence, nondeterminism, failure, repair, or material security/platform risk; if Luna cannot access the authoritative environment, Luna performs causal/targeted checks and Sol runs that environment once.

## Optional diagnostics

Use these only when their evidence question exists, not on every successful dispatch. Runtime and billing trust boundaries: [references/evidence-and-runtime.md](references/evidence-and-runtime.md), `scripts/runtime_receipt.py`, `scripts/evidence_ledger.py`, `scripts/phase_tracker.py`. Envelope and lifecycle diagnostics: `scripts/delegation_contract.py` for a schema-2 candidate-bound handoff, `scripts/closure_contract.py`, `scripts/lifecycle_contract.py`, `scripts/native_lifecycle_receipt.py`. Matched experiments: `scripts/matched_eval.py`. A persistent ledger needs an independently supplied claim index bound to each record and receipt; diagnostic credits or tokens cannot convert included-plan percentages.

Do not commit, push, deploy, install dependencies, delete data, or contact external systems unless the underlying user request separately authorizes that action.
