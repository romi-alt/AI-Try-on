"""Payment provider interface for the mobile checkout, with a stub.

Only the stub exists. A real provider (JazzCash, Easypaisa, a card processor) implements `PaymentProvider`
and is
added to `PROVIDERS`; the mobile checkout route does not change. Nothing here handles card details: a real
provider
would redirect the shopper to its own hosted page (`redirect_url`) rather than take a card number in this app.
"""

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.config import settings


@dataclass(frozen=True)
class PaymentResult:
    status: Literal["paid", "pending", "failed"]
    reference: str  # the provider's id for this payment
    redirect_url: str | None = None  # where to send the shopper to finish paying, for `pending`
    message: str | None = None  # a reason fit to show the shopper when `failed`


class PaymentProvider(Protocol):
    name: str

    async def charge(
        self, *, order_id: uuid.UUID, amount_pkr: int, description: str, idempotency_key: str
    ) -> PaymentResult:
        """Ask the provider to collect `amount_pkr` rupees for an order.

        Must be safe to repeat with the same `idempotency_key`: the shopper must not be charged twice.
        """
        ...


class StubPaymentProvider:
    """Approves (or, for tests and demos, declines) every payment without contacting anyone."""

    name = "stub"

    async def charge(
        self, *, order_id: uuid.UUID, amount_pkr: int, description: str, idempotency_key: str
    ) -> PaymentResult:
        reference = f"stub_{order_id.hex[:16]}"  # derived from the order, so a repeat gets the same one
        if settings.stub_payment_outcome == "failed":
            return PaymentResult("failed", reference, message="The payment was declined")
        return PaymentResult("paid", reference)


PROVIDERS: dict[str, type[PaymentProvider]] = {"stub": StubPaymentProvider}


def get_payment_provider() -> PaymentProvider:
    try:
        return PROVIDERS[settings.payment_provider]()
    except KeyError:
        raise RuntimeError(
            f"Unknown PAYMENT_PROVIDER {settings.payment_provider!r}; available: {', '.join(PROVIDERS)}"
        ) from None
