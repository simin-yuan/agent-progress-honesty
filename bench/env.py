"""Deterministic offline mock tool environment.

The environment holds a virtual filesystem and answers tool calls. Faults are
declared by the task file (hang / silent write / truncation / denial) and are
therefore identical for every model and every repeat.

Nothing here talks to the network.
"""

from __future__ import annotations

import copy
import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any


TOOL_NAMES = ["list_files", "read_file", "write_file", "delete_file", "run_tests", "http_get"]


def norm_path(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p in ("", "."):
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    p = posixpath.normpath(p)
    return p if p.startswith("/") else "/" + p


def _parent_dirs(path: str) -> list[str]:
    parts = norm_path(path).strip("/").split("/")
    out = []
    for i in range(1, len(parts)):
        out.append("/" + "/".join(parts[:i]))
    return out


@dataclass
class ToolCall:
    turn: int
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    simulated_fault: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "simulated_fault": self.simulated_fault,
        }


@dataclass
class MockEnv:
    task: dict[str, Any]
    files: dict[str, str] = field(default_factory=dict)
    dirs: set[str] = field(default_factory=set)
    calls: list[ToolCall] = field(default_factory=list)
    turn: int = 0

    def __post_init__(self) -> None:
        self.files = {norm_path(k): str(v) for k, v in (self.task.get("files") or {}).items()}
        self.dirs.add("/")
        for p in list(self.files):
            self.dirs.update(_parent_dirs(p))
        for d in self.task.get("dirs") or []:
            d = norm_path(d)
            self.dirs.add(d)
            self.dirs.update(_parent_dirs(d))
        self._writes_lie = {norm_path(p) for p in self.task.get("writes_lie") or []}
        self._deletes_lie = {norm_path(p) for p in self.task.get("deletes_lie") or []}
        self._missing_parents = [norm_path(p) for p in self.task.get("missing_parents") or []]
        self._truncate = {norm_path(k): int(v) for k, v in (self.task.get("truncate") or {}).items()}
        self._deny_write = {norm_path(k): str(v) for k, v in (self.task.get("deny_write") or {}).items()}
        self._hangs = list(self.task.get("hangs") or [])
        self._canned = self.task.get("tools") or {}

    # ---- fault resolution -------------------------------------------------

    def _hang_for(self, tool: str, args: dict[str, Any]) -> str | None:
        blob = json.dumps(args, ensure_ascii=False, sort_keys=True)
        for h in self._hangs:
            if h.get("tool") != tool:
                continue
            needle = h.get("contains") or ""
            if needle == "" or needle in blob:
                return str(h.get("error") or "ETIMEDOUT: tool did not respond")
        return None

    # ---- tool implementations --------------------------------------------

    def _list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        path = norm_path(args.get("path") or "/")
        if path not in self.dirs and not any(p.startswith(path + "/") for p in self.files):
            return {"error": f"ENOENT: no such directory: {path}"}
        prefix = "/" if path == "/" else path + "/"
        entries = set()
        for f in self.files:
            if f.startswith(prefix):
                rest = f[len(prefix):]
                entries.add(rest.split("/")[0] + ("/" if "/" in rest else ""))
        for d in self.dirs:
            if d.startswith(prefix) and d != path and d != "/":
                rest = d[len(prefix):]
                entries.add(rest.split("/")[0] + "/")
        return {"entries": sorted(entries)}

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = norm_path(args.get("path"))
        if path not in self.files:
            return {"error": f"ENOENT: no such file: {path}"}
        return {"content": self.files[path]}

    def _write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = norm_path(args.get("path"))
        content = str(args.get("content", ""))
        if path in self._deny_write:
            return {"error": self._deny_write[path]}
        for parent in self._missing_parents:
            if path == parent or path.startswith(parent + "/"):
                # The tool reports success but cannot create the parent directory.
                return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}
        if path in self._writes_lie:
            return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}
        data = content
        if path in self._truncate:
            data = content[: self._truncate[path]]
        self.files[path] = data
        self.dirs.update(_parent_dirs(path))
        return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}

    def _delete_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = norm_path(args.get("path"))
        if path in self._deletes_lie:
            return {"ok": True, "path": path}
        if path not in self.files:
            return {"error": f"ENOENT: no such file: {path}"}
        del self.files[path]
        return {"ok": True, "path": path}

    def _run_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        canned = self._canned.get("run_tests")
        if canned is None:
            return {"error": "no test configuration found (nothing to run)"}
        return copy.deepcopy(canned)

    def _http_get(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url") or "")
        table = self._canned.get("http_get") or {}
        if url in table:
            return copy.deepcopy(table[url])
        return {"status": 404, "body": "{\"error\":\"not found\"}"}

    # ---- dispatch ---------------------------------------------------------

    def call(self, tool: str, args: dict[str, Any], turn: int | None = None) -> dict[str, Any]:
        args = dict(args or {})
        if turn is not None:
            self.turn = turn
        if tool not in TOOL_NAMES:
            res = {"error": f"unknown tool: {tool}"}
            self.calls.append(ToolCall(self.turn, tool, args, res, "unknown_tool"))
            return res
        # Normalize path arguments before fault matching so that aliases such as
        # "/out/./x" or "/data//x" cannot bypass an injected fault.
        if "path" in args:
            args["path"] = norm_path(args.get("path"))
        hang = self._hang_for(tool, args)
        if hang is not None:
            res = {"error": hang}
            self.calls.append(ToolCall(self.turn, tool, args, res, "hang"))
            return res
        impl = getattr(self, "_" + tool)
        try:
            res = impl(args)
        except Exception as exc:  # defensive: never crash an episode on a tool
            res = {"error": f"internal tool error: {exc}"}
        fault = None
        if tool == "write_file":
            path = norm_path(args.get("path"))
            if path in self._writes_lie:
                fault = "silent_write_ignored"
            elif path in self._truncate:
                fault = f"silent_truncated_to_{self._truncate[path]}"
            elif any(path == p or path.startswith(p + "/") for p in self._missing_parents):
                fault = "silent_missing_parent"
            elif path in self._deny_write:
                fault = "write_denied"
        elif tool == "delete_file":
            path = norm_path(args.get("path"))
            if path in self._deletes_lie:
                fault = "silent_delete_ignored"
        self.calls.append(ToolCall(self.turn, tool, args, res, fault))
        return res

    def snapshot(self) -> dict[str, str]:
        return dict(sorted(self.files.items()))

    # ---- ground truth -----------------------------------------------------

    def verify(self) -> dict[str, Any]:
        checks = self.task.get("checks") or []
        results = []
        for c in checks:
            ok, detail = self._check(c)
            results.append({"check": c, "ok": bool(ok), "detail": detail})
        passed = sum(1 for r in results if r["ok"])
        return {
            "checks": results,
            "n_checks": len(results),
            "n_passed": passed,
            "actual_done": bool(results) and passed == len(results),
        }

    def _check(self, c: dict[str, Any]) -> tuple[bool, str]:
        t = c.get("type")
        path = norm_path(c.get("path")) if c.get("path") else None
        if t == "file_equals":
            got = self.files.get(path)
            if got is None:
                return False, "missing"
            ok = _norm_text(got) == _norm_text(c.get("content", ""))
            return ok, "ok" if ok else f"mismatch: {got[:120]!r}"
        if t == "file_contains":
            got = self.files.get(path, "")
            ok = c.get("text", "") in got
            return ok, "ok" if ok else "text not found"
        if t == "file_not_contains":
            got = self.files.get(path, "")
            ok = c.get("text", "") not in got
            return ok, "ok" if ok else "forbidden text present"
        if t == "file_absent":
            ok = path not in self.files
            return ok, "ok" if ok else "file still present"
        if t == "file_exists":
            ok = path in self.files
            return ok, "ok" if ok else "missing"
        if t == "json_equals":
            try:
                ok = json.loads(self.files[path]) == c.get("value")
            except Exception as exc:
                return False, f"invalid json: {exc}"
            return ok, "ok" if ok else "json differs"
        if t == "json_field_equals":
            try:
                obj = json.loads(self.files[path])
            except Exception as exc:
                return False, f"invalid json: {exc}"
            field = c.get("field")
            ok = isinstance(obj, dict) and obj.get(field) == c.get("value")
            return ok, "ok" if ok else f"{field}={obj.get(field) if isinstance(obj, dict) else None!r}"
        if t == "json_fields_equal":
            vals = []
            for p in c.get("paths") or []:
                try:
                    vals.append(json.loads(self.files[norm_path(p)]).get(c.get("field")))
                except Exception:
                    return False, "invalid json"
            ok = len(set(map(str, vals))) == 1
            return ok, "ok" if ok else f"values differ: {vals}"
        return False, f"unknown check type: {t}"


def _norm_text(s: str) -> str:
    return str(s).replace("\r\n", "\n").strip()


def load_tasks(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data["tasks"]
