"""Application configuration.

All settings are sourced from environment variables (or a ``.env`` file in
the project root). They are exposed as a singleton ``settings`` object so
the rest of the codebase never reads ``os.environ`` directly.

The values mirror ``.env.example``. Adjust there, not here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    # ---- App ---------------------------------------------------------
    app_name: str = Field(default="DataWarehouseBuilder", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    # ---- Storage -----------------------------------------------------
    storage_root: Path = Field(default=Path("./storage"), alias="STORAGE_ROOT")
    raw_dir: Path = Field(default=Path("./storage/raw"), alias="RAW_DIR")
    cache_dir: Path = Field(default=Path("./storage/cache"), alias="CACHE_DIR")
    exports_dir: Path = Field(default=Path("./storage/exports"), alias="EXPORTS_DIR")
    reports_dir: Path = Field(default=Path("./storage/reports"), alias="REPORTS_DIR")
    sql_output_dir: Path = Field(
        default=Path("./sql/generated"), alias="SQL_OUTPUT_DIR"
    )

    # ---- Storage backend ---------------------------------------------
    # file = parquet + JSON under storage/ (no MySQL required)
    # mysql = full MySQL pipeline (requires working DB)
    storage_backend: str = Field(default="file", alias="STORAGE_BACKEND")

    # ---- MySQL connection --------------------------------------------
    mysql_host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_user: str = Field(default="dw_user", alias="MYSQL_USER")
    mysql_password: str = Field(default="change_me", alias="MYSQL_PASSWORD")
    # Drivers: pymysql (recommended on Windows) | mysqlconnector
    mysql_driver: str = Field(default="pymysql", alias="MYSQL_DRIVER")
    mysql_charset: str = Field(default="utf8mb4", alias="MYSQL_CHARSET")
    mysql_collation: str = Field(
        default="utf8mb4_unicode_ci", alias="MYSQL_COLLATION"
    )

    # ---- Logical databases -------------------------------------------
    db_metadata: str = Field(default="dw_metadata", alias="MYSQL_DB_METADATA")
    db_bronze: str = Field(default="dw_bronze", alias="MYSQL_DB_BRONZE")
    db_silver: str = Field(default="dw_silver", alias="MYSQL_DB_SILVER")
    db_gold: str = Field(default="dw_gold", alias="MYSQL_DB_GOLD")

    # ---- Pipeline tuning ---------------------------------------------
    max_upload_mb: int = Field(default=512, alias="MAX_UPLOAD_MB")
    csv_sample_bytes: int = Field(default=131072, alias="CSV_SAMPLE_BYTES")
    excel_sheet_max_rows: int = Field(default=2_000_000, alias="EXCEL_SHEET_MAX_ROWS")
    relationship_min_confidence: float = Field(
        default=0.55, alias="RELATIONSHIP_MIN_CONFIDENCE"
    )
    relationship_value_overlap_threshold: float = Field(
        default=0.60, alias="RELATIONSHIP_VALUE_OVERLAP_THRESHOLD"
    )
    profiler_sample_rows: int = Field(default=100_000, alias="PROFILER_SAMPLE_ROWS")
    enable_arabic_normalization: bool = Field(
        default=True, alias="ENABLE_ARABIC_NORMALIZATION"
    )
    tashkeel_removal: bool = Field(default=True, alias="TASHKEEL_REMOVAL")
    normalize_taa_marbuta: bool = Field(default=False, alias="NORMALIZE_TAA_MARBUTA")

    # ---- Pydantic config ---------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Validators --------------------------------------------------
    @field_validator(
        "storage_root", "raw_dir", "cache_dir", "exports_dir",
        "reports_dir", "sql_output_dir",
        mode="after",
    )
    @classmethod
    def _ensure_path_exists(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v.resolve()

    # ---- Helpers -----------------------------------------------------
    def mysql_url(self, database: str) -> str:
        """Build a SQLAlchemy URL for the given MySQL schema."""
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        driver = self.mysql_driver.strip().lower()
        if driver in {"mysql", "mysqldb"}:
            driver = "pymysql"
        if driver == "mysql-connector":
            driver = "mysqlconnector"
        return (
            f"mysql+{driver}://"
            f"{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{database}"
            f"?charset={self.mysql_charset}"
        )

    def mysql_connect_args(self) -> dict:
        """Extra driver kwargs (reserved for future driver-specific options)."""
        return {}

    def batch_raw_dir(self, batch_id: str) -> Path:
        p = self.raw_dir / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def batch_exports_dir(self, batch_id: str) -> Path:
        p = self.exports_dir / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def batch_reports_dir(self, batch_id: str) -> Path:
        p = self.reports_dir / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def batch_sql_dir(self, batch_id: str) -> Path:
        p = self.sql_output_dir / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def batch_data_dir(self, batch_id: str) -> Path:
        """Per-batch workspace for file-mode parquet + JSON metadata."""
        p = self.storage_root / "batches" / batch_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def use_file_storage(self) -> bool:
        return self.storage_backend.strip().lower() == "file"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


settings = get_settings()
