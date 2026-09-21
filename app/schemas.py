from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class WidgetCreate(BaseModel):
    type: str = Field(default="signature", pattern="^(signature|initials|stamp)$")
    page: int = Field(default=1, ge=1)
    # Percentages of page width/height (WallaceSign style), origin top-left
    x: float = Field(..., ge=0)
    y: float = Field(..., ge=0)
    w: float = Field(..., gt=0)
    h: float = Field(..., gt=0)
    field_name: Optional[str] = Field(default=None, max_length=120)


class WidgetOut(BaseModel):
    id: int
    type: str
    page: int
    x: float
    y: float
    w: float
    h: float
    field_name: Optional[str] = None
    has_signature: bool = False

    class Config:
        from_attributes = True


class SignerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    role: str = Field(default="signer", pattern="^(signer|viewer|approver)$")
    order_index: int = 0
    phase: int = Field(default=0, ge=0)
    field_name: Optional[str] = Field(default=None, max_length=120)
    widgets: List[WidgetCreate] = Field(default_factory=list)


class SignerOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    order_index: int
    phase: int = 0
    field_name: Optional[str] = None
    status: str
    access_token: str
    sign_url: Optional[str] = None
    signed_at: Optional[datetime] = None
    widgets: List[WidgetOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    sequential: bool = False
    owner_name: str = Field(default="Admin", min_length=1)
    owner_email: EmailStr = "admin@wallacesign.local"
    signers: List[SignerCreate] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: int
    title: str
    description: str
    filename: str
    status: str
    sequential: bool
    public_token: str
    document_url: Optional[str] = None
    dealership_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    signers: List[SignerOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentListItem(BaseModel):
    id: int
    title: str
    filename: str
    status: str
    public_token: str
    document_url: Optional[str] = None
    created_at: datetime
    signer_count: int
    signed_count: int

    class Config:
        from_attributes = True


class AuditEventOut(BaseModel):
    id: int
    event_type: str
    message: str
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WidgetSignatureIn(BaseModel):
    widget_id: int
    signature_data: str = Field(..., description="Base64 PNG data URL for this widget")


class SignRequest(BaseModel):
    """Submit one signature image per signature widget assigned to this signer."""

    signatures: List[WidgetSignatureIn] = Field(default_factory=list)
    # Backward-compatible single pad (applied to first signature widget)
    signature_data: Optional[str] = None
    consent: bool = True


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    database: str
