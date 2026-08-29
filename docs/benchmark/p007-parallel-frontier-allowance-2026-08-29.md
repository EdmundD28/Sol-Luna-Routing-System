# P007 parallel-frontier allowance benchmark — 2026-08-29

## Result

P007 is one directional matched pair, not a universal claim. Both routes passed the same frozen hidden referee at 10/10. Within the route-only dashboard intervals, `SOL_LUNA` consumed 0 displayed five-hour percentage points and `SOL_ONLY` consumed 1; weekly readings did not move in either route. `SOL_LUNA` was 200.336 seconds (20.78%) slower.

This supports the specific hypothesis that one retained Luna writer can replace expensive Sol implementation work when Sol concurrently owns a substantial disjoint integration lane. It does not establish a savings ratio because the dashboard is quantized to whole percentages and the delegated route's true consumption is only bounded below 1 point.

## Frozen contract

- Starting commit: `e41458993e188565fa2051ef4ac2093a807c7bc1` (`v0.13.0`).
- Task digest: `sha256:2a276aead6d7d8c34787e1b5e9dee13ab49c9f3a61d957a23ee6d4ff7fd1b086`.
- Hidden referee digest: `sha256:afaa43e919ecc2539933cb8816e868b73746c697f7f0291854d7e490069155df`.
- Frozen policy: version `1.6.0`, `sha256:c5ce52d96bf764ad16661b7022aef60982fd5ca238890168d1ba84b17ef3229f`.
- Route order: `SOL_ONLY`, then `SOL_LUNA`, selected before either route because the task digest's first hexadecimal digit was even.
- One formal checkout only; no clone, copy, or worktree.
- Controller and route-specific work ended before commit, hidden acceptance, independent audit, or branch switching.

## Route-only observations

| Route | Candidate | Sydney interval | Five-hour left | Weekly left | Elapsed | Hidden referee |
|---|---|---|---:|---:|---:|---:|
| `SOL_ONLY` | `13e9d6d859c5db541b87023886d04077693efaf1` | 12:36:45.335–12:52:49.624 | 98% → 97% | 80% → 80% | 964.289 s | 10/10 |
| `SOL_LUNA` | `cf95fad659e58e0dbc41670376d6a600ccbc63b0` | 12:53:39.579–13:13:04.204 | 96% → 96% | 79% → 79% | 1164.625 s | 10/10 |

The dashboard moved from 97%/80% after `SOL_ONLY` to 96%/79% before `SOL_LUNA`. That movement occurred outside both route intervals while the orchestrator committed the first candidate and ran the common referee. It is deliberately excluded from both routes. This is why controller-return review and referee work must not be charged to the route that already returned.

All four five-hour boundary readings stayed inside one reset window, and all weekly readings stayed inside one weekly window. `Use reset` was never selected.

## Host-observed identities

`runtime_receipt.py --require-identity` read one explicit session per actor. Every receipt had zero invalid JSONL lines and zero requested/observed mismatches:

| Actor | Host-observed provider/model/effort | Redacted source | Receipt SHA-256 |
|---|---|---|---|
| `SOL_ONLY` controller | OpenAI `gpt-5.6-sol/high` | `redacted:session:cf4150f2d2e0` | `d3baed3b0dce5f274175b9da3706638edf3c552fe5ea45da78eb6f8efb63d358` |
| `SOL_LUNA` controller | OpenAI `gpt-5.6-sol/high` | `redacted:session:41b8575f19de` | `987aae2d21df164bd3e9f7a2fc551931b8b3f2f234c6d58c1e6bfebddebb08a4` |
| retained writer | OpenAI `gpt-5.6-luna/high` | `redacted:session:82dc2ab2a7c1` | `3b6c9c3c38ef7025995978ef5b5c09e60a3de225f9b79082e797a27e31410d2e` |

The delegated controller created one Luna writer and reused that same child session for the first implementation and two evidence-backed repairs. Sol changed only the CLI, CLI tests, and README while Luna owned the planner and planner tests. Sol did not edit or reclaim Luna-owned files.

## Quality and integration decision

The common referee passed both immutable candidates at 10/10. A later independent source audit nevertheless found stricter POSIX-path problems in the `SOL_LUNA` candidate that the referee did not cover. Therefore equal referee score did not override source quality: integration started from the `SOL_ONLY` candidate, then adopted the delegated candidate's better delayed CLI loading and added new boundary tests.

The release candidate also makes approved same-Luna repair consume the Luna writer frontier before new Luna dispatch, while Sol-ready and review work remain available. Routing policy `1.7.0` records that invariant. The integrated candidate passes 357 repository tests (one existing skip), the frozen referee at 10/10, and `skill-creator/scripts/quick_validate.py .agents/skills/sol-luna`.

## Interpretation

The v0.13 cooperation direction was useful rather than accidental in this task: Luna implemented the larger planner lane while Sol concurrently completed a non-conflicting CLI and integration lane, and exact failures returned to the same retained Luna without Sol shadow implementation. That is the structural change the user asked for—more useful Luna participation and less repeated Sol work.

The evidence boundary remains strict:

- One pair cannot prove general superiority or a 10–20× ratio.
- `0` displayed points means less than the dashboard's 1-point resolution, not zero underlying consumption.
- The elapsed regression is real for this pair.
- The positive allowance direction should be replicated on another high-throughput, path-disjoint task before widening automatic routing.
