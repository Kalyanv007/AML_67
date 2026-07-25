"""
Auto-discovering tool registry — see docs/CONTRACTS.md Contract 3.

Owner: Track A. Walks backend/tools/ and imports every module so that any
function decorated with @tool registers itself into backend.tools.base.TOOLS.
Track B adds tools by editing files in backend/tools/ and never needs to
touch this file.
"""

import importlib
import pkgutil
import sys

import backend.tools as tools_pkg
from backend.tools.base import TOOLS


def load_tools(use_mocks: bool = False) -> dict:
    """Populate TOOLS for the given mode and return a fresh snapshot.

    TOOLS is a single global dict — a module's @tool decorator only runs on
    its *first* import, so without clearing+reloading here, calling this
    function more than once with different `use_mocks` values (e.g. across a
    test session that exercises both modes) leaves stale entries: whichever
    module registered a given tool name *last* wins, regardless of the mode
    requested on this call. Clearing TOOLS and reloading already-imported
    modules makes every call deterministic in the requested mode.
    """
    TOOLS.clear()
    for mod in pkgutil.iter_modules(tools_pkg.__path__):
        if mod.name == "base":
            continue
        if mod.name == "_mocks" and not use_mocks:
            continue
        if mod.name != "_mocks" and use_mocks:
            continue
        module_name = f"backend.tools.{mod.name}"
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)
    return dict(TOOLS)
