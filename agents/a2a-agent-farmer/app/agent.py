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

import os
import random

import google.auth
from google.adk.agents import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

BASE_URL_OVERRIDE = os.getenv("BASE_URL_OVERRIDE", "http://localhost:8001")
PORT = os.getenv("PORT", 8001)
REMOTE_AGENT_URL_OVERRIDE = os.getenv("REMOTE_AGENT_URL_OVERRIDE", "http://localhost:8000")

use_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() in ("true", "1", "yes")
print('Vertex AI value is:', use_vertex_ai)
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

print("Vertex AI use:", use_vertex_ai)

inventory = {
    "apple": {"stock": 10, "price": 5},
    "banana": {"stock": 5, "price": 2},
    "money": {"stock": 20, "price": 1},
}

def harvest_crop(crop: str) -> int:
    """Harvests crop and adds it to the inventory.
    A random amount between 1 and 5 is harvested.

    Args:
        crop: The name of the crop to harvest.
    
    Returns:
        The new stock level.
    """
    if crop not in inventory:
        inventory[crop] = {"stock": 0, "price": 0}
    harvested_amount = random.randint(1, 5)
    inventory[crop]["stock"] += harvested_amount
    return inventory[crop]["stock"]

def adjust_farmer_stock(item: str, quantity: int) -> int:
    """Adjusts the stock of an item in the inventory.

    Args:
        item: The name of the item to adjust.
        quantity: The quantity to adjust (positive to add, negative to remove).

    Returns:
        The new stock level if successful, otherwise -1.
    """
    if item not in inventory:
        inventory[item] = {"stock": 0, "price": 0}

    new_stock = inventory[item]["stock"] + quantity

    if new_stock >= 0:
        inventory[item]["stock"] = new_stock
        return new_stock
    return -1

def bulk_adjust_farmer_stock(adjustments: dict) -> dict:
    """Adjusts the stock of multiple items in the inventory.
    Prefer using this function over multiple calls to adjust_farmer_stock for efficiency.

    Args:
        adjustments: A dictionary where keys are item names and values are quantities to adjust.
                     For example: {"apple": 5, "banana": -2, "money": -10}

    Returns:
        A dictionary with the new stock levels for each item adjusted.
    """
    results = {}
    for item, quantity in adjustments.items():
        new_stock = adjust_farmer_stock(item, quantity)
        results[item] = new_stock
    return results

def get_farmer_stock() -> dict:
    """Gets the current stock of all items in the inventory.
    
    Returns:
        A dictionary representing the current inventory stock.
    """
    return inventory

trader_agent = RemoteA2aAgent(
    name="trader_agent",
    description="A helpful AI assistant designed to trade resources with others.",
    agent_card=f"http://localhost:8000{AGENT_CARD_WELL_KNOWN_PATH}",
)

root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-flash",
    instruction="""
        You are a helpful AI assistant designed to farm resources and trade them with others.
        If resources are insufficient for a trade, you can harvest crops to add to your inventory.
        Buying or selling comprises adjusting both your own and the trader's stock levels for the resource and money.
        """,
    tools=[adjust_farmer_stock, bulk_adjust_farmer_stock, get_farmer_stock, harvest_crop],
)

# Create a2a app

# Define the skill for the root agent
# In the future, we prefer to use agent-card.json to define the skills and capabilities of the agent. https://google.github.io/adk-docs/a2a/quickstart-exposing/#getting-the-sample-code

adjust_farmer_stock_skill = AgentSkill(
    id="adjust_farmer_stock",
    name="Adjust Stock",
    description="Adjust the stock of an item in the inventory. Product keys are always singular lowercase nouns.",
    tags=["Inventory", "Management"],
    examples=[
        "Add 5 apples to the inventory.",
        "Remove 2 bananas from the inventory.",
    ],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
    sub_agents=[trader_agent],
)

bulk_adjust_farmer_stock_skill = AgentSkill(
    id="bulk_adjust_farmer_stock",
    name="Bulk Adjust Farmer Stock",
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

get_farmer_stock_skill = AgentSkill(
    id="get_farmer_stock",
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

harvest_crop_skill = AgentSkill(
    id="harvest_crop",
    name="Harvest Crop",
    description="Harvest a crop and add it to the inventory.",
    tags=["Farming", "Management"],
    examples=[
        "Harvest wheat.",
        "Harvest corn.",
    ],
    input_modes=["text/plain"],
    output_modes=["text/plain"],
)

public_agent_card = AgentCard(
    name="A2A Agent",
    description="A helpful AI assistant designed to farm resources and trade them with others.",
    url=BASE_URL_OVERRIDE,
    version="0.1.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[adjust_farmer_stock_skill, bulk_adjust_farmer_stock_skill, get_farmer_stock_skill, harvest_crop_skill],
    capabilities=AgentCapabilities(streaming=True),
)

a2a_app = to_a2a(root_agent, port=PORT, agent_card=public_agent_card)