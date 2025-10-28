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
from dataclasses import dataclass
from enum import Enum

import google.auth
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import HTTPException
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.genai import types as genai_types
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

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
    """Types of orders in the market. May be BUY or SELL.
    """

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class ComputeResource:
    """Describes an allocatable compute resource node managed by the trader."""

    gpu_model: GPUModel
    quantity: int
    sla: float  # percentage value in the range [0, 100]
    region: Region


# In-memory stand-in for compute nodes under the Agent's control. 
resource_portfolio = [
    ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=3,
        sla=90,
        region=Region.CALIFORNIA_US
        ),
    ComputeResource(
        gpu_model=GPUModel.TESLA_V100,
        quantity=2,
        sla=99.9,
        region=Region.TOKYO_JP
        )
]


def get_resource_portfolio() -> dict:
    """Gets the current stock of all resources managed by the node portfolio.

    Returns:
        A dictionary representing the current portfolio stock.
    """
    return resource_portfolio

def rebalance_internal_resources():
    """Reallocates internal resources to optimize usage.
    """
    print("[TOOL] Rebalancing resources...")
    return

def make_order(order_tag: OrderTag):
    """Create an order in the market.

    Returns:
        True if the order was successfully created.
    """
    print(f"[TOOL] Creating order of type {order_tag} for resource.")
    return True

def make_sell_order() -> bool:
    """Create a SELL order in the market.

    After order creation, signal for the remote_agent to evaluate the order on their end.

    Returns:
        True if the order was successfully created.
    """
    return make_order(OrderTag.SELL)

def make_buy_order() -> bool:
    """Create a BUY order in the market.
    
    After order creation, signal for the remote_agent to evaluate the order on their end.

    Returns:
        True if the order was successfully created.
    """
    return make_order(OrderTag.BUY)

def reject_offer() -> bool:
    """Reject a received offer.

    Returns:
        True if the rejection was successfully communicated.
    """
    print("[TOOL] Rejecting received offer.")
    return True

def accept_offer() -> bool:
    """Accept a received offer.

    Returns:
        True if the rejection was successfully communicated.
    """
    print("[TOOL] Accepting received offer.")
    return True

def evaluate_received_offer() -> str:
    """Given a make_offer event, evaluate whether or not to accept it.
    This should lead into invocation of either accept_offer or reject_offer.

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
                "MAKE OFFER. Create market order. If resource usage is HIGH, then make a BUY order. If resource usage is LOW, then make a SELL order to sell the excess.",
                "RESOLVE INTERALLY. Run rebalance_internal_resources utility.",
                ])
        case EventType.CRON_JOB.value:
            result = "UNAVAILABLE. No actions available for event type."
        case EventType.ARBITRAGE_OPPORTUNITY.value:
            result = "UNAVAILABLE. No actions available for event type."
        case _:
            result = "INVALID. Invalid event type."
    
    print(f"[TOOL] Response to {event_type}: {result}")
    return result

remote_agent = RemoteA2aAgent(
    name="remote_agent",
    description="A helpful AI assistant trading compute resources with others.",
    agent_card=f"{REMOTE_AGENT_URL_OVERRIDE}{AGENT_CARD_WELL_KNOWN_PATH}",
)

root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-flash",
    instruction="""
        You are a helpful AI assistant designed to manage, trade, and balance compute resources.

        FOR AUTOMATED ALERTS: When you receive inventory alerts, you must immediately execute action according to the policy recommendation:
        - Check your current inventory first using get_resource_portfolio()
        - Report transaction details and new inventory levels
        - After creation of offers in the market, instruct the remote agent to check received offers.
    """,
    tools=[
        get_resource_portfolio,
        consult_policy,
        rebalance_internal_resources,
        make_buy_order,
        make_sell_order,
        evaluate_received_offer,
        accept_offer,
        reject_offer,
        AgentTool(remote_agent),
        ],
    sub_agents=[],
)

# Create a2a app

# Define the skill for the root agent
# In the future, we prefer to use agent-card.json to define the skills and capabilities of the agent. https://google.github.io/adk-docs/a2a/quickstart-exposing/#getting-the-sample-code

get_resource_portfolio_skill = AgentSkill(
    id="get_resource_portfolio",
    name="Get Stock",
    description="Get the current stock of an item in the inventory",
    tags=["Inventory", "Information"],
    examples=[
        "What resources are you selling?",
        "Are you buying compute?",
    ],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
)

public_agent_card = AgentCard(
    name="A2A Agent",
    description="You are a helpful AI assistant designed to trade compute resources with others.",
    url=BASE_URL_OVERRIDE,
    version="0.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        # get_resource_portfolio_skill,
    ],
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
                    "RESOURCE MONITORING ALERT RECEIVED\n\n"
                    "ALERT DETAILS:\n"
                    f"{json.dumps(alert, indent=2)}\n\n"
                    "POLICY RECOMMENDATION:\n"
                    f"{json.dumps(policy_recommendation, indent=2)}\n\n"
                    "Execute the corresponding tool now and report the results. Include:\n"
                    "- What action was taken\n"
                    "- Whether the action had a result, and if so, what it was"
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
        # print(event)
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
