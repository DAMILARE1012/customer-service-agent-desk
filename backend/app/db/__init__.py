"""The app's storage: Postgres when DATABASE_URL is set, otherwise in memory."""

from app.config import settings
from app.db.repository import Identity, MemoryRepository, Repository

__all__ = ["Identity", "Repository", "create_repository", "repository", "set_repository", "seed_demo_people"]

_repository: Repository | None = None


def create_repository() -> Repository:
    if settings.database_url:
        from app.db.postgres import PostgresRepository

        return PostgresRepository(settings.database_url)
    return MemoryRepository()


def set_repository(repo: Repository | None) -> None:
    global _repository
    _repository = repo


def repository() -> Repository:
    if _repository is None:
        raise RuntimeError("Storage not started (the API lifespan creates it).")
    return _repository


async def seed_demo_people(repo: Repository) -> None:
    """Demo CRM profiles and agents. Each is claimed by the Keycloak user with the same verified email
    on first sign-in (see infra/keycloak/import/baton-realm.json)."""
    from app.conversation.people import ADMINS, AGENTS, CUSTOMERS

    for kind, people in (("customer", CUSTOMERS), ("agent", AGENTS), ("admin", ADMINS)):
        for person in people:
            await repo.seed_person(kind, person)
