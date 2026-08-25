# Preliminary Arm A vs Arm B Comparison

## Available facts

| Measure | Arm A — Sol only | Arm B — Sol + Luna | Interpretation |
|---|---:|---:|---|
| Task elapsed | 1429.313 s (23m 49.313s) | 3739.915 s (1h 02m 19.915s) | B took 2.62x as long |
| Codex thread duration | 1515080 ms (25m 15.080s) | 3835682 ms (1h 03m 55.682s) | B took 2.53x as long |
| Delegation | None | 1 Luna worker, 3 handoffs | B incurred coordination overhead |
| Repair iterations | 3 | 2 | Counts alone do not establish quality |
| Final reported tests | 300 passed | 288 passed | Suites differ; not a direct quality score |
| Targeted tests | 33 passed | 21 passed | A added/reported broader targeted coverage |
| Changed files | 10 | 11 | Descriptive only |
| Diff size | +2637/-17 | +2986/-22 | Descriptive only |
| Allowance change | Unavailable after reset | 84% to 75% (-9 percentage points) | Credit comparison is impossible |
| Reported outcome | PASS | PASS | Both still require independent judging |

## Timing calculation

- Difference using task timestamps: `3739.915 - 1429.313 = 2310.602 s` (`38m 30.602s`).
- Ratio using task timestamps: `3739.915 / 1429.313 = 2.6165`.
- Arm B was approximately `161.65%` slower than Arm A on this run.

## What can be concluded

1. The tested Sol + Luna workflow did not save wall-clock time on this task.
2. Both arms reported passing their own acceptance checks.
3. The experiment cannot answer whether the workflow saved credits because Arm A's usage delta is missing.
4. It is too early to declare a quality winner. The arms used different self-authored tests and produced different implementations.
5. This result predates the current rolling-pipeline Skill revision and therefore does not validate or invalidate that revision.

## Remaining evaluation

- Run the same independent hidden acceptance suite against both branches.
- Conduct a blind review of correctness, architecture, maintainability, scope control, and test quality.
- Record defects found by the independent evaluator.
- Repeat a paired run with before/after usage readings captured immediately, avoiding a reset boundary.

## Preliminary verdict

For this single paired run, the workflow failed the latency hypothesis and produced no evidence for the credit-saving hypothesis. Any claim that it was more economical would be speculation.
