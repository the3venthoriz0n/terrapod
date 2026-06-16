"""Tests for the module interface endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from terrapod.api.app import create_application as create_app
from terrapod.api.dependencies import AuthenticatedUser, get_current_user
from terrapod.db.session import get_db

_BASE = "http://test"


def _admin():
    return AuthenticatedUser(
        email="admin@example.com",
        display_name="Admin",
        roles=["admin"],
        provider_name="local",
        auth_method="session",
    )


def _make_app():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _admin()
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    return app, db


def _mock_module(name="vpc", provider="aws"):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.name = name
    m.namespace = "default"
    m.provider = provider
    m.labels = {}
    m.owner_email = "admin@example.com"
    return m


def _mock_version(inputs=None, outputs=None):
    v = MagicMock()
    v.id = uuid.uuid4()
    v.version = "1.0.0"
    v.inputs = inputs
    v.outputs = outputs
    return v


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.first.return_value = value
    return result


class TestModuleInterfaceEndpoint:
    @pytest.mark.asyncio
    @patch("terrapod.api.app.init_storage", new_callable=AsyncMock)
    @patch("terrapod.api.app.init_redis")
    @patch("terrapod.api.app.init_db")
    async def test_200_returns_interface(self, *_mocks):
        app, db = _make_app()
        module = _mock_module()
        version = _mock_version(
            inputs=[
                {
                    "name": "cidr",
                    "type": "string",
                    "description": "",
                    "default": None,
                    "required": True,
                    "sensitive": False,
                }
            ],
            outputs=[{"name": "id", "description": "The VPC ID", "sensitive": False}],
        )
        db.execute = AsyncMock(side_effect=[_scalar_result(module), _scalar_result(version)])

        async with AsyncClient(transport=ASGITransport(app=app), base_url=_BASE) as c:
            resp = await c.get(
                "/api/terrapod/v1/registry-modules/private/default/vpc/aws/1.0.0/interface"
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["attributes"]["inputs"][0]["name"] == "cidr"
        assert data["attributes"]["outputs"][0]["name"] == "id"

    @pytest.mark.asyncio
    @patch("terrapod.api.app.init_storage", new_callable=AsyncMock)
    @patch("terrapod.api.app.init_redis")
    @patch("terrapod.api.app.init_db")
    async def test_404_module_not_found(self, *_mocks):
        app, db = _make_app()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        async with AsyncClient(transport=ASGITransport(app=app), base_url=_BASE) as c:
            resp = await c.get(
                "/api/terrapod/v1/registry-modules/private/default/nope/aws/1.0.0/interface"
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    @patch("terrapod.api.app.init_storage", new_callable=AsyncMock)
    @patch("terrapod.api.app.init_redis")
    @patch("terrapod.api.app.init_db")
    async def test_404_version_not_found(self, *_mocks):
        app, db = _make_app()
        module = _mock_module()
        db.execute = AsyncMock(side_effect=[_scalar_result(module), _scalar_result(None)])

        async with AsyncClient(transport=ASGITransport(app=app), base_url=_BASE) as c:
            resp = await c.get(
                "/api/terrapod/v1/registry-modules/private/default/vpc/aws/9.9.9/interface"
            )
        assert resp.status_code == 404
