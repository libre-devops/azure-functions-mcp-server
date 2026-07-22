"""The MCP server's entry point: discovers and registers every tool blueprint in tools/.

Wiring in a new tool is dropping a module into tools/ that exposes a module-level `bp`
(an azure.functions.Blueprint) carrying one or more @bp.mcp_tool() functions. It is discovered
and registered here; nothing else needs touching.
"""

import importlib
import pkgutil

import azure.functions as func

import tools

app = func.FunctionApp()

for _module in pkgutil.iter_modules(tools.__path__):
    blueprint = getattr(importlib.import_module(f"tools.{_module.name}"), "bp", None)
    if isinstance(blueprint, func.Blueprint):
        app.register_blueprint(blueprint)
