# Matched Bounded-Function Campaign — 2026-08-26

## Verdict

This five-pair token cohort rejects the economic case for Sol→Luna on this task family. Both routes achieved 100% independent acceptance, zero final defects, and 100% first-code-attempt acceptance, but Sol→Luna used substantially more diagnostic tokens and elapsed time in every pair.

It does **not** prove a credit result. Codex diagnostic token totals are not credits, cached input is included, and no authoritative token-to-credit conversion was available.

## Frozen comparison

- Campaign: `bounded-functions-v1`
- Task family: `bounded-python-function`
- Starting commit: `48dd16e910fcacd78484d53e6a9174b5021272aa`
- Plan fingerprint: `sha256:ad6c8b5f1d3193611248f6a5ee717d5e86055aa900102605190e39a9b144f573`
- Policy fingerprint: `sha256:7500c2404cf715fccbf3ac0c6b2ad41eaae92072c22af7b89b503ec222778dd6`
- Independent suite: `bounded-hidden-v1`, `sha256:4e0628087fdcf3fbbe88d16073173b800d247596b6edc4828ef514fd49cab875`
- Arm order was counterbalanced. Each arm used a fresh worktree from the same commit.

## Results

| Pair | Task | Initial Luna effort | Sol-only tokens | Sol→Luna tokens | Token ratio | Sol-only elapsed | Sol→Luna elapsed | Elapsed ratio | Sol coordination share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | canonical slug | low | 148,283 | 405,206 | 2.73× | 46.642 s | 205.141 s | 4.40× | 49.46% |
| 002 | interval merge | low | 97,962 | 455,816 | 4.65× | 32.673 s | 223.626 s | 6.84× | 37.76% |
| 003 | duration parser | medium | 99,246 | 532,006 | 5.36× | 46.041 s | 242.263 s | 5.26× | 34.99% |
| 004 | stable unique | low | 97,478 | 237,120 | 2.43× | 32.272 s | 139.275 s | 4.32× | 53.65% |
| 005 | dependency layers | low | 102,320 | 205,724 | 2.01× | 37.848 s | 150.268 s | 3.97× | 52.41% |

Campaign medians:

- Sol-only: 99,246 tokens and 37.848 seconds.
- Sol→Luna: 405,206 tokens and 205.141 seconds.
- Ratio of medians: 4.08× tokens and 5.42× elapsed time.
- Ledger median paired token reduction: `-173.27%`; negative means regression.
- Ledger median elapsed delta: `+158.499 seconds`.
- Median Sol planning-plus-review share: `49.46%`.

All ten candidates passed the same independent suite. There were no code repair rounds. Several agents wrote faulty shell-side test probes and corrected those probes without changing candidate code; those incidents increased time and tokens but were not counted as implementation repairs.

## Integrity correction

The first four attempted delegated arms were discarded. Their agent names and requested roles said Luna, but native `turn_context` recorded `gpt-5.6-sol`. The authentic reruns used the host-enforced Codex CLI model selector for `gpt-5.6-luna`, followed by separate Sol review. This failure directly motivated schema v3 runtime-identity requirements in the ledger and matched evaluator.

The CLI did not emit a provider-side model echo, so the runtime-identity receipt records that uncertainty explicitly. The host-enforced model selector is stronger than an agent label or self-report, but weaker than a service-returned model identifier.

## Decision

For this narrow bounded-function family, keep the route `SOL_ONLY`. Do not spend another Luna cycle merely because delegation is available. The work is too small for planning, context loading, worker verification, and Sol review to amortize.

Do not generalize this result to larger parallelizable packages. A future campaign should target tasks large enough for Luna execution to dominate fixed coordination cost, while preserving the same frozen-start, runtime-identity, independent-acceptance, phase, and metric-cohort controls.

The status tool correctly reports `policy_change_eligible: false`: credible credit reduction is missing and elapsed time regressed. No automatic routing update is authorized.

## Evidence location

The runtime campaign plan, isolated worktrees, acceptance suite, and schema-v3 ledger remain under the ignored local `runtime/sol-luna/campaign/` directory. They contain no publishable private prompts, but they are intentionally not treated as release fixtures.
