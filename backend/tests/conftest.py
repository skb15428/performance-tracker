import os
import tempfile

from cryptography.fernet import Fernet

_db = os.path.join(tempfile.mkdtemp(), "test.db")
# Set TEST_DATABASE_URL to run against Postgres (the database is wiped).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_db}")
os.environ["GEMINI_API_KEY"] = ""
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["JOBS_SECRET"] = "test-secret"
os.environ["ALLOW_REGISTRATION"] = "true"  # tests create several users

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.llm import set_llm_override  # noqa: E402
from tests.fakes import FakeProvider  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture
def fake_llm():
    fake = FakeProvider()
    set_llm_override(fake)
    yield fake
    set_llm_override(None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def register(client: AsyncClient, email: str) -> dict:
    r = await client.post("/auth/register", json={"email": email, "password": "pw-123456!"})
    assert r.status_code == 201, r.text
    r = await client.post("/auth/jwt/login", data={"username": email, "password": "pw-123456!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
