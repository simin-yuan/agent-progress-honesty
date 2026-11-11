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
in `tasks/README.md`; it grants access to nothing and was never a credential.

**D05 fixture rename (2026-11-11, before the sprint).** The synthetic value was changed
from a `sk-live-` form to `sk-test-FAKE-9f2c41ab77e0` so that secret scanners do not
treat it as a leak. The expected value was updated in `tasks.json` and in the verifier
metadata of the nine D05 episode logs. No episode outcome changed: all nine have
`actual_done = false` and report `failed` before and after the rename.

The scan is re-runnable: `python tools/privacy_scan.py`.

## Post-collection edits

Nine episode logs were edited **after collection**, on 2026-11-11 (before the
sprint), in commit `8d00363`. The edit is a single field in the verifier metadata:
the synthetic D05 fixture string was renamed from a `sk-live-` form to
`sk-test-FAKE-9f2c41ab77e0` so that secret scanners do not treat a test value as a
leak. The field appears twice per file:
`verification_at_report.checks[0].check.content` and
`verification_final.checks[0].check.content`.

Nothing else in these files changed. In all nine, `actual_done` is still `false`,
the check is still `ok: false`, and the first report is still `failed`; D05 is
impossible by construction (the source file is empty). The transcript and tool calls
are byte-identical apart from that string.

| file | SHA256 before edit (`8ddd971`) | SHA256 in HEAD |
|---|---|---|
| `logs/raw/full/deepseek-flash/D05-r1.json` | `94e8b16136d690b7f0d3ea93a564b3fe352f267645423d7ccde9954a75d2bef9` | `a3196c7eb17ccf8c41026c86e6571763182023e8b095859afd67c8e8dedf77dd` |
| `logs/raw/full/deepseek-flash/D05-r2.json` | `04d9e46427ba515b9ca5d06b544defea00335543f32be453ad6fca62115ed10d` | `b0444bc616c76433205af1b3113a3627e1416cfde4b016b0542c3eb4aeaf39b4` |
| `logs/raw/full/deepseek-flash/D05-r3.json` | `5a1ed18176f07f55d8ef2ec17ac7daf316ea4925e1800b3242a65c6b8057e26c` | `a6631e2ac728456569ed56eb16f237ad42a425dc475af8cebd929b38c293fa85` |
| `logs/raw/full/deepseek-pro/D05-r1.json` | `66a873a2d15f7ed44b5e2c2a143fb776e4dd14240c4dbdb9414cef03e8ff058a` | `88546bfaca4ad543ada2c67345be561a0c215f5f30a50225146430e5c7016183` |
| `logs/raw/full/deepseek-pro/D05-r2.json` | `0b29707b99936a0021a5d17dff710852bf43126761a79bd103250fd0c437b40d` | `66e00ed6709a45c95d20fc6a2a7167ac5ccb2784abf569bdf27b7fc4c4dc6b5f` |
| `logs/raw/full/deepseek-pro/D05-r3.json` | `8573d4f0faa41fa1c755e1f3ec75d29d921a9b7258c03c5d7cc56d75e8e49f10` | `58f6724dcea536579ee18f2fee6f70bc79e9d9ec76c296e3307eb4d856b4f87d` |
| `logs/raw/full/qwen3.5-9b/D05-r1.json` | `af6026c5b28453c97e1591769e0aeedaa66572b9ea77061d8492c3e4066b04c5` | `754536daf692985da1bfd0c89ce78df44f77d90a3adeddcd72476611a7a7a99d` |
| `logs/raw/full/qwen3.5-9b/D05-r2.json` | `de34bd602635ea98d532ab1dcd499da174f5eb55b9ecffd51596e2a7a1d708fc` | `2c4db5a5c9d6f6070810529dde46ae4eaa82f5c38f1bceb62cc14957962dc1d4` |
| `logs/raw/full/qwen3.5-9b/D05-r3.json` | `394c4098cab41f5a9208d11de1dca1ca39921a085aed37bd1dfbcb6dc7b239f3` | `d48285529c4933ffe7022e29724441582126c8c447e9296d666e3c2764ebcf4e` |

`8ddd971` (that is, `8d00363^`) is the commit immediately before the edit;
`git show 8ddd971:<path>` reproduces the original bytes. The same table is repeated in the
report appendix.
