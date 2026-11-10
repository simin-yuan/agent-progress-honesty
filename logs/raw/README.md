# Raw logs

- `full/` — the 270 episodes behind every number in the README:
  30 tasks × 3 models (`deepseek-flash`, `deepseek-pro`, `qwen3.5-9b`) × 3 repeats.
  Each JSON file is one episode: system/user/assistant turns, every tool call and its
  result (with the injected fault marked), token usage, cost estimate, the verifier
  output at report time and at the end, and the three reports (`r0`, `r1`, `r2`).
- `trial/` — the 5-episode milestone-1 trial (one model, one repeat). Kept for the
  record; **not** included in any result table.
- `full-run.log`, `trial-run.log` — console logs of the two runs.

Development/pilot runs (used only to fix the harness) are not published; they live in
`logs/dev/` locally and are git-ignored.

## Redaction and privacy scan

Before publication, every file in the repository (all 270 episode logs included) was
scanned with `tools/privacy_scan.py` for:

| class | placeholder | result |
|---|---|---|
| local absolute paths (Windows user or install directories) | `<LOCAL_PATH>` | 0 found in episode logs |
| user names in paths, e-mail addresses | `<LOCAL_USER>`, `<EMAIL>` | 0 found |
| secret-like strings (`sk-` keys, GitHub tokens, auth headers) | `<REDACTED_TOKEN>` | 0 credentials; 2 documented non-secrets allowlisted (see below) |
| private repository names | `<PRIVATE_REPO>` | 0 found in logs |

No episode log contained a local path, account name, e-mail address or credential. The
two allowlisted values are (a) the HTTP header name `x-dsh-auth-token`, which is not a
secret, and (b) the synthetic `sk-` fixture used by the impossible task D05, documented
in `tasks/README.md`; it grants access to nothing and was never a credential. The scan is
re-runnable: `python tools/privacy_scan.py`.
