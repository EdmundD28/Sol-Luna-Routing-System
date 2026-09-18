# P123 bounded one-turn inheritance probe

Status: host-semantics rejection. No implementation route, repository edit, or allowance claim was involved.

A fresh two-turn Sol parent received one unique marker in each turn. In the second turn it spawned exactly one Luna child with `fork_turns="1"` and waited once. The child reported `MARKERS=NONE`; its host log contained neither concrete marker before its first response. The parent log proved that the positive fork count was supplied, but the active task marker was not available as auditable child context.

This is a changed-premise check against the older full-history inheritance mechanism: the current collaboration API accepts a positive turn count. The changed premise did not produce the required active-turn visibility in the nested controller route.

Keep `fork_turns="none"`. Do not retry by changing the count or wording. A retry requires host-level evidence that the active task turn is exposed to a model-overridden child and is auditable before that child responds. This probe does not address direct root-to-child behavior, route quality, credit, time, or included-plan allowance.
