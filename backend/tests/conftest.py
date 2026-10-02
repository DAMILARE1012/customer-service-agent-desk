import pytest

from app.config import settings


@pytest.fixture(autouse=True, scope="session")
def _isolated_settings():
    """Tests never reach real services: no Langfuse traces, no Groq calls, no judge sampling."""
    settings.langfuse_public_key = ""
    settings.langfuse_secret_key = ""
    settings.groq_api_key = ""
    settings.online_eval_sample_rate = 0
    settings.database_url = ""  # in-memory storage, seeded with the demo profiles
    settings.seed_demo_data = True
    yield
