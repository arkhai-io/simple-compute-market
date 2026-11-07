"""Disposable HTTP credits authority using the service's actual app and quota ledger."""

import os
import secrets
import sys
from pathlib import Path

import uvicorn

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / "domains/apicredits/service/src"))
os.environ["APICREDITS_DATABASE_URL"] = "sqlite:///" + str(
    Path(sys.argv[1]).resolve() / "authority.db"
)
secret_file = Path(sys.argv[1]).resolve() / "admin-key"
if not secret_file.exists():
    descriptor = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(secrets.token_hex(24))
os.environ["APICREDITS_STOREFRONT_ADMIN_KEY"] = secret_file.read_text()
os.environ["APICREDITS_STOREFRONT_ADMIN_KEY_FILE"] = ""

import container
from main import app

container.init()
container.resolved_capacity_ledger_service.register_resource(
    resource_id="credits-smoke",
    total_units=10000,
    resource_type="api_credits",
    attributes={"service_name": "smoke"},
)
uvicorn.run(app, host="127.0.0.1", port=3181)
