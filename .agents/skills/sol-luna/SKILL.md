---
name: sol-luna
description: "Use one bounded GPT-5.6 Luna worker only when it can replace substantial Sol implementation while preserving quality and reducing included-plan allowance; otherwise keep the task in Sol."
---

# Sol-Luna Delivery

Sol remains accountable. Luna is useful only when it substitutes expensive Sol work; adding a worker, protocol, or test is not a saving. Quality and included-plan allowance are co-primary gates, then elapsed time. Diagnostic tokens explain failures but never replace matched five-hour and weekly readings.

## Choose the route

Record `SOL_ONLY` or `SOL_LUNA` before dispatch. Choose `SOL_LUNA` only when it targets the same independent acceptance contract, predicted quality and defects are no worse, expected included-plan allowance is lower, expected elapsed time is no worse, one Luna can own substantial implementation, write ownership is exclusive, and Sol will not repeat that work. Never route below the current policy thresholds: at least 80% predicted first-pass acceptance, at least 50% expected accepted-cost reduction, and no predicted final-defect or elapsed regression. Base those predictions on matched task-family evidence. Without history, permit only one low-impact complete-Luna Low/Medium cold start whose settled architecture, complete deterministic acceptance, exact ownership, empty Sol controller queue, and conservative execution plus one repair plus Sol recovery and downstream dependency-closure re-execution still clear both economic gates. Otherwise choose `SOL_ONLY`.

While Luna runs, Sol advances useful path-disjoint architecture, acceptance preparation, integration, or another frozen review; it waits only when those queues are empty. Shared-interface, high-risk, and High-or-above critical-path work needs external quality evidence bound to the task family, actual effort, allocation shape, and acceptance suite.

Do not run planning scripts on the ordinary path. For a material decision that remains genuinely uncertain, read [references/orchestration-policy.md](references/orchestration-policy.md) and run `scripts/routing_policy.py` once. Formal comparisons may additionally use `scripts/net_substitution.py`. A result with missing evidence or no eligible Luna candidate remains `SOL_ONLY`/`HOLD_SOL_ONLY`.

Choose the lowest effort supported by the task:

- Low: mechanical, explicit, cheaply verified work.
- Medium: settled bounded implementation with deterministic acceptance.
- High: complex logic or substantial edge cases.
- XHigh: difficult debugging, shared interfaces, or costly ambiguity.
- Max: exceptional uncertainty that decomposition cannot remove.

Exact-byte, platform-sensitive, strict-serialization, and adversarial work normally needs High unless matched evidence supports less. High, XHigh, or Max on Luna-owned critical-path work is eligible only after the same-allocation lower-effort option is rejected by a quality or defect gate. Use `luna_scout` for a bounded read-only feasibility question and `luna_reviewer` for independent review. Never silently substitute another model family.

## Dispatch once

Default to one retained Luna writer. Start it with `fork_turns="none"`. The dispatch itself contains only what the worker needs: repository root, package ID, deliverable, exclusive writable paths, named read dependencies or interfaces, acceptance command and expected signal, forbidden actions, stop conditions, and effort. The worker returns its handoff only through normal completion to its immediate Sol parent; it never messages the root or another task on routine success or failure. Do not require a manifest, digest, ledger, ownership tool, or receipt generator on the normal path. Use schema-2 ownership and compact receipts only for formal evidence, concurrency, disputed scope, or high-risk work.

The intended worker path is one bounded read, one complete candidate, causal or changed-area checks, and a concise handoff. "Complete" is semantic, not a demand for one giant patch or the fewest changed lines: use stable file-scoped stages for multi-file or large-file work. A refactor must move the live implementation into the intended structure; when the acceptance contract requires a public compatibility facade, leave a genuine one. Never hide old executable source inside strings or comments, duplicate it to simulate decomposition, or compress statements to game a line cap. Never delete a tracked file merely to replace it. Stop a refused edit and never route around it; continue only with a permitted reviewable in-place update after any required user confirmation, otherwise report `BLOCK`. The final line is human-readable:

```text
READY|<package>|PATH=<paths>|TEST=<acceptance-id>:PASS:<passed>/<total>:EXIT=<code>|RISK=<none-or-code>
```

Use `BLOCK|<package>|K=<code>|REF=<minimal>` for missing authority, ownership conflict, or material ambiguity, and `FAILED|<package>|TEST=<acceptance-id>:FAIL:EXIT=<code>` for an in-scope implementation failure. Do not make Luna discover protocol syntax, compute decorative hashes, repeat passing checks, dump a full diff, or explain routine success in prose.

## Accept without replay

Luna runs causal or changed-area checks while implementing. For a semantic refactor, run one smallest representative causal smoke per moved public boundary; structural preflight alone is not acceptance. Before an expensive designated acceptance suite, structural edits also get the cheapest affected in-memory preflight: parse or compile already-read source without emitting files, or validate an already-read schema; exercise direct imports only when the contract explicitly requires and permits them. A candidate-changing edit invalidates only its affected checks; this is not another full-suite execution. During the initial task read, Sol freezes only explicit `create`, `add`, `update`, or `must cover` obligations as a short checklist of required-change paths and acceptance-boundary labels; allowed paths are not automatically required. Before the final suite, Luna supplies `boundary -> test-file::test-id` references for that checklist. Sol performs one bounded presence check: required-change paths must occur in the candidate diff, every boundary must have one reference in its designated changed test file, and every referenced test ID must exist there. A path mentioned in prose or code is not coverage. Sol does not read test bodies or judge semantics; the final suite remains authoritative. Missing items return to the same Luna before the expensive suite with only missing paths or labels; this is not a post-handoff repair and must not replay the task. Luna reviews the candidate before the final suite, then returns immediately after a pass without post-pass rereads, diffs, status checks, or tests. Sol verifies ownership, changed paths, causal coverage, diff risk, and the host-observed test command/result without redoing Luna's investigation. Exactly one executor runs the final full suite after the last candidate change. If Luna ran that final suite and its host-observed result is available, Sol does not rerun it; otherwise Sol is the sole full-suite executor. A specific failure, drift, nondeterminism, or safety risk may trigger only the smallest affected check.

After a final-suite failure Luna returns `FAILED`; it does not change the candidate or retest until Sol sends exact new failure evidence and any changed boundary for one focused repair. Do not resend the task background. One repair may address all exact failures from that suite when the fix stays local to the original ownership and needs no architecture or context expansion; failure count alone is not a reclaim signal. Reclaim when the evidence requires broad reimplementation or changed architecture, context, or ownership. A second repair or effort escalation needs new evidence and a still-positive substitution case; otherwise Sol reclaims only the affected slice and records that the route failed economically. Sol never shadow-implements Luna-owned work.

Report accepted quality, five-hour and weekly percentage-point changes when measured, elapsed time, effort, repairs, Sol rewrites or reclaims, and remaining uncertainty. Diagnostic tools under `scripts/` are optional and answer specific evidence questions; they never authorize routing or included-plan claims.

Do not commit, push, deploy, install, delete data, or contact external systems unless the underlying user request separately authorizes it.
