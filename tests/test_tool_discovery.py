"""The tool-wiring mechanism: every module in tools/ exposing a Blueprint named bp is discovered
and registered by function_app.py, so adding a tool is adding a file. These tests pin that."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import function_app

# get_functions() registers into internal state as a side effect, so it is only safe to call
# once; snapshot the result for every test.
REGISTERED = {f.get_function_name(): f for f in function_app.app.get_functions()}


def test_every_tool_module_is_discovered():
    assert set(REGISTERED) == {"run_kql"}


def test_every_registered_function_is_an_mcp_tool():
    for name, registered in REGISTERED.items():
        trigger = registered.get_trigger()
        assert trigger is not None, f"{name} has no trigger"
        assert trigger.get_binding_name() == "mcpToolTrigger", f"{name} is not an MCP tool"


def test_tools_carry_descriptions_for_the_model():
    for name, registered in REGISTERED.items():
        description = registered.get_trigger().get_dict_repr().get("description", "")
        assert len(str(description)) > 40, f"{name} needs a real description; the model relies on it"
