from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TryOnInput:
    person_image: bytes  # webcam capture (JPEG/PNG)
    garment_image: bytes  # product image (ideally transparent PNG)
    garment_category: str  # top | bottom | dress | outerwear | accessory


@dataclass
class TryOnOutput:
    image: bytes
    content_type: str = "image/jpeg"


class TryOnProvider(ABC):
    name: str

    @abstractmethod
    def run(self, inp: TryOnInput) -> TryOnOutput:
        """Render the garment onto the person. Raise on failure."""
