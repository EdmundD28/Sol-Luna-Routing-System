# Orchestration Policy

Read this reference when constructing a route estimate, dispatching or repairing packages, assigning review depth, or reporting a measured Sol-Luna run.

## Accepted-delivery objective

Apply the decision lexicographically:

1. The route must satisfy the same independent acceptance contract and must not increase predicted final defects.
2. The route must respect authority, ownership, sandbox, and failure-impact constraints.
3. Among eligible routes, maximize Luna's net substitution of expensive Sol work, then minimize expected accepted-result credits.
4. Require no expected elapsed regression; when parallelism is the justification, require an expected improvement.

For one disclosed cost unit, predict `net_substitution = sol_baseline - luna_execution - incremental_sol_planning_and_coordination - risk_proportional_review - integration - expected_replay_and_rework`. Every term must be non-negative, source-labelled, and scoped to the same accepted result. Calls, packages, actions, and concurrent writers never enter the benefit numerator. Expected time counts serial Sol overhead plus the longer of retained Sol execution and Luna execution, then expected recovery; overlap saves wall time but never removes either side's cost. Do not convert token counts, displayed allowance percentages, API dollars, and Codex credits into one another without an authoritative conversion source.

Predictions must name their basis: matched task-family evidence, a bounded feasibility map, or a disclosed estimate. Unknown inputs do not become zero.

## Predictive effort signals

Route lower when requirements are explicit, scope is isolated, acceptance is deterministic, architecture is settled, failure is cheap, and the task family has strong first-pass history. Prefer ready leaf responsibility units with exclusive ownership and cheap deterministic acceptance; keep coupled semantic cores in Sol. Route directly upward when interfaces are shared, debugging is emergent, context dependencies are long, acceptance is subjective, or rollback and review would be expensive. A High-or-above candidate on a Luna-owned critical path needs a same-allocation lower-effort comparator rejected by a quality or defect gate; XHigh may therefore use a failed High comparator and Max may use a failed XHigh comparator. An `effort_basis` sentence alone is not evidence.

Task size and reasoning difficulty are separate. Large repetitive work can suit Low or Medium; a small ambiguous defect can justify XHigh. When uncertainty is material, first repartition, route upward, retain the work in Sol, or run a read-only scout probe that returns `READY`, `NEEDS_REPARTITION`, or `INSUFFICIENT_CONTEXT` without editing.

For a new production route, schema 7 binds every candidate's claimed first-pass and final-defect probabilities to an externally loaded evidence record with the same task family, actual Luna effort, allocation-shape fingerprint, and acceptance-suite digest. It also derives a minimum effort from settled architecture, deterministic acceptance, semantic coupling, cross-module invariants, interface count, adversarial edges, platform-sensitive I/O, and strict serialization. Leaf ownership does not imply easy reasoning: a candidate below this floor is rejected, while High or XHigh still needs its own matching quality evidence and the lower-effort comparator required above. Schema 6 keeps external quality binding without the executable effort floor; schema 5 remains readable for compatibility.

## Package contract

Freeze the complete task allocation before dispatch. Every work unit has exactly one executor (`SOL` or `LUNA`), baseline Sol cost, dependency set, critical-path flag, writable scope, and acceptance IDs. The baseline totals reconcile to the Sol-only estimate, and candidate allocations use the same canonical baseline map. Delegated coverage is the Luna-owned share of baseline Sol cost; accepted coverage subtracts the whole affected claim when Sol replays it. These are routing weights, not authenticated plan-allowance readings, and cannot be inflated by splitting units. Unique acceptance assignment proves structural non-duplication, not semantic equivalence between differently named work; Sol must still reject shadow investigations during review.

Whenever authority, ownership, and deterministic acceptance permit it, the candidate set must include one complete-Luna envelope covering the entire accepted result. Compare it with mixed allocations and `SOL_ONLY`. Do not reserve a Sol implementation unit merely to keep the controller busy, manufacture overlap, or preserve an old topology; reject complete Luna only with an explicit quality, defect, authority, cost, or time gate. When observed controller evidence exists, use it to calibrate Sol planning, coordination, review, integration, and replay instead of defaulting those terms toward zero.

The executable production ownership plan is schema 2 and is frozen before dispatch. Executors have stable IDs and fixed actors; work units and acceptances name their executor directly; every unit and acceptance appears in exactly one executor-consistent partition; and each partition path set is the exact normalized union of its contents. The canonical partition digest is independent of input array order but changes with ownership, executor, or path changes. Schema 1 is compatibility-only and must never be inferred to provide these production guarantees.

Every dispatch contains:

- the canonical repository root observed by Sol at dispatch, with all package paths resolved relative to that root;
- package ID, concrete deliverable, and why it matters;
- readiness dependencies and stable interface assumptions;
- exclusive writable paths and read-only dependencies;
- shared or integration files reserved to Sol;
- observable acceptance commands and expected signals;
- forbidden actions and underlying permission boundary;
- selected effort and the routing receipt that justified it;
- handoff fields: disposition, changed paths or evidence, exact checks and results, ownership observations, risks, blockers, and next action.

Workers preserve user and concurrent changes, never cross ownership, and report a collision instead of editing through it. Generated outputs need unique destinations. A handoff freezes the package candidate until Sol explicitly opens a repair.

Do not infer that the child's default current directory equals the target repository. When a Codex workspace contains a nested checkout, bind the child to the canonical root in the package prompt or use the native workdir mechanism when one is available. Absolute roots may appear in private runtime instructions but must be redacted from committed receipts and public evidence.

## Rolling execution

Maintain `ready`, `awaiting review`, and `approved repair` queues. An approved same-Luna repair occupies the Luna writer frontier before new Luna dispatch; Sol-owned ready work and review may still advance. Dispatch other ready non-conflicting work within the writer cap. While Luna runs, Sol performs only Sol-owned critical-path work: architecture, acceptance design, integration preparation, or review of another frozen candidate. Reuse retained worker context only when it saves more than it biases review.

The normal production shape is one Sol controller plus one active Luna writer. Reuse that Luna across adjacent packages when the domain, interfaces, and assumptions stay stable so retained context amortizes reload cost; switch when the domain, assumptions, or need for independence changes. Add a writer only when the policy cap permits it and the writer's marginal net substitution remains positive after added coordination, review, integration, and recovery. Sol concurrently advances disjoint valuable work, then drains ready-package, review, integration, dispatch, and acceptance queues; it never builds a shadow implementation of Luna-owned work. Every unit is costed once. An all-Luna allocation may record `WAIT_ALLOWED` only when all five controller queue counts are zero.

In a complete-Luna envelope, Sol's useful concurrent lane is read-only acceptance preparation: freeze risk triggers, expected path ownership, and the smallest authoritative checks. It must not inspect the evolving candidate, prewrite integration code, or create replacement work. Once that lane is exhausted, bounded waiting is economically preferable to inventing Sol implementation.

Wait only when no ready package, review, integration preparation, or acceptance work remains. Inspect one compact status snapshot before interrupting a stalled worker; do not turn polling into its own workload.

### Stable-domain delegation envelope

When interfaces, ownership, and acceptance are stable, Sol may freeze one outer envelope instead of pre-scripting every Luna microtask. The envelope fixes writable scope, forbidden actions, acceptance IDs, allocation fingerprint, and final handoff contract. One Luna may then decompose its own internal dependency graph, implement, run deterministic preflight checks, make one bounded pre-handoff correction, and close out within that envelope; later review-driven repairs use the separate frozen rework cap below. Internal units never expand authority or ownership, and the final handoff remains a single frozen candidate.

The first handoff preflight is performed by Luna before Sol review, not reconstructed by Sol afterward. It covers the contract's applicable schema/type, boundary, capacity, derived-value, immutability, and error-channel cases, records exact acceptance and probe results, and binds them to the candidate digest. A structured manifest may be projected with `handoff_preflight.py`; any missing, failed, stale, out-of-scope, or open-risk evidence keeps the handoff at `HOLD`. This reduces review rediscovery but does not replace independent acceptance or authorize automatic acceptance.

The schema-2 handoff binds the candidate digest, exact changed-path union, every acceptance result, internal unit graph, replacement actions, baseline Sol cost claims, residual risks, and closeout state. Material envelopes use a small set of acceptance-bound responsibility units so a replay shadows only the affected unit; one unit is valid only when the work is genuinely indivisible. Sol performs one risk-proportional verification against each exact candidate. Its acceptance lane is read-only and path-disjoint from Luna ownership. If Sol repeats a Luna action, record the action and a bounded reason: discrepancy, safety risk, nondeterminism, or candidate drift. Extra Luna calls or internal units do not increase coverage by themselves.

## Risk-proportional review

- `TARGETED`: clean low-risk package, authoritative checks passed, no repair or shared interface. Inspect changed paths and compact diff; verify the authoritative targeted checks.
- `STANDARD`: ordinary bounded implementation. Inspect the package diff and rerun integration-relevant checks.
- `DEEP`: high/critical risk, repaired work, shared interfaces, security/safety impact, nondeterministic acceptance, scope discrepancy, or failed verification. Inspect the full diff and affected call paths; run adversarial and regression checks.

Any change to relevant code, generated artifacts, configuration, dependencies, or environment assumptions makes affected validation stale. Refresh only the smallest authoritative evidence needed for the exact final candidate.

## Rework state machine

Only Sol assigns final `ACCEPTED`. Other dispositions are `HANDOFF_AWAITING_REVIEW`, `NEEDS_REPAIR`, `FAILED`, `BLOCKED`, and `CANCELLED_OR_OBSOLETE`.

After a failed review:

1. Freeze one route-independent repair allowance by acceptance claim or baseline weight, plus a hard ceiling of three focused attempts. Exact new evidence may return the targeted unit to the same Luna while both the cost allowance and positive marginal net substitution remain. Splitting or renaming packages never increases the allowance, and repeating an unchanged correction is forbidden.
2. Otherwise repartition when coupling or ambiguity caused the failure.
3. Otherwise permit one evidence-backed effort escalation to the next supported tier.
4. When repair and escalation budgets are exhausted, Sol reclaims only the affected responsibility units and records their baseline weight as shadowed.

Do not restart an unchanged vague package. `BLOCKED` is reserved for missing authority, decisions, inputs, permissions, or external state; implementation and verification failures remain in-scope failures.

## Evidence and success gate

Record `sol_planning`, `sol_retained_execution`, `luna_execution`, `sol_review`, `repair`, and `integration` separately. Predict with `net_substitution.py`, then audit two independent views: `actual_sol_labor_reduction` compares measured Sol labor in matched routes; `structural_net_substitution` subtracts Luna execution and incremental Sol planning, coordination, risk-proportional review, integration, replay, and rework from the frozen Sol baseline. The decision value is `min(actual_sol_labor_reduction, structural_net_substitution)`. Also cap `(incremental_sol_overhead + context_credits) / gross_delegated_baseline`; delegation is not economical when this composite burden exceeds its frozen ceiling. Track participation counts separately; they are diagnostics, never savings. Acceptance also requires baseline reconciliation, single ownership, candidate-bound evidence, closed dispositions, and the same independent acceptance suite.

Production phase journals use schema 2 with an explicit route, executor-owned unique intervals, replayable open and closed interval collections, and route/phase actor validation. Legacy journals remain available for load, validation, and read-only export only. Execution accounting uses half-open intervals: merge overlapping or adjacent intervals per executor and across all execution, then measure cross-actor execution overlap. Review and the other auxiliary phases are not execution, so phase totals, execution unions, overlap, and end-to-end wall-clock duration are deliberately different measures.

A task-family policy change requires matched, independently assessed evidence. Five complete pairs permit human review; stronger claims should use a larger sample. Failed arms remain in the denominator. Improvement requires equal-or-better independent acceptance, no defect regression, at least the configured median credit reduction, no elapsed regression unless another explicit objective justifies it, and Sol planning plus review remaining a minority of total measured cost.

Each Sol-only arm is one complete top-level task in one continuous run by a single real Sol controller. Sol may naturally decompose its own work, but the experiment controller must not pre-split, separately dispatch, or artificially serialize Sol packages. Only the common independent referee runs outside both route intervals. Planning, review, integration, replay, or rework required specifically because Luna participated stays inside the `SOL_LUNA` interval.

Use `evidence_ledger.py feedback` to turn those gates into an advisory task-family posture. Missing, estimated-credit, token-only, allowance-delta, regressive, or under-sized evidence holds the posture at `HOLD_SOL_ONLY`. When exact credits and diagnostic tokens coexist, exact credits take comparison precedence. A passing exact-credit cohort exposes only its observed Luna efforts as candidates for human policy review; it never edits policy or dispatches work automatically. Concrete evidence for an unusual individual task may still justify a separately disclosed route estimate, but it must not be presented as learned task-family history.

Concurrency evidence is advisory: call `routing_policy.py evaluate --ledger LEDGER.jsonl --input ROUTE.json` to surface a human-review recommendation under the current policy fingerprint. It cannot raise the executable one-writer cap. A later explicit policy release may change that cap after matched plan-meter evidence; numbers embedded in a route request never unlock more writers.

The v0.10 evidence remains `HOLD`: it did not prove equal-quality, lower-elapsed subscription economics. `net_substitution.py` is a prediction and audit tool with `automatic_execution_allowed: false`, not an automatic dispatcher or policy release.
