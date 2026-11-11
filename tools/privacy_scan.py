"""Scan (and optionally redact) local paths, identities and secret-like strings.

Usage:
  python tools/privacy_scan.py            # report only
  python tools/privacy_scan.py --fix      # rewrite hits with placeholders

The scan covers every file in the repository except .git and this script. The
report is printed as `category: count` plus up to five example locations.
"""

from __future__ import annotations

import argparse
import collections
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.abspath(__file__)

PATTERNS = {
    "local_path": re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?:Users|HARNESS|harness|ollama|Windows|Program|dev|work)[^\s\"',;)]*", re.I
    ),
    "home_path": re.compile(r"(?:/Users/|/home/|\\\\Users\\)[A-Za-z0-9._-]+"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "token": re.compile(r"(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|x-dsh-auth-token)"),
    "private_repo": re.compile(r"(?i)(agent-faultbench|agent-hang-bench|superagent|shiqing|hermes|\u5149\u4e4b\u6d8c\u73b0)"),
    "account_id": re.compile(r"281164480"),
}

PLACEHOLDERS = {
    "local_path": "<LOCAL_PATH>",
    "home_path": "<LOCAL_PATH>",
    "email": "<EMAIL>",
    "token": "<REDACTED_TOKEN>",
    "private_repo": "<PRIVATE_REPO>",
    "account_id": "<ACCOUNT_ID>",
}

# Values that match a pattern but are not secrets. Both are documented in the repo.
ALLOWLIST = [
    (re.compile(r"^x-dsh-auth-token$"), "HTTP header name used by the client, not a credential"),
    (
        re.compile(r"^sk-test-FAKE-[A-Za-z0-9_-]*$"),
        "synthetic fixture for impossible task D05, documented in tasks/README.md",
    ),
]


def _is_allowed(value: str) -> bool:
    return any(rx.match(value) for rx, _ in ALLOWLIST)


def iter_files():
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            path = os.path.join(dirpath, fn)
            if os.path.abspath(path) == SELF:
                continue
            yield path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()

    hits = collections.Counter()
    allowed = collections.Counter()
    examples: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    changed = 0
    for path in iter_files():
        rel = os.path.relpath(path, ROOT)
        try:
            with open(path, "r", encoding="utf-8", errors="strict") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for name, rx in PATTERNS.items():
            matches = list(rx.finditer(new))
            ok = [m for m in matches if _is_allowed(m.group(0))]
            if ok:
                allowed[name] += len(ok)
            found = [m for m in matches if not _is_allowed(m.group(0))]
            if not found:
                continue
            hits[name] += len(found)
            for m in found[:5]:
                if len(examples[name]) < 5:
                    examples[name].append((rel, m.group(0)[:100]))
            if args.fix:
                new = "".join(
                    m.group(0) if _is_allowed(m.group(0)) else PLACEHOLDERS[name] for m in rx.finditer(new)
                )
        if new != text:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            changed += 1

    print("files changed:", changed if args.fix else "0 (report only)")
    if allowed:
        print("allowlisted (not secrets):")
        for rx, reason in ALLOWLIST:
            print(f"   {rx.pattern} - {reason}")
    if not hits:
        print("clean: no unredacted matches")
        return 0
    for name in PATTERNS:
        if hits[name]:
            print(f"{name}: {hits[name]}")
            for rel, sample in examples[name]:
                print(f"   {rel} | {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
