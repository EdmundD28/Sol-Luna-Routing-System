# Native App Lifecycle Smoke — 2026-08-26

## Scope

This was a live Codex collaboration smoke in the current desktop task, not a deterministic simulator. The parent explicitly requested `gpt-5.6-luna` for both children. It proves app-level delegation behavior observed in this task; it does **not** prove that the repository's custom `.codex/agents/*.toml` profile was loaded, because the host did not expose a strict identity receipt for these collaboration calls.

## Observed lifecycle

| Case | Live observation | Result |
|---|---|---|
| Delegation | A Luna child received a bounded, read-only two-line candidate inspection. | Real child dispatch occurred. |
| First pass | The relative path was resolved from the workspace root instead of the nested repository root. The child returned empty values and `FAILED` rather than inventing evidence. | Rejected. First-pass rate for this smoke was `0/1`. |
| Diagnostic continuation | The same child reported its current directory and exact `FILE_NOT_FOUND` path. | Root mismatch identified without edits. |
| Focused repair | The parent supplied the canonical nested repository path to the same child. It returned generation `1`, token `ALPHA-17`, and SHA-256 `c4cbd4f6c3e8ce380f587b83225a91cecb29aaf28ca1ad4da8cc16f75793f470`. Sol independently reproduced the hash. | Passed on repair `1/1`. |
| Stale evidence | Sol changed the candidate to generation `2`. The same child compared its prior receipt with the new file and returned `REJECTED_STALE`, observing SHA-256 `b97c2dc558707fdc39950cc02f4460dbfa740fd40e7387c65c9e9231c0fd6502`. | Stale evidence blocked acceptance. |
| Evidence refresh | The same child rechecked generation `2`, token `BETA-23`, and the new hash. | Fresh check passed; this was not a second repair. |
| Timeout | A second Luna child was given a larger read-only matrix task. The parent's 10-second wait timed out; interruption reported the child's prior native status as `running`. | Timeout/interruption path exercised. |
| Post-interruption continuation | The same interrupted child received a reduced read-only request and returned policy `1.1.0`, first-pass floor `0.8`, and credit-saving floor `0.15`. | Same-child continuation passed. |
| Conflicting ownership | Before dispatching two proposed writers, `ownership_guard.py check-plan` found `src/shared` versus `src/shared/api`, returned `FAIL`, exit `3`, and `parallel_writes_allowed: false`. | Conflicting writers were not dispatched. |

## Finding and correction

The initial failure was coordination waste caused by an incomplete package contract, not by task reasoning. "Repository-relative" was ambiguous because the child started at the outer workspace while the audited repository was nested under `work/sol-luna-remote-main-v2`. The Skill now requires a canonical repository root in every package and forbids assuming the child's current directory.

## Remaining proof boundary

- Requested model and reasoning effort came from the native dispatch call, but were not independently verified from a host session receipt.
- Sandbox and permission-profile values were not host-observed in this smoke.
- The custom Luna TOML profiles were not proven loaded.
- This single fixture does not demonstrate routing economics or the 15% median-credit success gate.
- A representative paid matched campaign still requires isolated starts, frozen acceptance suites, phase evidence, and credible credit measurements.
