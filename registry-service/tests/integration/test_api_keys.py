"""Integration tests for the admin /api-keys flow + the bearer-token
gate it protects.

Mints + revokes happen via httpx against the FastAPI app over the
ASGITransport, just like every other integration test in this
suite. Uses ``monkeypatch`` to flip ``settings.admin_api_key`` and
the ``settings.require_read_api_key`` / ``require_write_api_key``
toggles per test so each gate's on-vs-off branches are exercised.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from src.config import settings
from src.db.database import get_db
from src.main import app


@pytest_asyncio.fixture
async def raw_client(db_session):
    """A bare httpx.AsyncClient against the registry app — no
    RegistryClient wrapper. Used to send custom Authorization headers
    that the typed client doesn't surface."""
    def _override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = _override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminGate:
    async def test_returns_401_when_admin_key_unset(self, raw_client, monkeypatch):
        """If REGISTRY_ADMIN_API_KEY isn't configured on the server,
        the admin endpoints refuse every request — there's no
        bypass."""
        monkeypatch.setattr(settings, "admin_api_key", None)
        resp = await raw_client.get("/admin/api-keys")
        assert resp.status_code == 401
        assert "disabled" in resp.json()["detail"].lower()

    async def test_returns_401_with_wrong_admin_token(self, raw_client, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_key", "correct-admin")
        resp = await raw_client.get(
            "/admin/api-keys",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    async def test_returns_200_with_correct_admin_token(self, raw_client, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_key", "correct-admin")
        resp = await raw_client.get(
            "/admin/api-keys",
            headers={"Authorization": "Bearer correct-admin"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestApiKeyLifecycle:
    @pytest.fixture(autouse=True)
    def _admin(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_key", "admin-token")

    async def test_create_returns_raw_key_once(self, raw_client):
        """The mint response carries the raw bearer token — operators
        capture it now or never. The DB stores only its hash."""
        resp = await raw_client.post(
            "/admin/api-keys",
            headers={"Authorization": "Bearer admin-token"},
            json={"name": "alice"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "alice"
        assert body["key"] and isinstance(body["key"], str)
        assert body["scope"] == "read"  # least-privilege default
        assert "id" in body and "created_at" in body

        # Subsequent GET must NOT return the raw key — only metadata.
        resp = await raw_client.get(
            "/admin/api-keys",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert "key" not in rows[0]
        assert rows[0]["name"] == "alice"
        assert rows[0]["revoked_at"] is None

    async def test_revoke_marks_key_inactive(self, raw_client):
        create = await raw_client.post(
            "/admin/api-keys",
            headers={"Authorization": "Bearer admin-token"},
            json={"name": "bob"},
        )
        key_id = create.json()["id"]

        revoke = await raw_client.delete(
            f"/admin/api-keys/{key_id}",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert revoke.status_code == 204

        listing = await raw_client.get(
            "/admin/api-keys",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert listing.json()[0]["revoked_at"] is not None

    async def test_revoke_unknown_id_returns_404(self, raw_client):
        resp = await raw_client.delete(
            "/admin/api-keys/9999",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Bearer-token gate on non-admin routes
# ---------------------------------------------------------------------------

# A write endpoint whose only pre-route logic is the write gate, then an
# agent lookup that 404s for an unregistered id. So: 401 (no key) / 403
# (read key) come from the gate; 404 means the gate let the request
# through to the route. Avoids needing a signed payload to probe the gate.
_WRITE_PROBE = "/agents/0x000000000000000000000000000000000000dEaD/heartbeat"


class _GateBase:
    @pytest.fixture(autouse=True)
    def _admin(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_key", "admin-token")

    async def _mint(self, raw_client, name="user", scope="read"):
        resp = await raw_client.post(
            "/admin/api-keys",
            headers={"Authorization": "Bearer admin-token"},
            json={"name": name, "scope": scope},
        )
        return resp.json()["key"], resp.json()["id"]


class TestGatesDisabled(_GateBase):
    async def test_reads_and_writes_open_when_both_off(self, raw_client, monkeypatch):
        """Default public registry — neither direction needs a key."""
        monkeypatch.setattr(settings, "require_read_api_key", False)
        monkeypatch.setattr(settings, "require_write_api_key", False)
        assert (await raw_client.get("/listings")).status_code == 200
        # Write gate off → request reaches the route (404 for unknown agent).
        assert (await raw_client.post(_WRITE_PROBE)).status_code == 404


class TestReadGate(_GateBase):
    @pytest.fixture(autouse=True)
    def _gate(self, monkeypatch):
        monkeypatch.setattr(settings, "require_read_api_key", True)
        monkeypatch.setattr(settings, "require_write_api_key", False)

    async def test_401_without_key(self, raw_client):
        resp = await raw_client.get("/listings")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    async def test_200_with_read_key(self, raw_client):
        raw, _ = await self._mint(raw_client, scope="read")
        resp = await raw_client.get(
            "/listings", headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200

    async def test_200_with_write_key(self, raw_client):
        """A write key implies read access."""
        raw, _ = await self._mint(raw_client, scope="write")
        resp = await raw_client.get(
            "/listings", headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200

    async def test_401_after_revocation(self, raw_client):
        raw, key_id = await self._mint(raw_client, scope="read")
        ok = await raw_client.get(
            "/listings", headers={"Authorization": f"Bearer {raw}"},
        )
        assert ok.status_code == 200

        await raw_client.delete(
            f"/admin/api-keys/{key_id}",
            headers={"Authorization": "Bearer admin-token"},
        )
        gone = await raw_client.get(
            "/listings", headers={"Authorization": f"Bearer {raw}"},
        )
        assert gone.status_code == 401

    async def test_writes_open_when_only_read_gated(self, raw_client):
        """Read-gated but write-open: a write needs no key, reaches the route."""
        assert (await raw_client.post(_WRITE_PROBE)).status_code == 404


class TestWriteGate(_GateBase):
    @pytest.fixture(autouse=True)
    def _gate(self, monkeypatch):
        # Open-market posture: public discovery, gated publishing.
        monkeypatch.setattr(settings, "require_read_api_key", False)
        monkeypatch.setattr(settings, "require_write_api_key", True)

    async def test_reads_open_when_only_write_gated(self, raw_client):
        assert (await raw_client.get("/listings")).status_code == 200

    async def test_write_401_without_key(self, raw_client):
        resp = await raw_client.post(_WRITE_PROBE)
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    async def test_write_403_with_read_key(self, raw_client):
        raw, _ = await self._mint(raw_client, scope="read")
        resp = await raw_client.post(
            _WRITE_PROBE, headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 403
        assert "write-scoped" in resp.json()["detail"]

    async def test_write_passes_gate_with_write_key(self, raw_client):
        """Write key clears the gate; 404 is the route rejecting an
        unknown agent, not the gate rejecting the key."""
        raw, _ = await self._mint(raw_client, scope="write")
        resp = await raw_client.post(
            _WRITE_PROBE, headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404


class TestHealthAlwaysOpen(_GateBase):
    async def test_health_unaffected_by_gates(self, raw_client, monkeypatch):
        """/health stays open even with both gates on so liveness
        probes don't need credentials."""
        monkeypatch.setattr(settings, "require_read_api_key", True)
        monkeypatch.setattr(settings, "require_write_api_key", True)
        resp = await raw_client.get("/health")
        assert resp.status_code == 200
