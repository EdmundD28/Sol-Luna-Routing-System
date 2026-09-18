# P129 second unseen transfer evidence

Status: `SECOND_UNSEEN_TASK_LOCAL_PASS`. No installed Skill change.

P129 froze a deterministic half-open interval-policy compiler after P128 was
retired. The task family and acceptance boundary were independent of the
earlier rollout-planner development tasks and the P128 capacity-reservation
task. The fixed route order was Sol-only followed by Sol-Luna v0.38.3.

| Route | Public | Hidden | Full-session credit equivalent | Controller elapsed |
|---|---:|---:|---:|---:|
| Sol-only | 72/72 | 12/12 | 9.442300 | 205.376 s |
| Sol-Luna v0.38.3 | 72/72 | 12/12 | 3.489888 | 162.791 s |

Sol-Luna used `63.039853%` less official-rate credit equivalent and completed
`20.735139%` faster. Both routes required zero repair. The Luna Medium writer
ran one nine-test causal batch and one final full suite. The Sol-Luna controller
did not implement, reread the candidate, replay tests, rewrite, or reclaim. The
final successful full suite was the final tool call in both routes. Independent
read-only review returned `REVIEW_PASS`.

The frozen metric used each host session's complete cumulative input, cached
input, and output totals with Sol rates `100/10/500` and Luna rates
`5/0.5/30` per million. Reasoning was not charged twice. The current 20X
account percentage was intentionally not read.

The reviewer disclosed one non-blocking path-discovery miss: the writer first
tried a nonexistent public-test path, then used a bounded file listing and read
the real public test once. A route-external hidden-harness launch also omitted
the fixture from `PYTHONPATH`; it failed before candidate import and was
corrected before both 12/12 hidden results were recorded.

P129 is retired. P128 and P129 now provide two distinct unseen-task local
passes for the unchanged v0.38.3 mechanism, both with equal accepted quality,
more than 60% official-rate credit-equivalent reduction, and no elapsed-time
regression. This remains local task evidence, not included-plan percentage
evidence or a universal Sol-Luna-over-Sol-only claim.
