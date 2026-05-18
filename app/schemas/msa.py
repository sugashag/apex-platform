"""MSA document request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.msa_document import MsaStatus


class MsaGenerateRequest(BaseModel):
    deal_id: UUID


class MsaSendRequest(BaseModel):
    signer_email: EmailStr
    signer_name: str = Field(..., min_length=1, max_length=255)


class MsaConfirmSignedRequest(BaseModel):
    signed_at: datetime | None = None


class MsaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    deal_id: UUID
    generated_by_id: UUID | None
    status: MsaStatus
    document_url: str | None
    signing_url: str | None
    external_envelope_id: str | None
    signer_email: str | None
    signer_name: str | None
    sent_at: datetime | None
    signed_at: datetime | None
    expires_at: datetime | None
    netsuite_file_id: str | None
    created_at: datetime
    updated_at: datetime
