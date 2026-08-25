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
.codex/agents/
  luna-worker.toml
docs/benchmark/
  preliminary-comparison.md
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

## Validation boundary

The checked-in Skill passes the installed Skill Creator validator, and the TOML profile parses as `gpt-5.6-luna` with `max` reasoning. These are structural checks, not proof of routing behavior, runtime identity, implementation quality, or cost savings. Independent forward tests remain release work.

## Roadmap

Planned evaluation work:

1. Add forward scenarios for `SOL_ONLY`, `SOL_LUNA`, runtime-unknown, stale-evidence, failed-versus-blocked, and repair-budget behavior.
2. Add portable install, upgrade, conflict, and rollback lifecycle tests without overwriting user-modified configuration.
3. Compare Luna reasoning levels on matched bounded package families before changing the current `max` profile.
4. Record comparable tokens or credits, elapsed time, first-pass acceptance, and rework from clearly identified measurement sources.
5. Run matched tasks with an independent acceptance suite and blind review before changing the routing policy or claiming savings.

## License

No open-source license has been selected yet. The repository is public for inspection and collaboration planning, but reuse rights are not granted until a license is added.
