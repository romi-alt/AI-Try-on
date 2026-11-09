from worker.config import settings
from worker.providers.base import TryOnProvider
from worker.providers.replicate import ReplicateProvider
from worker.providers.stub import StubProvider


def get_provider() -> TryOnProvider:
    name = settings.tryon_provider.lower()
    if name == "stub":
        return StubProvider()
    if name == "replicate":
        return ReplicateProvider()
    raise ValueError(f"Unknown TRYON_PROVIDER {name!r}")
