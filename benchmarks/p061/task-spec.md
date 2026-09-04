# P061 incremental build planner

Implement a deterministic, in-memory incremental build planner under the target repository at `benchmarks/p061/buildkit/`. Create exactly these nine files:

- `__init__.py`
- `errors.py`
- `model.py`
- `graph.py`
- `impact.py`
- `batches.py`
- `critical.py`
- `planner.py`
- `explain.py`

Do not perform file, network, environment, subprocess, randomness, or clock I/O. Do not mutate caller-owned inputs. Public sequence outputs are tuples and public record outputs are frozen dataclasses. `dependents_map()` is the one mapping-output exception: it returns a fresh dict whose values are tuples.

## Common rules

- Task and resource identifiers match `[a-z][a-z0-9_-]{0,31}`.
- Integer fields reject booleans.
- Wrong Python value/container types raise `TypeError`; malformed values, duplicates, missing references, cycles, and invalid bounds raise `ValueError`.
- Input task records are a list/tuple of dicts with exactly `id`, `deps`, `resources`, and `cost`.
- `deps` is a list/tuple of task IDs. `resources` is a list/tuple/set/frozenset of resource IDs. Duplicates are rejected before canonicalization.
- `cost` is a strictly positive integer.

## Required APIs

`errors.py`

- Define `BuildPlanError(ValueError)`. Cycle, missing dependency, unknown changed/selected task, self-dependency, and selected-subgraph scheduling errors raise this type.

`model.py`

- Frozen dataclass `TaskSpec(task_id, deps, resources, cost)`, where `deps` is a sorted tuple and `resources` is a frozenset.
- Frozen dataclass `BuildPlan(changed, impacted, batches, critical_path, critical_cost, total_cost)`; tuple fields remain tuples.
- `normalize_tasks(records)` validates the complete graph, rejects duplicate task IDs/dependencies/resources, missing dependencies, self-dependencies, and cycles, and returns `TaskSpec` objects sorted by task ID.

`graph.py`

- `topological_order(tasks)` accepts raw records or normalized `TaskSpec` collections and returns all task IDs in deterministic lexicographic-ready topological order.
- `dependents_map(tasks)` returns a new dict mapping every task ID to a sorted tuple of direct dependents.

`impact.py`

- `impacted_tasks(tasks, changed)` validates `changed` as a list/tuple of unique known task IDs and returns the changed tasks plus all transitive dependents, ordered by the graph's full topological order. Empty changed input returns `()`.

`batches.py`

- `schedule_batches(tasks, selected, max_parallel)` validates `selected` as a list/tuple of unique known task IDs and `max_parallel` as a positive integer excluding booleans.
- Dependencies outside `selected` are already satisfied. Within `selected`, dependencies must be in earlier batches.
- At each batch, consider ready tasks in lexicographic order. Greedily add a task when the batch is below `max_parallel` and its resources do not intersect resources already used in that batch. Deferred ready tasks remain eligible for the next batch. Return a tuple of non-empty task-ID tuples. Empty selected input returns `()`.

`critical.py`

- `critical_path(tasks, selected)` uses only dependency edges whose endpoints are both selected. Return `(path_tuple, cost)` for the maximum total task cost path. Ties choose the lexicographically smaller complete path tuple. Empty selected input returns `((), 0)`.

`planner.py`

- `plan_build(records, changed, max_parallel)` normalizes once, computes impacted tasks, batches, critical path/cost, and total impacted cost, and returns a frozen `BuildPlan`. Empty changed input produces empty tuple fields and zero costs.

`explain.py`

- `explain_plan(plan)` requires a `BuildPlan` and returns deterministic text lines as a tuple:
  - `changed=<comma-list-or->`
  - `impacted=<comma-list-or->`
  - one `batch[N]=<comma-list>` line per batch, numbered from 1
  - `critical=<comma-list-or->:<critical_cost>`
  - `total_cost=<total_cost>`

`__init__.py`

- Re-export `BuildPlanError`, `TaskSpec`, `BuildPlan`, `normalize_tasks`, `topological_order`, `dependents_map`, `impacted_tasks`, `schedule_batches`, `critical_path`, `plan_build`, and `explain_plan`.

The acceptance suite is authoritative for exact edge behavior. Do not add convenience APIs or alternate semantics.
