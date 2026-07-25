"""
Frozen contract — see docs/CONTRACTS.md Contract 2.

Owner: Track A. Read-only for Track B. Every tool in backend/tools/ is a pure
function of (ToolContext, **params) -> ToolResult, registered with @tool.

No tool may import from backend.agent. No tool may import another tool.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
from pydantic import BaseModel, ConfigDict


@dataclass
class ToolContext:
    df: pd.DataFrame
    customers: pd.DataFrame | None = None
    intent: Any = None  # backend.schemas.QueryIntent; Any here to avoid agent<->tools import
    artifacts: dict[str, Any] = field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ok: bool = True
    df: Any | None = None
    artifacts: dict = {}
    tables: dict = {}
    charts: dict = {}
    metrics: dict = {}
    notes: list[str] = []
    error: str | None = None


TOOLS: dict[str, Callable] = {}


def tool(name: str, params: dict | None = None, description: str = ""):
    """Register a tool under `name`. backend.agent.registry auto-discovers everything
    decorated with this by walking backend/tools/ — do not hand-maintain an import list."""

    def deco(fn: Callable) -> Callable:
        fn._tool_name = name
        fn._tool_params = params or {}
        fn._tool_description = description
        TOOLS[name] = fn
        return fn

    return deco
