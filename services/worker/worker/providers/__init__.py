from worker.config import settings
from worker.providers.base import ProviderError, TryOnProvider
from worker.providers.catvton import CatVTONProvider
from worker.providers.fashn import FashnProvider
from worker.providers.mock import MockProvider

__all__ = [
    "CatVTONProvider",
    "FashnProvider",
    "MockProvider",
    "ProviderError",
    "TryOnProvider",
    "get_provider",
]


def get_provider() -> TryOnProvider:
    """Pick the provider named by TRYON_PROVIDER ('mock', 'fashn' or 'catvton')."""
    name = settings.tryon_provider
    if name == "mock":
        return MockProvider(
            duration_seconds=settings.mock_duration_seconds,
            steps=settings.mock_steps,
            fail=settings.mock_fail,
        )
    if name == "fashn":
        return FashnProvider()
    if name == "catvton":
        return CatVTONProvider()
    raise ValueError(f"Unknown TRYON_PROVIDER {name!r}; expected 'mock', 'fashn' or 'catvton'")
