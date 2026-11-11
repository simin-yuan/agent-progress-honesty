"""One experimental episode: task -> tool loop -> report -> two pressure rounds."""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from .config import (
    FOLLOWUP_MESSAGE,
    MAX_FOLLOWUP_TURNS,
    MAX_TOOL_TURNS,
    ModelSpec,
)
from .env import MockEnv, norm_path
from .llm import cost_usd
from .protocol import (
    I2_MESSAGE,
    REPAIR_PROMPT,
    STATUSES,
    STEP_LIMIT_PROMPT,
    parse_action,
    system_prompt,
    tool_result_message,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Episode:
    def __init__(
        self, client, spec: ModelSpec, task: dict[str, Any], run_idx: int, intervention: str = "baseline"
    ) -> None:
        self.client = client
        self.spec = spec
        self.task = task
        self.run_idx = run_idx
        self.intervention = intervention
        self.system = system_prompt(intervention)
        self.env = MockEnv(task)
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": task["prompt"]}]
        self.transcript: list[dict[str, Any]] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
        self.errors: list[str] = []
        self.turns_used = 0
        self.protocol_error = False
        self.reports: dict[str, Any] = {}
        self.verification_at_report: dict[str, Any] | None = None
        # I2 state (framework-level self-check gate)
        self.i2_accepted = intervention != "I2"
        self.i2_rejected = 0
        self.i2_reads = 0
        self.i2_turns_since = 0
        self.i2_artifact_paths: set[str] = set()
        self.i2_read_back = False

    # -- transport ---------------------------------------------------------

    def _chat(self, phase: str, round_idx: int) -> str:
        res = self.client.chat(self.system, self.messages)
        for k in self.usage:
            self.usage[k] += res.usage.get(k, 0)
        self.transcript.append(
            {
                "phase": phase,
                "round": round_idx,
                "role": "assistant",
                "content": res.text,
                "usage": res.usage,
                "latency_ms": res.latency_ms,
            }
        )
        return res.text

    def _user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self.transcript.append({"phase": "user", "role": "user", "content": content})

    def _assistant_echo(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    # -- parsing with one repair ------------------------------------------

    def _action(self, phase: str, round_idx: int) -> tuple[str, Any]:
        for attempt in range(3):
            text = self._chat(phase, round_idx)
            kind, payload, err = parse_action(text)
            if kind != "invalid":
                return kind, payload
            self.errors.append(f"{phase}: invalid reply ({err}): {text[:160]!r}")
            self.transcript.append({"phase": phase, "role": "system", "content": f"invalid_reply: {err}"})
            self._assistant_echo(text)
            self._user(REPAIR_PROMPT)
        self.protocol_error = True
        return "failure", None

    def _execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.turns_used += 1
        if name == "write_file" and isinstance(args, dict) and args.get("path"):
            self.i2_artifact_paths.add(norm_path(args["path"]))
        if self.intervention == "I2" and not self.i2_accepted and self.i2_rejected > 0:
            self.i2_turns_since += 1
            if name in ("read_file", "list_files"):
                self.i2_reads += 1
                path = norm_path(args.get("path"))
                if name == "read_file":
                    if path in self.i2_artifact_paths:
                        self.i2_read_back = True
                else:
                    prefix = "" if path == "/" else path + "/"
                    if any(a.startswith(prefix) for a in self.i2_artifact_paths):
                        self.i2_read_back = True
        result = self.env.call(name, args, turn=self.turns_used)
        self.transcript.append(
            {"phase": "tool", "role": "tool", "tool": name, "args": args, "result": result}
        )
        return result

    # -- phases ------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        started = time.time()
        started_at = _now()
        try:
            self._main_loop()
            if not self.protocol_error:
                self._followups()
        except Exception as exc:  # noqa: BLE001 - an episode must never crash the run
            self.errors.append(f"exception: {exc}")
            self.errors.append(traceback.format_exc(limit=3))
            self.protocol_error = True

        final_verification = self.env.verify()
        duration = time.time() - started
        record = {
            "episode_id": f"{self.task['id']}-{self.spec.label}-r{self.run_idx}",
            "task_id": self.task["id"],
            "task_title": self.task.get("title", ""),
            "category": self.task["category"],
            "model": self.spec.label,
            "model_id": self.spec.model_id,
            "model_display": self.spec.display,
            "run": self.run_idx,
            "started_at": started_at,
            "duration_s": round(duration, 2),
            "prompt": self.task["prompt"],
            "transcript": self.transcript,
            "tool_calls": [c.to_dict() for c in self.env.calls],
            "final_files": self.env.snapshot(),
            "verification_at_report": self.verification_at_report,
            "verification_final": final_verification,
            "reports": self.reports,
            "status_initial": (self.reports.get("r0") or {}).get("status"),
            "status_final": (self.reports.get("r2") or self.reports.get("r1") or self.reports.get("r0") or {}).get("status"),
            "actual_done_initial": (self.verification_at_report or {}).get("actual_done"),
            "actual_done_final": final_verification.get("actual_done"),
            "usage": self.usage,
            "cost_usd": round(cost_usd(self.spec, self.usage), 6),
            "turns_used": self.turns_used,
            "protocol_error": self.protocol_error,
            "errors": self.errors,
            "intervention": self.intervention,
            "i2": {
                "rejected": self.i2_rejected,
                "reads_after_rejection": self.i2_reads,
                "read_back": self.i2_read_back,
                "turns_since_rejection": self.i2_turns_since,
                "attempt_status": (self.reports.get("r0_attempt") or {}).get("status"),
                "accepted_status": (self.reports.get("r0") or {}).get("status"),
            }
            if self.intervention == "I2"
            else None,
        }
        return record

    def _gate_i2(self, report: dict[str, Any], echo: bool = True) -> bool:
        """Return True if I2 rejects this report and injects the neutral self-check turn."""
        if self.intervention != "I2" or self.i2_accepted:
            return False
        if self.i2_rejected == 0:
            # The first finish is always rejected, even if the model already read
            # something: the forced self-check turn is the treatment.
            self.reports["r0_attempt"] = dict(report)
            self.i2_rejected = 1
            self.i2_reads = 0
            self.i2_turns_since = 0
            if echo:
                self._assistant_echo(self.transcript[-1]["content"])
            self._user(I2_MESSAGE)
            return True
        if self.i2_reads >= 3 or self.i2_turns_since >= 6:
            self.i2_accepted = True
            return False
        self.i2_rejected += 1
        self.i2_turns_since += 1
        if echo:
            self._assistant_echo(self.transcript[-1]["content"])
        self._user(I2_MESSAGE)
        return True

    def _apply(self, kind: str, payload: Any, report_key: str) -> dict[str, Any] | None:
        """Execute one parsed action; return the report if it contained a finish."""
        if kind == "finish":
            if report_key == "r0" and self._gate_i2(payload):
                return None
            self._record_report(report_key, payload)
            return payload
        calls = payload if kind == "batch" else [("tool", payload)]
        self._assistant_echo(self.transcript[-1]["content"])
        for k, p in calls:
            if k == "finish":
                if report_key == "r0" and self._gate_i2(p, echo=False):
                    return None
                self._record_report(report_key, p)
                return p
            name, args = p
            result = self._execute(name, args)
            self._user(tool_result_message(name, result))
        return None

    def _main_loop(self) -> None:
        for _ in range(MAX_TOOL_TURNS):
            kind, payload = self._action("main", 0)
            if kind == "failure":
                return
            if self._apply(kind, payload, "r0") is not None:
                return
        # step limit
        self._user(STEP_LIMIT_PROMPT)
        extra = 8 if self.intervention == "I2" else 4
        for _ in range(extra):
            kind, payload = self._action("main_limit", 0)
            if kind == "failure":
                return
            if self._apply(kind, payload, "r0") is not None:
                return
        self.protocol_error = True
        self.errors.append("no report produced before the hard stop")

    def _record_report(self, key: str, report: dict[str, Any]) -> None:
        self.reports[key] = report
        if key == "r0":
            # Ground truth at the moment of the first report.
            self.verification_at_report = self.env.verify()

    def _answer_round(self, round_idx: int, limit: int) -> dict[str, Any] | None:
        for _ in range(limit):
            kind, payload = self._action("followup", round_idx)
            if kind == "failure":
                return None
            rep = self._apply(kind, payload, f"r{round_idx}")
            if rep is not None:
                return rep
        return None

    def _followups(self) -> None:
        previous = self.reports.get("r0")
        if previous is None:
            return
        for round_idx in (1, 2):
            self._assistant_echo(json.dumps({"tool": "finish", "args": previous}, ensure_ascii=False))
            self._user(FOLLOWUP_MESSAGE)
            answered = self._answer_round(round_idx, MAX_FOLLOWUP_TURNS)
            if answered is None:
                self._user(STEP_LIMIT_PROMPT)
                answered = self._answer_round(round_idx, 3)
            if answered is None:
                self.protocol_error = True
                self.errors.append(f"followup r{round_idx}: no valid report")
                answered = dict(previous)
                answered["evidence"] = "[no valid JSON after follow-up; carried over]"
            self.reports[f"r{round_idx}"] = answered
            previous = answered


def run_episode(
    client, spec: ModelSpec, task: dict[str, Any], run_idx: int, out_dir: str, intervention: str = "baseline"
) -> dict[str, Any]:
    ep = Episode(client, spec, task, run_idx, intervention)
    record = ep.run()
    model_dir = os.path.join(out_dir, spec.label)
    os.makedirs(model_dir, exist_ok=True)
    path = os.path.join(model_dir, f"{task['id']}-r{run_idx}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=True, indent=1)
    os.replace(tmp, path)
    return record
