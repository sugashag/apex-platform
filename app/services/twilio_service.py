"""Twilio integration — voice + SMS + softphone capability tokens.

Designed to degrade gracefully when Twilio credentials are not configured
(e.g. CI, local dev). In that mode every external call returns a mock SID
and `validate_webhook` accepts all requests so the rest of the stack can
still be exercised end-to-end.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class TwilioService:
    """Thin wrapper over the Twilio Python SDK with a dev-mode fallback."""

    def __init__(self) -> None:
        self._client: Any | None = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client

                self._client = Client(
                    settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
                )
            except ImportError:
                logger.warning("twilio package not installed; running in mock mode")

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def initiate_call(
        self,
        to_number: str,
        from_number: str,
        *,
        status_callback_url: str | None = None,
        recording_callback_url: str | None = None,
    ) -> str:
        """Initiate an outbound call. Returns the Twilio Call SID.

        In dev mode (no client), returns a synthetic SID prefixed with ``CA``.
        """
        if self._client is None:
            mock_sid = f"CA{uuid.uuid4().hex}"
            logger.info(
                "twilio not configured — returning mock call sid %s", mock_sid
            )
            return mock_sid

        kwargs: dict[str, Any] = {
            "to": to_number,
            "from_": from_number,
            "url": "http://demo.twilio.com/docs/voice.xml",
            "record": True,
        }
        if status_callback_url:
            kwargs["status_callback"] = status_callback_url
            kwargs["status_callback_event"] = [
                "initiated",
                "ringing",
                "answered",
                "completed",
            ]
        if recording_callback_url:
            kwargs["recording_status_callback"] = recording_callback_url

        call = self._client.calls.create(**kwargs)
        return str(call.sid)

    async def send_sms(self, to_number: str, from_number: str, body: str) -> str:
        """Send an SMS. Returns the Twilio Message SID (mocked when unconfigured)."""
        if self._client is None:
            mock_sid = f"SM{uuid.uuid4().hex}"
            logger.info(
                "twilio not configured — returning mock sms sid %s", mock_sid
            )
            return mock_sid

        msg = self._client.messages.create(
            to=to_number, from_=from_number, body=body
        )
        return str(msg.sid)

    def validate_webhook(
        self, url: str, params: dict[str, str], signature: str | None
    ) -> bool:
        """Verify Twilio's `X-Twilio-Signature` header against the request.

        Dev mode (no auth token) accepts everything so tests can exercise the
        flow without HMAC-ing a fake request.
        """
        if not settings.TWILIO_AUTH_TOKEN:
            return True
        if signature is None:
            return False

        try:
            from twilio.request_validator import RequestValidator

            validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
            return bool(validator.validate(url, params, signature))
        except ImportError:
            logger.warning("twilio package not installed; accepting webhook")
            return True

    def generate_twiml_dial(self, client_identity: str) -> str:
        """Generate TwiML to dial a Twilio Client (softphone)."""
        # `<Client>` connects the call to a Twilio Client identity (WebRTC).
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Dial><Client>{client_identity}</Client></Dial>"
            "</Response>"
        )

    def generate_twiml_voicemail(self) -> str:
        """Generate TwiML that announces voicemail and records a message."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Say>Please leave a message after the tone.</Say>"
            '<Record maxLength="120" playBeep="true"/>'
            "<Hangup/>"
            "</Response>"
        )

    def generate_capability_token(
        self, identity: str, ttl_seconds: int = 3600
    ) -> str:
        """Mint a Twilio Access Token granting the browser softphone permissions.

        Returns a synthetic token string in dev mode so the frontend can still
        wire up the flow.
        """
        if not (
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_API_KEY_SID
            and settings.TWILIO_API_KEY_SECRET
            and settings.TWILIO_TWIML_APP_SID
        ):
            logger.info(
                "twilio access token credentials not configured — returning mock token"
            )
            return f"mock-twilio-token-{identity}-{uuid.uuid4().hex}"

        try:
            from twilio.jwt.access_token import AccessToken
            from twilio.jwt.access_token.grants import VoiceGrant

            token = AccessToken(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_API_KEY_SID,
                settings.TWILIO_API_KEY_SECRET,
                identity=identity,
                ttl=ttl_seconds,
            )
            voice_grant = VoiceGrant(
                outgoing_application_sid=settings.TWILIO_TWIML_APP_SID,
                incoming_allow=True,
            )
            token.add_grant(voice_grant)
            return str(token.to_jwt())
        except ImportError:
            logger.warning("twilio package not installed; returning mock token")
            return f"mock-twilio-token-{identity}-{uuid.uuid4().hex}"


twilio_service = TwilioService()
