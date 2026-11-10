# Raw logs

- `full/` — the 270 episodes behind every number in the paper/README:
  30 tasks × 3 models (`deepseek-flash`, `deepseek-pro`, `qwen3.5-9b`) × 3 repeats.
  Each JSON file is one episode: system/user/assistant turns, every tool call and its
  result (with the injected fault marked), token usage, cost estimate, the verifier
  output at report time and at the end, and the three reports (`r0`, `r1`, `r2`).
- `trial/` — the 5-episode milestone-1 trial (one model, one repeat). Kept for the
  record; **not** included in any result table.
- `full-run.log`, `trial-run.log` — console logs of the two runs.

Development/pilot runs (used only to fix the harness) are not published; they live in
`logs/dev/` locally and are git-ignored.
