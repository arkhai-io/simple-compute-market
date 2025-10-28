import datetime
import os
from typing import Dict, Any
from zoneinfo import ZoneInfo

import google.auth
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp")
use_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() in ("true", "1", "yes")

def get_current_session_id(tool_context: ToolContext) -> Dict[str, Any]:
    """Retrieves and returns the ID of the current session."""
    session_id = tool_context._invocation_context.session.id
    # save the session id to the state also as a key called "current_session_id"
    tool_context.state["current_session_id"] = session_id
    return {"current_session_id": session_id}


if use_vertex_ai:
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            _, project_id = google.auth.default()
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        except Exception:
            # If default credentials are not available, continue without setting the project.
            # Downstream code should handle missing configuration gracefully or via env vars.
            pass
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global"))

root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-flash",
    instruction="You are a helpful AI Assistant with access to the current session id. Use the current session id as a key to saving information in redis",        
    tools=[
        MCPToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=MCP_SERVER_URL
            )
        ),
        get_current_session_id
    ],
)
