# P106 Medium semantic-split calibration

P106 retried complete Luna ownership under the changed premise established by
v0.37.4: one retained Luna Medium, an empty Sol implementation queue, one final
suite executor, and no Sol reread or rewrite.  The task was a fixed five-module
split of the existing `evidence_ledger.py` implementation with frozen public and
route-external acceptance.

The first calibration failed after 356.921 seconds because the task did not
enumerate constant ownership and facade exports precisely enough.  One focused
same-Luna repair also failed.  After the task and public acceptance explicitly
listed all 19 constants and every facade export, an independent review allowed
one fresh retry from baseline `da6015e55fd8a1ef9eff363abc72f29ddb70ae07`.

The retry ran for 512.967 seconds.  Its first full-suite attempt stopped with 11
errors after 321 tests due to an indentation error.  The only permitted focused
repair reached all 463 tests but finished with 3 failures and 35 errors (4
skipped): unresolved cross-module names in the store, receipt, and analysis
modules, plus a non-UTF-8 CLI behavior regression.  Sol did not inspect or
rewrite the implementation, and hidden acceptance was not run.

Decision: reject quality and duration; do not freeze the account.  Do not retry
the same monolith-to-modules split with more prompt detail, a higher effort, or
another repair allowance.  A future retry needs a different implementation
mechanism that makes dependency ownership executable rather than textual, while
remaining outside the ordinary dispatch path.
