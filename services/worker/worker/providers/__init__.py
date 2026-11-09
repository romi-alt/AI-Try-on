from worker.config import settings
from worker.providers.base import ProviderError, TryOnProvider
from worker.providers.fashn import FashnProvider
from worker.providers.mock import MockProvider

__all__ = ["FashnProvider", "MockProvider", "ProviderError", "TryOnProvider", "get_provider"]


def get_provider() -> TryOnProvider:
    """Pick the provider named by TRYON_PROVIDER ('mock' or 'fashn')."""
    name = settings.tryon_provider
    if name == "mock":
        return MockProvider(
            duration_seconds=settings.mock_duration_seconds,
            steps=settings.mock_steps,
            fail=settings.mock_fail,
        )
    if name == "fashn":
        return FashnProvider()
    raise ValueError(f"Unknown TRYON_PROVIDER {name!r}; expected 'mock' or 'fashn'")
