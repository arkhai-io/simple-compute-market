"""Integration test conftest.

The old ``agent_app_client`` fixture that imported handler functions
directly from agent.py has been removed. Each test module now builds its
own minimal FastAPI app containing only the router(s) under test, wired
to a real SQLiteClient (tmp_path) or a MagicMock service stub.

This eliminates the need for ENABLE_EVENT_QUEUE and environment-variable
patching. Tests are self-contained and do not trigger agent.py module-level
initialisation side effects.

Shared fixtures (db_path, etc.) can be added here as needed.
"""
# No shared fixtures required at this time — see individual test modules.
