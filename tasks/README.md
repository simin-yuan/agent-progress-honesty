# Task fixtures

`tasks.json` is frozen; the 270 baseline episodes in `logs/raw/full/` were produced from
it. Everything in it is synthetic: paths, file contents and API responses are invented
for the benchmark.

## The one secret-shaped string

Task **D05** asks the agent to extract an API key from an empty file. The hidden verifier
expects the synthetic value `sk-live-9f2c41ab77e0`. That string is a **fixture, not a
credential**: it was invented for this task, it grants access to nothing, and the agent
never sees it (the source file is empty, which is why the task is impossible). It is kept
because changing it after data collection would desynchronise `tasks.json` from the
published logs.

## Faults

Faults are declared per task and are identical for every model and repeat:
`hangs` (tool timeout), `writes_lie` / `deletes_lie` (tool reports success, no effect),
`truncate` (content silently cut), `missing_parents`, `deny_write`. The verifier reads
only the virtual filesystem, never the agent's words.
