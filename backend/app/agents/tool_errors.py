"""Turn a tool exception into a message the agent can read and react to.

`create_agent` (v1) no longer catches tool exceptions by default. Without
this, one provider hiccup would crash the whole run instead of costing one
tool call. Must be async: agents here run under `ainvoke`/`astream`, and
LangGraph's ToolNode requires an async `awrap_tool_call` in an async run.
"""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command


@wrap_tool_call
async def handle_tool_errors(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    try:
        return await handler(request)
    except Exception as e:  # noqa: BLE001 - deliberately broad, see module docstring
        return ToolMessage(
            content=f"Tool error ({request.tool_call['name']}): {e}",
            tool_call_id=request.tool_call["id"],
            status="error",
        )
