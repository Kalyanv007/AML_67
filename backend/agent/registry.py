"""
Auto-discovering tool registry — see docs/CONTRACTS.md Contract 3.

Owner: Track A. Walks backend/tools/ and imports every module so that any
function decorated with @tool registers itself into backend.tools.base.TOOLS.
Track B adds tools by editing files in backend/tools/ and never needs to
touch this file.
"""

import importlib
import pkgutil

import backend.tools as tools_pkg
from backend.tools.base import TOOLS


def load_tools(use_mocks: bool = False) -> dict:
    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name == "base":
            continue
        if mod.name == "_mocks" and not use_mocks:
            continue
        if mod.name != "_mocks" and use_mocks:
            continue
        importlib.import_module(f"backend.tools.{mod.name}")
    return dict(TOOLS)
