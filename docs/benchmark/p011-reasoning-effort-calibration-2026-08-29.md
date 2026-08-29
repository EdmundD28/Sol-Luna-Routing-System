# P011 reasoning-effort calibration

Date: 2026-08-29 (Australia/Sydney)

Decision: keep routing research active and replace the mistaken “leaf means Medium” shortcut with an executable, evidence-bound reasoning floor. This calibration is not a subscription-allowance comparison.

## Same P010 task

Both Sol-Luna candidates used a real `gpt-5.6-sol/high` controller, one retained `gpt-5.6-luna` writer, the same allocation, and the same external hidden referee.

| Luna effort | Public acceptance | Hidden referee | Full repository | Natural interval |
| --- | ---: | ---: | ---: | ---: |
| Medium, formal P010 arm | 16/16 | 11/12 | 395 passed, 1 skipped | 566.62 s |
| High, calibration | 21/21 | 12/12 | 400 passed, 1 skipped | about 538 s |

Medium failed exact CLI success serialization. High passed without a Luna repair round and was about 29 seconds faster than Medium. The High run was outside a frozen account-meter interval, so it supplies task-local quality and elapsed calibration only. It does not repair P010's failed allowance result and does not establish a general High advantage.

## Policy consequence

Policy 1.11.0 schema 7 derives a minimum Luna effort from a strict reasoning profile. The profile separates ownership shape from reasoning difficulty: semantic coupling, cross-module invariants, multiple interfaces, adversarial edges, platform-sensitive I/O, and strict serialization can raise a leaf package to High or XHigh.

The P010 replay produces a High floor. Its Medium candidate is rejected by both the floor and its observed quality record; the matching High candidate passes. High and XHigh still require their own external quality evidence plus the existing same-allocation lower-effort rejection. The policy never promotes automatically to Max.

## Boundary

This milestone fixes effort selection before another matched allowance run. It does not claim lower five-hour or weekly consumption. A later measured pair must still freeze the account only during each route interval, apply the same independent acceptance, and report displayed five-hour and weekly percentage-point changes separately.
