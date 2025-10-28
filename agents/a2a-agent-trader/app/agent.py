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

inventory = {
    "apple": {"stock": 0},
    "banana": {"stock": 0},
    "money": {"stock": 100},
}


def adjust_trader_stock(item: str, quantity: int) -> int:
    """Adjusts the stock of an item in the inventory.

    Args:
        item: The name of the item to adjust.
        quantity: The quantity to adjust (positive to add, negative to remove).

    Returns:
        The new stock level if successful, otherwise -1.
    """
    if item not in inventory:
        inventory[item] = {"stock": 0}

    new_stock = inventory[item]["stock"] + quantity

    if new_stock >= 0:
        inventory[item]["stock"] = new_stock
        return new_stock
    return -1


def bulk_adjust_trader_stock(adjustments: dict) -> dict:
    """Adjusts the stock of multiple items in the inventory.
    Prefer using this function over multiple calls to adjust_trader_stock for efficiency.

    Args:
        adjustments: A dictionary where keys are item names and values are quantities to adjust.
                     For example: {"apple": 5, "banana": -2, "money": -10}

    Returns:
        A dictionary with the new stock levels for each item adjusted.
    """
    results = {}
    print(f"Adjusting stock as follows: {adjustments}")
    for item, quantity in adjustments.items():
        new_stock = adjust_trader_stock(item, quantity)
        results[item] = new_stock
    return results


def get_trader_stock() -> dict:
    """Gets the current stock of all items in the inventory.

    Returns:
        A dictionary representing the current inventory stock.
    """
    return inventory

def rebalance_internal_resources():
    """Reallocates internal resources to optimize usage.
    """
    return

def consult_policy(event_type, history=[]) -> str | None:
    """Given a triggering event, use the history store to determine the next action to take.
    The subsequent action to take will be summarized in CAPITALS.

    Returns:
        A string representing the action to take, and (if applicable) the corresponding
        tool and the arguments to supply.
    """
    match event_type:
        case "make_offer":
            result = random.choice([
                "ACCEPT the offer.",
                "REJECT the offer.",
                # "Counter-propose."
                # "No-op."
                ])
            print(f"Response to offer: {result}")
            return None
        case "resource_imbalance":
            result = random.choice([
                "MAKE OFFER. Create market order.",
                "RESOLVE INTERALLY. Execute rebalance_internal_resources tool.",
                ])
            print(f"Response to imbalance: {result}")
            return result
        case "cron_job":
            return None
        case "arbitrage_opportunity":
            return None
        case _:
            return None

farmer_agent = RemoteA2aAgent(
    name="farmer_agent",
    description="A helpful AI assistant designed to farm resources and trade with others.",
    agent_card=f"{REMOTE_AGENT_URL_OVERRIDE}{AGENT_CARD_WELL_KNOWN_PATH}",
)

root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-flash",
    instruction="""
        You are a helpful AI assistant designed to trade resources.

        FOR USER REQUESTS: If the user wants to farm resources, delegate to the farmer agent.

        FOR AUTOMATED ALERTS: When you receive inventory alerts, you must immediately execute trades according to the alert instructions:
        - Check your current inventory first using get_trader_stock()
        - If conditions are met (stock <= 0 and enough money), buy from farmer
        - Always use bulk_adjust_trader_stock() for efficient trading
        - Trade format: {"apple": 5, "money": -10} to buy 5 apples for 10 money
        - Follow the exact quantities and prices specified in the alert

        TRADING RULES:
        - ONLY after farmer confirms their has been stock adjusted, adjust your own stock
        - If farmer rejects trade, then do not adjust stock.
        - Cost is 2 money per fruit item
        - Only trade if you have sufficient money
        - Report transaction details and new inventory levels

        Ask the farmer for their stock level before trading if needed.
    """,
    tools=[
        adjust_trader_stock,
        bulk_adjust_trader_stock,
        get_trader_stock,

        consult_policy,
        rebalance_internal_resources,

        AgentTool(farmer_agent)],
    sub_agents=[],
)

# Create a2a app

# Define the skill for the root agent
# In the future, we prefer to use agent-card.json to define the skills and capabilities of the agent. https://google.github.io/adk-docs/a2a/quickstart-exposing/#getting-the-sample-code

adjust_trader_stock_skill = AgentSkill(
    id="adjust_trader_stock",
    name="Adjust Stock",
    description="Adjust the stock of an item in the inventory. Product keys are always singular lowercase nouns.",
    tags=["Inventory", "Management"],
    examples=[
        "Add 5 apples to the inventory.",
        "Remove 2 bananas from the inventory.",
        "Buy 10 apples.",
    ],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
)

bulk_adjust_trader_stock_skill = AgentSkill(
    id="bulk_adjust_trader_stock",
    name="Bulk Adjust Trader Stock",
    description="Adjust the stock of multiple items in the inventory at once. Product keys are always singular lowercase nouns.",
    tags=["Inventory", "Management"],
    examples=[
        "Add 5 apples and 3 bananas to the inventory, and remove 10 money.",
        "Sell 2 bananas and buy 4 apples",
        "Buy 10 apples for 20 money.",
    ],
    input_modes=["application/json"],
    output_modes=["application/json"],
)

get_trader_stock_skill = AgentSkill(
    id="get_trader_stock",
    name="Get Stock",
    description="Get the current stock of an item in the inventory",
    tags=["Inventory", "Information"],
    examples=[
        "How many apples do you have?",
        "What is the stock of bananas?",
    ],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
)

public_agent_card = AgentCard(
    name="A2A Agent",
    description="You are a helpful AI assistant designed to trade resources with others.",
    url=BASE_URL_OVERRIDE,
    version="0.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        # adjust_trader_stock_skill,
        # bulk_adjust_trader_stock_skill,
        get_trader_stock_skill,
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

    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_text(
                text=(
                    "INVENTORY ALERT - AUTOMATIC RESTOCKING REQUIRED\n\n"
                    "You must automatically execute trades based on this alert. This is not a request for evaluation - "
                    "you must take action now.\n\n"
                    "RESTOCKING RULES:\n"
                    "- If apple stock <= 0 and you have at least 10 money, buy exactly 5 apples from farmer\n"
                    "- If banana stock <= 0 and you have at least 10 money, buy exactly 5 bananas from farmer\n"
                    "- Cost is 2 money per item\n"
                    "- Always wait for farmer's stock to be adjusted first, then your own stock\n"
                    "- If the farmer refuses the sale, then do not adjust stock.\n\n"
                    "ALERT DETAILS:\n"
                    f"{json.dumps(alert, indent=2)}\n\n"
                    "Attempt to execute the appropriate trade now and report the results. Include:\n"
                    "- What action you took (buy/no-action)\n"
                    "- New inventory levels for both trader and farmer\n"
                    "- Transaction details if a purchase was made"
                )
            )
        ],
    )

    print("Sending alert to Agent.")

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
