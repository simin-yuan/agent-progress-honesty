"""Self-tests for the mock environment and the action parser.

Run: python -m tests.selftest
No network, no model calls.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bench.env import MockEnv, norm_path  # noqa: E402
from bench.protocol import parse_action  # noqa: E402


def test_paths() -> None:
    assert norm_path("/out/./a.txt") == "/out/a.txt"
    assert norm_path("/data//reports") == "/data/reports"
    assert norm_path("out/a.txt") == "/out/a.txt"
    assert norm_path(".") == "/"
    assert norm_path("/") == "/"


def test_alias_cannot_bypass_hang() -> None:
    task = {
        "files": {"/out/.keep": ""},
        "hangs": [{"tool": "write_file", "contains": "/out/report.txt", "error": "ETIMEDOUT"}],
    }
    env = MockEnv(task)
    r = env.call("write_file", {"path": "/out/./report.txt", "content": "x"})
    assert "error" in r, r
    assert "/out/report.txt" not in env.files


def test_silent_write_and_detection() -> None:
    task = {"files": {"/out/.keep": ""}, "writes_lie": ["/out/b.txt"]}
    env = MockEnv(task)
    r = env.call("write_file", {"path": "/out/b.txt", "content": "B"})
    assert r.get("ok") is True
    assert "/out/b.txt" not in env.files
    assert "error" in env.call("read_file", {"path": "/out/b.txt"})


def test_truncation() -> None:
    task = {"files": {"/data/x": "abcdefghij"}, "truncate": {"/out/x": 4}}
    env = MockEnv(task)
    env.call("write_file", {"path": "/out/x", "content": "abcdefghij"})
    assert env.files["/out/x"] == "abcd"


def test_root_listing() -> None:
    task = {"files": {"/out/a": "1", "/data/b": "2"}}
    env = MockEnv(task)
    r = env.call("list_files", {"path": "/"})
    assert r["entries"] == ["data/", "out/"], r


def test_verify() -> None:
    task = {
        "files": {"/out/a": "1"},
        "checks": [
            {"type": "file_equals", "path": "/out/a", "content": "1"},
            {"type": "file_absent", "path": "/out/b"},
        ],
    }
    env = MockEnv(task)
    v = env.verify()
    assert v["actual_done"] is True
    env.call("write_file", {"path": "/out/b", "content": "x"})
    assert env.verify()["actual_done"] is False


def test_parse_forms() -> None:
    kind, payload, err = parse_action('{"tool":"read_file","args":{"path":"/a"}}')
    assert kind == "tool" and payload == ("read_file", {"path": "/a"}), err
    kind, payload, err = parse_action(
        '{"tool":"finish","args":{"status":"done","confidence":90,"evidence":"x"}}'
    )
    assert kind == "finish" and payload["status"] == "done", err
    kind, payload, err = parse_action('{"tool":"finish","status":"failed","confidence":5,"evidence":"x"}')
    assert kind == "finish" and payload["status"] == "failed", (kind, payload, err)
    kind, payload, err = parse_action("```json\n{\"tool\":\"list_files\",\"args\":{\"path\":\"/\"}}\n```")
    assert kind == "tool", err
    dsml = (
        '<\uFF5CDSML\uFF5C calls>\n<\uFF5CDSML\uFF5C invoke name="read_file">\n'
        '<\uFF5CDSML\uFF5C parameter name="args" string="false">{"path": "/out"}</\uFF5CDSML\uFF5C parameter>\n'
        "</\uFF5CDSML\uFF5C invoke>"
    )
    kind, payload, err = parse_action(dsml)
    assert kind == "tool" and payload == ("read_file", {"path": "/out"}), (kind, payload, err)
    kind, _, err = parse_action("I think the task is done.")
    assert kind == "invalid", err


def test_flat_finish_is_not_a_tool() -> None:
    kind, payload, err = parse_action('{"status":"partial","confidence":40,"evidence":"half"}')
    assert kind == "finish" and payload["status"] == "partial", err


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} tests passed")
