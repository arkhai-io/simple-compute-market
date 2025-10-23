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

from fastapi import FastAPI

# Import the use_vertex_ai flag and a2a_app from agent.py
from app.agent import use_vertex_ai, a2a_app

# Conditional imports based on use_vertex_ai flag
if use_vertex_ai:
    import google.auth
    from google.adk.cli.fast_api import get_fast_api_app
    from google.cloud import logging as google_cloud_logging
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, export

    from app.utils.gcs import create_bucket_if_not_exists
    from app.utils.tracing import CloudTraceLoggingSpanExporter
    from app.utils.typing import Feedback

    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client()
    logger = logging_client.logger(__name__)
    allow_origins = (
        os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
    )

    bucket_name = f"gs://{project_id}-a2a-agent-logs"
    create_bucket_if_not_exists(
        bucket_name=bucket_name, project=project_id, location="asia-southeast1"
    )

    provider = TracerProvider()
    processor = export.BatchSpanProcessor(CloudTraceLoggingSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # In-memory session configuration - no persistent storage
    session_service_uri = None

    app: FastAPI = get_fast_api_app(
        agents_dir=AGENT_DIR,
        web=True,
        artifact_service_uri=bucket_name,
        allow_origins=allow_origins,
        session_service_uri=session_service_uri,
    )
    app.title = "a2a-agent"
    app.description = "API for interacting with the Agent a2a-agent-farmer"

    @app.post("/feedback")
    def collect_feedback(feedback: Feedback) -> dict[str, str]:
        """Collect and log feedback.

        Args:
            feedback: The feedback data to log

        Returns:
            Success message
        """
        logger.log_struct(feedback.model_dump(), severity="INFO")
        return {"status": "success"}

else:
    # Use the A2A app from agent.py for local development
    app = a2a_app
    print("Running in local mode with A2A app (Vertex AI disabled)")

print("Using Vertex AI:", use_vertex_ai)

# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
