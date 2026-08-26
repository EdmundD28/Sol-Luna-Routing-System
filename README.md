# Sol-Luna Delivery System

An experimental, explicit Codex Skill for cost-aware two-tier delivery with one accountable Sol controller and optional, dynamically selected GPT-5.6 Luna workers.

Sol first chooses `SOL_ONLY` or `SOL_LUNA`. Sol owns architecture, scheduling, integration, verification, and final acceptance in either route. Luna workers receive only bounded, conflict-free implementation or verification packages. The workflow uses a rolling pipeline so Sol can review frozen handoffs and prepare acceptance tests while other ready packages continue.

## Status

This repository is an experimental public baseline, not a proven cost-saving product.

- The current Skill and Luna worker profile are published as the source of truth for future development.
- The current stability revision adds explicit Sol-only fallback, runtime evidence receipts, final-candidate evidence freshness, bounded repairs, and distinct failed-versus-blocked outcomes.
- One preliminary paired run found the earlier Sol-Luna workflow was 2.62x slower than Sol-only on that task.
- The paired run did not capture comparable credit usage and did not use an independent hidden acceptance suite.
- The current rolling-pipeline revision was created after that run and has not yet been evaluated by the same protocol.

See [the preliminary comparison](docs/benchmark/preliminary-comparison.md).

## Repository layout

```text
.agents/skills/sol-luna/
  SKILL.md
  agents/openai.yaml
  references/evidence-and-runtime.md
  scripts/runtime_receipt.py
  scripts/evidence_ledger.py
.codex/agents/
  luna-worker.toml
docs/benchmark/
  preliminary-comparison.md
docs/design/
  upstream-influences.md
tests/
  test_runtime_receipt.py
  test_evidence_ledger.py
```

## Invocation

The Skill is explicit-only:

```text
$sol-luna <substantial task>
```

Invocation does not force delegation. Small, tightly coupled, or inherently serial work can remain `SOL_ONLY`; Luna is used only when a bounded package is expected to improve accepted delivery.

## Design principles

- Optimize accepted delivery, not agent count.
- Treat `SOL_ONLY` as a valid outcome rather than forcing ceremonial delegation.
- Use the minimum economically justified parallelism.
- Give each worker exclusive write ownership and minimal sufficient context.
- Freeze worker output at handoff so Sol reviews a stable candidate.
- Distinguish requested, configuration-derived, host-observed, and unknown runtime facts.
- Invalidate affected validation evidence after the checked candidate changes.
- Reserve `BLOCKED` for missing authority, decisions, inputs, permissions, or external-state changes; report in-scope failures as failures.
- Treat worker summaries as claims; Sol independently inspects and verifies the result.
- Never claim token, credit, latency, or quality improvements without comparable measurements.

## Optional evidence tools

The stability revision includes two standard-library Python tools. They are not mandatory overhead for every invocation:

- `runtime_receipt.py` converts one explicitly supplied Codex session JSONL into an allowlisted, redacted requested-versus-host-observed receipt. Strict identity and boundary checks are opt-in.
- `evidence_ledger.py` validates and appends opt-in redacted run records, then checks whether at least five clean matched pairs are ready for human review. It never changes routing.

See [the runtime and evidence contract](.agents/skills/sol-luna/references/evidence-and-runtime.md) and [the upstream design review](docs/design/upstream-influences.md).

## Validation boundary

The checked-in Skill passes the installed Skill Creator validator, and the TOML profile parses as `gpt-5.6-luna` with `max` reasoning. Behavioral tests cover redaction, self-report exclusion, conflicting runtime evidence, failed-versus-blocked outcomes, repair exceptions, acceptance-suite matching, and the five-pair human-review gate. These tests validate the tools and contracts; they do not prove native worker routing, implementation quality, or cost savings.

## Roadmap

Planned evaluation work:

1. Add native worker lifecycle scenarios for `SOL_ONLY`, `SOL_LUNA`, stalled workers, and final-candidate evidence refresh.
2. Add portable install, upgrade, conflict, and rollback lifecycle tests without overwriting user-modified configuration.
3. Compare Luna reasoning levels on matched bounded package families before changing the current `max` profile.
4. Populate the opt-in ledger with comparable real measurements from clearly identified sources.
5. Run matched tasks with an independent acceptance suite and blind review before changing the routing policy or claiming savings.

## License

No open-source license has been selected yet. The repository is public for inspection and collaboration planning, but reuse rights are not granted until a license is added.
