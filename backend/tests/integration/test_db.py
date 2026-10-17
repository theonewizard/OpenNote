"""The app's engine is created by the lifespan and serves request-scoped sessions."""

import pytest
from sqlalchemy import text
from starlette.requests import Request

from app.api.main import create_app
from app.core.db import session_scope

pytestmark = pytest.mark.anyio


async def test_session_scope_queries_through_the_app_engine(make_settings):
    app = create_app(make_settings())
    async with app.router.lifespan_context(app):
        async for session in session_scope(Request({"type": "http", "app": app})):
            assert await session.scalar(text("SELECT 1")) == 1
            assert session.bind is app.state.engine
