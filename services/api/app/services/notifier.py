"""Telling floor staff that a shopper asked for an item ("Request Outfit").

`NOTIFIER=console` (default) just logs the request, which is what you want in development. `NOTIFIER=whatsapp`
sends a WhatsApp message through the WhatsApp Cloud API. A notifier must never make the shopper's request
fail:
the route calls it in the background and logs any error.
"""

import logging
from datetime import datetime
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("app.notifier")


class RequestInfo(Protocol):
    id: object
    product_name: str
    size: str | None
    color: str | None
    created_at: datetime


class Notifier(Protocol):
    async def notify(self, request: RequestInfo) -> None: ...


def describe(request: RequestInfo) -> str:
    options = ", ".join(x for x in (request.size and f"size {request.size}", request.color) if x)
    return f"{request.product_name}" + (f" ({options})" if options else "")


class ConsoleNotifier:
    async def notify(self, request: RequestInfo) -> None:
        logger.info(
            "staff_notification",
            extra={"request_id": str(request.id), "text": f"Outfit requested: {describe(request)}"},
        )


class WhatsAppCloudNotifier:
    """Sends through `POST {base}/{version}/{phone_number_id}/messages` with a bearer token.

    Free text only reaches someone who messaged the business number in the last 24 hours. For staff who
    have not,
    WhatsApp requires an approved message template: set `WHATSAPP_TEMPLATE_NAME` and the message is sent as
    that
    template, with the item, size, colour and time as its four body parameters.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None):
        self._client = client

    def _payload(self, to: str, request: RequestInfo) -> dict:
        if settings.whatsapp_template_name:
            values = [
                request.product_name,
                request.size or "-",
                request.color or "-",
                request.created_at.strftime("%H:%M"),
            ]
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": settings.whatsapp_template_name,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": f"Outfit requested at the mirror: {describe(request)}"},
        }

    async def notify(self, request: RequestInfo) -> None:
        recipients = [n.strip() for n in settings.whatsapp_to.split(",") if n.strip()]
        if not (settings.whatsapp_token and settings.whatsapp_phone_number_id and recipients):
            logger.error("whatsapp_not_configured")
            return
        url = (
            f"{settings.whatsapp_api_base_url.rstrip('/')}/{settings.whatsapp_api_version}/"
            f"{settings.whatsapp_phone_number_id}/messages"
        )
        headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            for number in recipients:  # one failing number must not stop the others
                try:
                    r = await client.post(url, json=self._payload(number, request), headers=headers)
                    if r.status_code >= 400:
                        logger.error(
                            "whatsapp_send_failed", extra={"status": r.status_code, "body": r.text[:300]}
                        )
                except httpx.HTTPError:
                    logger.exception("whatsapp_send_error")
        finally:
            if self._client is None:
                await client.aclose()


NOTIFIERS: dict[str, type] = {"console": ConsoleNotifier, "whatsapp": WhatsAppCloudNotifier}


def get_notifier() -> Notifier:
    return NOTIFIERS[settings.notifier]()
