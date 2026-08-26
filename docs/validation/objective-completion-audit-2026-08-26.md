# Objective completion audit — 2026-08-26

This audit separates implemented controls from measured economic improvement. It uses the current worktree, the 76-test local suite, Skill validation, and the frozen five-pair campaign. No additional model benchmark was run for this audit.

## Numbered requirements

| Item | Verdict | Authoritative evidence |
|---|---|---|
| P0.1 Executable routing economics | Implemented | `routing_policy.py` evaluates Sol execution, Sol coordination/review/integration, Luna execution, expected recovery, quality, defects, credits, and elapsed time; routing tests cover hard gates and direct XHigh selection. |
| P0.2 Matched evaluation harness | Implemented | `matched_eval.py` freezes start, task, acceptance suite, policy, arm order, and runtime identity; the five-pair campaign exercised both arms. |
| P0.3 Predictive Luna effort ladder | Implemented | Versioned policy and effort-specific profiles cover Low, Medium, High, XHigh, and Max. A lower-tier failure is not required before a higher initial selection. |
| P0.4 Rework budget | Implemented | Policy and lifecycle validators allow one evidence-backed repair, then repartition, one escalation, or Sol reclaim. |
| P0.5 Initial writer cap | Implemented | The default cap is two; expansion requires validated ledger feedback from at least five matched pairs under the current policy fingerprint, with elapsed improvement and no credit or failure regression. Caller-supplied route numbers cannot unlock expansion. |
| P1.6 Phase evidence | Implemented | `phase_tracker.py` and ledger schema v3 distinguish `sol_planning`, `sol_execution`, `luna_execution`, `sol_review`, `repair`, and `integration`; wall-clock elapsed remains separate from potentially overlapping active-phase durations. Token and credit totals reconcile additively. |
| P1.7 Risk-proportional review | Implemented | Targeted, Standard, and Deep review decisions are executable and tested. |
| P1.8 Runtime boundaries and ownership | Implemented as acceptance guards | Runtime receipts compare expected and host-observed identity/boundaries. Ownership plans and changed paths fail closed. These are not an OS security boundary. |
| P1.9 Native lifecycle tests | Implemented within the available host boundary | Local lifecycle tests cover dispatch, repair, stale evidence, timeout, continuation, and conflicts. The opt-in native receipt fails closed when the host cannot prove profile loading and child identity. |
| P1.10 Atomic cohort-aware ledger | Implemented | Cross-process locking, atomic replacement, duplicate detection, metric-source cohorting, runtime identity, exact-credit precedence, and failure-inclusive acceptance/defect gates are tested. |
| P2.11 Short core Skill | Implemented | `SKILL.md` is about 950 words; uncommon procedures live in routed references. |
| P2.12 Minimal profiles | Implemented | Worker effort variants plus one read-only reviewer and one bounded scout; no additional role taxonomy. |
| P2.13 Setup lifecycle, CI, fingerprints | Implemented | Preview/install/update/Doctor/rollback, Windows and Ubuntu CI, and versioned policy fingerprints are present and tested. |
| P2.14 Open-source licence | Conditional requirement not triggered | No external-reuse intent was supplied. The repository explicitly grants no reuse rights; a licence becomes required only if the owner later chooses external reuse. Do not silently infer MIT, Apache-2.0, or another legal intent. |

## Economic success gates

For the `bounded-python-function` campaign:

| Gate | Result |
|---|---|
| Independent acceptance equal or better | Passed: both routes accepted 5/5. |
| Final defects do not increase | Passed: zero recorded defects in both arms. |
| Median credits fall by at least 15% | Not proven: only diagnostic token totals were available. |
| Median elapsed time does not regress | Failed: Sol→Luna median paired elapsed delta was **+158.498615 seconds**. |
| First-pass acceptance at least 80% | Passed: both routes were 100%. |
| Sol planning and review are a minority | Diagnostic pass only: median token share was 49.4627%; credible credit share is unavailable. |

The ledger feedback posture is therefore `HOLD_SOL_ONLY`, with no supported Luna effort for this task-family policy. This is the correct controller behavior: retain a route that fails the economic gates instead of decorating it with a victory banner.

## Remaining priority

1. Keep bounded tiny Python-function work in Sol. Do not spend more quota proving the same negative result.
2. Collect credible credit telemetry opportunistically from ordinary authorized work if the host later exposes it; do not manufacture conversions from tokens or allowance percentages.
3. Re-evaluate a materially different task family only when the expected saving can plausibly exceed Sol coordination and review overhead, and only when the user authorizes the cost.
4. Add a licence only if the owner later declares that external reuse is intended.

Overall verdict: the P0–P2 implementation objective is complete and locally verified. The separate product-level claim “Sol–Luna improves cost and time” is **not achieved and is not made**. Existing evidence contradicts that claim for the tested tiny-task family, so the completed feedback controller correctly retains that family in Sol.
