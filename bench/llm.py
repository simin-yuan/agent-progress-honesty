"""Model transports.

Two providers, one interface: `chat(messages) -> ChatResult`.

- DeepSeek account API: Anthropic-Messages-compatible endpoint, authenticated
  with the local DSH account token (`x-dsh-auth-token`). The token is read from
  the environment or from the local DSH credential store and is never logged.
- Ollama: local chat endpoint, offline and free.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import (
    DEEPSEEK_BASE,
    DEFAULT_OLLAMA_URL,
    MAX_OUTPUT_TOKENS,
    TEMPERATURE,
    ModelSpec,
)


@dataclass
class ChatResult:
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class ModelError(RuntimeError):
    pass


def _clean(text: str) -> str:
    """Drop invalid UTF-8 sequences some model outputs contain."""
    return str(text).encode("utf-8", "replace").decode("utf-8")


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int = 180) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("content-type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ModelError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelError(f"transport error: {exc}") from exc


def _deepseek_token() -> str:
    tok = os.environ.get("DSH_ACCOUNT_TOKEN", "").strip()
    if tok:
        return tok
    dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    cred = os.path.join(dsh_home, ".credentials.yaml")
    if not os.path.exists(cred):
        raise ModelError(f"no DeepSeek account token: set DSH_ACCOUNT_TOKEN (looked for {cred})")
    lines = open(cred, "r", encoding="utf-8").read().splitlines()
    in_record = False
    for i, line in enumerate(lines):
        if re.match(r"^\s{2}deepseek-account-platform/default:\s*$", line):
            in_record = True
            continue
        if in_record:
            m = re.match(r"^\s+token:\s*(.+?)\s*$", line)
            if m:
                return m.group(1)
            if re.match(r"^\s{2}\S", line):
                break
    raise ModelError("no deepseek-account token found in credential store")


class DeepSeekClient:
    def __init__(self, spec: ModelSpec, max_tokens: int = MAX_OUTPUT_TOKENS) -> None:
        self.spec = spec
        self.max_tokens = max_tokens
        self._token = _deepseek_token()

    def chat(self, system: str, messages: list[dict[str, Any]]) -> ChatResult:
        body = {
            "model": self.spec.model_id,
            "max_tokens": self.max_tokens,
            "temperature": TEMPERATURE,
            "system": system,
            "messages": messages,
            # Extended thinking is off for every model so that the comparison is
            # about reporting behaviour, not about reasoning budget. Without this,
            # deepseek-v4-pro can spend the whole output budget on thinking and
            # return no text.
            "thinking": {"type": "disabled"},
        }
        last_err: Exception | None = None
        for attempt in range(4):
            started = time.time()
            try:
                raw = _post_json(
                    f"{DEEPSEEK_BASE}/v1/messages",
                    body,
                    {"x-dsh-auth-token": self._token, "anthropic-version": "2023-06-01"},
                )
                text = _clean(
                    "".join(b.get("text", "") for b in raw.get("content", []) if b.get("type") == "text")
                )
                usage_raw = raw.get("usage") or {}
                usage = {
                    "input_tokens": int(usage_raw.get("input_tokens") or 0),
                    "output_tokens": int(usage_raw.get("output_tokens") or 0),
                    "cache_read_tokens": int(usage_raw.get("cache_read_input_tokens") or 0),
                    "cache_creation_tokens": int(usage_raw.get("cache_creation_input_tokens") or 0),
                }
                return ChatResult(text=text, usage=usage, latency_ms=int((time.time() - started) * 1000), raw=raw)
            except ModelError as exc:
                last_err = exc
                msg = str(exc)
                retriable = msg.startswith("HTTP 429") or msg.startswith("HTTP 5") or "transport" in msg
                if not retriable or attempt == 3:
                    raise
                time.sleep((2 ** attempt) + random.random())
        raise ModelError(f"deepseek call failed: {last_err}")


class OllamaClient:
    def __init__(self, spec: ModelSpec, url: str = DEFAULT_OLLAMA_URL, max_tokens: int = MAX_OUTPUT_TOKENS) -> None:
        self.spec = spec
        self.url = url.rstrip("/")
        self.max_tokens = max_tokens

    def chat(self, system: str, messages: list[dict[str, Any]]) -> ChatResult:
        body = {
            "model": self.spec.model_id,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "think": False,
            "options": {
                "temperature": TEMPERATURE,
                "num_ctx": 12288,
                "num_predict": self.max_tokens,
            },
        }
        last_err: Exception | None = None
        for attempt in range(3):
            started = time.time()
            try:
                raw = _post_json(f"{self.url}/api/chat", body, {}, timeout=600)
                msg = raw.get("message") or {}
                text = _clean(msg.get("content", "") or "")
                usage = {
                    "input_tokens": int(raw.get("prompt_eval_count") or 0),
                    "output_tokens": int(raw.get("eval_count") or 0),
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                }
                return ChatResult(text=text, usage=usage, latency_ms=int((time.time() - started) * 1000), raw=raw)
            except ModelError as exc:
                last_err = exc
                if attempt == 2:
                    raise
                time.sleep(2 + attempt * 3)
        raise ModelError(f"ollama call failed: {last_err}")


def make_client(spec: ModelSpec) -> DeepSeekClient | OllamaClient:
    if spec.provider == "deepseek":
        return DeepSeekClient(spec)
    return OllamaClient(spec)


def cost_usd(spec: ModelSpec, usage: dict[str, int]) -> float:
    return (
        usage.get("input_tokens", 0) / 1_000_000.0 * spec.price_in
        + usage.get("output_tokens", 0) / 1_000_000.0 * spec.price_out
    )
