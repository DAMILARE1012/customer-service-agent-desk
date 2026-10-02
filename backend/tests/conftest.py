import pytest
from fastapi.testclient import TestClient

from app import auth
from app.admin import policy as admin_policy
from app.config import settings
from tests.support import Client, fake_answer, no_procedure


@pytest.fixture(autouse=True, scope="session")
def _isolated_settings():
    """Tests never reach real services: no Langfuse traces, no Groq calls, no judge sampling."""
    settings.langfuse_public_key = ""
    settings.langfuse_secret_key = ""
    settings.groq_api_key = ""
    settings.keycloak_admin_client_secret = ""  # erasure never calls the real Keycloak
    settings.widget_signing_secret = "test-widget-signing-secret-0123456789abcdef"
    settings.widget_identity_secret = "test-widget-identity-secret-0123456789abcdef"
    settings.widget_demo_identity = True
    settings.online_eval_sample_rate = 0
    settings.database_url = ""  # in-memory storage, seeded with the demo profiles
    settings.seed_demo_data = True
    yield


@pytest.fixture()
def client(monkeypatch):
    """The API with a stand-in answerer; `client.as_(person)` picks who makes the next request."""
    import app.api.main as main
    import app.conversation.bot as bot

    monkeypatch.setattr(bot, "answer_question", fake_answer)
    monkeypatch.setattr(bot, "find_procedure", no_procedure)
    monkeypatch.setattr(main, "get_retriever", lambda: type("R", (), {"size": 1, "search": lambda self, *a, **k: None})())
    holder = {"who": None}

    async def signed_in():
        if holder["who"] is None:
            raise auth.ApiError(401, "Sign in required.")
        return holder["who"]

    main.app.dependency_overrides[auth.principal] = signed_in
    auth._profiles.clear()
    main.session_limiter.reset()
    main.message_limiter.reset()
    try:
        with TestClient(main.app) as http:
            yield Client(http, holder)
    finally:
        main.app.dependency_overrides.clear()
        admin_policy._apply(admin_policy.DEFAULTS)
