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

The normal production shape is one Sol controller plus one Luna writer. Sol receives the whole user task and carves out one high-leverage package; the remaining work is not represented as serial Sol packages and is not dispatched through the worker queue. Do not split a task solely to create concurrency. Use a second Luna writer only in a pre-registered benchmark until matched included-allowance and elapsed evidence supports a later policy release.

Wait only when no ready package, review, integration preparation, or acceptance work remains. Inspect one compact status snapshot before interrupting a stalled worker; do not turn polling into its own workload.

## Risk-proportional review

- `TARGETED`: clean low-risk package, authoritative checks passed, no repair or shared interface. Inspect changed paths and compact diff; verify the authoritative targeted checks.
- `STANDARD`: ordinary bounded implementation. Inspect the package diff and rerun integration-relevant checks.
- `DEEP`: high/critical risk, repaired work, shared interfaces, security/safety impact, nondeterministic acceptance, scope discrepancy, or failed verification. Inspect the full diff and affected call paths; run adversarial and regression checks.

Any change to relevant code, generated artifacts, configuration, dependencies, or environment assumptions makes affected validation stale. Refresh only the smallest authoritative evidence needed for the exact final candidate.

## Rework state machine

Only Sol assigns final `ACCEPTED`. Other dispositions are `HANDOFF_AWAITING_REVIEW`, `NEEDS_REPAIR`, `FAILED`, `BLOCKED`, and `CANCELLED_OR_OBSOLETE`.

After a failed review:

1. Permit one focused repair only when exact new evidence identifies a bounded correction.
2. Otherwise repartition when coupling or ambiguity caused the failure.
3. Otherwise permit one evidence-backed effort escalation to the next supported tier.
4. When repair and escalation budgets are exhausted, Sol reclaims the package.

Do not restart an unchanged vague package. `BLOCKED` is reserved for missing authority, decisions, inputs, permissions, or external state; implementation and verification failures remain in-scope failures.

## Evidence and success gate

Record `sol_planning`, `sol_retained_execution`, `luna_execution`, `sol_review`, `repair`, and `integration` separately. A matched Sol-Luna record must include the retained phase even when its measured value is zero. Track source-aware credits or tokens, elapsed seconds, first-pass acceptance, repair rounds, independent defects, final candidate, policy fingerprint, task digest, acceptance-suite digest, effort, writer count, and review depth.

A task-family policy change requires matched, independently assessed evidence. Five complete pairs permit human review; stronger claims should use a larger sample. Failed arms remain in the denominator. Improvement requires equal-or-better independent acceptance, no defect regression, at least the configured median credit reduction, no elapsed regression unless another explicit objective justifies it, and Sol planning plus review remaining a minority of total measured cost.

Use `evidence_ledger.py feedback` to turn those gates into an advisory task-family posture. Missing, estimated-credit, token-only, allowance-delta, regressive, or under-sized evidence holds the posture at `HOLD_SOL_ONLY`. When exact credits and diagnostic tokens coexist, exact credits take comparison precedence. A passing exact-credit cohort exposes only its observed Luna efforts as candidates for human policy review; it never edits policy or dispatches work automatically. Concrete evidence for an unusual individual task may still justify a separately disclosed route estimate, but it must not be presented as learned task-family history.

Concurrency evidence is advisory: call `routing_policy.py evaluate --ledger LEDGER.jsonl --input ROUTE.json` to surface a human-review recommendation under the current policy fingerprint. It cannot raise the executable one-writer cap. A later explicit policy release may change that cap after matched plan-meter evidence; numbers embedded in a route request never unlock more writers.
