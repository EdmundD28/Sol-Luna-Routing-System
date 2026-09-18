# P126/P127 required-path causal ablation

Status: `DEVELOPMENT_METRICS_PASS_PROTOCOL_FAIL`. No product release.

## Changed premise

P124 Medium failed quality after omitting a representative pre-final check and
opening a controller repair turn. Earlier P046 evidence warned that nine
repeated checks can reduce elapsed time while increasing input cost. P126
therefore used one combined causal batch, allowed only failed test IDs to rerun
once inside the same Medium writer turn, and kept one final full suite. P127
added only the explicit twelve required paths and their existing structural
acceptance ID after P126 omitted `graph.py`.

## Results

| Route | Public | Hidden | Proxy credits | Controller elapsed |
|---|---:|---:|---:|---:|
| P124 Sol-only | 25/25 | 12/12 | 11.160600 | 243.823 s |
| P126 Medium, semantic batch only | 24/25 | not run | 3.402806 diagnostic | 217.122 s diagnostic |
| P127 Medium, required paths + batch | 25/25 | 12/12 | 3.428298 | 222.023 s |

P126's batch caught and repaired the prior dependency-contract miss, eliminated
the controller repair turn, reduced the diagnostic proxy 69.511%, and was
10.951% faster than Sol-only. It failed quality because `graph.py` was absent.

P127 named all twelve create obligations and added
`test_required_modules_and_exact_exports` to the same batch. The writer ran one
nine-test batch, reran only the failed dependency test once, and ran the full
suite once. Public 25/25 and route-external hidden 12/12 passed with no Sol
rewrite or reclaim. Proxy credits were 69.282% below Sol-only and controller
elapsed was 8.941% faster.

## Protocol failure

The P127 freeze incorrectly required `git diff --check` after the final suite,
and the writer then ran `git status --short` to construct its path receipt.
Installed v0.38.3 forbids any post-pass diff, status, reread, or test operation.
Those calls are included in the cost and time, so the numeric result is
conservative, but the route is not strictly protocol conformant. Independent
review therefore records protocol `REVIEW_FAIL`, not a product pass.

## Decision

Retire P124/P126/P127 from tuning. The numeric result supports one transfer
hypothesis: a complete required-path/acceptance-label capsule plus one combined
causal batch may let a Medium writer close quality without another Sol turn.
It does not justify a release.

The next comparison must use a distinct unseen task, run all diff/status checks
before the final suite, and censor any post-pass tool call. It must again pass
quality, >=50% credit-equivalent reduction, and no elapsed regression. No
included-plan percentage was measured.
