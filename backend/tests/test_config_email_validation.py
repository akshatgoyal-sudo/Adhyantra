from backend.config import Settings


def _base_settings(**overrides) -> Settings:
    return Settings(
        app_env="development",
        ai_provider="mock",
        ai_provider_chain="mock",
        db_url="sqlite:///./exam_guru.db",
        frontend_origin="http://localhost:3000",
        **overrides,
    )


def test_email_transport_accepts_resend_without_smtp_host() -> None:
    result = _base_settings(
        email_otp_delivery_mode="email",
        email_transport="resend",
        email_from_address="hello@adhyantra.example",
        resend_api_key="re_xxxxx",
    ).validate_runtime_config()

    error_codes = {issue.code for issue in result.errors}

    assert result.ok is True
    assert "unsupported_email_transport" not in error_codes
    assert "missing_resend_api_key" not in error_codes
    assert "missing_smtp_host" not in error_codes


def test_email_transport_accepts_smtp_with_smtp_settings() -> None:
    result = _base_settings(
        email_otp_delivery_mode="email",
        email_transport="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.gmail.com",
        smtp_username="test@gmail.com",
        smtp_password="real-smtp-password-123",
    ).validate_runtime_config()

    error_codes = {issue.code for issue in result.errors}

    assert result.ok is True
    assert "unsupported_email_transport" not in error_codes
    assert "missing_smtp_host" not in error_codes


def test_email_transport_accepts_console_without_smtp_or_resend_settings() -> None:
    result = _base_settings(
        email_otp_delivery_mode="console",
        email_transport="console",
    ).validate_runtime_config()

    error_codes = {issue.code for issue in result.errors}

    assert result.ok is True
    assert "unsupported_email_transport" not in error_codes
    assert "missing_resend_api_key" not in error_codes
    assert "missing_smtp_host" not in error_codes


def test_email_transport_rejects_resend_without_api_key() -> None:
    result = _base_settings(
        email_otp_delivery_mode="email",
        email_transport="resend",
        email_from_address="hello@adhyantra.example",
        resend_api_key="",
    ).validate_runtime_config()

    error_codes = {issue.code for issue in result.errors}

    assert result.ok is False
    assert "missing_resend_api_key" in error_codes
    assert "missing_smtp_host" not in error_codes


def test_email_transport_rejects_unknown_real_email_transport() -> None:
    result = _base_settings(
        email_otp_delivery_mode="email",
        email_transport="sendgrid",
        email_from_address="hello@adhyantra.example",
    ).validate_runtime_config()

    assert result.ok is False
    assert any(issue.code == "unsupported_email_transport" for issue in result.errors)
    assert any(
        issue.code == "unsupported_email_transport"
        and "smtp, resend" in issue.message
        and "console" in issue.message
        for issue in result.errors
    )
