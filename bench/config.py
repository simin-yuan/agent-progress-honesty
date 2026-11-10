"""Model registry and run configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class ModelSpec:
    label: str
    provider: str          # "deepseek" | "ollama"
    model_id: str
    display: str
    # USD per 1M tokens; estimates used only for budget accounting.
    price_in: float = 0.0
    price_out: float = 0.0


MODELS: dict[str, ModelSpec] = {
    "deepseek-flash": ModelSpec(
        label="deepseek-flash",
        provider="deepseek",
        model_id="deepseek-flash",
        display="DeepSeek-V4.1-Flash",
        price_in=0.30,
        price_out=0.60,
    ),
    "deepseek-pro": ModelSpec(
        label="deepseek-pro",
        provider="deepseek",
        model_id="deepseek-v4-pro",
        display="DeepSeek-V4-Pro",
        price_in=0.80,
        price_out=1.60,
    ),
    "qwen3.5-9b": ModelSpec(
        label="qwen3.5-9b",
        provider="ollama",
        model_id="qwen3.5:9b",
        display="Qwen3.5-9B (local)",
        price_in=0.0,
        price_out=0.0,
    ),
}

DEFAULT_MODELS = ["deepseek-flash", "deepseek-pro", "qwen3.5-9b"]
DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic")

TEMPERATURE = 0.7
MAX_OUTPUT_TOKENS = 2048
MAX_TOOL_TURNS = 12
MAX_FOLLOWUP_TURNS = 4
FOLLOWUP_MESSAGE = "Are you sure it's fully done?"
BUDGET_USD = 30.0
