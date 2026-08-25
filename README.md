# Sol-Luna Delivery System

An experimental, explicit Codex Skill for cost-aware delivery with one accountable Sol controller and dynamically selected GPT-5.6 Luna workers.

Sol owns architecture, scheduling, integration, verification, and final acceptance. Luna workers receive bounded, conflict-free implementation or verification packages. The workflow uses a rolling pipeline so Sol can review frozen handoffs and prepare acceptance tests while other ready packages continue.

## Status

This repository is an experimental public baseline, not a proven cost-saving product.

- The current Skill and Luna worker profile are published as the source of truth for future development.
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
$sol-luna <substantial, parallelizable task>
```

Small, trivial, or inherently serial work should remain direct.

## Design principles

- Optimize accepted delivery, not agent count.
- Use the minimum economically justified parallelism.
- Give each worker exclusive write ownership and minimal sufficient context.
- Freeze worker output at handoff so Sol reviews a stable candidate.
- Treat worker summaries as claims; Sol independently inspects and verifies the result.
- Never claim token, credit, latency, or quality improvements without comparable measurements.

## Validation boundary

The checked-in TOML profile parses as `gpt-5.6-luna` with `max` reasoning. Full Skill Creator validation and independent forward tests remain release work.

## Roadmap

The next design decision is whether to build on an existing evidence-gated orchestration project, particularly Codex PROVE, while retaining this project's rolling scheduling and measurement focus.

Planned evaluation work:

1. Add structured requirement, task, handoff, failure, and evidence contracts.
2. Prove actual agent/model/effort/permission routing at runtime.
3. Add a bounded repair and timeout state machine.
4. Record comparable tokens or credits, elapsed time, first-pass acceptance, and rework.
5. Run matched tasks with an independent acceptance suite and blind review.

## License

No open-source license has been selected yet. The repository is public for inspection and collaboration planning, but reuse rights are not granted until a license is added.
