# P012 controller-overhead audit

P012 produced equal hidden acceptance (12/12 each), a displayed five-hour tie (1 percentage point each), and a 28.26% elapsed regression for `SOL_LUNA`. The integer plan meter was too coarse to explain the route internals, so this audit separates host-observed Sol and Luna session usage as a secondary diagnostic. It does not convert purchased credits into included-plan percentages.

The calculation uses the [official Codex credit rates](https://learn.chatgpt.com/docs/pricing): per million tokens, Sol input/cached/output are 100/10/500 credits and Luna input/cached/output are 5/0.5/30 credits. Non-cached input is total input minus cached input.

| Component | Non-cached input | Cached input | Output | Standardized purchased-credit estimate |
| --- | ---: | ---: | ---: | ---: |
| `SOL_ONLY` Sol controller | 43,431 | 699,904 | 19,539 | 21.111640 |
| `SOL_LUNA` Sol controller | 83,658 | 1,811,968 | 20,106 | 36.538480 |
| `SOL_LUNA` Luna writer | 76,707 | 972,800 | 12,801 | 1.253965 |
| `SOL_LUNA` total | — | — | — | 37.792445 |

The Luna writer was only 3.32% of the `SOL_LUNA` estimate. The Sol controller alone cost 1.731 times the complete `SOL_ONLY` controller. Its trace contained 28 execution calls versus 12 in `SOL_ONLY`, and it implemented the semantic core, core tests, and README while Luna implemented the JSON/CLI lane and tests.

Therefore P012 does not show that Luna is expensive. It shows that a mixed topology can erase Luna's 16.67–20x rate advantage when Sol keeps a substantial implementation package and adds planning, dispatch, rereading, review, and integration loops.

Routing implication:

1. When ownership and deterministic acceptance permit it, compare a complete-Luna envelope with every mixed allocation and `SOL_ONLY`.
2. Do not reserve Sol implementation merely to keep the controller busy or manufacture overlap.
3. Calibrate Sol planning, coordination, review, integration, and replay from observed controller evidence rather than optimistic defaults.
4. Keep Sol's complete-Luna lane read-only and risk-triggered; waiting is cheaper than duplicate implementation.

The included-plan decision remains unchanged: only matched five-hour and weekly readings can establish the user-visible allowance result, with quality as a hard gate and elapsed time evaluated separately.
