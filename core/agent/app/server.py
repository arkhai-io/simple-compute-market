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

from core.agent.app.agent import a2a_app, _startup_tasks

# The app is a plain Starlette instance exported from agent.py. The
# historical name `a2a_app` is kept for import stability; no A2A or
# Google ADK machinery runs underneath it anymore.
app = a2a_app


@app.on_event("startup")
async def startup_event() -> None:
    """Start background tasks on server startup."""
    await _startup_tasks()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
