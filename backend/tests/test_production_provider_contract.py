from pathlib import Path

import pytest
import yaml

from backend.ai_client import AIProviderError
from backend.config import Settings
from backend.services.ai_service import AIService, AIServiceUnavailableError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "ai_provider": "gemini",
        "ai_provider_chain": "gemini",
        "allow_mock_ai_in_production": False,
        "gemini_api_key": "unit-test-gemini-material",
        "gemini_model": "gemini-3.6-flash",
        "groq_api_key": "unit-test-groq-material",
        "groq_model": "llama-3.1-8b-instant",
        "db_url": "postgresql://db.invalid/adhyantra_test",
        "frontend_origin": "https://frontend.invalid",
        "backend_public_url": "https://backend.invalid",
        "cors_allowed_origins": "https://frontend.invalid",
        "trusted_hosts": "backend.invalid",
        "email_otp_delivery_mode": "email",
        "email_transport": "smtp",
        "email_from_address": "beta-sender@example.invalid",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "beta-sender@example.invalid",
        "smtp_password": "unit-test-google-app-password",
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
        "auth_dev_return_otp": False,
        "tts_provider": "gemini",
        "tts_gemini_model": "gemini-2.5-flash-preview-tts",
        "tts_gemini_voice": "Kore",
        "media_storage_backend": "supabase",
        "media_render_output_dir": "/tmp/adhyantra-media",
        "supabase_url": "https://storage.invalid",
        "supabase_service_role_key": "unit-test-storage-material",
        "supabase_media_bucket": "unit-test-media",
        "payment_provider": "disabled",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_live_chain_remains_exact_and_mock_is_not_appended() -> None:
    settings = _production_settings()

    assert settings.configured_ai_provider_chain == ("gemini",)
    assert settings.effective_ai_provider_chain == ("gemini",)
    assert settings.mock_ai_runtime_allowed is False
    assert settings.validate_runtime_config().ok is True


def test_production_rejects_explicit_mock_provider_or_chain() -> None:
    primary_result = _production_settings(ai_provider="mock", ai_provider_chain="mock").validate_runtime_config()
    fallback_result = _production_settings(ai_provider_chain="gemini,groq,mock").validate_runtime_config()

    assert "mock_ai_forbidden_in_production_chain" in {issue.code for issue in primary_result.errors}
    assert "mock_ai_forbidden_in_production_chain" in {issue.code for issue in fallback_result.errors}


def test_implicit_gemini_chain_does_not_retain_unverified_fallback() -> None:
    settings = _production_settings(ai_provider_chain="")

    assert settings.configured_ai_provider_chain == ("gemini",)
    assert settings.effective_ai_provider_chain == ("gemini",)


def test_total_live_provider_failure_is_sanitized_and_never_builds_mock_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingLiveRouter:
        provider_name = "router"
        last_attempted_provider_names = ["gemini"]
        last_fallback_used = False
        last_fallback_reason = "provider URL key=should-not-escape"

        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            raise AIProviderError(
                "all providers failed key=should-not-escape",
                provider_metadata={
                    "provider_name": "live_ai",
                    "model_name": None,
                    "attempted_provider_chain": ["gemini"],
                    "provider_fallback_used": False,
                    "provider_fallback_reason": "key=should-not-escape",
                },
            )

    service = AIService(settings=_production_settings(), provider=FailingLiveRouter())
    monkeypatch.setattr(
        service,
        "default_explanation_response",
        lambda **kwargs: pytest.fail("strict production constructed a mock lesson"),
    )
    monkeypatch.setattr(
        service,
        "default_quiz_response",
        lambda **kwargs: pytest.fail("strict production constructed a mock quiz"),
    )

    with pytest.raises(AIServiceUnavailableError) as explanation_error:
        service.explain_topic(topic="Preamble", context="private full prompt text")
    with pytest.raises(AIServiceUnavailableError) as quiz_error:
        service.generate_quiz(topic="Preamble", difficulty="medium", question_count=5, context="private full prompt text")

    for error in (explanation_error.value, quiz_error.value):
        assert error.status_code == 503
        assert error.attempted_provider_chain == ("gemini",)
        assert str(error) == "AI generation is temporarily unavailable. Please try again."
        assert "should-not-escape" not in str(error)
        assert "private full prompt text" not in str(error)


def test_development_explicit_mock_remains_available() -> None:
    settings = Settings(app_env="development", ai_provider="mock", ai_provider_chain="mock")
    response = AIService(settings=settings).explain_topic(topic="Preamble", context="")

    assert settings.mock_ai_runtime_allowed is True
    assert response["generation_mode"] == "mock"
    assert response["generation_provider"] == "mock"


def test_text_and_tts_model_defaults_are_current_and_distinct() -> None:
    settings = Settings()

    assert settings.gemini_model == "gemini-3.6-flash"
    assert settings.groq_model == "llama-3.1-8b-instant"
    assert settings.tts_gemini_model == "gemini-2.5-flash-preview-tts"
    assert settings.tts_gemini_model != settings.gemini_model


def test_production_gmail_smtp_accepts_authenticated_starttls() -> None:
    settings = _production_settings()
    result = settings.validate_runtime_config()

    assert result.ok is True
    assert not {issue.code for issue in result.errors} & {
        "missing_gmail_smtp_username",
        "missing_gmail_smtp_password",
        "gmail_smtp_requires_starttls",
        "gmail_sender_username_mismatch",
    }
    assert settings.smtp_password not in str(result.to_public_dict())


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"smtp_username": ""}, "missing_gmail_smtp_username"),
        ({"smtp_password": ""}, "missing_gmail_smtp_password"),
        ({"smtp_use_tls": False}, "gmail_smtp_requires_starttls"),
        ({"smtp_use_ssl": True}, "smtp_tls_modes_conflict"),
        ({"smtp_use_tls": False, "smtp_use_ssl": True}, "smtp_ssl_common_port_mismatch"),
        ({"email_from_address": "different@example.invalid"}, "gmail_sender_username_mismatch"),
    ],
)
def test_production_gmail_smtp_rejects_unsafe_configuration(overrides: dict, expected_code: str) -> None:
    result = _production_settings(**overrides).validate_runtime_config()

    assert expected_code in {issue.code for issue in result.errors}


def test_production_rejects_console_email_while_resend_remains_supported_in_development() -> None:
    console = _production_settings(email_otp_delivery_mode="console", email_transport="console").validate_runtime_config()
    resend = Settings(
        app_env="development",
        ai_provider="mock",
        ai_provider_chain="mock",
        email_otp_delivery_mode="email",
        email_transport="resend",
        email_from_address="sender@example.invalid",
        resend_api_key="unit-test-resend-material",
    ).validate_runtime_config()

    assert "console_email_in_production" in {issue.code for issue in console.errors}
    assert resend.ok is True


def test_render_blueprint_uses_strict_live_ai_gmail_and_disabled_payments() -> None:
    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    env = {item["key"]: item for item in service["envVars"]}

    assert env["AI_PROVIDER"]["value"] == "gemini"
    assert env["AI_PROVIDER_CHAIN"]["value"] == "gemini"
    assert env["ALLOW_MOCK_AI_IN_PRODUCTION"]["value"] == "false"
    assert env["GEMINI_MODEL"]["value"] == "gemini-3.6-flash"
    assert "GROQ_MODEL" not in env
    assert env["EMAIL_TRANSPORT"]["value"] == "smtp"
    assert env["SMTP_HOST"]["value"] == "smtp.gmail.com"
    assert env["SMTP_PORT"]["value"] == "587"
    assert env["SMTP_USE_TLS"]["value"] == "true"
    assert env["SMTP_USE_SSL"]["value"] == "false"
    assert env["PAYMENT_PROVIDER"]["value"] == "disabled"
    assert "RESEND_API_KEY" not in env
    assert env["GEMINI_API_KEY"] == {"key": "GEMINI_API_KEY", "sync": False}
    assert "GROQ_API_KEY" not in env
    assert env["SMTP_USERNAME"] == {"key": "SMTP_USERNAME", "sync": False}
    assert env["SMTP_PASSWORD"] == {"key": "SMTP_PASSWORD", "sync": False}
    serialized = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8").lower()
    assert "type: worker" not in serialized
    assert "alembic" not in serialized
    assert "predeploy" not in serialized


def test_provider_secrets_are_not_frontend_environment_variables() -> None:
    text_suffixes = {".css", ".html", ".js", ".jsx", ".json", ".md", ".ts", ".tsx"}
    frontend_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "frontend").rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() in text_suffixes
            and "node_modules" not in path.parts
            and ".next" not in path.parts
        )
    )

    for forbidden_name in (
        "NEXT_PUBLIC_GEMINI_API_KEY",
        "NEXT_PUBLIC_GROQ_API_KEY",
        "NEXT_PUBLIC_SMTP_PASSWORD",
        "NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY",
    ):
        assert forbidden_name not in frontend_text
