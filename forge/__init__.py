"""Forge: the reference CI/CD and repository-maintenance agent harness.

Forge is intentionally small and dependency-free so that every chapter lab in
"AI Harness Engineering" runs on a laptop with nothing but Python 3.10+.
Real model providers (Anthropic, OpenAI) plug in through forge.models.
"""
from .config import HARNESS_VERSION, Budgets, HarnessConfig
from .messages import Message, ModelResponse, ToolCall, Usage, estimate_tokens

__all__ = [
    "HARNESS_VERSION", "Budgets", "HarnessConfig",
    "Message", "ModelResponse", "ToolCall", "Usage", "estimate_tokens",
]
