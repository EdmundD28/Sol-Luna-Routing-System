# Matched Included-Allowance Campaign p003

## Decision

`HOLD`. The fixed v0.6.0 shape—one Luna implementation package plus retained Sol documentation, integration, and deep review—did not beat Sol-only at equal quality and lower elapsed time.

The campaign used four counterbalanced pairs from the same commit and task specification. Each arm received the complete top-level task, used the same independent hidden acceptance suite, and recorded the signed-in ChatGPT five-hour and weekly plan meters immediately before and after the route-only interval. Independent acceptance, commits, branch changes, and dashboard preparation were excluded. Failed arms remained in the denominator.

## Results

| Pair | First route | Sol-only five-hour points | Sol-Luna five-hour points | Sol-only seconds | Sol-Luna seconds | Independent quality |
|---|---|---:|---:|---:|---:|---|
| 001 | Sol-only | 1 | 1 | 1234.980 | 1463.829 | both passed |
| 002 | Sol-Luna | 3 | 1 | 711.004 | 773.574 | Sol-Luna failed one strict-type case |
| 003 | Sol-Luna | 1 | 1 | 708.152 | 1302.249 | both passed |
| 004 | Sol-only | 0, followed by 1 delayed point between arms | 1 | 798.021 | 989.799 | both passed |

Direct arm totals were 5 five-hour percentage points for Sol-only and 4 for Sol-Luna, a displayed 1.25× advantage. Assigning both observed delayed five-hour points to their immediately preceding Sol-only arms gives a disclosed sensitivity result of 7 versus 4, or 1.75×; that attribution is plausible but is not the direct arm reading. Weekly arm totals were both zero, with one delayed weekly point observed after a Sol-only arm.

Sol-only passed 4/4 independent acceptance runs. Sol-Luna passed 3/4; the failed candidate accepted floating-point `1.0` as an integer schema version. Total elapsed time was 3452.157 seconds for Sol-only and 4529.451 seconds for Sol-Luna, so Sol-Luna was 31.2% slower. Every Sol-Luna arm was slower than its pair.

## Measurement boundary

The plan meter is the correct user-value measure, but its integer display and delayed refresh prevent exact per-arm attribution at this task size. Direct arm readings, excluded between-arm changes, and any sensitivity attribution must remain separate. Diagnostic tokens and purchased-credit estimates are not substitutes for plan-limit percentage points.

One user message invalidated the first attempted arm, and controller bookkeeping invalidated one later begin event before any route launched. Both attempts were retained as invalid diagnostics and excluded from the four completed pairs.

## Policy consequence

The result rejects fixed one-package delegation, not Luna participation. Policy 1.4.0 separates active concurrency from delegated coverage: one active Luna may roll through multiple positive-benefit packages from a complete single-owner allocation, while Sol advances only disjoint critical-path work. The next matched campaign must measure that mechanism, accepted delegated coverage, zero duplicate work, quality, plan allowance, and elapsed time.
