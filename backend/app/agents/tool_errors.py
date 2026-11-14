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


def tool_budget(limit: int, per_tool: dict[str, int] | None = None):
    """Middleware that lets an agent make at most `limit` tool calls.

    `per_tool` additionally caps individual tools by name (e.g. Reddit searches).

    Past the limit a call is not executed; the agent gets a message telling it
    to stop searching and answer with what it has. Create one per agent run —
    the counter lives in the closure.
    """
    used = 0
    used_by_tool: dict[str, int] = {}
    caps = per_tool or {}

    @wrap_tool_call
    async def budget(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        nonlocal used
        name = request.tool_call["name"]
        if name in caps:
            used_by_tool[name] = used_by_tool.get(name, 0) + 1
            if used_by_tool[name] > caps[name]:
                return ToolMessage(
                    content=(
                        f"{name} is limited to {caps[name]} calls per run and that is used up. "
                        "Work with what you already have."
                    ),
                    tool_call_id=request.tool_call["id"],
                    status="error",
                )
        used += 1
        if used > limit:
            return ToolMessage(
                content=(
                    f"Tool budget of {limit} calls is used up. Do not search any more: "
                    "return your final structured answer now with the candidates you already have."
                ),
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return await handler(request)

    return budget
