---
name: sol-luna
description: "Use one bounded GPT-5.6 Luna worker only when it can replace substantial Sol implementation while preserving quality and reducing included-plan allowance; otherwise keep the task in Sol."
---

# Sol-Luna Delivery

Sol remains accountable. Luna is useful only when it substitutes substantial Sol work. Quality and included-plan allowance are co-primary gates, then elapsed time. Diagnostic tokens explain failures; they never replace matched five-hour and weekly readings.

## Choose the route

For difficult or uncertain shape-dependent work, optionally use
`select_adaptive_route` in `routing_policy.py`; Sol may apply the same rules
directly for clear tasks. It returns S0–S4, model/effort, responsibilities,
reason, and evidence status. Unknown/unavailable capability => S0; unproven
capability => bounded S4 research. High requires same-distribution evidence
and a lower-effort comparator. Cold start uses exact `C=L+O+qR`. The selector
and `validate_adaptive_execution` are optional; the token checks consistency,
not host-observed execution.

Record `SOL_ONLY` or `SOL_LUNA` before dispatch. Production uses the same independent acceptance contract; at least 80% predicted first-pass acceptance; at least 50% expected accepted-cost reduction; no predicted final-defect or elapsed regression; predicted quality and defects are no worse; expected included-plan allowance is lower; and expected elapsed time is no worse. Apply conservative Wilson, credit, and time gates. Bind operations to actors and reachable surfaces, including Sol review cost. Missing evidence/economics is unknown. S4 is research, never production evidence. Without matched task-family evidence, permit at most one low-impact complete-Luna Low/Medium cold start with an empty Sol controller queue, priced as conservative execution plus one repair plus Sol recovery and downstream dependency-closure re-execution. Proceed only when one Luna can own substantial work and Sol will not repeat that work.

While Luna runs, Sol advances useful path-disjoint work. If none exists, wait once on the retained worker until completion; never poll, enumerate all agents, or wake on commentary. Shared-interface, high-risk, and High-or-above critical-path work needs external quality evidence bound to the task family, actual effort, allocation shape, and acceptance suite.

Do not run planning scripts normally. For an uncertain decision, read [references/orchestration-policy.md](references/orchestration-policy.md) and run `scripts/routing_policy.py` once; formal comparisons may use `scripts/net_substitution.py`. Missing evidence or no eligible candidate means `SOL_ONLY`/`HOLD_SOL_ONLY`.

Choose the lowest effort supported by the task:

- Low/Medium: explicit bounded work; High/XHigh/Max require corresponding evidence.

Exact-byte, platform-sensitive, strict-serialization, and adversarial labels do not authorize High. High+ critical-path work requires matched task-family evidence that the same allocation at lower effort missed a quality or defect gate. Use `luna_scout` for a bounded read-only feasibility question and `luna_reviewer` for independent review. Never silently substitute another model family.

## Dispatch once

Default to one retained Luna writer with `fork_turns="none"`. Dispatch repository root, package ID, deliverable, exclusive paths, named dependencies/interfaces, launch-ready acceptance capsule, prohibitions, stop conditions, and effort. That capsule is a dispatch contract, not a runtime launcher: name the canonical repository workdir, exact executable and arguments, and environment values resolved there; Luna executes there without `cd` or reinterpretation. If that root differs from the parent workspace, edit only with absolute paths under it; command workdirs do not retarget edit tools. Verify the first changed path stays inside. A missing, inconsistent, or unexecutable capsule before launch returns `BLOCK` with `K=ACCEPTANCE_CAPSULE`; an exact launch that fails before tests collect returns infrastructure `FAILED` with minimal launch evidence. Neither is quality evidence or authorizes effort escalation; retry only with a corrected capsule, not an implementation repair. The worker returns only through normal completion to its immediate Sol parent; routine success or failure never messages the root or another task. Do not require a manifest, digest, ledger, ownership tool, or receipt generator normally. Use schema-2 ownership and compact receipts only for formal evidence, concurrency, disputed scope, or high risk.

The intended worker path is one bounded read, one complete candidate, causal or changed-area checks, and a concise handoff. "Complete" is semantic, not a demand for one giant patch or the fewest changed lines: use stable file-scoped stages for multi-file or large-file work. A refactor must move the live implementation into the intended structure; when the acceptance contract requires a public compatibility facade, leave a genuine one. Never hide old executable source inside strings or comments, duplicate it to simulate decomposition, or compress statements to game a line cap. Never delete a tracked file merely to replace it. Stop a refused edit and never route around it. A user-authorized parent package permits bounded edits; otherwise report `BLOCK`. The final line is human-readable:

```text
READY|<package>|PATH=<paths>|TEST=<acceptance-id>:PASS:<passed>/<total>:EXIT=<code>|RISK=<none-or-code>
```

Use `BLOCK|<package>|K=<code>|REF=<minimal>` for missing authority, ownership conflict, or material ambiguity, and `FAILED|<package>|TEST=<acceptance-id>:FAIL:EXIT=<code>` for an in-scope implementation failure. Do not make Luna discover protocol syntax, compute decorative hashes, repeat passing checks, dump a full diff, or explain routine success in prose.

## Accept without replay

Luna runs causal or changed-area checks while implementing. For semantic refactors, smoke each moved public boundary once; structural preflight alone is not acceptance. Before an expensive suite, parse or compile already-read structural inputs without output, or validate an already-read schema; direct imports only when the contract permits. Candidate changes invalidate affected checks, not the whole suite.

During the initial task read, Sol freezes explicit `create`, `add`, `update`, and `must cover` obligations as required paths and acceptance labels; allowed paths are not required. Luna maps each label to `test-file::test-id`, checks required paths changed and named IDs exist, and fixes omissions in the same turn. A path mentioned in prose or code is not coverage.

If designated acceptance is pre-existing and independent, Luna runs the final full suite once after the last change; Sol checks ownership, paths, mapping, diff risk, and the host result without reading test bodies or rerunning. If Luna creates or changes designated acceptance tests, those tests cannot certify themselves: Luna runs causal or changed-area checks and returns before the full suite; Sol reviews only the changed test bodies against the frozen labels, rejects empty, assertion-free, or tautological tests, then becomes the sole final-suite executor. Price that Sol work before routing; choose `SOL_ONLY` if either economic gate fails. A discrepancy returns only missing labels and minimal evidence to the same Luna. Exactly one executor runs the final full suite. After a pass, no post-pass rereads, diffs, status checks, or tests. Drift, nondeterminism, failure, repair, or material security/platform risk triggers only the smallest affected check.

After a final-suite failure Luna returns `FAILED`; it does not change the candidate or retest until Sol sends exact new failure evidence and any changed boundary for one focused repair. Do not resend the task background. One repair may address all exact failures from that suite when the fix stays local to the original ownership and needs no architecture or context expansion; failure count alone is not a reclaim signal. Reclaim when the evidence requires broad reimplementation or changed architecture, context, or ownership. A second repair or effort escalation needs new evidence and a still-positive substitution case; otherwise Sol reclaims only the affected slice and records that the route failed economically. Sol never shadow-implements Luna-owned work.

Report accepted quality, five-hour and weekly percentage-point changes when measured, elapsed time, effort, repairs, Sol rewrites or reclaims, and remaining uncertainty. Diagnostic tools under `scripts/` are optional and answer specific evidence questions; they never authorize routing or included-plan claims.

Do not commit, push, deploy, install, delete data, or contact external systems unless the underlying user request separately authorizes it.
