"""Stripe API wrapper with graceful degradation.

When ``STRIPE_SECRET_KEY`` is not configured, every call returns a
deterministic mock response. This lets the test suite and dev environments
exercise the payments pipeline without an actual Stripe account.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def _mock_id(prefix: str) -> str:
    return f"{prefix}_mock_{secrets.token_hex(12)}"


class StripeService:
    """Thin wrapper around the `stripe` Python SDK."""

    def __init__(self) -> None:
        self.api_key: str | None = settings.STRIPE_SECRET_KEY
        self.webhook_secret: str | None = settings.STRIPE_WEBHOOK_SECRET
        self.stripe: Any | None = None

        if self.api_key:
            try:
                import stripe  # type: ignore[import-not-found]

                stripe.api_key = self.api_key
                self.stripe = stripe
            except ImportError:
                logger.warning(
                    "stripe package not installed; running in mock mode"
                )

    @property
    def enabled(self) -> bool:
        """True when a real Stripe key + SDK are wired up."""
        return self.stripe is not None

    async def create_customer(
        self,
        *,
        email: str,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Create a Stripe Customer. Returns the customer id."""
        if not self.enabled:
            cid = _mock_id("cus")
            logger.info("stripe disabled — mock customer %s for %s", cid, email)
            return cid

        params: dict[str, Any] = {"email": email}
        if name is not None:
            params["name"] = name
        if metadata is not None:
            params["metadata"] = metadata
        customer = self.stripe.Customer.create(**params)  # type: ignore[union-attr]
        return str(customer["id"])

    async def create_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str | None = None,
        metadata: dict[str, str] | None = None,
        description: str | None = None,
    ) -> dict[str, str]:
        """Create a PaymentIntent. Returns {client_secret, payment_intent_id}."""
        if not self.enabled:
            pi_id = _mock_id("pi")
            return {
                "payment_intent_id": pi_id,
                "client_secret": f"{pi_id}_secret_{secrets.token_hex(8)}",
            }

        params: dict[str, Any] = {
            "amount": amount_cents,
            "currency": currency.lower(),
        }
        if customer_id is not None:
            params["customer"] = customer_id
        if description is not None:
            params["description"] = description
        if metadata is not None:
            params["metadata"] = metadata
        intent = self.stripe.PaymentIntent.create(**params)  # type: ignore[union-attr]
        return {
            "payment_intent_id": str(intent["id"]),
            "client_secret": str(intent["client_secret"]),
        }

    async def create_invoice(
        self,
        *,
        customer_id: str,
        amount_cents: int,
        currency: str = "USD",
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Create + finalize a Stripe Invoice. Returns {invoice_id, hosted_invoice_url}."""
        if not self.enabled:
            inv_id = _mock_id("in")
            return {
                "invoice_id": inv_id,
                "hosted_invoice_url": f"https://invoice.stripe.example/{inv_id}",
            }

        item_params: dict[str, Any] = {
            "customer": customer_id,
            "amount": amount_cents,
            "currency": currency.lower(),
        }
        if description is not None:
            item_params["description"] = description
        self.stripe.InvoiceItem.create(**item_params)  # type: ignore[union-attr]

        invoice_params: dict[str, Any] = {"customer": customer_id}
        if metadata is not None:
            invoice_params["metadata"] = metadata
        invoice = self.stripe.Invoice.create(**invoice_params)  # type: ignore[union-attr]
        finalized = self.stripe.Invoice.finalize_invoice(invoice["id"])  # type: ignore[union-attr]
        return {
            "invoice_id": str(finalized["id"]),
            "hosted_invoice_url": str(
                finalized.get("hosted_invoice_url") or ""
            ),
        }

    def validate_webhook(
        self, payload: bytes, sig_header: str | None
    ) -> dict[str, Any]:
        """Verify the Stripe-Signature header and parse the event.

        Raises ValueError on any failure. In mock mode (no webhook secret
        configured) the raw JSON is parsed without signature verification.
        """
        if not self.webhook_secret or self.stripe is None:
            import json

            try:
                event = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("invalid JSON payload") from exc
            if not isinstance(event, dict):
                raise ValueError("event payload is not an object")
            return event

        if sig_header is None:
            raise ValueError("missing stripe-signature header")
        try:
            event = self.stripe.Webhook.construct_event(  # type: ignore[union-attr]
                payload, sig_header, self.webhook_secret
            )
        except Exception as exc:  # noqa: BLE001 — surface as ValueError
            raise ValueError(f"signature verification failed: {exc}") from exc
        return dict(event)


stripe_service = StripeService()
