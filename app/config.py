from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WALLACESIGN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "WallaceSign"
    app_version: str = "0.2.0"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me-in-production-wallacesign-secret"

    # Admin login credentials (seeded into DB on startup)
    admin_name: str = "Admin"
    admin_email: str = "admin@wallacesign.local"
    admin_password: str = "admin123"

    base_dir: Path = Path(__file__).resolve().parent.parent

    # true  → SQLite (local file)
    # false → MySQL server
    use_sqlite: bool = True

    sqlite_path: Path = base_dir / "wallacesign.db"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "wallacesign"
    mysql_password: str = "wallacesign"
    mysql_database: str = "wallacesign"

    # Optional full override. When set, this wins over use_sqlite / mysql_* fields.
    database_url: str = ""

    storage_dir: Path = base_dir / "storage"
    uploads_dir: Path = storage_dir / "uploads"
    signed_dir: Path = storage_dir / "signed"
    signatures_dir: Path = storage_dir / "signatures"
    attachments_dir: Path = storage_dir / "attachments"

    # Public URL used in signature emails (no trailing slash).
    # Example: https://sign.wallace1.com
    public_base_url: str = ""

    # Outgoing mail (Bluehost: mail.wallace1.com:465 SSL)
    mail_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    smtp_use_tls: bool = False
    mail_from: str = "office@wallace1.com"
    mail_from_name: str = "Wallace"

    def resolved_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()

        if self.use_sqlite:
            db_path = self.sqlite_path.resolve().as_posix()
            return f"sqlite:///{db_path}"

        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    def database_backend(self) -> str:
        url = self.resolved_database_url()
        if url.startswith("sqlite"):
            return "sqlite"
        if "mysql" in url:
            return "mysql"
        return "other"


settings = Settings()


def ensure_directories() -> None:
    for path in (
        settings.storage_dir,
        settings.uploads_dir,
        settings.signed_dir,
        settings.signatures_dir,
        settings.attachments_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
