# Sol-Luna Delivery System

An experimental, explicit Codex Skill for increasing Luna's effective participation only when it produces net substitution of expensive Sol work without lowering independent quality or increasing elapsed time.

The objective is not fewer writers or more Luna calls. Quality, safety, ownership, and authority are hard gates; `SOL_ONLY` is correct whenever Luna execution plus incremental Sol planning, coordination, review, integration, replay, or rework erases the saving.

## Status

This revision adds executable policy and evidence controls. It is still an experimental baseline, not a proven cost optimizer or a filesystem security boundary.

- Predictive routing compares Sol-only delivery with Luna `low`, `medium`, `high`, `xhigh`, and `max` using expected accepted-result credits and time. The user-facing word `light` is accepted as an alias for Codex `low`.
- A lower-effort failure is not required before direct XHigh or Max selection.
- Production routing defaults to one active Luna writer, but concurrency is not the objective. Reuse the same Luna while the domain and assumptions remain stable; switch when they change, and add a writer only when policy permits it and marginal net substitution stays positive.
- When ownership and deterministic acceptance allow it, routing must compare a complete-Luna envelope against mixed allocations and `SOL_ONLY`. Sol does not keep an implementation package merely to stay busy; its complete-Luna lane is read-only acceptance preparation followed by risk-triggered verification.
- The [P012 controller-overhead audit](docs/benchmark/p012-controller-overhead-audit-2026-08-29.md) found that Luna was only 3.32% of the route's standardized purchased-credit estimate; excess Sol controller work, not Luna execution, erased the expected saving.
- [P016](docs/benchmark/p016-complete-luna-allowance-2026-08-29.md) tested the complete-Luna envelope on a 17–24 minute cross-file refactor. Sol-Luna passed 12/12 hidden groups and used 1 displayed five-hour point; Sol-only passed 9/12 and used 2 points. Sol-Luna was 6:48 slower, so this is task-local evidence of better allowance substitution and quality, not an equal-quality time win or a universal ratio.
- The legacy schema-2 delegation envelope remains readable and conservative at whole-claim level. The strict closure contract adds fine-grained responsibility units, read-only Sol acceptance, same-Luna repair, and partial reclaim; both are structural routing evidence rather than plan-allowance measurements.
- Repair authority is frozen by route-independent acceptance claims or baseline weight; splitting work into more packages never creates more repair budget.
- Risk-proportional review avoids replaying clean low-risk work while requiring deep review for material risk and discrepancies.
- A candidate-bound first-handoff preflight moves contract boundary checks into Luna's delivery, so Sol reviews evidence instead of rediscovering the whole implementation surface. It exposes missing, failed, stale, scope, and risk blockers but never accepts work.
- Runtime receipts compare expected identity and boundary values with host-observed records.
- Ownership, frozen handoffs, lifecycle transitions, phase evidence, atomic ledger writes, and matched cohorts have executable validators.
- Evidence-ledger schema 5 requires retained Sol execution in new matched Sol-Luna records. Older schemas remain readable with their origin preserved but cannot satisfy the current measurement-policy gate. Schema 4 credit trust remains fail-closed: self-declared exact sources cannot pass, and claim-index schema 2 binds each external claim to the complete normalized record and a unique receipt. The ledger does not validate provider signatures or collect Codex desktop billing data.
- A five-pair matched bounded-function campaign achieved equal independent acceptance and zero final defects, but Sol→Luna regressed to 4.08× the median diagnostic tokens and 5.42× the median elapsed time. It did not capture five-hour or weekly plan-limit readings, so it cannot decide subscription-allowance economics.
- A later [matched allowance pilot p002](docs/benchmark/matched-allowance-p002-2026-08-28.md) found that two Luna High writers failed equal acceptance, consumed no less displayed five-hour allowance, and were 4.72% slower. The subsequent [p003 campaign](docs/benchmark/matched-allowance-p003-2026-08-28.md) found only a displayed 1.25× five-hour advantage for fixed one-package Sol-Luna, with worse quality and 31.2% longer elapsed time. Policy 1.5.0 therefore keeps one active Luna as the default while removing the artificial requirement that Sol retain an implementation package merely to create overlap.
- The p004 rolling-context campaign repeated an allowance signal: two Sol-only arms consumed 7 displayed five-hour percentage points versus 2 for Sol-Luna, a 3.5× point estimate. All four arms missed independent acceptance and Sol-Luna was 0.75% slower in aggregate. The later [P005 field pilot](docs/benchmark/p005-field-pilot-2026-08-28.md) passed equal hidden acceptance but was 2.17× slower; its displayed allowance readings were contaminated by unequal controller polling, and Sol replay shadowed the only coarse Luna claim. Both remain `HOLD`.
- [P008](docs/benchmark/p008-first-handoff-preflight-allowance-2026-08-29.md) recorded 2 displayed five-hour percentage points and 1 weekly point for Sol-only versus no displayed decrease for Sol-Luna in the same reset windows. Sol-Luna used one retained Luna, reduced same-Luna repair from P007's two rounds to one, and produced the stronger audited candidate, but took 20:43 versus 12:04. Diagnostic token counts moved in the opposite direction, so this comparison does not support treating them as a subscription-allowance proxy. One pair is directional evidence, not a universal claim.
- Local lifecycle tests validate the state machine. A [native desktop-app smoke](docs/validation/native-app-lifecycle-smoke-2026-08-26.md) exercised real Luna delegation, one repair, stale-evidence rejection, timeout/interruption, same-child continuation, and pre-dispatch ownership conflict rejection. It did not prove that the packaged custom TOML profile was loaded; the automated opt-in runner remains unavailable until Codex exposes a stable non-interactive custom-subagent surface.

See [P016](docs/benchmark/p016-complete-luna-allowance-2026-08-29.md), [the p004 rolling-context campaign](docs/benchmark/matched-allowance-p004-2026-08-28.md), [the p003 allowance campaign](docs/benchmark/matched-allowance-p003-2026-08-28.md), [the p002 allowance pilot](docs/benchmark/matched-allowance-p002-2026-08-28.md), [the matched bounded-function campaign](docs/benchmark/matched-bounded-campaign-2026-08-26.md), and the [older preliminary comparison](docs/benchmark/preliminary-comparison.md).

## Core workflow

Invoke explicitly:

```text
$sol-luna <substantial task>
```

Sol estimates each eligible route before dispatch. Policy `1.12.0` requires at least 80% predicted first-pass acceptance, no predicted final-defect regression, at least 50% expected accepted-cost reduction by default, and no expected elapsed regression. Schema 7 derives an auditable Luna effort floor from coupling and failure surfaces, then requires matching external quality evidence; leaf ownership alone cannot justify Low or Medium. High+ critical-path candidates require a same-allocation lower-effort quality failure in policy order, so XHigh can learn from High and Max can learn from XHigh. The policy still caps incremental Sol-plus-context burden and rejects shadow ownership. It is a route guard; only matched account-meter readings prove subscription-allowance savings.

```powershell
python .agents/skills/sol-luna/scripts/routing_policy.py template
python .agents/skills/sol-luna/scripts/routing_policy.py quality-evidence-template
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input route.json --quality-evidence-index quality.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --ledger runtime/sol-luna/ledger.jsonl --verified-credit-receipts runtime/sol-luna/verified-credit-receipts.json --input route.json
python .agents/skills/sol-luna/scripts/routing_policy.py review --input review.json
python .agents/skills/sol-luna/scripts/routing_policy.py rework --input rework.json
python .agents/skills/sol-luna/scripts/routing_policy.py fingerprint
python .agents/skills/sol-luna/scripts/net_substitution.py template
```

The policy is advisory and never launches a worker automatically. Missing estimates stay unknown; Sol can retain the task or run a short read-only scout probe.
The default schema-7 template keeps quality records in a separate strict index and binds each candidate by content to the same task family, Luna effort, allocation shape, and acceptance-suite digest. Its reasoning profile produces a minimum effort but never auto-selects Max. Placeholder or missing evidence routes to Sol-only. Schema 6 remains compatible without the effort floor; schema 5 is legacy compatibility.

## Profiles

The project ships two roles rather than a large role hierarchy:

- `luna_worker_{low,medium,high,xhigh,max}`: workspace-write implementation variants selected predictively.
- `luna_reviewer`: read-only independent reviewer/tester.
- `luna_scout`: read-only Low feasibility probe.

`luna_worker` remains a backward-compatible High profile. Every writer has an explicit `workspace-write` sandbox, and read-only roles declare `read-only`. Parent live permission overrides can still affect a native child; use host-observed receipts when boundary compliance is material.

Official OpenAI documentation describes Luna as the cost-sensitive, high-volume GPT-5.6 tier and recommends reserving higher reasoning settings for workloads where evaluation shows a quality gain:

- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Codex custom agents and subagents](https://developers.openai.com/codex/subagents)

## Evidence and enforcement tools

The Skill uses standard-library Python tools:

| Tool | Purpose |
|---|---|
| `routing_policy.py` | Predict route, effort, concurrency, review depth, and rework action |
| `net_substitution.py` | Predict structural substitution and expected Sol-labor reduction, using the lower value without enabling automatic execution |
| `closure_contract.py` | Validate complete fine-grained closures, or project the next legal event and compact repair handoff from a frozen live prefix; projection is replay-only and never dispatches work |
| `ownership_guard.py` | Validate frozen schema-2 partitions, bind final changed paths to their digest, and preserve schema-1 compatibility checks |
| `lifecycle_contract.py` | Replay package transitions, stale evidence, timeout, repair, escalation, continuation, and acceptance |
| `native_lifecycle_receipt.py` | Fail closed unless a native runner proves profile loading, requested/observed identity and boundaries, timeout, child continuity, stale rejection, repair, and ownership blocking |
| `runtime_receipt.py` | Compare expected identity and boundaries with one explicit host session record |
| `phase_tracker.py` | Record schema-2 executor-owned intervals and export execution unions and cross-actor overlap without double-counting |
| `evidence_ledger.py` | Validate schema-5 phase evidence, preserve legacy readability without inventing retained Sol cost, require record-bound external claims for credible credits, and emit fail-closed task-family feedback |
| `matched_eval.py` | Freeze paired arms and reject mismatched starts, task specs, suites, policies, and metric cohorts |
| `allowance_meter.py` | Quantify conservative Sol-only versus Sol-Luna advantage from matched five-hour and weekly plan-limit percentage readings |
| `allowance_campaign.py` | Pre-register route order, atomically record route-only meter intervals, recover active arms, report excluded referee gaps, and assess completed pairs |
| `benchmark_identity.py` | Bind host-observed Sol/Luna models, effort, and an explicitly pre-registered writer-pool shape while rejecting logical receipt reuse |
| `benchmark_attestation.py` | Deterministically bind a completed allowance campaign, verified identity index, and frozen benchmark contract into one redacted attestation |
| `credit_model.py` | Estimate purchased credits from classified phase usage and a fingerprinted rate card; never convert included plan percentages |
| `frontier_planner.py` / `frontier_cli.py` | Project deterministic queues and a repair-first retained-domain Luna envelope without ever dispatching work |
| `handoff_preflight.py` / `handoff_preflight_cli.py` | Expose candidate-bound missing, failed, stale, scope, and risk evidence before Sol review without ever accepting work |
| `candidate_snapshot.py` | Read-only content-addressed snapshot and verification of the exact Git candidate |
| `compact_protocol.py` | One-time manifest freeze with strict `MAN` reference and `RUN`/`OK`/`BLOCK` handoff lines |
| `communication_audit.py` | Optional offline communication diagnostic; transcripts and provider counters are captured outside normal messages and measured route intervals, and never authorize routing or included-plan conclusions |

Snapshot a candidate relative to `HEAD` (or an explicit commit), then verify its `candidate_digest` without staging or writing:

```powershell
python -B .agents/skills/sol-luna/scripts/candidate_snapshot.py snapshot --repo .
python -B .agents/skills/sol-luna/scripts/candidate_snapshot.py verify --repo . --expected sha256:LOWERCASE_DIGEST
```

### Production ownership and phase schemas

Ownership plan schema 2 is the production format: a frozen route registers each executor and its fixed actor, assigns every work unit and acceptance explicitly, and places each exactly once in an executor-consistent partition whose paths are the exact normalized union of its contents. `partition_digest(plan)` hashes the canonical, order-independent plan. Ownership schema 1 remains readable under its original package-overlap rules, but it is not silently upgraded into a complete production partition.

Phase journal schema 2 is the production write format. Every production interval carries an explicit executor and unique interval ID; open intervals and closed intervals remain separately replayable, including concurrent intervals. Legacy journals may be loaded, validated, and exported read-only, but production `start`, `stop`, and `run` writes reject them.

Execution metrics use half-open intervals `[start, end)`: `executor_execution_union_seconds` merges overlapping or adjacent execution for each executor, `execution_union_seconds` merges all execution, and `execution_overlap_seconds` measures only cross-actor execution overlap. Planning, review, repair, and integration are not execution; in particular, review never inflates overlap. These unions are auditable execution measures, not a claim about end-to-end wall-clock duration.

The matched harness binds each pair to the same starting candidate, task digest, independent acceptance-suite digest, policy fingerprint, and observed runtime identity. It does not launch paid model work. See [runtime and evidence details](.agents/skills/sol-luna/references/evidence-and-runtime.md) and [the orchestration policy](.agents/skills/sol-luna/references/orchestration-policy.md).

Complete-Luna validation uses one Luna implementation loop with targeted checks and one final authoritative full suite; Sol verifies the candidate snapshot and causal coverage, rerunning only the smallest check triggered by drift, incomplete evidence, nondeterminism, failure, repair, or material security/platform risk. If Luna cannot access the authoritative environment, Luna performs causal/targeted checks and Sol runs that environment once; the common external referee remains outside route intervals.

The compact handoff protocol writes and reads one frozen manifest reference (`MAN|<package_ref>`); normal messages carry that reference followed by `RUN`/`OK`, only `BLOCK` expands, and it remains a projection rather than a second ownership or acceptance authority.

## Installation lifecycle

Preview is non-mutating:

```powershell
python scripts/setup.py preview
```

The default user Skill location is `<codex-home>/skills`, normally
`~/.codex/skills`. If the managed state records an older Skill under
`~/.agents/skills/sol-luna`,
inspect a state-bound migration plan instead of overwriting or manually
copying files:

```powershell
python scripts/setup.py migration-preview
python scripts/setup.py migrate --confirm --plan-fingerprint sha256:REVIEWED_PLAN
```

The fingerprint binds the repository source, every existing managed target,
and the complete legacy Skill tree. Migration recomputes it immediately before
writing, backs up only the exact installation assets it replaces or retires,
and fails if anything drifted after Preview. An explicitly overlapping or
unsafe skills root is rejected rather than deleting a newly written tree.
When many skills are installed, the initial skill list may omit some entries
because it is budgeted; restart Codex if a changed skill is not detected. See
the official [Codex skill discovery documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
Update any links or scripts that still point at the old `~/.agents/skills`
location; do not create a duplicate skill tree.

After reviewing the plan:

```powershell
python scripts/setup.py install --confirm
python scripts/setup.py doctor
python scripts/setup.py update --confirm
python scripts/setup.py rollback --confirm
```

Setup manages only the Sol-Luna Skill and named agent TOMLs. It uses source hashes, conflict refusal, atomic writes, backups, install state, post-write Doctor verification, and rollback refusal when a managed target has user drift. Tests use isolated temporary homes; this repository does not install itself during validation.

## Release safety

`v0.1.1` remains the pinned Latest release because it is the current user-validated baseline. Publish later milestones with `scripts/publish_release.py`; it refuses to proceed unless Latest is still `v0.1.1`, forces `--latest=false`, and verifies the pin again after publication. Omit `--confirm` for a non-mutating preview.

## Repository layout

```text
.agents/skills/sol-luna/
  SKILL.md
  references/
    orchestration-policy.md
    evidence-and-runtime.md
    allowance-benchmark.md
    routing-policy.v1.json
  scripts/
    routing_policy.py
    net_substitution.py
    closure_contract.py
    ownership_guard.py
    lifecycle_contract.py
    native_lifecycle_receipt.py
    runtime_receipt.py
    allowance_campaign.py
    benchmark_identity.py
    phase_tracker.py
    evidence_ledger.py
    matched_eval.py
.codex/agents/
  luna-worker-{low,medium,high,xhigh,max}.toml
  luna-reviewer.toml
  luna-scout.toml
scripts/setup.py
tests/
.github/workflows/ci.yml
```

## Validation boundary

Run:

```powershell
python -m unittest discover -s tests -v
python C:\path\to\skill-creator\scripts\quick_validate.py .agents\skills\sol-luna
git diff --check
```

When a native runner can emit the strict receipt, opt in with `SOL_LUNA_NATIVE_RECEIPT` and run `python -m unittest discover -s tests/live -v`. A missing receipt skips; an incomplete or self-reported receipt fails closed.

CI runs the behavioral suite on Windows and Ubuntu with Python 3.11 and 3.14. Tests cover predictive direct effort selection, hard quality/cost/time gates, writer caps, evidence-bound same-Luna closure and partial reclaim, review depth, runtime boundary mismatches, ownership conflicts, frozen handoffs, stale evidence, timeout and continuation states, atomic concurrent appends, phase reconciliation, matched-cohort isolation, and setup lifecycle.

These tests and the native app smoke do not prove routing economics. The completed five-pair campaign supplies diagnostic token and elapsed evidence, but no plan-limit readings; see the [objective completion audit](docs/validation/objective-completion-audit-2026-08-26.md). A subscription benchmark uses matched changes on the same account meters: five-hour percentage points are the higher-resolution primary measure, while weekly percentage points are reported separately as corroboration. Purchased-credit estimates and raw diagnostic tokens remain secondary and cannot be substituted for included allowance.

A locally bound claim index does not establish a Codex desktop task-level authenticated credit receipt. Without a cryptographically trusted provider verifier, externally bound ledger evidence may recommend human review but cannot raise the executable one-writer cap.

## Success gate

Within each task family, do not call the system improved unless a pre-registered matched campaign shows:

- independent acceptance remains equal or better;
- final defects do not increase;
- the conservative aggregate five-hour allowance advantage meets the declared benchmark threshold (10× for the first v0.1.1 comparison);
- total elapsed time is strictly lower;
- first-pass acceptance is at least 80%, keeping repair cost from consuming the saving;
- Sol planning and review remain less than half of measured delivery cost.
- the lower of `actual_sol_labor_reduction` and `structural_net_substitution` meets the pre-registered net-substitution floor; participation, package, action, and concurrency counts do not enter its benefit numerator.

Counterbalance route order and keep both arms in the same unchanged account windows. Each Sol-only arm is one complete top-level task in one continuous run by a single real Sol controller: Sol may decompose naturally, but the experiment controller must not pre-split, separately dispatch, or artificially serialize it. The common independent referee runs outside both route intervals; Luna-specific planning, review, integration, replay, and rework remain inside `SOL_LUNA`. Report referee cost separately and take a fresh reading before the next route. Weekly readings are never added to five-hour readings. Failed arms remain in every denominator. Benchmark evidence and `net_substitution.py` permit human review only; `automatic_execution_allowed` remains false.

## License

Copyright 2026 Edmund Dai.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution and the official project repository. The license does not grant permission to use the Licensor's trade names or product names except for customary attribution and origin notices.
