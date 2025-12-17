"""
Agent card utilities for building agent card data from configuration.
Shared by server (agent.py) and registration script (onchain_registration.py).
"""
from typing import Optional


def build_agent_card_data(
    agent_id: str,
    base_url: str,
    description: Optional[str] = None
) -> dict:
    """
    Build agent card JSON data from configuration.
    Shared function used by both server (agent.py) and registration script.
    
    Args:
        agent_id: Agent ID/name (from AGENT_ID env var or CONFIG.agent_id)
        base_url: Base URL of the agent (e.g., http://localhost:8000)
        description: Optional description (defaults to standard description)
    
    Returns:
        Agent card JSON dict matching A2A AgentCard format
    """
    return {
        "name": agent_id,
        "description": description or "A helpful AI assistant designed to trade compute resources with others.",
        "url": base_url,
        "version": "0.1.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [],
        "capabilities": {
            "streaming": True
        }
    }

