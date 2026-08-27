# Included-Allowance Benchmark

Use this protocol only when the task is to quantify Sol-only versus Sol-Luna subscription usage. The user-visible plan meters are authoritative for this question; diagnostic tokens and purchased-credit estimates are secondary explanations.

## Freeze the comparison

- Use one account, plan, speed setting, formal repository checkout, task family, starting Git reference, task specification, independent acceptance suite, and Sol-Luna revision.
- Store the campaign ledger and dashboard captures outside the repository. Do not create a clone, copied project, or worktree.
- Pre-register the route order, pair count, batch size, quality gate, time gate, and minimum allowance advantage. For the first v0.1.1 campaign, test a conservative lower bound of at least 10×.
- Run counterbalanced pairs. Four pairs in `ABBA` or `BAAB` order are the minimum pilot; use more pairs when the meter remains too coarse.

## Read the meters

For each arm, wait for the usage dashboard to settle, then retain the before and after evidence for both the five-hour and weekly remaining percentages. Record the same window identifier and the display uncertainty. Stop and invalidate the pair if either window resets, the remaining value rises, another shared-pool task runs, the plan or speed changes, or the readings between sequential arms are not continuous.

The five-hour meter is primary because its smaller allowance window usually magnifies the same usage into a larger percentage change. The weekly meter is a separate, coarser corroborating view of the same shared usage. Never add the two percentages or infer one window's hidden capacity from the other without calibration.

Within one unchanged meter, the hidden capacity cancels:

```text
allowance advantage = Sol-only percentage-point consumption / Sol-Luna percentage-point consumption
```

Use `scripts/allowance_meter.py assess` to aggregate the paired intervals. If integer display resolution makes the denominator indistinguishable from zero or the conservative lower bound misses the pre-registered threshold, enlarge the matched batch within the quota budget or report `HOLD`; do not manufacture precision.

## Accept or hold

Call the campaign a pass only when independent acceptance is equal, defects do not increase, total Sol-Luna elapsed time is strictly lower, the five-hour conservative aggregate advantage reaches the declared threshold, weekly evidence does not contradict the direction, and the arm order is counterbalanced. Report the displayed ratio and uncertainty interval, both meters separately, all failures and repairs, and any contamination boundary.

The official per-model rate card can estimate purchased credits from complete classified phase usage. It does not reveal the capacity behind a personal plan's five-hour or weekly percentage and cannot replace the account-meter result.
