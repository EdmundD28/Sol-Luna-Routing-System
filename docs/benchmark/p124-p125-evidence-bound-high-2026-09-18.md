# P124/P125 evidence-bound High ablation

Status: `HOLD_V0.38.3_FOR_THIS_TASK_FAMILY`. No product change or release.

## Question

P124 used a new architecture-complete rollout-planner task to test whether a
larger Luna-owned package could amortize the remaining Sol controller envelope.
After the frozen Luna Medium route failed public quality 24/25 following its one
repair, P125 reused the same task as development data and changed only Luna
effort to High. This is the exact lower-effort failure premise required by the
v0.38.0 effort gate; task-risk labels alone did not authorize escalation.

Both Sol-Luna routes used a fresh `gpt-5.6-sol/high` controller, one retained
writer, an empty Sol implementation queue, one final full-suite executor, no
Sol rewrite or reclaim, and the same frozen task, baseline, public suite, hidden
referee, ownership, and official purchased-credit-equivalent rate card. The
baseline Sol-only route used no worker. No included-plan percentage was read.

## Results

| Route | Public | Hidden | Credit-equivalent proxy | Controller elapsed |
|---|---:|---:|---:|---:|
| Sol-only | 25/25 | 12/12 | 11.160600 | 243.823 s |
| v0.38.3 + Luna Medium | 24/25 after one repair | not run | 4.614559 diagnostic | 284.885 s diagnostic |
| v0.38.3 + Luna High | 25/25 | 12/12 | 3.893229 | 381.235 s |

Medium was 58.653% cheaper than Sol-only but failed the quality gate and was
16.841% slower. Its first candidate misclassified a frozen dependency fixture;
the only repair corrected the code but retained one extra error-path index.

High recovered equal measured quality and was 65.116% cheaper than Sol-only.
It remained in one writer turn and was 15.632% cheaper than the failed Medium
route, but it was 137.412 seconds, or 56.357%, slower than Sol-only. The writer
needed three pre-final changed-area test commands plus one diagnostic before the
only final full suite. That debugging work is included, not normalized away.

## Infrastructure censor

The first P125 attempt stopped before task/test reads, edits, or tests because
the newly created branch's HEAD, ref, and index were all-zero files. Old refs,
objects, and reflog remained intact. The pointers were restored to the
reflog-proven frozen commit and the index was rebuilt from HEAD; `git fsck` and
a clean status then passed. A new identifier and branch were used for the
measured attempt. The censored attempt contributes no product evidence.

## Decision

The v0.38.0 rule is directionally correct: High was withheld until matched
lower-effort quality failure existed, then recovered quality without erasing the
large credit-equivalent saving. It is not sufficient for the full product goal:
High failed the no-time-regression gate by a wide margin. Do not make High the
default, add another repair, or add routing fields from this sample.

The next candidate must reduce Luna's initial defect-discovery time without
adding Sol controller work, repeated full suites, another worker, or a normal-
path protocol artifact. P124/P125 are now development data. Any future product
claim requires a different frozen unseen task and still must pass quality,
credit, and elapsed gates together.

This single task family does not prove general or included-plan superiority.
