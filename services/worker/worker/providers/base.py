import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# Providers report how far along they are as 0-100 for their own part of the job.
ProgressFn = Callable[[int], None]


@dataclass(frozen=True)
class GarmentInput:
    product_id: uuid.UUID
    name: str
    category: str  # top | bottom | dress | shoes | bag | accessory
    image: bytes


@dataclass(frozen=True)
class TryOnRequest:
    person_image: bytes  # the shopper's capture (WebP)
    garments: Sequence[GarmentInput]  # applied in order


@dataclass(frozen=True)
class TryOnResult:
    image: bytes
    content_type: str


class ProviderError(Exception):
    """A try-on failure with a message that is safe and useful to show to a shopper.

    `detail` carries the technical specifics for the logs only.
    """

    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class TryOnProvider(ABC):
    name: str

    @abstractmethod
    def run(self, request: TryOnRequest, on_progress: ProgressFn) -> TryOnResult:
        """Render the garments onto the person. Raise ProviderError for expected failures."""
