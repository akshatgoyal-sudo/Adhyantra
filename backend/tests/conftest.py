from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import uuid

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TEST_RUNTIME_ROOT = PROJECT_ROOT / ".test-runtime" / f"backend-{os.getpid()}-{uuid.uuid4().hex[:8]}"
TEST_DATABASE_PATH = TEST_RUNTIME_ROOT / "backend.sqlite3"
TEST_MEDIA_PATH = TEST_RUNTIME_ROOT / "media"

_ORIGINAL_ENVIRONMENT = dict(os.environ)
_TEST_ENVIRONMENT = {
    "APP_ENV": "development",
    "APP_VERSION": "0.1.0",
    "RELEASE_COMMIT": "",
    "GIT_SHA": "",
    "VERCEL_GIT_COMMIT_SHA": "",
    "DEPLOYMENT_ID": "",
    "RENDER_INSTANCE_ID": "",
    "FLY_ALLOC_ID": "",
    "EXAM_GURU_DB_URL": f"sqlite:///{TEST_DATABASE_PATH.as_posix()}",
    "DB_POOL_SIZE": "2",
    "DB_MAX_OVERFLOW": "1",
    "DB_POOL_TIMEOUT_SECONDS": "15",
    "DB_POOL_RECYCLE_SECONDS": "300",
    "DB_POOL_PRE_PING": "true",
    "AI_PROVIDER": "mock",
    "AI_PROVIDER_CHAIN": "",
    "AI_TIMEOUT_SECONDS": "30",
    "OPENAI_MODEL": "gpt-4o-mini",
    "AI_MODEL": "",
    "OPENAI_API_KEY": "",
    "AI_API_KEY": "",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "AI_BASE_URL": "",
    "TTS_PROVIDER": "disabled",
    "TTS_OUTPUT_FORMAT": "mp3",
    "TTS_OPENAI_MODEL": "gpt-4o-mini-tts",
    "TTS_OPENAI_API_KEY": "",
    "TTS_OPENAI_BASE_URL": "https://api.openai.com/v1",
    "TTS_OPENAI_VOICE": "alloy",
    "TTS_TIMEOUT_SECONDS": "60",
    "MEDIA_RENDER_OUTPUT_DIR": str(TEST_MEDIA_PATH),
    "MEDIA_STORAGE_BACKEND": "local",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "SUPABASE_MEDIA_BUCKET": "",
    "MEDIA_STORAGE_REQUEST_TIMEOUT_SECONDS": "15",
    "MEDIA_STORAGE_MAX_OBJECT_BYTES": "49000000",
    "MEDIA_SIGNED_URL_TTL_SECONDS": "300",
    "MEDIA_RENDER_WORKER_MODE": "embedded",
    "MEDIA_RENDER_WORKER_POLL_SECONDS": "0.25",
    "MEDIA_RENDER_CLAIM_LEASE_SECONDS": "300",
    "MEDIA_RENDER_WORKER_HEARTBEAT_SECONDS": "15",
    "MEDIA_RENDER_WORKER_STALE_AFTER_SECONDS": "90",
    "MEDIA_RENDER_ARTIFACT_RETENTION_HOURS": "168",
    "PAYMENT_PROVIDER": "disabled",
    "PAYMENT_TIMEOUT_SECONDS": "30",
    "PAYMENT_PREMIUM_PRICE_ID": "",
    "PAYMENT_STRIPE_SECRET_KEY": "",
    "PAYMENT_STRIPE_WEBHOOK_SECRET": "",
    "PAYMENT_STRIPE_BASE_URL": "https://api.stripe.com/v1",
    "PAYMENT_RAZORPAY_KEY_ID": "",
    "PAYMENT_RAZORPAY_KEY_SECRET": "",
    "PAYMENT_RAZORPAY_WEBHOOK_SECRET": "",
    "PAYMENT_RAZORPAY_BASE_URL": "https://api.razorpay.com/v1",
    "PAYMENT_RAZORPAY_TOTAL_COUNT": "12",
    "GEMINI_MODEL": "gemini-1.5-flash",
    "GEMINI_API_KEY": "",
    "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    "GROQ_MODEL": "llama-3.1-8b-instant",
    "GROQ_API_KEY": "",
    "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
    "MISTRAL_MODEL": "mistral-small-latest",
    "MISTRAL_API_KEY": "",
    "MISTRAL_BASE_URL": "https://api.mistral.ai/v1",
    "EXAM_GURU_SUBJECT": "polity",
    "EXAM_GURU_EXAM": "upsc",
    "FRONTEND_ORIGIN": "http://localhost:3000",
    "BACKEND_PUBLIC_URL": "",
    "CORS_ALLOWED_ORIGINS": "",
    "CORS_ALLOWED_METHODS": "",
    "CORS_ALLOWED_HEADERS": "",
    "CORS_MAX_AGE_SECONDS": "600",
    "TRUSTED_HOSTS": "",
    "SESSION_COOKIE_NAME": "exam_guru_session",
    "SESSION_TTL_DAYS": "30",
    "SESSION_IDLE_TIMEOUT_MINUTES": "0",
    "SESSION_COOKIE_SAMESITE": "lax",
    "SESSION_COOKIE_DOMAIN": "",
    "SESSION_COOKIE_PATH": "/",
    "SECURE_SESSION_COOKIES": "false",
    "EMAIL_OTP_TTL_MINUTES": "10",
    "EMAIL_OTP_MAX_ATTEMPTS": "5",
    "EMAIL_OTP_REQUEST_COOLDOWN_SECONDS": "45",
    "EMAIL_OTP_MAX_REQUESTS_PER_HOUR_PER_EMAIL": "6",
    "EMAIL_OTP_MAX_REQUESTS_PER_HOUR_PER_IP": "20",
    "EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_EMAIL": "15",
    "EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_IP": "45",
    "EMAIL_DELIVERY_MODE": "console",
    "EMAIL_OTP_DELIVERY_MODE": "console",
    "EMAIL_TRANSPORT": "smtp",
    "EMAIL_PROVIDER": "",
    "EMAIL_FROM_NAME": "Adhyantra",
    "EMAIL_FROM_ADDRESS": "",
    "EMAIL_REPLY_TO_ADDRESS": "",
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "SMTP_USE_TLS": "true",
    "SMTP_USE_SSL": "false",
    "SMTP_TIMEOUT_SECONDS": "15",
    "RESEND_API_KEY": "",
    "AUTH_DEV_RETURN_OTP": "true",
    "ALLOW_MOCK_AI_IN_PRODUCTION": "false",
    "ALLOW_SQLITE_IN_PRODUCTION": "false",
    "LOG_LEVEL": "WARNING",
}


def _restore_test_environment() -> None:
    os.environ.clear()
    os.environ.update(_CLEAN_TEST_ENVIRONMENT)


def _stop_app_background_state() -> None:
    main_module = sys.modules.get("backend.main")
    if main_module is None:
        return
    app = getattr(main_module, "app", None)
    if app is None:
        return
    dispatcher = getattr(app.state, "media_render_dispatcher", None)
    if dispatcher is not None:
        dispatcher.stop()
        app.state.media_render_dispatcher = None
    app.dependency_overrides.clear()
    app.state.testing_session_factory = None


def _reset_cached_backend_state() -> None:
    config_module = sys.modules.get("backend.config")
    if config_module is not None:
        config_module.get_settings.cache_clear()
        fresh_settings = config_module.get_settings()
        for module_name in (
            "backend.db",
            "backend.main",
            "backend.routes.account_billing_routes",
            "backend.routes.auth_routes",
            "backend.services.auth_service",
            "backend.services.mail_service",
        ):
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, "settings"):
                module.settings = fresh_settings

    payment_module = sys.modules.get("backend.services.payment_provider_service")
    if payment_module is not None:
        payment_module.get_payment_provider.cache_clear()


TEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=False)
os.environ.update(_TEST_ENVIRONMENT)
_CLEAN_TEST_ENVIRONMENT = dict(os.environ)


def pytest_configure(config: pytest.Config) -> None:
    config.option.basetemp = str(TEST_RUNTIME_ROOT / "pytest")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    _restore_test_environment()
    _reset_cached_backend_state()
    try:
        yield
    finally:
        _stop_app_background_state()
        _restore_test_environment()
        _reset_cached_backend_state()


def pytest_unconfigure(config: pytest.Config) -> None:
    _stop_app_background_state()
    db_module = sys.modules.get("backend.db")
    if db_module is not None:
        db_module.engine.dispose()
    os.environ.clear()
    os.environ.update(_ORIGINAL_ENVIRONMENT)
    if TEST_RUNTIME_ROOT.exists():
        shutil.rmtree(TEST_RUNTIME_ROOT)
