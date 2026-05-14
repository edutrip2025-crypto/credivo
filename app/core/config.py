import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Credivo Assessment API"
    app_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./credivo.db"
    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    auth_mode: str = "firebase"
    enable_ai_review: bool = False
    allow_dev_role_override: bool = False
    admin_recovery_key: str = ""
    firebase_project_id: str = ""
    firebase_service_account_path: str = ""
    firebase_service_account_json: str = ""
    firebase_web_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_storage_bucket: str = ""
    firebase_messaging_sender_id: str = ""
    firebase_app_id: str = ""
    firebase_measurement_id: str = ""
    object_storage_backend: str = "s3"  # s3 | firebase | bunny | local | auto
    aws_region: str = ""
    aws_s3_bucket_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    bunny_storage_zone: str = ""
    bunny_storage_access_key: str = ""
    bunny_storage_endpoint: str = "storage.bunnycdn.com"
    bunny_storage_pull_zone: str = ""
    bunny_storage_upload_timeout_seconds: int = 900
    bunny_storage_upload_retries: int = 3
    bunny_stream_library_id: int = 0
    bunny_stream_api_key: str = ""
    bunny_stream_pull_zone: str = ""
    bunny_stream_embed_token_key: str = ""
    media_dir: str = "app/web/media"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = "noreply@credivo.local"
    admin_emails: str = "admin@credivo.local"
    identity_verify_enforce: bool = True
    identity_verify_timeout_seconds: int = 15
    identity_verify_api_key: str = ""
    identity_verify_api_key_header: str = "x-api-key"
    identity_verify_bearer_token: str = ""
    identity_verify_extra_headers_json: str = ""
    identity_verify_aadhaar_url: str = ""
    identity_verify_pan_url: str = ""
    identity_verify_cin_url: str = ""
    identity_verify_gst_url: str = ""
    identity_verify_passport_url: str = ""
    identity_verify_national_id_url: str = ""
    identity_verify_driving_license_url: str = ""
    identity_verify_voter_id_url: str = ""
    identity_verify_tax_id_url: str = ""
    identity_verify_other_url: str = ""
    cloudflare_stream_account_id: str = ""
    cloudflare_stream_api_token: str = ""
    cloudflare_stream_customer_code: str = ""
    cloudflare_stream_signing_key_id: str = ""
    cloudflare_stream_signing_key_secret: str = ""
    stream_playback_token_ttl_seconds: int = 180
    stream_direct_upload_expiry_seconds: int = 3600
    stream_drm_license_secret: str = ""
    stream_drm_license_ttl_seconds: int = 180
    stream_drm_nonce_ttl_seconds: int = 240
    stream_drm_enforce_heartbeat: bool = True
    stream_drm_max_concurrent_sessions_per_course: int = 2
    stream_drm_auto_revoke_on_ip_mismatch: bool = False
    stream_drm_auto_revoke_on_user_agent_mismatch: bool = False
    fair_usage_default_multiplier: float = 2.5
    fair_usage_warn_threshold_1: float = 0.8
    fair_usage_warn_threshold_2: float = 1.0
    fair_usage_warn_threshold_3: float = 1.2
    pricing_currency: str = "INR"
    pricing_stream_storage_cost_per_minute_month: float = 0.08
    pricing_stream_delivery_cost_per_minute: float = 0.03
    pricing_platform_fee_pct: float = 0.1
    pricing_creator_margin_floor_pct: float = 0.35
    course_pricing_default_currency: str = "INR"
    course_pricing_gst_rate: float = 0.18
    course_pricing_platform_commission_rate: float = 0.25
    course_pricing_one_time_hosting_fee: float = 2500
    cors_allow_origins: str = ""
    trusted_hosts: str = ""
    enable_gzip: bool = True
    gzip_minimum_size: int = 1024
    security_enable_csp: bool = True
    security_csp_frame_ancestors: str = "'none'"
    security_csp_extra: str = ""
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 180
    rate_limit_auth_requests_per_minute: int = 35
    ops_enable_request_logs: bool = True
    ops_slow_request_ms: int = 1200
    microsoft_graph_tenant_id: str = ""
    microsoft_graph_client_id: str = ""
    microsoft_graph_client_secret: str = ""
    microsoft_graph_drive_id: str = ""
    microsoft_graph_excel_item_id: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def is_vercel(self) -> bool:
        return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))

    @property
    def is_production(self) -> bool:
        v = (self.app_env or "").strip().lower()
        return v in {"prod", "production"}

    @property
    def resolved_database_url(self) -> str:
        raw = (self.database_url or "").strip()
        if raw.startswith("postgres://"):
            raw = "postgresql+psycopg://" + raw[len("postgres://"):]
        elif raw.startswith("postgresql://"):
            raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
        if not self.is_vercel:
            return raw
        if raw.startswith("sqlite"):
            raise RuntimeError(
                "On Vercel, DATABASE_URL must be a Postgres connection string (for example Neon). "
                "SQLite is not supported for deployment.",
            )
        if not raw.startswith("postgresql+psycopg://"):
            raise RuntimeError(
                "On Vercel, DATABASE_URL must resolve to 'postgresql+psycopg://...'. "
                "Please verify the DATABASE_URL environment variable.",
            )
        return raw

    @property
    def resolved_media_dir(self) -> str:
        raw = (self.media_dir or "").strip() or "app/web/media"
        if not self.is_vercel:
            return raw
        path = Path(raw)
        if path.is_absolute():
            return str(path)
        return "/tmp/certora-media"

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in (self.admin_emails or "").split(",") if e.strip()}

    @property
    def resolved_object_storage_backend(self) -> str:
        raw = (self.object_storage_backend or "auto").strip().lower()
        if raw in {"s3", "firebase", "bunny", "local"}:
            return raw
        has_bunny = bool(self.bunny_storage_zone and self.bunny_storage_access_key and self.bunny_storage_pull_zone)
        if has_bunny:
            return "bunny"
        has_s3 = bool(self.aws_region and self.aws_s3_bucket_name and self.aws_access_key_id and self.aws_secret_access_key)
        if has_s3:
            return "s3"
        has_firebase_storage = bool(self.firebase_storage_bucket or self.firebase_project_id)
        if has_firebase_storage:
            return "firebase"
        return "local"

    @property
    def cors_origins_list(self) -> list[str]:
        raw = [x.strip() for x in (self.cors_allow_origins or "").split(",")]
        return [x for x in raw if x]

    @property
    def trusted_hosts_list(self) -> list[str]:
        raw = [x.strip() for x in (self.trusted_hosts or "").split(",")]
        return [x for x in raw if x]


@lru_cache
def get_settings() -> Settings:
    return Settings()
