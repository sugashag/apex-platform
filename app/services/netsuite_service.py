"""NetSuite REST API client (Token Based Authentication / OAuth 1.0a TBA).

Most calls go through ``_request``, which signs every outgoing request with
TBA using ``requests-oauthlib`` when the connector is in live mode. In test
or dev mode (``mock=True`` or missing config) it returns deterministic
canned responses so the rest of the funnel can be exercised without a
NetSuite sandbox.

Implementation notes
--------------------
* The REST record API base URL is
  ``https://{account_id}.suitetalk.api.netsuite.com/services/rest/record/v1``.
  Account IDs containing underscores (sandbox) need the underscore replaced
  with a dash for the hostname; we apply that transformation in
  ``_account_host``.
* This client does not stream large file uploads — File Cabinet uploads are
  base64-encoded JSON, sufficient for MSA PDFs (under a few hundred KB).
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.netsuite_config import NetSuiteConfig, NetSuiteTestStatus

logger = logging.getLogger(__name__)


def _account_host(account_id: str) -> str:
    # NetSuite sandbox account IDs use the form ``1234567_SB1`` but the
    # corresponding host substitutes the underscore with a dash.
    return account_id.lower().replace("_", "-")


class NetSuiteService:
    """REST client for one workspace's NetSuite account."""

    def __init__(
        self,
        config: NetSuiteConfig | None,
        *,
        mock: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.mock = mock or config is None
        self.base_url = (
            f"https://{_account_host(config.account_id)}"
            ".suitetalk.api.netsuite.com/services/rest/record/v1"
            if config is not None
            else "https://mock.netsuite.example/services/rest/record/v1"
        )
        self._client = client

    # ------------------------------------------------------------------ helpers

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    def _oauth(self) -> Any:
        """Build a requests-oauthlib OAuth1 signer.

        We import lazily so unit tests that never touch the network don't
        need ``requests-oauthlib`` installed.
        """
        if self.config is None:
            raise RuntimeError("NetSuite config missing")
        from requests_oauthlib import OAuth1  # type: ignore[import-not-found]

        return OAuth1(
            client_key=self.config.consumer_key,
            client_secret=self.config.consumer_secret,
            resource_owner_key=self.config.token_id,
            resource_owner_secret=self.config.token_secret,
            realm=self.config.account_id,
            signature_method="HMAC-SHA256",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self.mock:
            return _mock_response(method, path, json)

        url = f"{self.base_url}/{path.lstrip('/')}"
        client = await self._http()
        try:
            resp = await client.request(
                method,
                url,
                json=json,
                params=params,
                auth=self._oauth(),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "netsuite %s %s failed: %s — %s",
                method,
                path,
                exc.response.status_code,
                exc.response.text[:500],
            )
            raise

    # ------------------------------------------------------------------ public API

    async def test_connection(self) -> bool:
        """Fetch ``/subsidiary`` to verify credentials. Updates the config row."""
        if self.config is None:
            return False
        try:
            await self._request("GET", "subsidiary", params={"limit": "1"})
            self.config.last_tested_at = datetime.now(UTC)
            self.config.last_test_status = NetSuiteTestStatus.SUCCESS
            self.config.last_test_error = None
            return True
        except Exception as exc:  # noqa: BLE001 — record failure on config
            self.config.last_tested_at = datetime.now(UTC)
            self.config.last_test_status = NetSuiteTestStatus.FAILED
            self.config.last_test_error = str(exc)[:1000]
            return False

    async def find_customer_by_email(self, email: str) -> str | None:
        """Search NetSuite Customer by email. Returns internal_id or None."""
        # NetSuite REST exposes SuiteQL for arbitrary queries; using a simple
        # GET with ``q`` filter is enough for an exact-match email lookup.
        try:
            data = await self._request(
                "GET",
                "customer",
                params={"q": f'email IS "{email}"'},
            )
        except Exception:  # noqa: BLE001 — search failures should not poison sync
            logger.exception("netsuite customer lookup failed for %s", email)
            return None
        items = data.get("items") or []
        if not items:
            return None
        first = items[0]
        return str(first.get("id") or first.get("internalId") or "") or None

    async def create_customer(
        self,
        company: Any,
        contact: Contact | None,
    ) -> str:
        """Create a NetSuite Customer. Returns the new internal id."""
        body: dict[str, Any] = {
            "companyName": company.name,
            "isPerson": False,
        }
        if contact is not None:
            body["email"] = contact.email
            if contact.first_name:
                body["firstName"] = contact.first_name
            if contact.last_name:
                body["lastName"] = contact.last_name
            if contact.phone:
                body["phone"] = contact.phone
        if self.config is not None and self.config.subsidiary_id:
            body["subsidiary"] = {"id": self.config.subsidiary_id}

        result = await self._request("POST", "customer", json=body)
        return str(result.get("id") or result.get("internalId") or "")

    async def create_sales_order(
        self,
        deal: Deal,
        customer_internal_id: str,
    ) -> str:
        """Create a Sales Order tied to ``customer_internal_id``."""
        body: dict[str, Any] = {
            "entity": {"id": customer_internal_id},
            "memo": deal.name,
            "item": {
                "items": [
                    {
                        "amount": (deal.value_cents or 0) / 100,
                        "description": deal.name,
                        "quantity": 1,
                    }
                ]
            },
        }
        result = await self._request("POST", "salesOrder", json=body)
        return str(result.get("id") or result.get("internalId") or "")

    async def create_invoice(
        self,
        payment: Any,
        customer_internal_id: str,
    ) -> str:
        """Create a NetSuite Invoice and mark it paid."""
        body: dict[str, Any] = {
            "entity": {"id": customer_internal_id},
            "memo": payment.description or f"Payment {payment.id}",
            "item": {
                "items": [
                    {
                        "amount": (payment.amount_cents or 0) / 100,
                        "description": payment.description or "Payment",
                        "quantity": 1,
                    }
                ]
            },
        }
        result = await self._request("POST", "invoice", json=body)
        invoice_id = str(result.get("id") or result.get("internalId") or "")
        # Apply a customer payment so the invoice is marked paid. We swallow
        # the error here — the invoice itself is the load-bearing record.
        try:
            await self._request(
                "POST",
                "customerPayment",
                json={
                    "customer": {"id": customer_internal_id},
                    "apply": {"items": [{"doc": invoice_id, "apply": True}]},
                    "payment": (payment.amount_cents or 0) / 100,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not auto-apply payment to invoice %s", invoice_id)
        return invoice_id

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        folder_id: str,
    ) -> str:
        """Upload a file to the File Cabinet. Returns the file's internal id."""
        encoded = base64.b64encode(file_bytes).decode("ascii")
        body = {
            "name": filename,
            "folder": {"id": folder_id},
            "content": encoded,
        }
        result = await self._request("POST", "file", json=body)
        return str(result.get("id") or result.get("internalId") or "")

    async def attach_file_to_record(
        self,
        file_id: str,
        record_type: str,
        record_id: str,
    ) -> bool:
        """Attach a file to a NetSuite record (e.g. a Sales Order)."""
        body = {
            "file": {"id": file_id},
            "record": {"id": record_id, "type": record_type},
        }
        try:
            await self._request("POST", "fileAttachment", json=body)
            return True
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to attach file %s to %s/%s",
                file_id,
                record_type,
                record_id,
            )
            return False

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _mock_response(
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic-ish mock responses for offline/test mode."""
    import secrets

    path = path.strip("/")
    if path == "subsidiary":
        return {"items": [{"id": "1", "name": "Mock Subsidiary"}]}
    if path == "customer" and method == "GET":
        return {"items": []}
    if path == "customer" and method == "POST":
        return {"id": f"cust_{secrets.token_hex(6)}"}
    if path == "salesOrder" and method == "POST":
        return {"id": f"so_{secrets.token_hex(6)}"}
    if path == "invoice" and method == "POST":
        return {"id": f"inv_{secrets.token_hex(6)}"}
    if path == "customerPayment" and method == "POST":
        return {"id": f"cp_{secrets.token_hex(6)}"}
    if path == "file" and method == "POST":
        return {"id": f"file_{secrets.token_hex(6)}"}
    if path == "fileAttachment" and method == "POST":
        return {"id": f"att_{secrets.token_hex(6)}"}
    return {"id": f"mock_{secrets.token_hex(6)}"}
