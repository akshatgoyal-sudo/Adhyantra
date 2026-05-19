from __future__ import annotations

from scripts import staging_smoke


def test_staging_smoke_billing_account_state_summarizes_authenticated_payload() -> None:
    result = staging_smoke._check_billing_account_state(
        backend_url="http://127.0.0.1:8000",
        auth_payload={
            "authenticated": True,
            "user": {
                "plan_tier": "free",
                "subscription_status": "inactive",
                "billing": {
                    "billing_email": "learner@example.com",
                    "customer_ref": "cust_demo",
                    "checkout_ready": True,
                    "portal_ready": False,
                    "subscription_lifecycle": {"state": "free"},
                },
            },
        },
    )

    assert result.ok is True
    assert result.name == "billing_account_state"
    assert '"checkout_ready": true' in result.detail
    assert '"customer_ref_linked": true' in result.detail
    assert '"lifecycle_state": "free"' in result.detail


def test_staging_smoke_billing_account_state_fails_without_lifecycle_state() -> None:
    result = staging_smoke._check_billing_account_state(
        backend_url="http://127.0.0.1:8000",
        auth_payload={
            "authenticated": True,
            "user": {
                "plan_tier": "free",
                "subscription_status": "inactive",
                "billing": {
                    "checkout_ready": True,
                    "portal_ready": False,
                    "subscription_lifecycle": None,
                },
            },
        },
    )

    assert result.ok is False
    assert "lifecycle state" in result.detail.lower()


def test_staging_smoke_learner_admin_separation_summarizes_denials(monkeypatch) -> None:
    def fake_json_check_result(*, name: str, url: str, method: str, client, expected_status: int = 200, required_keys=(), json_payload=None):
        assert method == "GET"
        assert expected_status == 403
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=403, detail=""), {
            "detail": {
                "required_privilege": "content_qa" if "ops" in name else "content_read",
                "account_role": "student",
                "admin_access": False,
            }
        }

    monkeypatch.setattr(staging_smoke, "_json_check_result", fake_json_check_result)

    results = staging_smoke._check_learner_admin_separation(
        backend_url="http://127.0.0.1:8000",
        client=object(),
        learner_email="learner@example.com",
    )

    assert len(results) == 3
    assert all(result.ok for result in results)
    assert all('"admin_access": false' in result.detail for result in results)


def test_staging_smoke_admin_authenticated_flow_skips_support_lookup_without_target(monkeypatch) -> None:
    def fake_auth_me_payload(*, backend_url: str, client):
        return staging_smoke.CheckResult(
            name="auth_me",
            url=f"{backend_url}/api/auth/me",
            ok=True,
            status_code=200,
            detail="",
        ), {
            "authenticated": True,
            "user": {
                "email": "admin@example.com",
                "admin_access": {
                    "is_admin": True,
                    "role": "content_admin",
                    "privileges": ["content_qa", "content_read"],
                },
            },
        }

    def fake_json_endpoint(*, name: str, url: str, client, expected_status: int = 200, required_key: str | None = None):
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=200, detail="ok")

    def fake_json_check_result(*, name: str, url: str, method: str, client, expected_status: int = 200, required_keys=(), json_payload=None):
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=200, detail=""), {
            "checked_at": "2026-05-18T00:00:00Z",
            "provider": {"provider_name": "razorpay"},
            "validation": {
                "validation_state": "ready",
                "provider_config_ready": True,
                "checkout_ready": True,
                "webhook_ready": True,
                "subscription_sync_ready": True,
                "blocker_count": 0,
            },
            "webhook": {"failed_count": 0},
            "subscriptions": {"attention_account_count": 0},
        }

    monkeypatch.setattr(staging_smoke, "_check_auth_me_payload", fake_auth_me_payload)
    monkeypatch.setattr(staging_smoke, "_check_json_endpoint", fake_json_endpoint)
    monkeypatch.setattr(staging_smoke, "_json_check_result", fake_json_check_result)

    results = staging_smoke._check_admin_authenticated_flow(
        backend_url="http://127.0.0.1:8000",
        client=object(),
        learner_email="",
    )

    support_result = next(result for result in results if result.name == "admin_support_lookup")
    assert support_result.ok is True
    assert support_result.detail.startswith("SKIPPED:")
    billing_result = next(result for result in results if result.name == "admin_billing_overview")
    assert '"validation_state": "ready"' in billing_result.detail


def test_staging_smoke_admin_authenticated_flow_can_require_provider_validation_ready(monkeypatch) -> None:
    def fake_auth_me_payload(*, backend_url: str, client):
        return staging_smoke.CheckResult(
            name="auth_me",
            url=f"{backend_url}/api/auth/me",
            ok=True,
            status_code=200,
            detail="",
        ), {
            "authenticated": True,
            "user": {
                "email": "admin@example.com",
                "admin_access": {
                    "is_admin": True,
                    "role": "content_admin",
                    "privileges": ["content_qa", "content_read"],
                },
            },
        }

    def fake_json_endpoint(*, name: str, url: str, client, expected_status: int = 200, required_key: str | None = None):
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=200, detail="ok")

    def fake_json_check_result(*, name: str, url: str, method: str, client, expected_status: int = 200, required_keys=(), json_payload=None):
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=200, detail=""), {
            "checked_at": "2026-05-18T00:00:00Z",
            "provider": {"provider_name": "razorpay"},
            "validation": {
                "validation_state": "attention",
                "provider_config_ready": True,
                "checkout_ready": True,
                "webhook_ready": False,
                "subscription_sync_ready": False,
                "blocker_count": 1,
            },
            "webhook": {"failed_count": 1},
            "subscriptions": {"attention_account_count": 1},
        }

    monkeypatch.setattr(staging_smoke, "_check_auth_me_payload", fake_auth_me_payload)
    monkeypatch.setattr(staging_smoke, "_check_json_endpoint", fake_json_endpoint)
    monkeypatch.setattr(staging_smoke, "_json_check_result", fake_json_check_result)

    results = staging_smoke._check_admin_authenticated_flow(
        backend_url="http://127.0.0.1:8000",
        client=object(),
        learner_email="",
        require_provider_validation_ready=True,
    )

    billing_result = next(result for result in results if result.name == "admin_billing_overview")
    assert billing_result.ok is False
    assert "launch-ready" in billing_result.detail


def test_staging_smoke_prefix_check_results_preserves_details() -> None:
    results = [
        staging_smoke.CheckResult(name="alpha", url="http://127.0.0.1:8000/alpha", ok=True, status_code=200, detail="ok"),
        staging_smoke.CheckResult(name="beta", url="http://127.0.0.1:8000/beta", ok=False, status_code=403, detail="denied"),
    ]

    prefixed = staging_smoke._prefix_check_results(results, prefix="switch_")

    assert [result.name for result in prefixed] == ["switch_alpha", "switch_beta"]
    assert prefixed[0].detail == "ok"
    assert prefixed[1].status_code == 403


def test_staging_smoke_account_switch_flow_reauthenticates_second_learner(monkeypatch) -> None:
    def fake_auth_me_payload(*, backend_url: str, client):
        if fake_auth_me_payload.calls == 0:
            payload = {
                "authenticated": True,
                "user": {
                    "email": "learner.one@example.com",
                    "account_role": "student",
                    "plan_tier": "free",
                },
            }
        else:
            payload = {
                "authenticated": True,
                "user": {
                    "email": "learner.two@example.com",
                    "account_role": "student",
                    "plan_tier": "free",
                },
            }
        fake_auth_me_payload.calls += 1
        return staging_smoke.CheckResult(
            name="auth_me",
            url=f"{backend_url}/api/auth/me",
            ok=True,
            status_code=200,
            detail="",
        ), payload

    fake_auth_me_payload.calls = 0

    def fake_json_check_result(*, name: str, url: str, method: str, client, expected_status: int = 200, required_keys=(), json_payload=None):
        if name == "account_switch_logout":
            return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=200, detail=""), {"success": True}
        raise AssertionError(f"Unexpected json check request: {name}")

    def fake_json_endpoint(*, name: str, url: str, client, expected_status: int = 200, required_key: str | None = None):
        return staging_smoke.CheckResult(name=name, url=url, ok=True, status_code=401 if expected_status == 401 else 200, detail="ok")

    def fake_otp_request(*, backend_url: str, email: str, client):
        assert email == "learner.two@example.com"
        return staging_smoke.CheckResult(name="otp_request", url=f"{backend_url}/api/auth/request-otp", ok=True, status_code=200, detail=""), "654321"

    def fake_auth_verify(*, backend_url: str, email: str, code: str, client):
        assert email == "learner.two@example.com"
        assert code == "654321"
        return staging_smoke.CheckResult(name="auth_verify_otp", url=f"{backend_url}/api/auth/verify-otp", ok=True, status_code=200, detail="verified")

    def fake_billing_state(*, backend_url: str, auth_payload):
        return staging_smoke.CheckResult(
            name="billing_account_state",
            url=f"{backend_url}/api/auth/me",
            ok=True,
            status_code=200,
            detail='{"lifecycle_state":"free"}',
        )

    def fake_learner_admin_separation(*, backend_url: str, client, learner_email: str):
        assert learner_email == "learner.two@example.com"
        return [
            staging_smoke.CheckResult(name="learner_admin_ops_denied", url=f"{backend_url}/api/admin/ops/overview", ok=True, status_code=403, detail="denied")
        ]

    def fake_logout(*, backend_url: str, client):
        return [
            staging_smoke.CheckResult(name="auth_logout", url=f"{backend_url}/api/auth/logout", ok=True, status_code=200, detail="ok"),
            staging_smoke.CheckResult(name="auth_me_after_logout", url=f"{backend_url}/api/auth/me", ok=True, status_code=401, detail="ok"),
        ]

    monkeypatch.setattr(staging_smoke, "_check_auth_me_payload", fake_auth_me_payload)
    monkeypatch.setattr(staging_smoke, "_json_check_result", fake_json_check_result)
    monkeypatch.setattr(staging_smoke, "_check_json_endpoint", fake_json_endpoint)
    monkeypatch.setattr(staging_smoke, "_check_otp_request", fake_otp_request)
    monkeypatch.setattr(staging_smoke, "_check_auth_verify", fake_auth_verify)
    monkeypatch.setattr(staging_smoke, "_check_billing_account_state", fake_billing_state)
    monkeypatch.setattr(staging_smoke, "_check_learner_admin_separation", fake_learner_admin_separation)
    monkeypatch.setattr(staging_smoke, "_check_logout", fake_logout)

    results = staging_smoke._check_account_switch_flow(
        backend_url="http://127.0.0.1:8000",
        client=object(),
        current_email="learner.one@example.com",
        switch_email="learner.two@example.com",
        switch_code="",
        interactive=False,
        learner_email="learner.two@example.com",
    )

    assert all(result.ok for result in results)
    assert any(result.name == "account_switch_auth_me" for result in results)
    assert any(result.name == "account_switch_billing_state" for result in results)
    assert any(result.name == "account_switch_learner_admin_ops_denied" for result in results)
    assert any(result.name == "account_switch_auth_logout" for result in results)


def test_staging_smoke_public_launch_routes_cover_auth_pricing_exam_and_discovery() -> None:
    class FakeClient:
        def request(self, method: str, url: str, *, json_payload=None):
            assert method == "GET"
            if url.endswith("/auth"):
                return 200, None, "<html><head><title>Sign in to Adhyantra | Adhyantra</title></head></html>"
            if url.endswith("/pricing"):
                return 200, None, "<html><head><title>Pricing | Adhyantra</title></head></html>"
            if url.endswith("/exams/upsc"):
                return 200, None, "<html><head><title>UPSC study workspace and premium lesson tools</title></head></html>"
            if url.endswith("/robots.txt"):
                return 200, None, "User-agent: *\nAllow: /auth\nAllow: /pricing\nDisallow: /\n"
            if url.endswith("/sitemap.xml"):
                return 200, None, "<urlset><url><loc>https://adhyantra.example/auth</loc></url><url><loc>https://adhyantra.example/pricing</loc></url><url><loc>https://adhyantra.example/exams/upsc</loc></url></urlset>"
            raise AssertionError(f"Unexpected URL: {url}")

    results = staging_smoke._check_public_launch_routes(
        frontend_url="https://adhyantra.example",
        client=FakeClient(),
    )

    assert len(results) == 5
    assert all(result.ok for result in results)


def test_staging_smoke_learner_surface_cleanliness_rejects_provider_leakage() -> None:
    class FakeClient:
        def request(self, method: str, url: str, *, json_payload=None):
            assert method == "GET"
            return 200, None, '<html><head><meta name="robots" content="noindex, nofollow"></head><body>Razorpay debug info</body></html>'

    results = staging_smoke._check_learner_surface_cleanliness(
        frontend_url="https://adhyantra.example",
        client=FakeClient(),
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert "Unexpected learner-visible fragment" in results[0].detail


def test_staging_smoke_launch_workflow_summary_groups_launch_lanes() -> None:
    checks = [
        staging_smoke.CheckResult(name="frontend_auth", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="auth_me_requires_session", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="public_auth_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_pricing_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_exam_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_robots_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_sitemap_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="learner_settings_cleanliness", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="billing_account_state", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="billing_flow", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="admin_ops_requires_auth", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="admin_content_requires_auth", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="admin_ops_overview", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="admin_billing_overview", url="", ok=True, status_code=200, detail=""),
    ]

    summary = staging_smoke._build_launch_workflow_summary(
        checks=checks,
        skip_frontend=False,
        require_auth_flow=True,
        product_flow_requested=True,
        scenario_requested=False,
        check_billing_flow=True,
        require_switch_flow=True,
        admin_flow_requested=True,
        require_provider_validation_ready=True,
        auth_flow_checked=True,
        product_flow_checked=True,
        scenario_baseline_checked=False,
        learner_admin_separation_checked=True,
        account_switch_checked=True,
        admin_flow_checked=True,
    )

    assert summary["public_routes_checked"] is True
    assert summary["auth_public_checked"] is True
    assert summary["product_and_exam_checked"] is True
    assert summary["learner_surface_cleanliness_checked"] is True
    assert summary["premium_payment_checked"] is True
    assert summary["admin_route_protection_checked"] is True
    assert summary["account_session_continuity_checked"] is True
    assert summary["admin_provider_signoff_checked"] is True
    assert summary["next_step"] is None


def test_staging_smoke_launch_workflow_summary_requires_learner_admin_separation_when_auth_flow_runs() -> None:
    checks = [
        staging_smoke.CheckResult(name="frontend_auth", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="auth_me_requires_session", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="public_auth_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_pricing_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_exam_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_robots_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="public_sitemap_route", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="learner_settings_cleanliness", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="billing_account_state", url="", ok=True, status_code=200, detail=""),
        staging_smoke.CheckResult(name="admin_ops_requires_auth", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="admin_content_requires_auth", url="", ok=True, status_code=401, detail=""),
        staging_smoke.CheckResult(name="admin_billing_overview", url="", ok=True, status_code=200, detail=""),
    ]

    summary = staging_smoke._build_launch_workflow_summary(
        checks=checks,
        skip_frontend=False,
        require_auth_flow=True,
        product_flow_requested=False,
        scenario_requested=False,
        check_billing_flow=False,
        require_switch_flow=False,
        admin_flow_requested=False,
        require_provider_validation_ready=False,
        auth_flow_checked=True,
        product_flow_checked=False,
        scenario_baseline_checked=False,
        learner_admin_separation_checked=False,
        account_switch_checked=False,
        admin_flow_checked=False,
    )

    assert summary["admin_route_protection_checked"] is False
    assert summary["admin_provider_signoff_checked"] is False
    assert summary["next_step"] is not None
