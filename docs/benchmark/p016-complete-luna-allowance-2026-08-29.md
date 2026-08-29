# P016 complete-Luna allowance benchmark — 2026-08-29

P016 tested the v0.19 complete-Luna envelope on one frozen cross-file refactor in the only formal checkout. Both routes used `gpt-5.6-sol/high`; Sol-Luna retained one `gpt-5.6-luna/xhigh` writer for the complete five-path package, while Sol-only used no subagents. Route work alone was inside each dashboard interval. Branch setup, commits, hidden acceptance, audit, and reporting were outside it. `Use reset` was not used.

| Route | Hidden groups | Five-hour meter | Weekly meter | Natural elapsed |
|---|---:|---:|---:|---:|
| Sol-Luna | 12/12 | 98% to 97%: 1 point | 67% to 67%: below display resolution | 24:14 |
| Sol-only | 9/12 | 95% to 93%: 2 points | 66% to 66%: below display resolution | 17:26 |

The Sol-Luna controller dispatched once, returned one focused repair to the same Luna, and performed no Sol rewrite or reclaim. Its candidate needed one non-semantic packaging correction after the interval: staging exposed a trailing blank line that unstaged `git diff --check` could not see. The corrected immutable candidate passed all 12 hidden groups.

Sol-only completed sooner and passed its 84 targeted plus 408 full tests, but failed three independent groups. Its fixed-name sibling loader created a second module instance when the evidence module had already been loaded under an arbitrary `importlib` name. That broke shared `PolicyError` and external-evidence marker identity, which in turn broke frozen-route and evidence-binding behavior. The Sol-Luna candidate used path-aware discovery plus a stable registry and passed the same loading order.

## Decision

Quality is a hard gate, so this is not an equal-quality matched win and the displayed 2:1 point ratio is not a universal savings claim. It is nevertheless direct task-local evidence that the complete-Luna route achieved more accepted functionality with lower included-plan consumption. The remaining regression is time: Sol-Luna was 6:48, or 39%, slower.

This supports an experimental non-Latest v0.19 release while `v0.1.1` remains GitHub Latest. Routing research is not finished: the next matched task should retain complete Luna ownership, shorten Sol's acceptance path, and seek an equal-quality allowance and time win before shifting the main effort to the high-density communication protocol.

## v0.12–v0.15 retrospective

| Change | Classification | Current judgment |
|---|---|---|
| v0.12 same-Luna closure and focused repair | Reduces repeated work | Keep the repair closure; do not attach the full closure document to ordinary success. |
| v0.13 live closure projection | Measurement/refusal guard | Keep as an optional diagnostic. It prevents invalid continuation but is not itself an allowance lever. |
| v0.14 repair-first frontier planner | Measurement/refusal guard with runtime burden | Keep the repair-first invariant; avoid generating full queue projections for a single complete package. |
| v0.15 candidate-bound handoff preflight | Reduces Sol rediscovery, with bounded runtime cost | Keep the compact boundary matrix; P008 and P016 both support risk-triggered rather than full replay review. |
| v0.15.1 Windows path test fix | Test-only | Keep; it adds no route-time protocol burden. |

The useful product thread across these versions is same-Luna repair plus candidate-bound, risk-triggered acceptance. The planners, ledgers, and projections belong in the diagnostic layer unless a concrete risk activates them.
