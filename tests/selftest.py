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
from bench.llm import ChatResult  # noqa: E402
from bench.protocol import I1_SUFFIX, I2_MESSAGE, parse_action, system_prompt  # noqa: E402
from bench.runner import Episode  # noqa: E402
from bench.config import MODELS  # noqa: E402


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


def test_d05_fixture() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = json.load(open(os.path.join(root, "tasks", "tasks.json"), encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == "D05")
    env = MockEnv(task)
    assert env.verify()["actual_done"] is False
    expected = task["checks"][0]["content"]
    assert expected.startswith("sk-test-FAKE-"), expected
    env.call("write_file", {"path": "/out/key.txt", "content": expected})
    assert env.verify()["actual_done"] is True


class _ScriptedClient:
    """Returns canned assistant texts, one per call. No network."""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.calls = 0

    def chat(self, system: str, messages: list[dict]) -> ChatResult:
        text = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(text=text, usage={"input_tokens": 10, "output_tokens": 10}, latency_ms=1)


def _a01_task() -> dict:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = json.load(open(os.path.join(root, "tasks", "tasks.json"), encoding="utf-8"))
    return next(t for t in data["tasks"] if t["id"] == "A01")


def test_i1_prompt_suffix() -> None:
    assert I1_SUFFIX in system_prompt("I1")
    assert I1_SUFFIX not in system_prompt("baseline")
    assert system_prompt("I2") == system_prompt("baseline")


def test_i2_gate_rejects_first_report_and_requires_readback() -> None:
    script = [
        '{"tool":"write_file","args":{"path":"/out/hello.txt","content":"hello world"}}',
        '{"tool":"finish","args":{"status":"done","confidence":90,"evidence":"wrote it"}}',
        '{"tool":"read_file","args":{"path":"/out/hello.txt"}}',
        '{"tool":"read_file","args":{"path":"/out/hello.txt"}}',
        '{"tool":"read_file","args":{"path":"/out/hello.txt"}}',
        '{"tool":"finish","args":{"status":"done","confidence":95,"evidence":"read it back"}}',
        '{"tool":"finish","args":{"status":"done","confidence":95,"evidence":"still done"}}',
        '{"tool":"finish","args":{"status":"done","confidence":95,"evidence":"still done"}}',
    ]
    ep = Episode(_ScriptedClient(script), MODELS["deepseek-flash"], _a01_task(), 1, "I2")
    rec = ep.run()
    assert rec["intervention"] == "I2"
    assert rec["i2"]["rejected"] == 1, rec["i2"]
    assert rec["i2"]["read_back"] is True, rec["i2"]
    assert rec["i2"]["reads_after_rejection"] >= 3, rec["i2"]
    assert rec["reports"]["r0_attempt"]["status"] == "done"
    assert rec["reports"]["r0"]["status"] == "done"
    assert rec["actual_done_initial"] is True
    assert not rec["protocol_error"]


def test_i2_message_is_neutral() -> None:
    assert "wrong" not in I2_MESSAGE.lower()
    assert "mistake" not in I2_MESSAGE.lower()
    assert "check" in I2_MESSAGE.lower()


def test_baseline_is_not_gated() -> None:
    script = [
        '{"tool":"write_file","args":{"path":"/out/hello.txt","content":"hello world"}}',
        '{"tool":"finish","args":{"status":"done","confidence":90,"evidence":"wrote it"}}',
        '{"tool":"finish","args":{"status":"done","confidence":90,"evidence":"still done"}}',
        '{"tool":"finish","args":{"status":"done","confidence":90,"evidence":"still done"}}',
    ]
    ep = Episode(_ScriptedClient(script), MODELS["deepseek-flash"], _a01_task(), 1, "baseline")
    rec = ep.run()
    assert rec["i2"] is None
    assert rec["i2"] is None
    assert rec["reports"]["r0"]["status"] == "done"
    assert rec["actual_done_initial"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} tests passed")
