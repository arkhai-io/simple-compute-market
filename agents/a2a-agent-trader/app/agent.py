# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import random
import uuid
from dataclasses import asdict, dataclass
from typing import Optional, override, AsyncGenerator
from enum import Enum

import google.auth
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import HTTPException
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent, BaseAgent,  InvocationContext
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
from google.genai import types as genai_types
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import logging
logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp")
BASE_URL_OVERRIDE = os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000")
PORT = os.getenv("PORT", 8000)
REMOTE_AGENT_URL_OVERRIDE = os.getenv(
    "REMOTE_AGENT_URL_OVERRIDE", "http://localhost:8001"
)

use_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() in (
    "true",
    "1",
    "yes",
)
if use_vertex_ai:
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            _, project_id = google.auth.default()
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        except Exception:
            # If default credentials are not available, continue without setting the project.
            # Downstream code should handle missing configuration gracefully or via env vars.
            pass
    os.environ.setdefault(
        "GOOGLE_CLOUD_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    )


class GPUModel(str, Enum):
    """Supported GPU SKUs for compute resources."""

    H200 = "H200"
    TESLA_V100 = "Tesla V100"
    RTX_5080 = "RTX 5080"


class Region(str, Enum):
    """Regions where compute resources can be provisioned."""

    CALIFORNIA_US = "California, US"
    NEW_YORK_US = "New York, US"
    TOKYO_JP = "Tokyo, JP"

class EventType(str, Enum):
    """Events that can be handled by the Agent"""

    MAKE_OFFER = "make_offer"
    RESOURCE_IMBALANCE = "resource_imbalance"
    CRON_JOB = "cron_job"
    ARBITRAGE_OPPORTUNITY = "arbitrage_opportunity"

class OrderTag(str, Enum):
    """Types of orders in the market. May be BUY or SELL."""

    BUY = "buy"
    SELL = "sell"


@dataclass
class ComputeResource:
    """Describes an allocatable compute resource node managed by the trader."""

    gpu_model: GPUModel
    quantity: int
    sla: float  # percentage value in the range [0, 100]
    region: Region


# In-memory stand-in for compute nodes under the Agent's control. 
resource_portfolio = {
    "us-node-1a": ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=3,
        sla=90.0,
        region=Region.CALIFORNIA_US
        ),
    "jp-node-7b": ComputeResource(
        gpu_model=GPUModel.TESLA_V100,
        quantity=2,
        sla=99.9,
        region=Region.TOKYO_JP
        )
}

@dataclass
class Order:
    """Describes an order on the market."""

    order_id: str
    tag: OrderTag
    order_maker: str # Card URL  (TODO: Replace this with the Agent's later on ID.)
    compute_resource: ComputeResource
    duration: int  # duration in days
    offer_token: str
    offer_value: float
    buyer_attestation: Optional[str] = None  # To be filled after negotation
    seller_attestation: Optional[str] = None # To be filled after negotation



def get_resource_portfolio() -> dict:
    """Get the current stock of all resources managed by the node portfolio.

    Returns:
        A dictionary representing the current portfolio stock.
    """
    return resource_portfolio

def rebalance_internal_resources() -> bool:
    """Reallocate internal resources to optimize usage.

    Returns:
        True if the process was successfully initiated.
    """
    logger.info("[TOOL] Rebalancing resources...")
    return True

def make_order(order_tag: OrderTag, gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create an order in the market.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The created order as a dictionary if the order was successfully created, or None otherwise.
        This creates a UUID identifying the new order, and the details should match the provided arguments.
    """
    logger.info(f"[TOOL] Creating order of type {order_tag} for resource.")
    order = Order(
        order_id=str(uuid.uuid4()),
        tag=order_tag,
        order_maker=BASE_URL_OVERRIDE,
        compute_resource=ComputeResource(
            gpu_model=GPUModel(gpu_model_str),
            quantity=1,
            sla=sla,
            region=Region(region_str),
        ),
        duration=1, # 1 Day
        offer_token="USDT",
        offer_value=9*100,
    )
    return asdict(order)

def make_sell_order(gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create a SELL order in the market, selling available resources. After order creation, save it to Redis,
    report to confirm order details, and signal for the remote_agent to evaluate the order on their end.
    Provide the remote_agent the order_id.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The order as a dictionary if the order was successfully created, or None otherwise.
    """
    return make_order(OrderTag.SELL, gpu_model_str, sla, region_str)

def make_buy_order(gpu_model_str: str, sla: float, region_str: str) -> dict | None:
    """Create a BUY order in the market. After order creation, report to confirm order details, save it to Redis,
    and signal for the remote_agent to evaluate the order on their end. Provide the remote_agent the order_id.

    Args:
        order_tag: The type of transaction (OrderTag.BUY or OrderTag.SELL).
        gpu_model_str: The GPU model, one of: {"H200", "Tesla V100", "RTX 5080"}
        sla: SLA required for the order.
        region_str: Geographic region, one of: {"California, US", "New York, US, "Tokyo, JP"}

    Returns:
        The order as a dictionary if the order was successfully created, or None otherwise.
    """
    return make_order(OrderTag.BUY, gpu_model_str, sla, region_str)

def reject_offer() -> bool:
    """Reject a received offer.

    Returns:
        True if the rejection was successfully communicated.
    """
    logger.info("[TOOL] Rejecting received offer.")
    return True

def accept_offer() -> bool:
    """Accept a received offer.

    Returns:
        String UUID with which to fill up if the rejection was successfully communicated.
    """
    logger.info("[TOOL] Accepting received offer.")
    return True

def evaluate_received_offer(order_id: str) -> str:
    """Given a make_offer event denoting an INCOMING offer from another agent, evaluate whether or not to accept it.
    Following the recommendation, invoke either accept_offer or reject_offer.

    Returns:
        String with policy recommendation of next action to take.
    """

    policy_recommendation = consult_policy(EventType.MAKE_OFFER.value)

    return policy_recommendation

def consult_policy(event_type: str) -> str | None:
    """Given a triggering event, use the history store to determine the next action to take.
    The subsequent action to take will be summarized in CAPITALS.

    The available event trigger types are:
        make_offer
        resource_imbalance

    Returns:
        A string representing the action to take, and (if applicable) the corresponding
        tool and the arguments to supply, or None if no action is available for the event type.
        A valid event with no available actions will be distinct from an invalid, unrecognized event type.
    """
    match event_type:
        case EventType.MAKE_OFFER.value:
            result = random.choice([
                "ACCEPT the offer.",
                "REJECT the offer.",
                # "Counter-propose."
                # "No-op."
                ])
        case EventType.RESOURCE_IMBALANCE.value:
            result = random.choice([
                "MAKE OFFER. Create market order. If resource usage is HIGH, then make a BUY order matching the resource model and region. If resource usage is LOW, then make a SELL order to sell the excess.",
                "RESOLVE INTERALLY. Run rebalance_internal_resources utility.",
                ])
        case EventType.CRON_JOB.value:
            result = "UNAVAILABLE. No actions available for event type."
        case EventType.ARBITRAGE_OPPORTUNITY.value:
            result = "UNAVAILABLE. No actions available for event type."
        case _:
            result = "INVALID. Invalid event type."
    
    logger.info(f"[TOOL] Response to {event_type}: {result}")
    return result


def _extract_text_from_content(content: genai_types.Content | None) -> str:
    """Concatenate text parts from generative content."""
    if not content or not getattr(content, "parts", None):
        return ""
    text_parts: list[str] = []
    for part in content.parts:
        if getattr(part, "text", None):
            text_parts.append(part.text)  # type: ignore[arg-type]
    return "".join(text_parts).strip()


remote_agent = RemoteA2aAgent(
    name=f"remote_agent_{PORT}",
    description="A helpful AI assistant trading compute resources with others.",
    agent_card=f"{REMOTE_AGENT_URL_OVERRIDE}{AGENT_CARD_WELL_KNOWN_PATH}",
)

class TraderAgent(BaseAgent):
    """
    Custom agent for trading computational resources.
    """

    def __init__(
        self,
        # tools,
        name: str,
    ):
        """
        Initializes the Trader Agent.
        """

        logger.info("Starting TraderAgent.")
        super().__init__(
            name=name,
            # tools=tools,
        )

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_text = _extract_text_from_content(ctx.user_content)
        logger.info("[%s] User text: %s", self.name, user_text)

        previous_text = _extract_text_from_content(ctx.session.events[-1].content)
        logger.info("[%s] Previous text: %s", self.name, previous_text)

        if "User" not in previous_text:
            # I'm in Step 1. Add "User()".
            text_to_remote = f"User({previous_text})"
            next_text = text_to_remote

            await ctx.session_service.append_event(ctx.session, Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part.from_text(text=text_to_remote)],
                ),
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
            ))

            async for event in remote_agent.run_async(ctx):
                text_from_remote = _extract_text_from_content(event.content)
                next_text = f"Local({text_from_remote})"

        elif "User" in previous_text and "Remote" not in previous_text:
            # I'm in Step 2. Add "Remote()".
            next_text = f"Remote({previous_text})"

        yield Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=next_text)],
            ),
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
        )

root_agent = TraderAgent(
    name="root_agent",
    # tools=[
    #     get_resource_portfolio,
    #     consult_policy,
    #     rebalance_internal_resources,
    #     make_buy_order,
    #     make_sell_order,
    #     evaluate_received_offer,
    #     accept_offer,
    #     reject_offer,
    #     AgentTool(remote_agent),
    #     MCPToolset(
    #         connection_params=StreamableHTTPConnectionParams(
    #             url=MCP_SERVER_URL
    #         )
    #     ),
    #     ],
    # sub_agents=[],
)

# Create a2a app

# Define the skill for the root agent
# In the future, we prefer to use agent-card.json to define the skills and capabilities of the agent. https://google.github.io/adk-docs/a2a/quickstart-exposing/#getting-the-sample-code

public_agent_card = AgentCard(
    name="A2A Agent",
    description="A helpful AI assistant designed to trade compute resources with others.",
    url=BASE_URL_OVERRIDE,
    version="0.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[],
    capabilities=AgentCapabilities(streaming=True),
)

ALERTS_APP_NAME = "alerts"
ALERTS_USER_ID = "resource-monitor"


async def _run_alert_conversation(alert: dict) -> str:
    """Route alert details through the root agent so it can decide on next steps."""
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        app_name=ALERTS_APP_NAME,
        user_id=ALERTS_USER_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=ALERTS_APP_NAME,
        session_service=session_service,
    )

    event_type = EventType.RESOURCE_IMBALANCE.value
    policy_recommendation = consult_policy(event_type)

    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_text(
                text=(
                    # "ALERT DETAILS:\n"
                    f"{json.dumps(alert, indent=2)}"
                    # "POLICY RECOMMENDATION:\n"
                    # f"{json.dumps(policy_recommendation, indent=2)}\n\n"
                )
            )
        ],
    )

    final_response: str | None = None
    async for event in runner.run_async(
        user_id=ALERTS_USER_ID,
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text_parts = [
                part.text
                for part in event.content.parts
                if hasattr(part, "text") and part.text
            ]
            if text_parts:
                final_response = "".join(text_parts)
                break

    if not final_response:
        raise HTTPException(
            status_code=500,
            detail="root_agent did not provide a response to the resource alert.",
        )
    return final_response


async def handle_resource_alert(request: Request) -> JSONResponse:
    """Expose an endpoint that forwards resource alerts to the root agent."""
    try:
        alert = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    response_text = await _run_alert_conversation(alert)
    response = dict(alert)
    response["root_agent_response"] = response_text

    return JSONResponse(response)


# Create Starlette route for the alert endpoint
alert_route = Route("/alerts/resource", handle_resource_alert, methods=["POST"])


a2a_app = to_a2a(root_agent, port=PORT, agent_card=public_agent_card)

# Add the alert route to the A2A app
a2a_app.routes.append(alert_route)
