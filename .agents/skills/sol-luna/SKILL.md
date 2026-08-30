---
name: sol-luna
description: "Run a cost-aware Sol-led workflow that uses bounded GPT-5.6 Luna work only when equal-quality accepted delivery is expected to consume less included-plan allowance and no more elapsed time than Sol-only."
---

# Sol-Luna Delivery

Sol remains accountable; Luna substitutes expensive Sol implementation. Quality and safety are hard gates. Among accepted routes, minimize included-plan allowance before elapsed time. Diagnostic credits, prices, bytes, and tokens never replace matched five-hour readings.

## Route economically

Record `SOL_ONLY` or `SOL_LUNA` before dispatch. For material work, freeze one complete-task estimate and run the commands below. Resolve the interpreter once; if `python` is absent, use the bundled Python path returned by the workspace dependency loader instead of claiming Python is missing.

```text
python .agents/skills/sol-luna/scripts/net_substitution.py evaluate --input ALLOCATION.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input ROUTE.json
```

Compare `SOL_ONLY`, one complete-Luna envelope, and any useful mixed allocation. Include complete Luna only when authority, sandbox, exclusive ownership, and deterministic acceptance allow it; otherwise retain work in Sol or use one bounded read-only scout. Calls, packages, actions, and writer count are not savings.

Do not read [references/orchestration-policy.md](references/orchestration-policy.md) on the normal path. Load it when either command errors or lacks required evidence, a high-risk/High+ critical-path/ownership/rework/reclaim decision activates, or a formal evidence report needs the detailed contract. A result with no eligible Luna candidate remains `SOL_ONLY`. Shared-interface, high-risk, or High+ critical-path work without external quality evidence bound to the task family, actual Luna effort, allocation shape, and acceptance suite must remain `SOL_ONLY`/`HOLD_SOL_ONLY`; schema-5 compatibility output, self-reported probabilities, diagnostic metrics, and policy defaults cannot replace that evidence.

Choose the lowest evidence-supported effort expected to pass: `luna_worker_low` for mechanical work, `luna_worker_medium` for settled bounded implementation, `luna_worker_high` for complex logic, `luna_worker_xhigh` for difficult debugging/shared interfaces, and `luna_worker_max` only for exceptional uncertainty that decomposition cannot remove. Use `luna_scout` for feasibility and `luna_reviewer` for independent review. High+ critical-path work requires the same-allocation lower effort to be rejected by a quality or defect gate. Never silently substitute another model family; disclose any exact-effort `gpt-5.6-luna` fallback.

## Freeze one complete envelope

Default to one retained Luna writer. Add another only when its marginal substitution stays positive after coordination, review, integration, and recovery. Writers never overlap, Luna never spawns agents, and Sol does not pre-script Luna's internal units.

For material work, bind the canonical repository root in the envelope, then freeze a schema-2 ownership plan using exact normalized repository-relative paths, interfaces, acceptance IDs, forbidden actions, stop conditions, effort, and repair cap. Assign every responsibility unit and acceptance to exactly one executor; reserve shared/integration files to Sol. Validate before dispatch with `python .agents/skills/sol-luna/scripts/ownership_guard.py check-plan --input OWNERSHIP.json`, then bind production schema-2 final paths with `check-changes --input CHANGES.json --plan OWNERSHIP.json --repo REPO --base BASE_SHA`; this required authoritative mode performs a non-atomic, double-captured point-in-time check of actual candidate paths, and the candidate may still drift after return. Before final acceptance, verify again using the returned `base_commit` and `candidate_digest`. Calls without `--repo`/`--base` are retained only for legacy compatibility and are not evidence against path under-reporting; schema 1 remains compatibility-only. Prefer complete-Luna ownership of implementation, integration edits, tests, documentation, and repair. Sol keeps a path-disjoint read-only acceptance lane and never shadow-implements Luna work.

Reference frozen task and manifest material instead of repeating it. Normal dispatch uses `MAN|<package_ref>` then `RUN`; normal success returns a candidate-digest-bound `OK`. Missing, failed, stale, out-of-scope, or open-risk evidence remains `HOLD`. Only blockers, acceptance failures, ownership conflicts, or material semantic uncertainty expand into prose.

## Accept without replay

The same Luna runs targeted checks during implementation and one final authoritative suite. If Luna cannot access the authoritative environment, Luna runs causal/targeted checks and Sol runs that environment once. Sol verifies ownership, exact changed paths, candidate digest, causal coverage, reported tests, and diff risk. Use targeted review for clean low-risk work, standard review for ordinary bounded work, and deep review only for high risk, shared interfaces, repair, discrepancy, nondeterminism, security/safety, or failed verification. Sol reruns only the smallest triggered check.

Return exact new failures and changed boundaries to the same Luna for at most three focused repairs while positive substitution remains. Each retry needs new failure evidence; never repeat an unchanged correction. Permit at most one evidence-backed effort escalation, then reclaim only the affected responsibility unit. Any Sol edit in Luna scope is a declared replay or reclaim. A common independent referee runs outside both route intervals; Luna-specific planning, review, repair, integration, and rework remain inside `SOL_LUNA`.

Report accepted quality, five-hour and weekly percentage-point changes, elapsed time, Sol rewrites/reclaims, ownership exceptions, and uncertainty. Optional diagnostics in `scripts/` answer specific evidence questions only; they never authorize routing or included-plan conclusions.

Do not commit, push, deploy, install, delete data, or contact external systems unless the underlying user request separately authorizes it.
