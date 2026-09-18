# P128 unseen transfer evidence

Status: `UNSEEN_TASK_LOCAL_PASS`. No installed Skill change.

P128 froze a semantically new deterministic capacity-reservation package after
retiring the P124/P126/P127 rollout-planner development family. Both arms used
fresh `gpt-5.6-sol` High controllers, the same baseline and 49-test public plus
12-test hidden acceptance. The Sol-Luna arm used one `gpt-5.6-luna` Medium
writer; Sol's implementation queue was empty.

| Route | Public | Hidden | Full-session credit equivalent | Controller elapsed |
|---|---:|---:|---:|---:|
| Sol-Luna v0.38.3 | 49/49 | 12/12 | 5.078984 | 186.875 s |
| Sol-only | 49/49 | 12/12 | 13.906900 | 329.289 s |

Sol-Luna used `63.478676%` less official-rate credit equivalent and completed
`43.248939%` faster. The writer ran one nine-test causal batch and one final
full suite, with zero repair; Sol did not implement, replay, rewrite, or
reclaim. The final full suite was the final tool call in both arms. Independent
read-only review returned `REVIEW_PASS`.

The frozen metric used each host session's complete cumulative input, cached
input, and output totals with Sol rates `100/10/500` and Luna rates
`5/0.5/30` per million. The current 20X account percentage was intentionally
not read. Therefore this is one-task transfer evidence for the current v0.38.3
mechanism, not included-plan percentage evidence or a general superiority
claim.

P128 is retired after this pair. Do not tune it. A future claim expansion would
require another independently frozen task family or an account-meter comparison
when the meter has sufficient resolution; it must not add ordinary-path
protocol burden merely to strengthen reporting.

