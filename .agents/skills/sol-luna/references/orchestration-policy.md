# Orchestration Policy

Read this reference when constructing a route estimate, dispatching or repairing packages, assigning review depth, or reporting a measured Sol-Luna run.

## Accepted-delivery objective

Apply the decision lexicographically:

1. The route must satisfy the same independent acceptance contract and must not increase predicted final defects.
2. The route must respect authority, ownership, sandbox, and failure-impact constraints.
3. Among eligible routes, minimize expected accepted-result credits.
4. Require no expected elapsed regression; when parallelism is the justification, require an expected improvement.

Expected accepted cost includes Luna execution, all retained Sol execution, Sol coordination and review, integration, and failure probability multiplied by recovery cost. Expected time counts serial Sol overhead plus the longer of retained Sol execution and Luna execution, then expected recovery; overlapping work saves wall time but never removes either side's cost. Do not convert token counts, displayed allowance percentages, API dollars, and Codex credits into one another without an authoritative conversion source.

Predictions must name their basis: matched task-family evidence, a bounded feasibility map, or a disclosed estimate. Unknown inputs do not become zero.

## Predictive effort signals

Route lower when requirements are explicit, scope is isolated, acceptance is deterministic, architecture is settled, failure is cheap, and the task family has strong first-pass history. Route directly upward when interfaces are shared, debugging is emergent, context dependencies are long, acceptance is subjective, or rollback and review would be expensive.

Task size and reasoning difficulty are separate. Large repetitive work can suit Low or Medium; a small ambiguous defect can justify XHigh. When uncertainty is material, first repartition, route upward, retain the work in Sol, or run a read-only scout probe that returns `READY`, `NEEDS_REPARTITION`, or `INSUFFICIENT_CONTEXT` without editing.

## Package contract

Freeze the complete task allocation before dispatch. Every work unit has exactly one executor (`SOL` or `LUNA`), baseline Sol cost, dependency set, critical-path flag, writable scope, and acceptance IDs. The baseline totals reconcile to the Sol-only estimate, and candidate allocations use the same canonical baseline map. Delegated coverage is the Luna-owned share of baseline Sol credits; it is an explanatory mechanism, not a target to inflate by splitting units. Unique acceptance assignment proves structural non-duplication, not semantic equivalence between differently named work; Sol must still reject shadow investigations during review.

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

Maintain `ready`, `awaiting review`, and `approved repair` queues. Dispatch ready non-conflicting work within the writer cap. While Luna runs, Sol performs only Sol-owned critical-path work: architecture, acceptance design, integration preparation, or review of another frozen candidate. Reuse retained worker context only when it saves more than it biases review.

The normal production shape is one Sol controller plus one active Luna writer. Active concurrency and accepted Luna coverage are separate: maximize accepted coverage only where Luna replaces real Sol work and each package keeps positive marginal delivery benefit. Prefer the same Luna for adjacent packages with stable interfaces so repository and domain context are amortized; change workers when assumptions, domain, or independence needs change. Sol concurrently advances only disjoint critical-path units; it never builds a shadow implementation of Luna-owned work. Every unit is costed once, and mixed Sol/Luna dependencies determine predicted overlap and elapsed time. If no legitimate Sol work remains, record `WAIT_ALLOWED` instead of inventing work. Use a second active Luna writer only in a pre-registered benchmark until matched included-allowance and elapsed evidence supports a later policy release.

Wait only when no ready package, review, integration preparation, or acceptance work remains. Inspect one compact status snapshot before interrupting a stalled worker; do not turn polling into its own workload.

### Stable-domain delegation envelope

When interfaces, ownership, and acceptance are stable, Sol may freeze one outer envelope instead of pre-scripting every Luna microtask. The envelope fixes writable scope, forbidden actions, acceptance IDs, allocation fingerprint, and final handoff contract. One Luna may then decompose its own internal dependency graph, implement, run deterministic preflight checks, make one bounded evidence-backed correction, and close out within that envelope. Internal units never expand authority or ownership, and the final handoff remains a single frozen candidate.

The handoff binds the candidate digest, exact changed-path union, every acceptance result, internal unit graph, replacement actions, residual risks, and closeout state. Sol performs one risk-proportional final verification against that exact candidate. If Sol repeats a Luna action, record the action and a bounded reason: discrepancy, safety risk, nondeterminism, or candidate drift. Replayed actions are shadow work and are subtracted from effective substitution; extra Luna calls or internal units do not increase coverage by themselves.

## Risk-proportional review

- `TARGETED`: clean low-risk package, authoritative checks passed, no repair or shared interface. Inspect changed paths and compact diff; verify the authoritative targeted checks.
- `STANDARD`: ordinary bounded implementation. Inspect the package diff and rerun integration-relevant checks.
- `DEEP`: high/critical risk, repaired work, shared interfaces, security/safety impact, nondeterministic acceptance, scope discrepancy, or failed verification. Inspect the full diff and affected call paths; run adversarial and regression checks.

Any change to relevant code, generated artifacts, configuration, dependencies, or environment assumptions makes affected validation stale. Refresh only the smallest authoritative evidence needed for the exact final candidate.

## Rework state machine

Only Sol assigns final `ACCEPTED`. Other dispositions are `HANDOFF_AWAITING_REVIEW`, `NEEDS_REPAIR`, `FAILED`, `BLOCKED`, and `CANCELLED_OR_OBSOLETE`.

After a failed review:

1. Permit at most one focused repair for that package only when exact new evidence identifies a bounded correction and its expected marginal saving remains positive. A repair used by another package does not consume this package's budget.
2. Otherwise repartition when coupling or ambiguity caused the failure.
3. Otherwise permit one evidence-backed effort escalation to the next supported tier.
4. When repair and escalation budgets are exhausted, Sol reclaims the package.

Do not restart an unchanged vague package. `BLOCKED` is reserved for missing authority, decisions, inputs, permissions, or external state; implementation and verification failures remain in-scope failures.

## Evidence and success gate

Record `sol_planning`, `sol_retained_execution`, `luna_execution`, `sol_review`, `repair`, and `integration` separately. A matched Sol-Luna record must include the retained phase even when its measured value is zero. Track source-aware credits or tokens, elapsed seconds, first-pass acceptance, repair rounds, independent defects, final candidate, policy and allocation fingerprints, task digest, acceptance-suite digest, accepted delegated coverage, duplicate work, Sol/Luna overlap, effort, active writer count, and review depth. For an envelope also track replacement actions, Sol replay actions, substitution fraction, verification reuse, context reloads, and handoff count. Acceptance requires complete baseline reconciliation, exactly one executor per unit, non-overlapping write scopes, candidate-bound fresh evidence, all package dispositions closed, and the same independent acceptance suite.

Production phase journals use schema 2 with an explicit route, executor-owned unique intervals, replayable open and closed interval collections, and route/phase actor validation. Legacy journals remain available for load, validation, and read-only export only. Execution accounting uses half-open intervals: merge overlapping or adjacent intervals per executor and across all execution, then measure cross-actor execution overlap. Review and the other auxiliary phases are not execution, so phase totals, execution unions, overlap, and end-to-end wall-clock duration are deliberately different measures.

A task-family policy change requires matched, independently assessed evidence. Five complete pairs permit human review; stronger claims should use a larger sample. Failed arms remain in the denominator. Improvement requires equal-or-better independent acceptance, no defect regression, at least the configured median credit reduction, no elapsed regression unless another explicit objective justifies it, and Sol planning plus review remaining a minority of total measured cost.

Use `evidence_ledger.py feedback` to turn those gates into an advisory task-family posture. Missing, estimated-credit, token-only, allowance-delta, regressive, or under-sized evidence holds the posture at `HOLD_SOL_ONLY`. When exact credits and diagnostic tokens coexist, exact credits take comparison precedence. A passing exact-credit cohort exposes only its observed Luna efforts as candidates for human policy review; it never edits policy or dispatches work automatically. Concrete evidence for an unusual individual task may still justify a separately disclosed route estimate, but it must not be presented as learned task-family history.

Concurrency evidence is advisory: call `routing_policy.py evaluate --ledger LEDGER.jsonl --input ROUTE.json` to surface a human-review recommendation under the current policy fingerprint. It cannot raise the executable one-writer cap. A later explicit policy release may change that cap after matched plan-meter evidence; numbers embedded in a route request never unlock more writers.
