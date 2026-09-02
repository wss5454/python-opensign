from datetime import datetime, timezone
import secrets

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    documents = relationship("Document", back_populates="owner")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    filename = Column(String(255), nullable=False)
    original_path = Column(String(500), nullable=False)
    signed_path = Column(String(500), nullable=True)
    status = Column(String(50), default="draft", index=True)
    # draft | sent | partially_signed | completed | voided
    sequential = Column(Boolean, default=False)
    # Public document URL token: /d/{public_token}
    public_token = Column(String(64), unique=True, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="documents")
    signers = relationship(
        "Signer",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Signer.order_index",
    )
    audit_events = relationship(
        "AuditEvent",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="AuditEvent.created_at",
    )


class Signer(Base):
    __tablename__ = "signers"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), default="signer")  # signer | viewer | approver
    order_index = Column(Integer, default=0)
    # 0 = customer (sig1..N), 1 = company/marina (companysig1..N)
    phase = Column(Integer, default=0, nullable=False, index=True)
    field_name = Column(String(120), nullable=True)
    status = Column(String(50), default="pending")  # pending | viewed | signed | declined
    # Unique signing URL token: /sign/{access_token}
    access_token = Column(String(64), unique=True, nullable=False, index=True)
    signature_path = Column(String(500), nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="signers")
    widgets = relationship(
        "SignerWidget",
        back_populates="signer",
        cascade="all, delete-orphan",
        order_by="SignerWidget.id",
    )


class SignerWidget(Base):
    """Per-signer signature location on the PDF (WallaceSign-style widget).

    x, y, w, h are percentages of the page width/height (0-100),
    measured from the top-left of the page.
    """

    __tablename__ = "signer_widgets"

    id = Column(Integer, primary_key=True, index=True)
    signer_id = Column(Integer, ForeignKey("signers.id"), nullable=False, index=True)
    type = Column(String(50), default="signature", nullable=False)
    page = Column(Integer, default=1, nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    field_name = Column(String(120), nullable=True)
    signature_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    signer = relationship("Signer", back_populates="widgets")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    signer_id = Column(Integer, ForeignKey("signers.id"), nullable=True)
    event_type = Column(String(80), nullable=False)
    message = Column(Text, nullable=False)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="audit_events")


_db_url = settings.resolved_database_url()
_connect_args = {}
_engine_kwargs = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
}

if _db_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(_db_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _table_columns(inspector, table_name: str) -> set[str]:
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _migrate_schema() -> None:
    """Add columns/tables introduced after the first SQLite schema."""
    inspector = inspect(engine)
    dialect = engine.dialect.name

    with engine.begin() as conn:
        doc_cols = _table_columns(inspector, "documents")
        if doc_cols and "public_token" not in doc_cols:
            # Add nullable first, backfill, then unique index.
            conn.execute(text("ALTER TABLE documents ADD COLUMN public_token VARCHAR(64)"))

            rows = conn.execute(
                text("SELECT id FROM documents WHERE public_token IS NULL")
            ).fetchall()
            for (doc_id,) in rows:
                token = secrets.token_urlsafe(32)
                conn.execute(
                    text("UPDATE documents SET public_token = :token WHERE id = :id"),
                    {"token": token, "id": doc_id},
                )

            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_public_token "
                        "ON documents (public_token)"
                    )
                )
            else:
                try:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX ix_documents_public_token "
                            "ON documents (public_token)"
                        )
                    )
                except Exception:
                    pass

        user_cols = _table_columns(inspector, "users")
        if user_cols:
            if "password_hash" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
            if "is_admin" not in user_cols:
                if dialect == "sqlite":
                    conn.execute(
                        text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN is_admin TINYINT(1) "
                            "NOT NULL DEFAULT 0"
                        )
                    )

        signer_cols = _table_columns(inspector, "signers")
        if signer_cols:
            if "phase" not in signer_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN phase INTEGER DEFAULT 0"))
                conn.execute(text("UPDATE signers SET phase = 0 WHERE phase IS NULL"))
            if "field_name" not in signer_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN field_name VARCHAR(120)"))

        widget_cols = _table_columns(inspector, "signer_widgets")
        if widget_cols and "field_name" not in widget_cols:
            conn.execute(text("ALTER TABLE signer_widgets ADD COLUMN field_name VARCHAR(120)"))

    # Ensure newer tables exist (e.g. signer_widgets)
    Base.metadata.create_all(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
