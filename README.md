# Sol-Luna Delivery System

An experimental, explicit Codex Skill that predicts whether bounded GPT-5.6 Luna execution can reduce the credits and elapsed time of an independently accepted result while Sol retains architecture, integration, and final judgment.

The objective is not to maximize delegation. Quality, safety, ownership, and authority are hard gates; `SOL_ONLY` is correct whenever expected Sol coordination, Luna recovery, review, or integration would erase the saving.

## Status

This revision adds executable policy and evidence controls. It is still an experimental baseline, not a proven cost optimizer or a filesystem security boundary.

- Predictive routing compares Sol-only delivery with Luna `low`, `medium`, `high`, `xhigh`, and `max` using expected accepted-result credits and time. The user-facing word `light` is accepted as an alias for Codex `low`.
- A lower-effort failure is not required before direct XHigh or Max selection.
- Production routing defaults to one active Luna writer, but that writer may roll through multiple ready packages from one complete, single-owner allocation. A second active writer remains benchmark-only until matched plan-meter evidence supports an explicit policy release.
- Rework is limited to one evidence-backed focused repair, then repartition, one effort escalation, or Sol reclaim.
- Risk-proportional review avoids replaying clean low-risk work while requiring deep review for material risk and discrepancies.
- Runtime receipts compare expected identity and boundary values with host-observed records.
- Ownership, frozen handoffs, lifecycle transitions, phase evidence, atomic ledger writes, and matched cohorts have executable validators.
- Evidence-ledger schema 5 requires retained Sol execution in new matched Sol-Luna records. Older schemas remain readable with their origin preserved but cannot satisfy the current measurement-policy gate. Schema 4 credit trust remains fail-closed: self-declared exact sources cannot pass, and claim-index schema 2 binds each external claim to the complete normalized record and a unique receipt. The ledger does not validate provider signatures or collect Codex desktop billing data.
- A five-pair matched bounded-function campaign achieved equal independent acceptance and zero final defects, but Sol→Luna regressed to 4.08× the median diagnostic tokens and 5.42× the median elapsed time. It did not capture five-hour or weekly plan-limit readings, so it cannot decide subscription-allowance economics.
- A later [matched allowance pilot p002](docs/benchmark/matched-allowance-p002-2026-08-28.md) found that two Luna High writers failed equal acceptance, consumed no less displayed five-hour allowance, and were 4.72% slower. The subsequent [p003 campaign](docs/benchmark/matched-allowance-p003-2026-08-28.md) found only a displayed 1.25× five-hour advantage for fixed one-package Sol-Luna, with worse quality and 31.2% longer elapsed time. Policy 1.4.0 therefore keeps one active Luna while allowing higher rolling delegated coverage from a complete allocation; that mechanism still needs a new matched campaign.
- Local lifecycle tests validate the state machine. A [native desktop-app smoke](docs/validation/native-app-lifecycle-smoke-2026-08-26.md) exercised real Luna delegation, one repair, stale-evidence rejection, timeout/interruption, same-child continuation, and pre-dispatch ownership conflict rejection. It did not prove that the packaged custom TOML profile was loaded; the automated opt-in runner remains unavailable until Codex exposes a stable non-interactive custom-subagent surface.

See [the p003 allowance campaign](docs/benchmark/matched-allowance-p003-2026-08-28.md), [the p002 allowance pilot](docs/benchmark/matched-allowance-p002-2026-08-28.md), [the matched bounded-function campaign](docs/benchmark/matched-bounded-campaign-2026-08-26.md), and the [older preliminary comparison](docs/benchmark/preliminary-comparison.md).

## Core workflow

Invoke explicitly:

```text
$sol-luna <substantial task>
```

Sol estimates each eligible route before dispatch. Policy `1.4.0` requires at least 80% predicted first-pass acceptance, no predicted final-defect regression, at least 50% expected accepted-cost reduction by default, and no expected elapsed regression. It starts from one active Luna at the lowest task-supported effort, evaluates complete Sol/Luna allocations with structurally unique acceptance ownership, and may increase Luna's rolling package coverage without increasing active concurrency. It selects the lowest expected accepted-delivery cost—not automatically the lowest effort or highest coverage. It is a route guard; only matched account-meter readings prove subscription-allowance savings.

```powershell
python .agents/skills/sol-luna/scripts/routing_policy.py template
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --input route.json
python .agents/skills/sol-luna/scripts/routing_policy.py evaluate --ledger runtime/sol-luna/ledger.jsonl --verified-credit-receipts runtime/sol-luna/verified-credit-receipts.json --input route.json
python .agents/skills/sol-luna/scripts/routing_policy.py review --input review.json
python .agents/skills/sol-luna/scripts/routing_policy.py rework --input rework.json
python .agents/skills/sol-luna/scripts/routing_policy.py fingerprint
```

The policy is advisory and never launches a worker automatically. Missing estimates stay unknown; Sol can retain the task or run a short read-only scout probe.

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
| `ownership_guard.py` | Validate frozen schema-2 executor/unit/acceptance partitions and their deterministic digest while preserving schema-1 plan checks |
| `lifecycle_contract.py` | Replay package transitions, stale evidence, timeout, repair, escalation, continuation, and acceptance |
| `native_lifecycle_receipt.py` | Fail closed unless a native runner proves profile loading, requested/observed identity and boundaries, timeout, child continuity, stale rejection, repair, and ownership blocking |
| `runtime_receipt.py` | Compare expected identity and boundaries with one explicit host session record |
| `phase_tracker.py` | Record schema-2 executor-owned intervals and export execution unions and cross-actor overlap without double-counting |
| `evidence_ledger.py` | Validate schema-5 phase evidence, preserve legacy readability without inventing retained Sol cost, require record-bound external claims for credible credits, and emit fail-closed task-family feedback |
| `matched_eval.py` | Freeze paired arms and reject mismatched starts, task specs, suites, policies, and metric cohorts |
| `allowance_meter.py` | Quantify conservative Sol-only versus Sol-Luna advantage from matched five-hour and weekly plan-limit percentage readings |
| `allowance_campaign.py` | Pre-register route order, atomically record route-only meter intervals, recover active arms, report excluded referee gaps, and assess completed pairs |
| `benchmark_identity.py` | Bind host-observed Sol/Luna models, effort, and an explicitly declared one- or two-writer benchmark shape while rejecting logical receipt reuse |
| `benchmark_attestation.py` | Deterministically bind a completed allowance campaign, verified identity index, and frozen benchmark contract into one redacted attestation |
| `credit_model.py` | Estimate purchased credits from classified phase usage and a fingerprinted rate card; never convert included plan percentages |

### Production ownership and phase schemas

Ownership plan schema 2 is the production format: a frozen route registers each executor and its fixed actor, assigns every work unit and acceptance explicitly, and places each exactly once in an executor-consistent partition whose paths are the exact normalized union of its contents. `partition_digest(plan)` hashes the canonical, order-independent plan. Ownership schema 1 remains readable under its original package-overlap rules, but it is not silently upgraded into a complete production partition.

Phase journal schema 2 is the production write format. Every production interval carries an explicit executor and unique interval ID; open intervals and closed intervals remain separately replayable, including concurrent intervals. Legacy journals may be loaded, validated, and exported read-only, but production `start`, `stop`, and `run` writes reject them.

Execution metrics use half-open intervals `[start, end)`: `executor_execution_union_seconds` merges overlapping or adjacent execution for each executor, `execution_union_seconds` merges all execution, and `execution_overlap_seconds` measures only cross-actor execution overlap. Planning, review, repair, and integration are not execution; in particular, review never inflates overlap. These unions are auditable execution measures, not a claim about end-to-end wall-clock duration.

The matched harness binds each pair to the same starting candidate, task digest, independent acceptance-suite digest, policy fingerprint, and observed runtime identity. It does not launch paid model work. See [runtime and evidence details](.agents/skills/sol-luna/references/evidence-and-runtime.md) and [the orchestration policy](.agents/skills/sol-luna/references/orchestration-policy.md).

## Installation lifecycle

Preview is non-mutating:

```powershell
python scripts/setup.py preview
```

The default user Skill location is `~/.agents/skills`. If Preview reports a
legacy user Skill under `~/.codex/skills/sol-luna`,
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
Update any links or scripts that still point at the old `~/.codex/skills`
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

CI runs the behavioral suite on Windows and Ubuntu with Python 3.11 and 3.14. Tests cover predictive direct effort selection, hard quality/cost/time gates, writer caps, rework limits, review depth, runtime boundary mismatches, ownership conflicts, frozen handoffs, stale evidence, timeout and continuation states, atomic concurrent appends, phase reconciliation, matched-cohort isolation, and setup lifecycle.

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

Counterbalance route order and keep both arms in the same unchanged account windows. Measure each route only from its settled pre-launch reading until that tested agent returns. Run the experiment controller's independent acceptance, commit, branch restoration, and next-arm preparation outside both route intervals, report that referee cost separately, and take a fresh reading before the next route. Weekly readings are never added to five-hour readings. Failed arms remain in acceptance, defect, and first-pass denominators. Benchmark evidence permits human review only; it never dispatches work or edits policy automatically.

## License

Copyright 2026 Edmund Dai.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution and the official project repository. The license does not grant permission to use the Licensor's trade names or product names except for customary attribution and origin notices.
