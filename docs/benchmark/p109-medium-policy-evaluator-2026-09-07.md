# P109 Medium access-policy evaluator calibration

- Purpose: challenge the P108 duration failure with a new pure-memory domain combining recursive conditions, multidimensional selectors, deterministic precedence, and deny override.
- Route: one retained `gpt-5.6-luna/medium`; Sol performed no implementation or public-suite replay.
- Frozen acceptance: 19 public tests and 9 route-external hidden tests.
- Result: the first public run had one action-specificity failure. One evidence-only same-Luna repair produced 19/19 public and 9/9 hidden passes.
- Measured route boundary: 241.048 seconds.
- Account meter: not read; the account was not frozen.
- Decision: reject as a quota candidate. The task was materially shorter than P108 and far below the 15-minute floor, so recursive policy semantics did not create the expected natural duration.
- Next retry rule: do not enlarge this evaluator with more operators, selectors, or error cases. The next quota candidate must obtain duration from real code volume and integration work in an existing coherent subsystem, while keeping deterministic independent acceptance and Medium-safe semantics.
