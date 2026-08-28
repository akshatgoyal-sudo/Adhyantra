from pathlib import Path

import pytest
import yaml

from backend.config import Settings
from backend.db import DatabaseLifecycleError, database_engine_options


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_render_blueprint_is_one_free_embedded_web_service():
    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = blueprint["services"]
    assert len(services) == 1
    service = services[0]
    assert service["type"] == "web"
    assert service["runtime"] == "python"
    assert service["plan"] == "free"
    assert service["region"] == "singapore"
    assert service["healthCheckPath"] == "/health/live"
    assert "--workers 1" in service["startCommand"]
    serialized = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8").lower()
    assert "predeploy" not in serialized and "alembic" not in serialized
    assert "disk" not in serialized and "type: worker" not in serialized
    assert "service-role" not in serialized and "postgresql://" not in serialized
    env = {item["key"]: item for item in service["envVars"]}
    assert env["MEDIA_RENDER_WORKER_MODE"]["value"] == "embedded"
    assert env["MEDIA_STORAGE_BACKEND"]["value"] == "supabase"
    assert env["SUPABASE_SERVICE_ROLE_KEY"] == {"key": "SUPABASE_SERVICE_ROLE_KEY", "sync": False}
    assert env["TTS_PROVIDER"]["value"] == "gemini"
    assert env["TTS_GEMINI_MODEL"]["value"] == "gemini-2.5-flash-preview-tts"
    assert env["AI_PROVIDER_CHAIN"]["value"] == "gemini"
    assert env["ALLOW_MOCK_AI_IN_PRODUCTION"]["value"] == "false"
    assert env["GEMINI_MODEL"]["value"] == "gemini-3.6-flash"
    assert "GROQ_MODEL" not in env
    assert env["EMAIL_TRANSPORT"]["value"] == "brevo"
    assert env["BREVO_BASE_URL"]["value"] == "https://api.brevo.com/v3"
    assert env["BREVO_API_KEY"] == {"key": "BREVO_API_KEY", "sync": False}
    assert "SMTP_HOST" not in env
    assert "SMTP_PASSWORD" not in env
    assert env["PAYMENT_PROVIDER"]["value"] == "disabled"
    assert "RESEND_API_KEY" not in env
    assert env["GEMINI_API_KEY"] == {"key": "GEMINI_API_KEY", "sync": False}
    assert "GROQ_API_KEY" not in env
    assert "TTS_OPENAI_API_KEY" not in env
    assert all("NEXT_PUBLIC" not in key for key in env if "GEMINI" in key)


def test_non_sqlite_engine_uses_conservative_pool_defaults():
    options = database_engine_options(Settings(db_url="postgresql://example.invalid/app"))
    assert options == {
        "pool_size": 2,
        "max_overflow": 1,
        "pool_timeout": 15,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    assert database_engine_options(Settings(db_url="sqlite:///:memory:")) == {
        "connect_args": {"check_same_thread": False}
    }


def test_invalid_pool_configuration_fails_without_url_disclosure():
    settings = Settings(db_url="postgresql://secret:password@example.invalid/app", db_pool_size=0)
    with pytest.raises(DatabaseLifecycleError) as captured:
        database_engine_options(settings)
    assert captured.value.status == "invalid_pool_configuration"
    assert "password" not in str(captured.value)
    assert "example.invalid" not in str(captured.value)


def test_production_storage_configuration_fails_closed():
    local = Settings(app_env="production", db_url="postgresql://example.invalid/app", media_storage_backend="local")
    result = local.validate_runtime_config()
    assert any(issue.code == "local_media_storage_in_production" for issue in result.errors)

    incomplete = Settings(app_env="production", db_url="postgresql://example.invalid/app", media_storage_backend="supabase")
    result = incomplete.validate_runtime_config()
    codes = {issue.code for issue in result.errors}
    assert {"missing_supabase_url", "missing_supabase_service_role_key", "missing_supabase_media_bucket"} <= codes
