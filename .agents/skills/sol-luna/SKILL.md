---
name: sol-luna
description: "Run an explicit, evidence-driven Sol-Luna delivery workflow that predicts whether bounded Luna execution will reduce accepted-result credits and elapsed time without lowering quality. Use only when the user invokes $sol-luna; SOL_ONLY remains valid."
---

# Sol-Luna Delivery System

Sol is the accountable controller. Luna executes or independently reviews bounded packages. Optimize the **accepted result**, not the first attempt, worker count, or raw token total.

Quality and safety are hard gates. Among routes that satisfy the same independent acceptance contract and do not increase predicted final defects, minimize the user's included plan allowance first and elapsed time second, including Sol planning, Luna work, review, repair, and integration. Purchased-credit estimates may guide planning but cannot replace matched five-hour plan-limit readings in a completed economic claim. Invocation authorizes subagent delegation only for this task; it does not broaden filesystem, network, destructive-action, deployment, or approval authority.

## Decide before dispatch

Choose and record `SOL_ONLY` or `SOL_LUNA` before the first worker. Do not delegate when estimates are missing, the work is tightly coupled, or coordination and expected recovery erase the saving.

For a material package, read [references/orchestration-policy.md](references/orchestration-policy.md), create an explicit estimate, and use:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input ROUTE.json
```

The versioned [routing policy](references/routing-policy.v1.json) accounts for Sol-only execution, Sol planning, retained execution, review, integration, each Luna effort's first-pass probability, execution, expected recovery, final-defect probability, latency, and a default 50% accepted-cost saving floor. Retained Sol work overlaps Luna time but never disappears from cost. The policy never launches work. This prediction is a feasibility guard, not proof about a subscription meter. If inputs cannot be estimated from matched history or concrete task evidence, retain the work in Sol or run a short read-only `luna_scout` feasibility probe.

## Select Luna effort predictively

Choose the initial effort with the lowest expected accepted-delivery credits among candidates that pass every quality, defect, savings, and latency gate. A failed cheaper attempt is not required before selecting a stronger tier.

Start from the lowest effort that concrete task evidence can support. High or above needs an explicit reason that Low or Medium is unlikely to meet the same acceptance contract; do not use High merely because the parent Sol uses High.

- `luna_worker_low`: mechanical and deterministic work with cheap authoritative verification. The user-facing word `light` maps to Codex `low`.
- `luna_worker_medium`: clear bounded implementation with established architecture.
- `luna_worker_high`: complex logic, assumptions, or substantial edge cases.
- `luna_worker_xhigh`: difficult debugging, shared interfaces, ambiguity, or costly failure.
- `luna_worker_max`: exceptional reasoning-heavy work that decomposition cannot simplify.

Use `luna_reviewer` for independent read-only review and `luna_scout` only for a strictly bounded feasibility probe. Keep this a Sol-Luna system; do not substitute Terra or another model family silently. If an effort-specific custom agent is unavailable, request `gpt-5.6-luna` and that exact reasoning effort explicitly, preserve the same sandbox, and disclose the fallback.

## Bound packages and concurrency

Every package binds a canonical repository root, then states one deliverable, readiness dependencies, repository-root-relative exclusive writable paths, read-only dependencies, shared files reserved to Sol, acceptance checks, forbidden actions, and a compact evidence handoff. Give the worker the root explicitly when the checkout is nested; never assume the child's current directory. Redact private absolute roots from publishable receipts. Two active writers must never have overlapping ownership. Handoff freezes the owned candidate until Sol opens a repair package.

Before parallel dispatch, validate the ownership plan with `scripts/ownership_guard.py check-plan`; before acceptance, compare observed changed paths with `check-changes`. A violation blocks acceptance. This is an acceptance guard, not a filesystem security boundary.

Default to **one Luna writer**. Sol receives the complete user task, keeps architecture, integration, and a complementary Sol-owned critical-path slice, and delegates only one high-leverage bounded package; do not manufacture two Sol packages or keep Sol idle merely to make the comparison look parallel. A second Luna writer is benchmark-only until matched plan-meter evidence proves equal quality, lower allowance use, and lower elapsed time, followed by an explicit policy release. Read-only review may overlap when it cannot race the candidate.

Give Luna only the context required for its objective, contracts, evidence, and constraints. Luna must not spawn agents. Shared entry points, lockfiles, status files, and common generated outputs stay with Sol or one named integrator.

## Review, repair, and finish

Luna's handoff is a claim. Sol assigns risk-proportional review before acceptance:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py review --input REVIEW.json
```

Use targeted review for clean low-risk work, standard review for ordinary packages, and deep review for shared interfaces, security/safety impact, scope discrepancies, failed checks, nondeterministic acceptance, high risk, or repaired work. Sol independently runs the smallest authoritative checks appropriate to that depth; it does not blindly repeat a clean investigation.

The rework budget is one focused evidence-backed repair, then repartition, one effort escalation, or Sol reclaim:

```text
python .agents/skills/sol-luna/scripts/routing_policy.py rework --input REWORK.json
```

Never repeat the same correction without new evidence. Stop for user direction when the next action requires new authority, a product or architecture decision, destructive action, or expanded scope. Use `FAILED` for in-scope delivery failure and `BLOCKED` only for a missing external decision, input, permission, authority, or state change.

Before completion, Sol verifies the exact final candidate, host-observed Sol/Luna model identity, fresh acceptance evidence, ownership cleanliness, integration behavior, and every required package disposition. Agent or profile labels are not runtime proof. Report route and effort decisions, policy fingerprint, Sol/Luna ownership, retained Sol execution, concurrency, repairs, review depth, acceptance results, elapsed time, five-hour and weekly allowance readings when measured, available purchased-credit or token diagnostics with source and uncertainty, and remaining unverified boundaries.

## Conditional tools

- For runtime identity or boundary compliance, read [references/evidence-and-runtime.md](references/evidence-and-runtime.md) and use `scripts/runtime_receipt.py` against one explicitly identified session. Self-report is not proof.
- For persistent phase evidence or routing comparisons, use `scripts/evidence_ledger.py`; its `feedback` command converts exact task-family cohorts into a fail-closed policy posture. Self-declared `exact` credit is insufficient: the gate also requires an independently supplied claim index bound to each record and receipt. It is advisory and never routes automatically.
- For automatic phase-duration accumulation and optional source readings, use `scripts/phase_tracker.py`; overlapping active-phase totals are not wall-clock duration.
- For matched Sol-only versus Sol-Luna evaluation, use `scripts/matched_eval.py` with the same starting commit, task digest, policy fingerprint, and independent acceptance-suite digest.
- For a subscription-allowance benchmark, read [references/allowance-benchmark.md](references/allowance-benchmark.md), record route-only intervals with `scripts/allowance_campaign.py`, bind host receipts with `scripts/benchmark_identity.py`, and assess the retained dashboard readings with `scripts/allowance_meter.py`. Five-hour percentage points are primary; weekly percentage points are separate corroboration.
- After a completed allowance campaign has a verified identity index and frozen benchmark contract, use `scripts/benchmark_attestation.py` to emit one deterministic, redacted structural attestation; it does not decide the economic threshold.
- For a secondary purchased-credit estimate only, use `scripts/credit_model.py` with a current fingerprinted rate card and complete classified phase usage. It cannot convert included plan percentages or authorize routing.
- For package state transitions or stale-evidence checks, use `scripts/lifecycle_contract.py`; simulated transitions are not native runtime proof.
- For opt-in native lifecycle acceptance, validate a host-produced receipt with `scripts/native_lifecycle_receipt.py`; requested settings or worker prose without matching host-observed identity, boundary, profile, and child continuity fail proof.
- For detailed ownership, rolling-pipeline, review, and evidence contracts, read [references/orchestration-policy.md](references/orchestration-policy.md).

Do not commit, push, deploy, install dependencies, delete data, or contact external systems unless the underlying user request separately authorizes that exact action.
