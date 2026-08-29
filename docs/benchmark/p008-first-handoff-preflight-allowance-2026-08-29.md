# P008 first-handoff preflight allowance pilot

P008 tested whether moving a compact contract-boundary preflight into Luna's first handoff could preserve Luna ownership, reduce Sol rediscovery, and improve included-plan allowance consumption. It is one directional field pair, not a task-family policy claim.

## Frozen comparison

- Starting commit: `a2b05100e17de466c8fbe0b43ef0be3a66f1798c` (`v0.14.0`).
- Task digest: `sha256:a2b23d2b73de7c1183ad399b091dc92f35a088da99df69a353e4d10812b0bf4a`.
- Independent referee digest: `sha256:7b917fc885a8cd42460b4f1693a000b0e2244d8632dd36e393e2aff36c008266`.
- One formal repository and two sequential branches; no clone, copy, checkout, or worktree was created.
- Both controllers were host-observed OpenAI `gpt-5.6-sol/high`.
- `SOL_ONLY` used no child. `SOL_LUNA` used one retained host-observed OpenAI `gpt-5.6-luna/high` writer.
- The same five-hour and weekly reset windows covered all four route boundaries. `Use reset` was never selected.
- Commit, referee, source audit, and branch switching were outside both measured route intervals.

The Sol-Luna allocation froze Luna ownership of the core preflight module and its tests. Sol concurrently owned the CLI, CLI tests, and README entry. Luna had to test schema/types, boundaries, capacity, derived values, immutability, and error-channel behavior before first handoff. Exact new evidence returned to the same Luna.

## Observed routes

| Route | Sydney interval | Five-hour left | Weekly left | Elapsed | Referee | Route candidate |
|---|---:|---:|---:|---:|---:|---|
| `SOL_ONLY` | 14:20:56–14:33:00 | 90% → 88% | 79% → 78% | 12:04 | 9/10 | `a90470ee6f802e0f9f01585b43c12fa043bcfff3` |
| `SOL_LUNA` | 14:33:58–14:54:41 | 88% → 88% | 78% → 78% | 20:43 | 10/10 | `f59848ac27f2e93806765ca3157e591cc99e9ebc` |

The 58-second between-route gap showed no displayed meter change and belongs to neither route. The five-hour reset countdown moved from 3h 1m before the first route to 2h 27m after the second, so no reset crossed a boundary.

At dashboard resolution, Sol-only consumed 2 displayed five-hour percentage points and 1 weekly point; Sol-Luna showed no displayed decrease. A ratio cannot be computed from a zero displayed denominator. The result is a directional allowance signal, not a precise multiplier.

Sol-Luna was 8:39, or 71.7%, slower. It used one same-Luna repair round, down from P007's two, without shrinking Luna ownership or causing Sol to replay the core implementation.

## Quality and audit boundary

The routes were not quality-equal. The frozen Sol-only candidate accepted `src/con .txt` and scored 9/10. Its commit also failed a fresh `git diff --check` because a test file gained an extra terminal blank line.

The frozen Sol-Luna candidate scored 10/10, but independent source review found a referee gap: it accepted the reserved-device stream path `src/core/nul:stream`, and an isolated Unicode surrogate leaked `UnicodeEncodeError` instead of `PreflightError`. The release candidate therefore uses the Sol-Luna implementation only after a separately recorded, route-external hardening repair and fresh acceptance. The original route result is not rewritten.

No evidence of hidden-suite access, hidden constants, or suspicious copying was found in either candidate. Both changed only the five allowed paths.

## Why diagnostic token counts were excluded

Host session diagnostic token counters moved in the opposite direction from the included-plan dashboard: the Sol-Luna controller plus Luna writer reported substantially more diagnostic token traffic while the five-hour and weekly displays did not decrease. This comparison therefore does not support using diagnostic token counts as a proxy for Codex subscription allowance consumption. P008 compares only the user-visible included-plan percentage boundaries; purchased-credit estimates remain a separate metric.

## Decision

P008 is a real stage improvement in orchestration: it increased Luna's implementation ownership, reduced repair round trips, avoided Sol replay, produced the stronger audited candidate, and showed a 2-point displayed five-hour allowance advantage. It did not improve elapsed time and did not produce an equal-quality matched pair. The result justifies shipping the candidate-bound first-handoff preflight as an experimental non-Latest release, while keeping `v0.1.1` pinned as GitHub Latest and continuing matched allowance work.
