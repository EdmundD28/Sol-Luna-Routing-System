# Orchestration Policy

Read this reference only when an ordinary route decision remains uncertain, ownership is concurrent or disputed, risk requires deeper review, or a formal measured run needs the detailed contract. It is not part of the normal dispatch payload.

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

For a new production route, schema 7 binds every candidate's claimed first-pass and final-defect probabilities to an externally loaded evidence record with the same task family, actual Luna effort, allocation-shape fingerprint, and acceptance-suite digest. It also derives a minimum effort from settled architecture, deterministic acceptance, semantic coupling, cross-module invariants, interface count, adversarial edges, platform-sensitive I/O, and strict serialization. Leaf ownership does not imply easy reasoning: a candidate below this floor is rejected, while High or XHigh still needs its own matching quality evidence and the lower-effort comparator required above. Schema 8 is the only history-free cold-start exception: one Low/Medium, low-impact, complete-Luna allocation with settled architecture, deterministic acceptance, one writer, and an empty Sol queue. When the executable router is used, a strict external manifest supplies the complete acceptance-ID set, executable commands, expected signals, and task family. An ordinary Sol decision applies the same logical gates without serializing or sending that artifact to the worker. Schema 8 disregards claimed probabilities and uses a conservative accepted-delivery bound containing execution, one repair, terminal Sol recovery, and downstream dependency-closure re-execution. The binding does not prove the controller's semantic risk classification or estimates, so execution remains subject to Sol approval. Schema 6 keeps external quality binding without the executable effort floor; schema 5 remains readable for compatibility.

## Package contract

Decide the complete task allocation before dispatch. This is a logical ownership and cost decision, not necessarily a file. When a formal machine plan is activated, every work unit has exactly one executor (`SOL` or `LUNA`), baseline Sol cost, dependency set, critical-path flag, writable scope, and acceptance IDs. The baseline totals reconcile to the Sol-only estimate, and candidate allocations use the same canonical baseline map. Delegated coverage is the Luna-owned share of baseline Sol cost; accepted coverage subtracts the whole affected claim when Sol replays it. These are routing weights, not authenticated plan-allowance readings, and cannot be inflated by splitting units.

Whenever authority, ownership, and deterministic acceptance permit it, the candidate set must include one complete-Luna envelope covering the entire accepted result. Compare it with mixed allocations and `SOL_ONLY`. Do not reserve a Sol implementation unit merely to keep the controller busy, manufacture overlap, or preserve an old topology; reject complete Luna only with an explicit quality, defect, authority, cost, or time gate. When observed controller evidence exists, use it to calibrate Sol planning, coordination, review, integration, and replay instead of defaulting those terms toward zero.

For concurrent writers, disputed scope, high-risk work, or formal evidence, freeze the executable schema-2 ownership plan before dispatch. Executors have stable IDs and fixed actors; work units and acceptances name their executor directly; every unit and acceptance appears in exactly one executor-consistent partition; and each partition path set is the exact normalized union of its contents. The canonical partition digest is independent of input array order but changes with ownership, executor, or path changes. Schema 1 is compatibility-only. A single ordinary writer with explicit exclusive paths does not need to construct or validate this artifact.

An ordinary one-writer dispatch contains the repository root, package ID, deliverable, exclusive writable paths, named read dependencies, one acceptance command, forbidden actions, stop conditions, and effort. During that same initial read, imperative `create`, `add`, `update`, and `must cover` clauses freeze a short required-change and coverage checklist; the broader allowed-path set does not. In the same turn and before the final suite, Luna maps each coverage label to `test-file::test-id`, checks that every required-change path is in the diff and every mapped ID exists in its designated changed test file, and fixes omissions. The compact final handoff carries that mapping; Sol confirms only changed paths and named-ID presence after return, without reading test bodies or repeating the suite. A discrepancy sends only missing paths or labels to the same Luna as exception evidence. Do not attach route estimates, manifests, ledgers, digests, or tool manuals unless the worker needs them to perform the actual change.

A formal, concurrent, or high-risk dispatch additionally records as needed:

- the canonical repository root observed by Sol at dispatch, with all package paths resolved relative to that root;
- package ID, concrete deliverable, and why it matters;
- readiness dependencies and stable interface assumptions;
- exclusive writable paths and read-only dependencies;
- shared or integration files reserved to Sol;
- observable acceptance commands and expected signals;
- forbidden actions and underlying permission boundary;
- selected effort and the evidence that justified it;
- any extra handoff fields required by the formal evidence contract.

Workers preserve user and concurrent changes, never cross ownership, and report a collision instead of editing through it. Generated outputs need unique destinations. A handoff freezes the package candidate until Sol explicitly opens a repair.

Do not infer that the child's default current directory equals the target repository. When a Codex workspace contains a nested checkout, bind the child to the canonical root in the package prompt or use the native workdir mechanism when one is available. Absolute roots may appear in private runtime instructions but must be redacted from committed receipts and public evidence.

## Rolling execution

Maintain `ready`, `awaiting review`, and `approved repair` queues. An approved same-Luna repair occupies the Luna writer frontier before new Luna dispatch; Sol-owned ready work and review may still advance. Dispatch other ready non-conflicting work within the writer cap. While Luna runs, Sol performs only Sol-owned critical-path work: architecture, acceptance design, integration preparation, or review of another frozen candidate. Reuse retained worker context only when it saves more than it biases review.

The normal production shape is one Sol controller plus one active Luna writer. Reuse that Luna across adjacent packages when the domain, interfaces, and assumptions stay stable so retained context amortizes reload cost; switch when the domain, assumptions, or need for independence changes. Add a writer only when the policy cap permits it and the writer's marginal net substitution remains positive after added coordination, review, integration, and recovery. Sol concurrently advances disjoint valuable work, then drains ready-package, review, integration, dispatch, and acceptance queues; it never builds a shadow implementation of Luna-owned work. Every unit is costed once. An all-Luna allocation may record `WAIT_ALLOWED` only when all five controller queue counts are zero.

In a complete-Luna envelope, Sol's useful concurrent lane is read-only acceptance preparation: freeze risk triggers, expected path ownership, and the smallest authoritative checks. It must not inspect the evolving candidate, prewrite integration code, or create replacement work. Once that lane is exhausted, bounded waiting is economically preferable to inventing Sol implementation.

Wait only when no ready package, review, integration preparation, or acceptance work remains. Inspect one compact status snapshot before interrupting a stalled worker; do not turn polling into its own workload.

### Stable-domain delegation envelope

When interfaces, ownership, and acceptance are stable, Sol may freeze one outer envelope instead of pre-scripting every Luna microtask. The envelope fixes writable scope, forbidden actions, acceptance IDs, allocation fingerprint, and final handoff contract. One Luna may then decompose its own internal dependency graph, implement through stable file-scoped stages, run deterministic preflight checks, make one bounded pre-handoff correction, and close out within that envelope; later review-driven repairs use the separate frozen rework cap below. Refactors move live behavior into the intended modules and retain a real compatibility facade only when the acceptance contract requires it; comments, string wrappers, duplicated implementations, and compressed statements that game line caps are not decomposition. Internal units never expand authority or ownership, and the final handoff remains a single frozen candidate.

Luna performs causal and changed-area checks before Sol review. For formal or high-risk work, a structured manifest may additionally be projected with `handoff_preflight.py`; missing, failed, stale, out-of-scope, or open-risk evidence then keeps that formal handoff at `HOLD`. Ordinary work must not pay this projection cost.

Validation separation: name one in-route executor for every suite. Luna runs the smallest representative causal smoke for each changed public boundary during a semantic refactor; a structural gate alone is insufficient. Before an expensive suite, use the cheapest in-memory structural gate activated by the edits: parse or compile already-read source without emitting files, or validate an already-read schema; use direct imports only when the contract explicitly requires and permits them. Refresh only affected checks after another candidate change; these checks do not consume the one-full-suite budget. Luna reviews the candidate before the final suite and returns immediately after a pass; post-pass rereads, diffs, status checks, and tests are duplicate work. Sol reviews ownership, paths, causal coverage, risk, and host-observed command results without repeating Luna's checks. A formal route also reviews its candidate receipt. The designated executor runs the final suite once. If Luna lacks the authoritative environment or its result is not host-observable, Luna does causal checks and Sol is the sole full-suite executor. After a final-suite failure Luna returns `FAILED` and waits for Sol to authorize repair with new evidence. The first repair message may carry every exact failure from that run when all fixes remain local to the frozen ownership and require no architecture or context expansion; the number of failing tests or causal roots alone never forces reclaim. A rerun is an explicit exception activated only by drift, incomplete evidence, nondeterminism, failure, repair, or material security/platform risk, and uses the smallest affected check. The external common referee remains outside measured route intervals.

The compact protocol is an optional formal-evidence projection, not the normal worker interface. Use `MAN` references, candidate digests, and path-set digests only when a measured campaign or disputed/high-risk candidate needs machine-verifiable receipts. Never make an ordinary worker inspect the protocol tool, discover its command syntax, or compute decorative hashes. The normal handoff is one short human-readable `READY`, `BLOCK`, or `FAILED` line. In either mode, reuse the same Luna for focused repair and transmit only new failure evidence.

An optional offline communication audit may measure descriptive byte and lexical-unit proxies plus externally supplied counters. Its preparation/reporting transcripts and provider counters are outside normal messages and measured route intervals; no diagnostic result dispatches work, infers provider usage, or authorizes routing or included-plan conclusions.

When schema-2 evidence is activated, its handoff binds the candidate digest, exact changed-path union, acceptance results, replacement actions, residual risks, and closeout state. Otherwise the repository diff, named checks, and concise worker handoff are the facts. Sol performs risk-proportional verification and keeps its acceptance lane path-disjoint from Luna ownership. If Sol repeats a Luna action, record the action and a bounded reason: discrepancy, safety risk, nondeterminism, or candidate drift.

## Risk-proportional review

- `TARGETED`: clean low-risk package, authoritative checks passed, no repair or shared interface. Inspect changed paths and compact diff; verify the authoritative targeted checks.
- `STANDARD`: ordinary bounded implementation. Inspect the package diff and its integration risks; rerun only a triggered integration check.
- `DEEP`: high/critical risk, repaired work, shared interfaces, security/safety impact, nondeterministic acceptance, scope discrepancy, or failed verification. Inspect the full diff and affected call paths; run only the adversarial or regression checks activated by those risks.

When formal schema-2 ownership evidence is activated, perform its authoritative ownership check once after the final suite and last candidate-changing action. Ordinary one-writer work checks actual changed paths directly. A candidate change invalidates affected acceptance evidence; refresh only what the exact trigger invalidated.

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
