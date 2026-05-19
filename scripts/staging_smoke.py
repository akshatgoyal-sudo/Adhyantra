from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import getpass
import json
import os
from pathlib import Path
import re
import sys
from http.cookiejar import CookieJar
from typing import Any
from urllib import error, parse, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.demo_seed_service import (
    DemoSmokeScenarioSeed,
    demo_smoke_scenario_keys,
    get_demo_account_seed,
    get_demo_smoke_scenario_seed,
)


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_URL = "http://localhost:3000"


@dataclass
class CheckResult:
    name: str
    url: str
    ok: bool
    status_code: int | None
    detail: str


@dataclass(frozen=True)
class ResolvedSmokeTarget:
    otp_email: str
    exam: str
    subject: str
    topic: str
    scenario: DemoSmokeScenarioSeed | None = None
    email_source: str = "explicit"


class SmokeClient:
    def __init__(self, *, timeout: float):
        self.timeout = timeout
        self.cookie_jar = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookie_jar))

    def request(
        self,
        method: str,
        url: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any, str]:
        body = None
        headers = {
            "User-Agent": "adhyantra-staging-smoke/1.0",
            "X-Request-ID": "adhyantra-staging-smoke",
        }
        if json_payload is not None:
            body = json.dumps(json_payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw_body = response.read()
                return int(response.status), _parse_json(raw_body), _decode_body(raw_body)
        except error.HTTPError as exc:
            raw_body = exc.read()
            return int(exc.code), _parse_json(raw_body), _decode_body(raw_body)


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _flag_was_provided(argv: list[str], flag: str) -> bool:
    return flag in argv


def _resolve_smoke_target(args: argparse.Namespace, argv: list[str]) -> ResolvedSmokeTarget:
    scenario = get_demo_smoke_scenario_seed(args.scenario) if str(getattr(args, "scenario", "") or "").strip() else None
    if scenario is None:
        return ResolvedSmokeTarget(
            otp_email=str(args.otp_email or "").strip(),
            exam=str(args.exam or "").strip(),
            subject=str(args.subject or "").strip(),
            topic=str(args.topic or "").strip(),
            email_source="explicit" if _flag_was_provided(argv, "--otp-email") else "env_or_default",
        )

    account_seed = get_demo_account_seed(scenario.account_key)
    email_source = "scenario_default"
    otp_email = account_seed.email
    if _flag_was_provided(argv, "--otp-email"):
        otp_email = str(args.otp_email or "").strip()
        email_source = "explicit_override"
    exam = str(args.exam or "").strip() if _flag_was_provided(argv, "--exam") else scenario.exam
    subject = str(args.subject or "").strip() if _flag_was_provided(argv, "--subject") else scenario.subject
    topic = str(args.topic or "").strip() if _flag_was_provided(argv, "--topic") else scenario.topic
    return ResolvedSmokeTarget(
        otp_email=otp_email,
        exam=exam,
        subject=subject,
        topic=topic,
        scenario=scenario,
        email_source=email_source,
    )


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _query_url(base_url: str, path: str, params: dict[str, str]) -> str:
    query = parse.urlencode({key: value for key, value in params.items() if value})
    return f"{_join_url(base_url, path)}?{query}" if query else _join_url(base_url, path)


def _decode_body(raw_body: bytes) -> str:
    return raw_body.decode("utf-8", errors="replace")


def _parse_json(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    try:
        return json.loads(_decode_body(raw_body))
    except json.JSONDecodeError:
        return None


def _safe_email_detail(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "masked_email": payload.get("masked_email"),
        "delivery_mode": payload.get("delivery_mode"),
        "challenge_expires_at": payload.get("challenge_expires_at"),
        "resend_available_at": payload.get("resend_available_at"),
        "dev_otp_returned": bool(payload.get("dev_otp_code")),
    }


def _mask_email(email: str) -> str | None:
    cleaned = str(email or "").strip()
    if not cleaned or "@" not in cleaned:
        return None
    local, domain = cleaned.split("@", 1)
    local_mask = f"{local[:2]}***" if len(local) > 2 else f"{local[:1]}***"
    return f"{local_mask}@{domain}"


def _is_local_backend_url(backend_url: str) -> bool:
    hostname = (parse.urlparse(backend_url).hostname or "").strip().lower()
    return hostname in {"127.0.0.1", "localhost"}


def _build_verification_hygiene(*, backend_url: str, resolved_target: ResolvedSmokeTarget) -> dict[str, Any]:
    local_target = _is_local_backend_url(backend_url)
    smoke_email = str(resolved_target.otp_email or "").strip().lower()
    uses_demo_email = smoke_email.endswith("@adhyantra.test")

    if resolved_target.scenario is not None and local_target:
        return {
            "lane": "deterministic_demo_verification",
            "label": "Deterministic Demo Verification",
            "target_scope": "local",
            "email_source": resolved_target.email_source,
            "uses_demo_email": uses_demo_email,
            "note": "This smoke run expects intentionally seeded local demo data. Reset and load the named scenario first, then use the smoke result as QA/demo evidence rather than ordinary product history.",
        }
    if resolved_target.scenario is not None:
        return {
            "lane": "scenario_seeded_remote_verification",
            "label": "Scenario-Seeded Remote Verification",
            "target_scope": "remote",
            "email_source": resolved_target.email_source,
            "uses_demo_email": uses_demo_email,
            "note": "This smoke run is checking a named scenario on a non-local target. Only use this when the remote environment was intentionally seeded to match the scenario.",
        }
    if local_target:
        return {
            "lane": "ordinary_local_runtime_verification",
            "label": "Ordinary Local Runtime Verification",
            "target_scope": "local",
            "email_source": resolved_target.email_source,
            "uses_demo_email": uses_demo_email,
            "note": "This smoke run is using whatever local runtime data currently exists. Prefer a named scenario for repeatable QA instead of ad hoc local state.",
        }
    return {
        "lane": "staging_verification_data",
        "label": "Staging Verification Data",
        "target_scope": "remote",
        "email_source": resolved_target.email_source,
        "uses_demo_email": uses_demo_email,
        "note": "This smoke run targets a deployed environment. Use a dedicated staging smoke mailbox and keep it separate from local @adhyantra.test demo identities.",
    }


def _summarize_payload(payload: Any, raw_body: str) -> str:
    if isinstance(payload, dict):
        safe_payload = dict(payload)
        for key in ("dev_otp_code", "session_token", "code", "otp_code"):
            safe_payload.pop(key, None)
        if "email" in safe_payload and "masked_email" in safe_payload:
            safe_payload.pop("email", None)
        return json.dumps(safe_payload, sort_keys=True)[:900]
    return raw_body[:900] if raw_body else "No response body."


def _scenario_detail(**data: Any) -> str:
    return json.dumps({key: value for key, value in data.items() if value is not None}, sort_keys=True)


def _append_scenario_mismatch(
    mismatches: dict[str, dict[str, Any]],
    *,
    field: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected is None or actual == expected:
        return
    mismatches[field] = {"expected": expected, "actual": actual}


def _json_check_result(
    *,
    name: str,
    url: str,
    method: str,
    client: SmokeClient,
    expected_status: int = 200,
    required_keys: tuple[str, ...] = (),
    json_payload: dict[str, Any] | None = None,
) -> tuple[CheckResult, Any]:
    try:
        status_code, payload, raw_body = client.request(method, url, json_payload=json_payload)
    except Exception as exc:
        return CheckResult(name=name, url=url, ok=False, status_code=None, detail=f"{type(exc).__name__}: {exc}"), None

    if status_code != expected_status:
        return CheckResult(name=name, url=url, ok=False, status_code=status_code, detail=_summarize_payload(payload, raw_body)), payload
    if not isinstance(payload, dict):
        return CheckResult(name=name, url=url, ok=False, status_code=status_code, detail="Response was not JSON."), payload

    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return CheckResult(name=name, url=url, ok=False, status_code=status_code, detail=f"Missing JSON keys: {', '.join(missing_keys)}"), payload
    return CheckResult(name=name, url=url, ok=True, status_code=status_code, detail=_summarize_payload(payload, raw_body)), payload


def _check_json_endpoint(
    *,
    name: str,
    url: str,
    client: SmokeClient,
    expected_status: int = 200,
    required_key: str | None = None,
) -> CheckResult:
    result, _payload = _json_check_result(
        name=name,
        url=url,
        method="GET",
        client=client,
        expected_status=expected_status,
        required_keys=(required_key,) if required_key else (),
    )
    return result


def _check_html_endpoint(*, name: str, url: str, client: SmokeClient) -> CheckResult:
    try:
        status_code, _payload, raw_body = client.request("GET", url)
    except Exception as exc:
        return CheckResult(name=name, url=url, ok=False, status_code=None, detail=f"{type(exc).__name__}: {exc}")

    if status_code < 200 or status_code >= 400:
        return CheckResult(name=name, url=url, ok=False, status_code=status_code, detail=raw_body[:240])
    return CheckResult(name=name, url=url, ok=True, status_code=status_code, detail="Frontend route responded.")


def _extract_html_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, flags=re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).strip()
    return title or None


def _extract_meta_robots(html: str) -> str | None:
    match = re.search(
        r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _check_html_expectations(
    *,
    name: str,
    url: str,
    client: SmokeClient,
    title_contains: str | None = None,
    robots_contains: str | None = None,
    required_fragments: tuple[str, ...] = (),
    forbidden_fragments: tuple[str, ...] = (),
) -> CheckResult:
    try:
        status_code, _payload, raw_body = client.request("GET", url)
    except Exception as exc:
        return CheckResult(name=name, url=url, ok=False, status_code=None, detail=f"{type(exc).__name__}: {exc}")

    if status_code < 200 or status_code >= 400:
        return CheckResult(name=name, url=url, ok=False, status_code=status_code, detail=raw_body[:240])

    if title_contains:
        title = _extract_html_title(raw_body)
        if title is None or title_contains.lower() not in title.lower():
            return CheckResult(
                name=name,
                url=url,
                ok=False,
                status_code=status_code,
                detail=f"Expected title containing {title_contains!r}, got {title!r}.",
            )

    if robots_contains:
        robots_value = _extract_meta_robots(raw_body)
        if robots_value is None or robots_contains.lower() not in robots_value.lower():
            return CheckResult(
                name=name,
                url=url,
                ok=False,
                status_code=status_code,
                detail=f"Expected robots meta containing {robots_contains!r}, got {robots_value!r}.",
            )

    for fragment in required_fragments:
        if fragment not in raw_body:
            return CheckResult(
                name=name,
                url=url,
                ok=False,
                status_code=status_code,
                detail=f"Expected fragment {fragment!r} was missing from the frontend response.",
            )

    for fragment in forbidden_fragments:
        if fragment in raw_body:
            return CheckResult(
                name=name,
                url=url,
                ok=False,
                status_code=status_code,
                detail=f"Unexpected learner-visible fragment {fragment!r} was present in the frontend response.",
            )

    return CheckResult(name=name, url=url, ok=True, status_code=status_code, detail="Frontend route content matched launch expectations.")


def _check_public_launch_routes(*, frontend_url: str, client: SmokeClient) -> list[CheckResult]:
    return [
        _check_html_expectations(
            name="public_auth_route",
            url=_join_url(frontend_url, "/auth"),
            client=client,
            title_contains="Adhyantra",
        ),
        _check_html_expectations(
            name="public_pricing_route",
            url=_join_url(frontend_url, "/pricing"),
            client=client,
            title_contains="Adhyantra",
        ),
        _check_html_expectations(
            name="public_exam_route",
            url=_join_url(frontend_url, "/exams/upsc"),
            client=client,
            title_contains="UPSC",
        ),
        _check_html_expectations(
            name="public_robots_route",
            url=_join_url(frontend_url, "/robots.txt"),
            client=client,
            required_fragments=("Allow: /auth", "Allow: /pricing", "Disallow: /"),
        ),
        _check_html_expectations(
            name="public_sitemap_route",
            url=_join_url(frontend_url, "/sitemap.xml"),
            client=client,
            required_fragments=("/auth", "/pricing", "/exams/upsc"),
        ),
    ]


def _check_learner_surface_cleanliness(*, frontend_url: str, client: SmokeClient) -> list[CheckResult]:
    forbidden_fragments = (
        "Razorpay",
        "razorpay",
        "webhook",
        "subscription_provider_ref",
        "subscription_customer_ref",
    )
    return [
        _check_html_expectations(
            name="learner_settings_cleanliness",
            url=_join_url(frontend_url, "/settings"),
            client=client,
            robots_contains="noindex, nofollow",
            forbidden_fragments=forbidden_fragments,
        )
    ]


def _build_launch_workflow_summary(
    *,
    checks: list[CheckResult],
    skip_frontend: bool,
    require_auth_flow: bool,
    product_flow_requested: bool,
    scenario_requested: bool,
    check_billing_flow: bool,
    require_switch_flow: bool,
    admin_flow_requested: bool,
    require_provider_validation_ready: bool,
    auth_flow_checked: bool,
    product_flow_checked: bool,
    scenario_baseline_checked: bool,
    learner_admin_separation_checked: bool,
    account_switch_checked: bool,
    admin_flow_checked: bool,
) -> dict[str, Any]:
    by_name = {check.name: check for check in checks}
    public_route_names = {
        "public_auth_route",
        "public_pricing_route",
        "public_exam_route",
        "public_robots_route",
        "public_sitemap_route",
    }
    learner_clean_names = {"learner_settings_cleanliness"}

    public_routes_checked = False if skip_frontend else all(by_name.get(name, CheckResult(name, "", False, None, "")).ok for name in public_route_names)
    learner_clean_checked = False if skip_frontend else all(by_name.get(name, CheckResult(name, "", False, None, "")).ok for name in learner_clean_names)
    auth_public_checked = bool(
        by_name.get("frontend_auth", CheckResult("", "", False, None, "")).ok
        and by_name.get("auth_me_requires_session", CheckResult("", "", False, None, "")).ok
        and (not require_auth_flow or auth_flow_checked)
    )
    premium_payment_checked = bool(
        by_name.get("billing_account_state", CheckResult("", "", False, None, "")).ok
        and (not check_billing_flow or by_name.get("billing_flow", CheckResult("", "", False, None, "")).ok)
    )
    admin_route_protection_checked = all(
        by_name.get(name, CheckResult(name, "", False, None, "")).ok
        for name in {"admin_ops_requires_auth", "admin_content_requires_auth"}
    ) and (not require_auth_flow or learner_admin_separation_checked)
    admin_signoff_checked = bool(
        admin_flow_requested
        and admin_flow_checked
        and by_name.get("admin_ops_overview", CheckResult("", "", False, None, "")).ok
        and by_name.get("admin_billing_overview", CheckResult("", "", False, None, "")).ok
    )
    product_and_exam_checked = (
        (not product_flow_requested or product_flow_checked)
        and (not scenario_requested or scenario_baseline_checked)
    )
    account_session_continuity_checked = (
        account_switch_checked if require_switch_flow else (auth_flow_checked if require_auth_flow else True)
    )

    checklist = [
        {
            "key": "public_routes",
            "label": "Public routes and discovery surfaces",
            "ok": public_routes_checked,
            "detail": "Auth, pricing, exam landing, robots, and sitemap routes responded with launch-safe content.",
        },
        {
            "key": "auth_and_public_entry",
            "label": "Auth and public entry",
            "ok": auth_public_checked,
            "detail": (
                "Public auth entry responded and the requested sign-in path completed cleanly."
                if require_auth_flow
                else "Public auth entry responded and authenticated API access still required a real session."
            ),
        },
        {
            "key": "product_and_exam_context",
            "label": "Product and exam-aware context",
            "ok": product_and_exam_checked,
            "detail": (
                "Settings, tutor, progress, and exam-aware product routes stayed aligned with the requested study context."
                if product_flow_requested or scenario_requested
                else "No authenticated product or scenario context was requested in this run."
            ),
        },
        {
            "key": "premium_and_payment",
            "label": "Premium and payment checks",
            "ok": premium_payment_checked,
            "detail": "Learner billing state was visible and any requested live billing action behaved consistently.",
        },
        {
            "key": "admin_protection",
            "label": "Admin route protection",
            "ok": admin_route_protection_checked,
            "detail": (
                "Anonymous and learner-authenticated access to admin routes stayed blocked."
                if require_auth_flow
                else "Anonymous access to admin ops/content routes remained blocked."
            ),
        },
        {
            "key": "account_and_session_continuity",
            "label": "Account and session continuity",
            "ok": account_session_continuity_checked,
            "detail": (
                "Same-browser session switching stayed user-scoped and preserved the correct account context."
                if require_switch_flow
                else "Auth continuity stayed coherent for the requested learner flow."
                if require_auth_flow
                else "No authenticated session continuity check was requested in this run."
            ),
        },
        {
            "key": "learner_surface_cleanliness",
            "label": "Learner-facing route cleanliness",
            "ok": learner_clean_checked,
            "detail": "Internal learner routes stayed noindex and free of provider/debug leakage.",
        },
        {
            "key": "admin_and_provider_signoff",
            "label": "Admin and provider validation",
            "ok": admin_signoff_checked,
            "detail": (
                "Admin ops and provider-backed billing validation were available for final sign-off."
                if admin_flow_requested
                else "No admin smoke account or admin sign-off flow was requested in this run."
            ),
        },
    ]

    next_step = None
    first_incomplete = next((item for item in checklist if not item["ok"]), None)
    if first_incomplete is not None:
        next_step = f"Resolve the {first_incomplete['label'].lower()} lane before final launch sign-off."

    return {
        "public_routes_checked": public_routes_checked,
        "auth_public_checked": auth_public_checked,
        "product_and_exam_checked": product_and_exam_checked,
        "premium_payment_checked": premium_payment_checked,
        "admin_route_protection_checked": admin_route_protection_checked,
        "account_session_continuity_checked": account_session_continuity_checked,
        "learner_surface_cleanliness_checked": learner_clean_checked,
        "admin_provider_signoff_checked": admin_signoff_checked,
        "checklist": checklist,
        "next_step": next_step,
    }


def _check_otp_request(*, backend_url: str, email: str, client: SmokeClient) -> tuple[CheckResult, str | None]:
    url = _join_url(backend_url, "/api/auth/request-otp")
    result, payload = _json_check_result(
        name="otp_request",
        url=url,
        method="POST",
        client=client,
        required_keys=("masked_email", "delivery_mode", "challenge_expires_at"),
        json_payload={"email": email, "display_name": "Adhyantra Staging Smoke"},
    )
    if not result.ok or not isinstance(payload, dict):
        return result, None

    result.detail = json.dumps(_safe_email_detail(payload), sort_keys=True)
    dev_otp_code = payload.get("dev_otp_code")
    return result, str(dev_otp_code).strip() if dev_otp_code else None


def _resolve_otp_code(*, configured_code: str, dev_otp_code: str | None, interactive: bool) -> str:
    if configured_code.strip():
        return configured_code.strip()
    if dev_otp_code:
        return dev_otp_code.strip()
    if interactive:
        return getpass.getpass("Enter the OTP received by the staging smoke account: ").strip()
    return ""


def _check_auth_verify(*, backend_url: str, email: str, code: str, client: SmokeClient) -> CheckResult:
    result, payload = _json_check_result(
        name="auth_verify_otp",
        url=_join_url(backend_url, "/api/auth/verify-otp"),
        method="POST",
        client=client,
        required_keys=("authenticated", "user", "settings"),
        json_payload={"email": email, "code": code},
    )
    if result.ok and isinstance(payload, dict):
        result.detail = json.dumps(
            {
                "authenticated": bool(payload.get("authenticated")),
                "user_plan": (payload.get("user") or {}).get("subscription_plan"),
                "settings_exam": (payload.get("settings") or {}).get("preferred_exam"),
            },
            sort_keys=True,
        )
    return result


def _check_auth_me_payload(*, backend_url: str, client: SmokeClient) -> tuple[CheckResult, Any]:
    return _json_check_result(
        name="auth_me",
        url=_join_url(backend_url, "/api/auth/me"),
        method="GET",
        client=client,
        required_keys=("authenticated", "user", "settings"),
    )


def _check_auth_me(*, backend_url: str, client: SmokeClient) -> CheckResult:
    result, payload = _check_auth_me_payload(backend_url=backend_url, client=client)
    if result.ok and isinstance(payload, dict):
        result.detail = json.dumps(
            {
                "authenticated": bool(payload.get("authenticated")),
                "preferred_exam": (payload.get("settings") or {}).get("preferred_exam"),
                "preferred_subject": (payload.get("settings") or {}).get("preferred_subject"),
            },
            sort_keys=True,
        )
    return result


def _extract_authenticated_user(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    user = payload.get("user")
    return user if isinstance(user, dict) else None


def _check_billing_account_state(*, backend_url: str, auth_payload: Any) -> CheckResult:
    user = _extract_authenticated_user(auth_payload)
    if user is None:
        return CheckResult(
            name="billing_account_state",
            url=_join_url(backend_url, "/api/auth/me"),
            ok=False,
            status_code=None,
            detail="Authenticated user payload was not available for billing state checks.",
        )

    billing = user.get("billing")
    if not isinstance(billing, dict):
        return CheckResult(
            name="billing_account_state",
            url=_join_url(backend_url, "/api/auth/me"),
            ok=False,
            status_code=None,
            detail="Billing overview was not present on the authenticated user payload.",
        )

    lifecycle = billing.get("subscription_lifecycle")
    if not isinstance(lifecycle, dict):
        return CheckResult(
            name="billing_account_state",
            url=_join_url(backend_url, "/api/auth/me"),
            ok=False,
            status_code=None,
            detail="Billing lifecycle state was not available on the authenticated user payload.",
        )

    checkout_ready = billing.get("checkout_ready")
    portal_ready = billing.get("portal_ready")
    if not isinstance(checkout_ready, bool) or not isinstance(portal_ready, bool):
        return CheckResult(
            name="billing_account_state",
            url=_join_url(backend_url, "/api/auth/me"),
            ok=False,
            status_code=None,
            detail="Billing readiness flags were not available as booleans on the authenticated user payload.",
        )

    return CheckResult(
        name="billing_account_state",
        url=_join_url(backend_url, "/api/auth/me"),
        ok=True,
        status_code=200,
        detail=json.dumps(
            {
                "plan_tier": user.get("plan_tier"),
                "subscription_status": user.get("subscription_status"),
                "lifecycle_state": lifecycle.get("state"),
                "checkout_ready": checkout_ready,
                "portal_ready": portal_ready,
                "billing_email_linked": bool(billing.get("billing_email")),
                "customer_ref_linked": bool(billing.get("customer_ref")),
            },
            sort_keys=True,
        ),
    )


def _check_billing_checkout_start(*, backend_url: str, client: SmokeClient) -> CheckResult:
    result, payload = _json_check_result(
        name="billing_checkout_start",
        url=_join_url(backend_url, "/api/account/billing/checkout"),
        method="POST",
        client=client,
        required_keys=("status", "checkout_url", "return_path"),
        json_payload={"plan_tier": "premium", "return_path": "/settings", "source": "staging_smoke_launch_qa"},
    )
    if result.ok and isinstance(payload, dict):
        checkout_url = str(payload.get("checkout_url") or "").strip()
        if not checkout_url.startswith("http"):
            return CheckResult(
                name="billing_checkout_start",
                url=result.url,
                ok=False,
                status_code=result.status_code,
                detail="Checkout response did not include a usable absolute checkout URL.",
            )
        result.detail = json.dumps(
            {
                "status": payload.get("status"),
                "return_path": payload.get("return_path"),
                "checkout_host": parse.urlparse(checkout_url).netloc,
            },
            sort_keys=True,
        )
    return result


def _check_billing_portal_start(*, backend_url: str, client: SmokeClient) -> CheckResult:
    result, payload = _json_check_result(
        name="billing_portal_start",
        url=_join_url(backend_url, "/api/account/billing/portal"),
        method="POST",
        client=client,
        required_keys=("status", "portal_url", "return_path"),
        json_payload={"return_path": "/settings", "source": "staging_smoke_launch_qa"},
    )
    if result.ok and isinstance(payload, dict):
        portal_url = str(payload.get("portal_url") or "").strip()
        if not portal_url.startswith("http"):
            return CheckResult(
                name="billing_portal_start",
                url=result.url,
                ok=False,
                status_code=result.status_code,
                detail="Portal response did not include a usable absolute portal URL.",
            )
        result.detail = json.dumps(
            {
                "status": payload.get("status"),
                "return_path": payload.get("return_path"),
                "portal_host": parse.urlparse(portal_url).netloc,
            },
            sort_keys=True,
        )
    return result


def _check_admin_requires_auth(*, backend_url: str, client: SmokeClient) -> list[CheckResult]:
    return [
        _check_json_endpoint(
            name="admin_ops_requires_auth",
            url=_join_url(backend_url, "/api/admin/ops/overview"),
            client=client,
            expected_status=401,
            required_key="detail",
        ),
        _check_json_endpoint(
            name="admin_content_requires_auth",
            url=_join_url(backend_url, "/api/admin/content/overview"),
            client=client,
            expected_status=401,
            required_key="detail",
        ),
    ]


def _check_learner_admin_separation(*, backend_url: str, client: SmokeClient, learner_email: str) -> list[CheckResult]:
    checks: list[CheckResult] = []
    ops_result, ops_payload = _json_check_result(
        name="learner_admin_ops_denied",
        url=_join_url(backend_url, "/api/admin/ops/overview"),
        method="GET",
        client=client,
        expected_status=403,
        required_keys=("detail",),
    )
    if ops_result.ok and isinstance(ops_payload, dict) and isinstance(ops_payload.get("detail"), dict):
        detail = ops_payload["detail"]
        ops_result.detail = json.dumps(
            {
                "required_privilege": detail.get("required_privilege"),
                "account_role": detail.get("account_role"),
                "admin_access": detail.get("admin_access"),
            },
            sort_keys=True,
        )
    checks.append(ops_result)

    content_result, content_payload = _json_check_result(
        name="learner_admin_content_denied",
        url=_join_url(backend_url, "/api/admin/content/overview"),
        method="GET",
        client=client,
        expected_status=403,
        required_keys=("detail",),
    )
    if content_result.ok and isinstance(content_payload, dict) and isinstance(content_payload.get("detail"), dict):
        detail = content_payload["detail"]
        content_result.detail = json.dumps(
            {
                "required_privilege": detail.get("required_privilege"),
                "account_role": detail.get("account_role"),
                "admin_access": detail.get("admin_access"),
            },
            sort_keys=True,
        )
    checks.append(content_result)

    support_result, support_payload = _json_check_result(
        name="learner_admin_support_denied",
        url=_query_url(backend_url, "/api/admin/ops/support", {"email": learner_email}),
        method="GET",
        client=client,
        expected_status=403,
        required_keys=("detail",),
    )
    if support_result.ok and isinstance(support_payload, dict) and isinstance(support_payload.get("detail"), dict):
        detail = support_payload["detail"]
        support_result.detail = json.dumps(
            {
                "required_privilege": detail.get("required_privilege"),
                "account_role": detail.get("account_role"),
                "admin_access": detail.get("admin_access"),
            },
            sort_keys=True,
        )
    checks.append(support_result)

    return checks


def _prefix_check_results(results: list[CheckResult], *, prefix: str) -> list[CheckResult]:
    return [replace(result, name=f"{prefix}{result.name}") for result in results]


def _check_account_switch_flow(
    *,
    backend_url: str,
    client: SmokeClient,
    current_email: str,
    switch_email: str,
    switch_code: str,
    interactive: bool,
    learner_email: str,
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    current_auth_result, current_auth_payload = _check_auth_me_payload(backend_url=backend_url, client=client)
    current_user = _extract_authenticated_user(current_auth_payload) if current_auth_result.ok else None
    if not isinstance(current_user, dict):
        checks.append(
            CheckResult(
                name="account_switch_current_auth",
                url=current_auth_result.url,
                ok=False,
                status_code=current_auth_result.status_code,
                detail="Current learner session was not available before account switching checks.",
            )
        )
        return checks

    authenticated_email = str(current_user.get("email") or "").strip().lower()
    if authenticated_email != current_email.strip().lower():
        checks.append(
            CheckResult(
                name="account_switch_current_auth",
                url=current_auth_result.url,
                ok=False,
                status_code=current_auth_result.status_code,
                detail=(
                    f"Expected the current learner session to belong to {current_email}, "
                    f"but auth/me reported {current_user.get('email')!r}."
                ),
            )
        )
        return checks

    checks.append(
        CheckResult(
            name="account_switch_current_auth",
            url=current_auth_result.url,
            ok=True,
            status_code=current_auth_result.status_code,
            detail=json.dumps(
                {
                    "email": current_user.get("email"),
                    "account_role": current_user.get("account_role"),
                    "plan_tier": current_user.get("plan_tier"),
                },
                sort_keys=True,
            ),
        )
    )

    logout_result, logout_payload = _json_check_result(
        name="account_switch_logout",
        url=_join_url(backend_url, "/api/auth/logout"),
        method="POST",
        client=client,
        required_keys=("success",),
    )
    if logout_result.ok and isinstance(logout_payload, dict):
        logout_result.detail = json.dumps({"success": bool(logout_payload.get("success"))}, sort_keys=True)
    checks.append(logout_result)

    cleared_result = _check_json_endpoint(
        name="account_switch_auth_me_cleared",
        url=_join_url(backend_url, "/api/auth/me"),
        client=client,
        expected_status=401,
        required_key="detail",
    )
    checks.append(cleared_result)
    if not logout_result.ok or not cleared_result.ok:
        return checks

    otp_result, dev_otp_code = _check_otp_request(backend_url=backend_url, email=switch_email, client=client)
    otp_result.name = "account_switch_otp_request"
    checks.append(otp_result)
    if not otp_result.ok:
        return checks

    resolved_code = _resolve_otp_code(
        configured_code=switch_code,
        dev_otp_code=dev_otp_code,
        interactive=interactive,
    )
    if not resolved_code:
        checks.append(
            CheckResult(
                name="account_switch_verify_otp",
                url=_join_url(backend_url, "/api/auth/verify-otp"),
                ok=False,
                status_code=None,
                detail="Account-switch OTP request succeeded, but no OTP code was available for the second learner account.",
            )
        )
        return checks

    verify_result = _check_auth_verify(backend_url=backend_url, email=switch_email, code=resolved_code, client=client)
    verify_result.name = "account_switch_verify_otp"
    checks.append(verify_result)
    if not verify_result.ok:
        return checks

    switch_auth_result, switch_auth_payload = _check_auth_me_payload(backend_url=backend_url, client=client)
    switch_user = _extract_authenticated_user(switch_auth_payload) if switch_auth_result.ok else None
    if not isinstance(switch_user, dict):
        checks.append(
            CheckResult(
                name="account_switch_auth_me",
                url=switch_auth_result.url,
                ok=False,
                status_code=switch_auth_result.status_code,
                detail="Second learner auth payload was not available after account switching.",
            )
        )
        return checks

    switched_email = str(switch_user.get("email") or "").strip().lower()
    if switched_email != switch_email.strip().lower() or switched_email == current_email.strip().lower():
        checks.append(
            CheckResult(
                name="account_switch_auth_me",
                url=switch_auth_result.url,
                ok=False,
                status_code=switch_auth_result.status_code,
                detail=(
                    f"Expected account switch to land on {switch_email}, "
                    f"but auth/me reported {switch_user.get('email')!r}."
                ),
            )
        )
        return checks

    checks.append(
        CheckResult(
            name="account_switch_auth_me",
            url=switch_auth_result.url,
            ok=True,
            status_code=switch_auth_result.status_code,
            detail=json.dumps(
                {
                    "email": switch_user.get("email"),
                    "account_role": switch_user.get("account_role"),
                    "plan_tier": switch_user.get("plan_tier"),
                },
                sort_keys=True,
            ),
        )
    )

    billing_result = _check_billing_account_state(backend_url=backend_url, auth_payload=switch_auth_payload)
    checks.append(replace(billing_result, name="account_switch_billing_state"))

    learner_admin_checks = _check_learner_admin_separation(
        backend_url=backend_url,
        client=client,
        learner_email=learner_email or switch_email,
    )
    checks.extend(_prefix_check_results(learner_admin_checks, prefix="account_switch_"))
    checks.extend(_prefix_check_results(_check_logout(backend_url=backend_url, client=client), prefix="account_switch_"))
    return checks


def _check_admin_authenticated_flow(
    *,
    backend_url: str,
    client: SmokeClient,
    learner_email: str,
    require_provider_validation_ready: bool = False,
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    auth_result, auth_payload = _check_auth_me_payload(backend_url=backend_url, client=client)
    if auth_result.ok and isinstance(auth_payload, dict):
        user = _extract_authenticated_user(auth_payload) or {}
        admin_access = user.get("admin_access") if isinstance(user, dict) else {}
        if not isinstance(admin_access, dict) or not admin_access.get("is_admin"):
            auth_result = CheckResult(
                name="admin_auth_me",
                url=auth_result.url,
                ok=False,
                status_code=auth_result.status_code,
                detail="Authenticated admin smoke account did not report admin access.",
            )
        else:
            auth_result = CheckResult(
                name="admin_auth_me",
                url=auth_result.url,
                ok=True,
                status_code=auth_result.status_code,
                detail=json.dumps(
                    {
                        "role": admin_access.get("role"),
                        "privileges": admin_access.get("privileges"),
                        "email": user.get("email"),
                    },
                    sort_keys=True,
                ),
            )
    checks.append(auth_result)
    if not auth_result.ok:
        return checks

    checks.append(
        _check_json_endpoint(
            name="admin_ops_overview",
            url=_join_url(backend_url, "/api/admin/ops/overview"),
            client=client,
            required_key="checked_at",
        )
    )

    billing_result, billing_payload = _json_check_result(
        name="admin_billing_overview",
        url=_join_url(backend_url, "/api/admin/ops/billing"),
        method="GET",
        client=client,
        required_keys=("checked_at", "provider", "validation", "webhook", "subscriptions"),
    )
    if billing_result.ok and isinstance(billing_payload, dict):
        provider = billing_payload.get("provider") if isinstance(billing_payload.get("provider"), dict) else {}
        validation = billing_payload.get("validation") if isinstance(billing_payload.get("validation"), dict) else {}
        webhook = billing_payload.get("webhook") if isinstance(billing_payload.get("webhook"), dict) else {}
        subscriptions = billing_payload.get("subscriptions") if isinstance(billing_payload.get("subscriptions"), dict) else {}
        validation_summary = {
            "provider": provider.get("provider_name"),
            "validation_state": validation.get("validation_state"),
            "provider_config_ready": validation.get("provider_config_ready"),
            "checkout_ready": validation.get("checkout_ready"),
            "webhook_ready": validation.get("webhook_ready"),
            "subscription_sync_ready": validation.get("subscription_sync_ready"),
            "blocker_count": validation.get("blocker_count"),
            "webhook_failed_count": webhook.get("failed_count"),
            "attention_account_count": subscriptions.get("attention_account_count"),
        }
        billing_result.detail = json.dumps(validation_summary, sort_keys=True)
        if require_provider_validation_ready and (
            str(validation.get("validation_state") or "").strip().lower() != "ready"
            or int(validation.get("blocker_count") or 0) > 0
            or not bool(validation.get("provider_config_ready"))
            or not bool(validation.get("checkout_ready"))
            or not bool(validation.get("webhook_ready"))
            or not bool(validation.get("subscription_sync_ready"))
        ):
            billing_result = CheckResult(
                name="admin_billing_overview",
                url=billing_result.url,
                ok=False,
                status_code=billing_result.status_code,
                detail=f"Provider validation is not launch-ready: {json.dumps(validation_summary, sort_keys=True)}",
            )
    checks.append(billing_result)

    if learner_email.strip():
        support_result, support_payload = _json_check_result(
            name="admin_support_lookup",
            url=_query_url(backend_url, "/api/admin/ops/support", {"email": learner_email}),
            method="GET",
            client=client,
            required_keys=("user", "billing", "media", "quotas", "investigation_cues"),
        )
        if support_result.ok and isinstance(support_payload, dict):
            support_user = support_payload.get("user") if isinstance(support_payload.get("user"), dict) else {}
            support_billing = support_payload.get("billing") if isinstance(support_payload.get("billing"), dict) else {}
            if str(support_user.get("email") or "").strip().lower() != learner_email.strip().lower():
                support_result = CheckResult(
                    name="admin_support_lookup",
                    url=support_result.url,
                    ok=False,
                    status_code=support_result.status_code,
                    detail="Admin support lookup returned the wrong learner account.",
                )
            else:
                support_result.detail = json.dumps(
                    {
                        "learner_email": support_user.get("email"),
                        "plan_tier": support_user.get("plan_tier"),
                        "lifecycle_state": support_user.get("lifecycle_state"),
                        "provider": support_billing.get("provider_name"),
                        "suggested_next_step": support_billing.get("suggested_next_step"),
                    },
                    sort_keys=True,
                )
        checks.append(support_result)
    else:
        checks.append(
            _skipped_check(
                "admin_support_lookup",
                detail="No learner target email was configured for admin support lookup validation.",
            )
        )

    return checks


def _resolve_settings_persistence_target(*, resolved_target: ResolvedSmokeTarget) -> dict[str, str]:
    scenario = resolved_target.scenario
    preferred_exam = (
        str(scenario.expected_preferred_exam or "").strip()
        if scenario is not None
        else ""
    ) or str(resolved_target.exam or "").strip()
    preferred_subject = (
        str(scenario.expected_preferred_subject or "").strip()
        if scenario is not None
        else ""
    ) or str(resolved_target.subject or "").strip()
    current_exam = (
        str(scenario.expected_current_exam or "").strip()
        if scenario is not None
        else ""
    ) or str(resolved_target.exam or "").strip()
    current_subject = (
        str(scenario.expected_current_subject or "").strip()
        if scenario is not None
        else ""
    ) or str(resolved_target.subject or "").strip()
    return {
        "preferred_exam": preferred_exam,
        "preferred_subject": preferred_subject,
        "current_exam": current_exam,
        "current_subject": current_subject,
    }


def _check_settings_persistence(
    *,
    backend_url: str,
    client: SmokeClient,
    preferred_exam: str,
    preferred_subject: str,
    current_exam: str,
    current_subject: str,
) -> CheckResult:
    url = _join_url(backend_url, "/api/settings")
    expected = {
        "theme_preference": "light",
        "mentor_mode": "strict",
        "preferred_exam": preferred_exam,
        "preferred_subject": preferred_subject,
        "current_exam": current_exam,
        "current_subject": current_subject,
        "timezone": "Asia/Calcutta",
        "study_reminders_enabled": True,
        "marketing_emails_enabled": False,
        "progress_digest_frequency": "important_only",
        "billing_notifications_enabled": True,
    }
    update_result, update_payload = _json_check_result(
        name="settings_update",
        url=url,
        method="PUT",
        client=client,
        json_payload=expected,
        required_keys=(
            "theme_preference",
            "mentor_mode",
            "preferred_exam",
            "preferred_subject",
            "current_exam",
            "current_subject",
        ),
    )
    if not update_result.ok:
        return update_result

    get_result, get_payload = _json_check_result(
        name="settings_persistence",
        url=url,
        method="GET",
        client=client,
        required_keys=(
            "theme_preference",
            "mentor_mode",
            "preferred_exam",
            "preferred_subject",
            "current_exam",
            "current_subject",
        ),
    )
    if not get_result.ok:
        return get_result

    mismatches = {
        key: {"expected": value, "actual": get_payload.get(key)}
        for key, value in expected.items()
        if isinstance(get_payload, dict) and get_payload.get(key) != value
    }
    if mismatches:
        return CheckResult(name="settings_persistence", url=url, ok=False, status_code=get_result.status_code, detail=json.dumps(mismatches, sort_keys=True))
    return CheckResult(
        name="settings_persistence",
        url=url,
        ok=True,
        status_code=get_result.status_code,
        detail=json.dumps(
            {
                "preferred_exam": preferred_exam,
                "preferred_subject": preferred_subject,
                "current_exam": current_exam,
                "current_subject": current_subject,
                "mentor_mode": "strict",
            },
            sort_keys=True,
        ),
    )


def _check_profile_persistence(*, backend_url: str, client: SmokeClient) -> CheckResult:
    url = _join_url(backend_url, "/api/profile")
    expected = {
        "display_name": "Adhyantra Smoke Check",
        "bio": "Dedicated staging smoke account.",
        "locale": "en-IN",
    }
    update_result, _update_payload = _json_check_result(
        name="profile_update",
        url=url,
        method="PUT",
        client=client,
        json_payload=expected,
        required_keys=("display_name", "bio", "locale"),
    )
    if not update_result.ok:
        return update_result

    get_result, get_payload = _json_check_result(
        name="profile_persistence",
        url=url,
        method="GET",
        client=client,
        required_keys=("display_name", "bio", "locale"),
    )
    if not get_result.ok:
        return get_result

    mismatches = {
        key: {"expected": value, "actual": get_payload.get(key)}
        for key, value in expected.items()
        if isinstance(get_payload, dict) and get_payload.get(key) != value
    }
    if mismatches:
        return CheckResult(name="profile_persistence", url=url, ok=False, status_code=get_result.status_code, detail=json.dumps(mismatches, sort_keys=True))
    return CheckResult(name="profile_persistence", url=url, ok=True, status_code=get_result.status_code, detail="Profile update persisted for smoke account.")


def _check_tutor_slice(*, backend_url: str, client: SmokeClient, exam: str, subject: str, topic: str) -> CheckResult:
    result, payload = _json_check_result(
        name="tutor_explain",
        url=_join_url(backend_url, "/api/tutor/explain"),
        method="POST",
        client=client,
        required_keys=("subject", "exam", "topic", "simple_explanation", "key_points"),
        json_payload={
            "exam": exam,
            "subject": subject,
            "topic": topic,
            "lesson_mode": "mini_lesson",
        },
    )
    if result.ok and isinstance(payload, dict):
        key_points = payload.get("key_points") or []
        if payload.get("subject") != subject or payload.get("topic") != topic or not key_points:
            return CheckResult(name="tutor_explain", url=result.url, ok=False, status_code=result.status_code, detail="Tutor response was not grounded to requested subject/topic.")
        result.detail = json.dumps(
            {
                "subject": payload.get("subject"),
                "topic": payload.get("topic"),
                "lesson_mode": payload.get("lesson_mode"),
                "key_point_count": len(key_points),
            },
            sort_keys=True,
        )
    return result


def _check_quiz_and_progress_slice(*, backend_url: str, client: SmokeClient, exam: str, subject: str, topic: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    generate_url = _join_url(backend_url, "/api/test/generate")
    generate_result, quiz = _json_check_result(
        name="quiz_generate",
        url=generate_url,
        method="POST",
        client=client,
        required_keys=("quiz_id", "subject", "topic", "questions"),
        json_payload={
            "exam": exam,
            "subject": subject,
            "topic": topic,
            "question_count": 5,
            "quiz_mode": "practice",
        },
    )
    results.append(generate_result)
    if not generate_result.ok or not isinstance(quiz, dict):
        return results

    questions = quiz.get("questions") or []
    if len(questions) < 5:
        results[-1] = CheckResult(name="quiz_generate", url=generate_url, ok=False, status_code=generate_result.status_code, detail="Expected at least 5 quiz questions.")
        return results
    if any("correct_answer" in question or "explanation" in question for question in questions if isinstance(question, dict)):
        results[-1] = CheckResult(name="quiz_generate", url=generate_url, ok=False, status_code=generate_result.status_code, detail="Public quiz response leaked answer-only fields.")
        return results

    answers = [
        {
            "question_id": question["question_id"],
            "selected_answer": (question.get("options") or [""])[0],
        }
        for question in questions
        if isinstance(question, dict) and question.get("question_id") and question.get("options")
    ]
    submit_result, submit_payload = _json_check_result(
        name="quiz_submit",
        url=_join_url(backend_url, "/api/test/submit"),
        method="POST",
        client=client,
        required_keys=("subject", "topic", "score", "accuracy"),
        json_payload={
            "quiz_id": quiz.get("quiz_id"),
            "answers": answers,
            "exam": exam,
            "subject": subject,
        },
    )
    if submit_result.ok and isinstance(submit_payload, dict):
        submit_result.detail = json.dumps(
            {
                "subject": submit_payload.get("subject"),
                "topic": submit_payload.get("topic"),
                "score": submit_payload.get("score"),
                "accuracy": submit_payload.get("accuracy"),
            },
            sort_keys=True,
        )
    results.append(submit_result)
    if not submit_result.ok:
        return results

    progress_url = _query_url(backend_url, "/api/progress/summary", {"exam": exam, "subject": subject})
    progress_result, progress_payload = _json_check_result(
        name="progress_summary",
        url=progress_url,
        method="GET",
        client=client,
        required_keys=("subject", "recent_quizzes", "recommended_next_topic"),
    )
    if progress_result.ok and isinstance(progress_payload, dict):
        recent_quizzes = progress_payload.get("recent_quizzes") or []
        if progress_payload.get("subject") != subject or not recent_quizzes:
            progress_result = CheckResult(name="progress_summary", url=progress_url, ok=False, status_code=progress_result.status_code, detail="Progress summary did not reflect the smoke quiz activity.")
        else:
            progress_result.detail = json.dumps(
                {
                    "subject": progress_payload.get("subject"),
                    "recent_quiz_count": len(recent_quizzes),
                    "recommended_next_topic": progress_payload.get("recommended_next_topic"),
                },
                sort_keys=True,
            )
    results.append(progress_result)
    return results


def _check_plan_revision_coach_slice(*, backend_url: str, client: SmokeClient, exam: str, subject: str) -> list[CheckResult]:
    results: list[CheckResult] = []

    plan_url = _query_url(backend_url, "/api/plan/today", {"exam": exam, "subject": subject, "mentor_mode": "strict"})
    plan_result, plan_payload = _json_check_result(
        name="today_plan",
        url=plan_url,
        method="GET",
        client=client,
        required_keys=("exam", "subject", "focus_topic", "recommended_mode", "coach_note"),
    )
    if plan_result.ok and isinstance(plan_payload, dict):
        if plan_payload.get("exam") != exam or plan_payload.get("subject") != subject:
            plan_result = CheckResult(name="today_plan", url=plan_url, ok=False, status_code=plan_result.status_code, detail="Today plan did not preserve requested exam/subject scope.")
        else:
            plan_result.detail = json.dumps(
                {
                    "exam": plan_payload.get("exam"),
                    "subject": plan_payload.get("subject"),
                    "focus_topic": plan_payload.get("focus_topic"),
                    "recommended_mode": plan_payload.get("recommended_mode"),
                },
                sort_keys=True,
            )
    results.append(plan_result)

    revision_url = _query_url(backend_url, "/api/revision/due", {"exam": exam, "subject": subject})
    revision_result, revision_payload = _json_check_result(
        name="revision_due",
        url=revision_url,
        method="GET",
        client=client,
        required_keys=("exam", "subject", "overdue", "due_now", "due_soon", "total_due_count"),
    )
    if revision_result.ok and isinstance(revision_payload, dict):
        revision_buckets = (
            revision_payload.get("overdue"),
            revision_payload.get("due_now"),
            revision_payload.get("due_soon"),
        )
        if revision_payload.get("exam") != exam or revision_payload.get("subject") != subject or not all(isinstance(bucket, list) for bucket in revision_buckets):
            revision_result = CheckResult(name="revision_due", url=revision_url, ok=False, status_code=revision_result.status_code, detail="Revision due response did not preserve requested scope or bucket structure.")
        else:
            revision_result.detail = json.dumps(
                {
                    "exam": revision_payload.get("exam"),
                    "subject": revision_payload.get("subject"),
                    "total_due_count": revision_payload.get("total_due_count"),
                },
                sort_keys=True,
            )
    results.append(revision_result)

    coach_url = _query_url(backend_url, "/api/coach/summary", {"exam": exam, "subject": subject, "mentor_mode": "strict"})
    coach_result, coach_payload = _json_check_result(
        name="coach_summary",
        url=coach_url,
        method="GET",
        client=client,
        required_keys=("exam", "subject", "study_today", "coach_note", "accountability_summary", "warnings"),
    )
    if coach_result.ok and isinstance(coach_payload, dict):
        accountability = coach_payload.get("accountability_summary")
        accountability_subject = accountability.get("subject") if isinstance(accountability, dict) else None
        if coach_payload.get("exam") != exam or coach_payload.get("subject") != subject or accountability_subject != subject:
            coach_result = CheckResult(name="coach_summary", url=coach_url, ok=False, status_code=coach_result.status_code, detail="Coach summary did not preserve requested exam/subject/accountability scope.")
        else:
            coach_result.detail = json.dumps(
                {
                    "exam": coach_payload.get("exam"),
                    "subject": coach_payload.get("subject"),
                    "study_today": coach_payload.get("study_today"),
                    "warning_count": len(coach_payload.get("warnings") or []),
                },
                sort_keys=True,
            )
    results.append(coach_result)

    return results


def _check_scenario_auth_context(*, backend_url: str, client: SmokeClient, scenario: DemoSmokeScenarioSeed) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_auth_context",
        url=_join_url(backend_url, "/api/auth/me"),
        method="GET",
        client=client,
        required_keys=("authenticated", "settings"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    settings_payload = payload.get("settings")
    if not isinstance(settings_payload, dict):
        return CheckResult(
            name="scenario_auth_context",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail="Authenticated settings payload was not available for scenario checks.",
        )

    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(
        mismatches,
        field="preferred_exam",
        expected=scenario.expected_preferred_exam,
        actual=settings_payload.get("preferred_exam"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="preferred_subject",
        expected=scenario.expected_preferred_subject,
        actual=settings_payload.get("preferred_subject"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="current_exam",
        expected=scenario.expected_current_exam,
        actual=settings_payload.get("current_exam"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="current_subject",
        expected=scenario.expected_current_subject,
        actual=settings_payload.get("current_subject"),
    )
    if mismatches:
        return CheckResult(
            name="scenario_auth_context",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_auth_context",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            current_exam=settings_payload.get("current_exam"),
            current_subject=settings_payload.get("current_subject"),
            preferred_exam=settings_payload.get("preferred_exam"),
            preferred_subject=settings_payload.get("preferred_subject"),
        ),
    )


def _check_scenario_progress_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_progress_baseline",
        url=_join_url(backend_url, "/api/progress/summary"),
        method="GET",
        client=client,
        required_keys=("exam", "subject", "content_subject", "recommended_mode", "accountability_summary", "recent_quizzes"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    accountability = payload.get("accountability_summary")
    motivation = accountability.get("motivation_summary") if isinstance(accountability, dict) else None
    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(mismatches, field="exam", expected=scenario.expected_current_exam, actual=payload.get("exam"))
    _append_scenario_mismatch(mismatches, field="subject", expected=scenario.expected_current_subject, actual=payload.get("subject"))
    _append_scenario_mismatch(
        mismatches,
        field="content_subject",
        expected=scenario.expected_content_subject,
        actual=payload.get("content_subject"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="recommended_mode",
        expected=scenario.expected_recommended_mode,
        actual=payload.get("recommended_mode"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="warning_level",
        expected=scenario.expected_warning_level,
        actual=accountability.get("warning_level") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="consistency_status",
        expected=scenario.expected_consistency_status,
        actual=accountability.get("consistency_status") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="missed_revision_signal",
        expected=scenario.expected_missed_revision_signal,
        actual=accountability.get("missed_revision_signal") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="motivation_state",
        expected=scenario.expected_motivation_state,
        actual=motivation.get("motivation_state") if isinstance(motivation, dict) else None,
    )
    if mismatches:
        return CheckResult(
            name="scenario_progress_baseline",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_progress_baseline",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            exam=payload.get("exam"),
            subject=payload.get("subject"),
            content_subject=payload.get("content_subject"),
            recommended_mode=payload.get("recommended_mode"),
            warning_level=accountability.get("warning_level") if isinstance(accountability, dict) else None,
            recent_quiz_count=len(payload.get("recent_quizzes") or []),
        ),
    )


def _check_scenario_plan_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_plan_baseline",
        url=_join_url(backend_url, "/api/plan/today"),
        method="GET",
        client=client,
        required_keys=("exam", "subject", "content_subject", "focus_topic", "recommended_mode", "coach_note"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(mismatches, field="exam", expected=scenario.expected_current_exam, actual=payload.get("exam"))
    _append_scenario_mismatch(mismatches, field="subject", expected=scenario.expected_current_subject, actual=payload.get("subject"))
    _append_scenario_mismatch(
        mismatches,
        field="content_subject",
        expected=scenario.expected_content_subject,
        actual=payload.get("content_subject"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="recommended_mode",
        expected=scenario.expected_recommended_mode,
        actual=payload.get("recommended_mode"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="focus_topic",
        expected=scenario.expected_plan_focus_topic,
        actual=payload.get("focus_topic"),
    )
    if mismatches:
        return CheckResult(
            name="scenario_plan_baseline",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_plan_baseline",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            exam=payload.get("exam"),
            subject=payload.get("subject"),
            focus_topic=payload.get("focus_topic"),
            recommended_mode=payload.get("recommended_mode"),
            plan_mode=payload.get("plan_mode"),
        ),
    )


def _check_scenario_revision_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_revision_baseline",
        url=_join_url(backend_url, "/api/revision/due"),
        method="GET",
        client=client,
        required_keys=("exam", "subject", "content_subject", "overdue", "due_now", "due_soon", "total_due_count"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    total_due_count = payload.get("total_due_count")
    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(mismatches, field="exam", expected=scenario.expected_current_exam, actual=payload.get("exam"))
    _append_scenario_mismatch(mismatches, field="subject", expected=scenario.expected_current_subject, actual=payload.get("subject"))
    _append_scenario_mismatch(
        mismatches,
        field="content_subject",
        expected=scenario.expected_content_subject,
        actual=payload.get("content_subject"),
    )
    if scenario.expected_revision_due_min is not None and (not isinstance(total_due_count, int) or total_due_count < scenario.expected_revision_due_min):
        mismatches["revision_due_min"] = {
            "expected_at_least": scenario.expected_revision_due_min,
            "actual": total_due_count,
        }
    if scenario.expected_revision_due_max is not None and (not isinstance(total_due_count, int) or total_due_count > scenario.expected_revision_due_max):
        mismatches["revision_due_max"] = {
            "expected_at_most": scenario.expected_revision_due_max,
            "actual": total_due_count,
        }
    if mismatches:
        return CheckResult(
            name="scenario_revision_baseline",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_revision_baseline",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            exam=payload.get("exam"),
            subject=payload.get("subject"),
            content_subject=payload.get("content_subject"),
            total_due_count=total_due_count,
        ),
    )


def _check_scenario_coach_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_coach_baseline",
        url=_join_url(backend_url, "/api/coach/summary"),
        method="GET",
        client=client,
        required_keys=("exam", "subject", "content_subject", "study_today", "recommended_mode", "accountability_summary", "warnings"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    accountability = payload.get("accountability_summary")
    motivation = accountability.get("motivation_summary") if isinstance(accountability, dict) else None
    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(mismatches, field="exam", expected=scenario.expected_current_exam, actual=payload.get("exam"))
    _append_scenario_mismatch(mismatches, field="subject", expected=scenario.expected_current_subject, actual=payload.get("subject"))
    _append_scenario_mismatch(
        mismatches,
        field="content_subject",
        expected=scenario.expected_content_subject,
        actual=payload.get("content_subject"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="recommended_mode",
        expected=scenario.expected_recommended_mode,
        actual=payload.get("recommended_mode"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="study_today",
        expected=scenario.expected_plan_focus_topic,
        actual=payload.get("study_today"),
    )
    _append_scenario_mismatch(
        mismatches,
        field="warning_level",
        expected=scenario.expected_warning_level,
        actual=accountability.get("warning_level") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="consistency_status",
        expected=scenario.expected_consistency_status,
        actual=accountability.get("consistency_status") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="missed_revision_signal",
        expected=scenario.expected_missed_revision_signal,
        actual=accountability.get("missed_revision_signal") if isinstance(accountability, dict) else None,
    )
    _append_scenario_mismatch(
        mismatches,
        field="motivation_state",
        expected=scenario.expected_motivation_state,
        actual=motivation.get("motivation_state") if isinstance(motivation, dict) else None,
    )
    if mismatches:
        return CheckResult(
            name="scenario_coach_baseline",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_coach_baseline",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            exam=payload.get("exam"),
            subject=payload.get("subject"),
            study_today=payload.get("study_today"),
            recommended_mode=payload.get("recommended_mode"),
            warning_level=accountability.get("warning_level") if isinstance(accountability, dict) else None,
        ),
    )


def _check_scenario_history_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> CheckResult:
    result, payload = _json_check_result(
        name="scenario_history_baseline",
        url=_join_url(backend_url, "/api/progress/history"),
        method="GET",
        client=client,
        required_keys=("exam", "subject", "content_subject", "history"),
    )
    if not result.ok or not isinstance(payload, dict):
        return result

    history = payload.get("history")
    mismatches: dict[str, dict[str, Any]] = {}
    _append_scenario_mismatch(mismatches, field="exam", expected=scenario.expected_current_exam, actual=payload.get("exam"))
    _append_scenario_mismatch(mismatches, field="subject", expected=scenario.expected_current_subject, actual=payload.get("subject"))
    _append_scenario_mismatch(
        mismatches,
        field="content_subject",
        expected=scenario.expected_content_subject,
        actual=payload.get("content_subject"),
    )
    if not isinstance(history, list):
        mismatches["history"] = {"expected": "list", "actual": type(history).__name__}
    else:
        history_count = len(history)
        if scenario.expected_history_count_min is not None and history_count < scenario.expected_history_count_min:
            mismatches["history_count_min"] = {
                "expected_at_least": scenario.expected_history_count_min,
                "actual": history_count,
            }
        if scenario.expected_history_count_max is not None and history_count > scenario.expected_history_count_max:
            mismatches["history_count_max"] = {
                "expected_at_most": scenario.expected_history_count_max,
                "actual": history_count,
            }
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                mismatches[f"history[{index}]"] = {"expected": "dict", "actual": type(item).__name__}
                continue
            if scenario.expected_current_exam is not None and item.get("exam") != scenario.expected_current_exam:
                mismatches[f"history[{index}].exam"] = {
                    "expected": scenario.expected_current_exam,
                    "actual": item.get("exam"),
                }
            if scenario.expected_current_subject is not None and item.get("subject") != scenario.expected_current_subject:
                mismatches[f"history[{index}].subject"] = {
                    "expected": scenario.expected_current_subject,
                    "actual": item.get("subject"),
                }
    if mismatches:
        return CheckResult(
            name="scenario_history_baseline",
            url=result.url,
            ok=False,
            status_code=result.status_code,
            detail=json.dumps(mismatches, sort_keys=True),
        )

    return CheckResult(
        name="scenario_history_baseline",
        url=result.url,
        ok=True,
        status_code=result.status_code,
        detail=_scenario_detail(
            scenario=scenario.key,
            exam=payload.get("exam"),
            subject=payload.get("subject"),
            content_subject=payload.get("content_subject"),
            history_count=len(history),
        ),
    )


def _check_scenario_baseline(
    *,
    backend_url: str,
    client: SmokeClient,
    scenario: DemoSmokeScenarioSeed,
) -> list[CheckResult]:
    return [
        _check_scenario_auth_context(backend_url=backend_url, client=client, scenario=scenario),
        _check_scenario_progress_baseline(backend_url=backend_url, client=client, scenario=scenario),
        _check_scenario_plan_baseline(backend_url=backend_url, client=client, scenario=scenario),
        _check_scenario_revision_baseline(backend_url=backend_url, client=client, scenario=scenario),
        _check_scenario_coach_baseline(backend_url=backend_url, client=client, scenario=scenario),
        _check_scenario_history_baseline(backend_url=backend_url, client=client, scenario=scenario),
    ]


def _check_logout(*, backend_url: str, client: SmokeClient) -> list[CheckResult]:
    results: list[CheckResult] = []
    logout_result, payload = _json_check_result(
        name="auth_logout",
        url=_join_url(backend_url, "/api/auth/logout"),
        method="POST",
        client=client,
        required_keys=("success",),
    )
    if logout_result.ok and isinstance(payload, dict):
        logout_result.detail = json.dumps({"success": bool(payload.get("success"))}, sort_keys=True)
    results.append(logout_result)

    me_after_logout = _check_json_endpoint(
        name="auth_me_after_logout",
        url=_join_url(backend_url, "/api/auth/me"),
        client=client,
        expected_status=401,
        required_key="detail",
    )
    results.append(me_after_logout)
    return results


def _readiness_reports_secure_cookies(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary")
    if isinstance(summary, dict) and "secure_session_cookies" in summary:
        return bool(summary.get("secure_session_cookies"))
    runtime = payload.get("runtime")
    security = runtime.get("security") if isinstance(runtime, dict) else None
    if isinstance(security, dict) and "secure_session_cookies" in security:
        return bool(security.get("secure_session_cookies"))
    return False


def _check_session_cookie_transport(*, backend_url: str, readiness_payload: Any, auth_requested: bool) -> tuple[CheckResult | None, bool]:
    if not auth_requested:
        return None, True
    if not _readiness_reports_secure_cookies(readiness_payload):
        return None, True

    scheme = parse.urlparse(backend_url).scheme.lower()
    if scheme == "https":
        return CheckResult(
            name="session_cookie_transport",
            url=backend_url,
            ok=True,
            status_code=None,
            detail="Authenticated smoke will use HTTPS, so Secure session cookies can round-trip.",
        ), True

    return CheckResult(
        name="session_cookie_transport",
        url=backend_url,
        ok=False,
        status_code=None,
        detail="Backend readiness reports Secure session cookies, but the smoke backend URL is not HTTPS. Use the public HTTPS backend URL for authenticated staging smoke checks.",
    ), False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Adhyantra staging smoke checks against deployed URLs.")
    parser.add_argument(
        "--backend-url",
        default=_first_env("STAGING_BACKEND_URL", "BACKEND_PUBLIC_URL", default=DEFAULT_BACKEND_URL),
        help="Backend base URL. Defaults to STAGING_BACKEND_URL, BACKEND_PUBLIC_URL, or local backend.",
    )
    parser.add_argument(
        "--frontend-url",
        default=_first_env("STAGING_FRONTEND_URL", "FRONTEND_ORIGIN", default=DEFAULT_FRONTEND_URL),
        help="Frontend base URL. Defaults to STAGING_FRONTEND_URL, FRONTEND_ORIGIN, or local frontend.",
    )
    parser.add_argument(
        "--otp-email",
        default=_first_env("STAGING_SMOKE_EMAIL"),
        help="Optional smoke account email. Required for authenticated product-flow checks.",
    )
    parser.add_argument(
        "--otp-code",
        default=_first_env("STAGING_SMOKE_OTP_CODE"),
        help="Optional OTP code for the latest requested smoke login. Prefer --interactive-otp for real staging.",
    )
    parser.add_argument(
        "--support-target-email",
        default=_first_env("STAGING_SMOKE_SUPPORT_TARGET_EMAIL"),
        help="Optional learner email used for admin support lookup checks. Defaults to the learner smoke email when available.",
    )
    parser.add_argument(
        "--switch-otp-email",
        default=_first_env("STAGING_SMOKE_SWITCH_EMAIL"),
        help="Optional second learner email used to validate same-browser account/session switching after the main learner flow.",
    )
    parser.add_argument(
        "--switch-otp-code",
        default=_first_env("STAGING_SMOKE_SWITCH_OTP_CODE"),
        help="Optional OTP code for the second learner account used during session-switch checks.",
    )
    parser.add_argument(
        "--interactive-otp",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_INTERACTIVE_OTP", False),
        help="Prompt for the OTP after requesting it.",
    )
    parser.add_argument(
        "--switch-interactive-otp",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_SWITCH_INTERACTIVE_OTP", False),
        help="Prompt for the second learner OTP after requesting it for same-browser account switching checks.",
    )
    parser.add_argument(
        "--require-auth-flow",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_REQUIRE_AUTH_FLOW", False),
        help="Fail if OTP verification and authenticated product-flow checks cannot run.",
    )
    parser.add_argument(
        "--require-switch-flow",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_REQUIRE_SWITCH_FLOW", False),
        help="Fail if same-browser learner account switching cannot run when a second learner smoke email is configured.",
    )
    parser.add_argument(
        "--admin-otp-email",
        default=_first_env("STAGING_SMOKE_ADMIN_EMAIL"),
        help="Optional admin smoke account email. When set, the smoke runner validates real admin access on internal ops routes.",
    )
    parser.add_argument(
        "--admin-otp-code",
        default=_first_env("STAGING_SMOKE_ADMIN_OTP_CODE"),
        help="Optional admin OTP code for the latest requested admin smoke login.",
    )
    parser.add_argument(
        "--admin-interactive-otp",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_ADMIN_INTERACTIVE_OTP", False),
        help="Prompt for the admin OTP after requesting it.",
    )
    parser.add_argument(
        "--require-admin-flow",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_REQUIRE_ADMIN_FLOW", False),
        help="Fail if admin-authenticated validation cannot run.",
    )
    parser.add_argument(
        "--require-provider-validation-ready",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_REQUIRE_PROVIDER_VALIDATION_READY", False),
        help="Fail if admin billing ops does not report provider config, checkout, webhook, and sync as launch-ready.",
    )
    parser.add_argument(
        "--check-billing-flow",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_CHECK_BILLING_FLOW", False),
        help="Attempt real learner billing actions when the authenticated learner account reports they are ready.",
    )
    parser.add_argument(
        "--require-billing-flow",
        action="store_true",
        default=_env_bool("STAGING_SMOKE_REQUIRE_BILLING_FLOW", False),
        help="Fail if real learner billing-action validation cannot run when billing flow checks are requested.",
    )
    parser.add_argument("--skip-product-flow", action="store_true", help="Skip settings/profile/tutor/quiz/progress/plan/revision/coach checks after login.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(_first_env("STAGING_SMOKE_TIMEOUT_SECONDS", default="10")),
        help="Per-request timeout in seconds.",
    )
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend /auth check.")
    parser.add_argument(
        "--scenario",
        default=_first_env("STAGING_SMOKE_SCENARIO"),
        help=(
            "Optional deterministic smoke scenario key. "
            f"Available scenarios: {', '.join(demo_smoke_scenario_keys())}. "
            "When set, the smoke runner uses the scenario's demo account and baseline exam context unless explicitly overridden on the CLI."
        ),
    )
    parser.add_argument("--exam", default=_first_env("STAGING_SMOKE_EXAM", default="upsc"), help="Exam code used for product-flow checks.")
    parser.add_argument("--subject", default=_first_env("STAGING_SMOKE_SUBJECT", default="polity"), help="Subject used for product-flow checks.")
    parser.add_argument("--topic", default=_first_env("STAGING_SMOKE_TOPIC", default="Fundamental Rights"), help="Topic used for tutor/quiz checks.")
    return parser


def _skipped_check(name: str, *, detail: str) -> CheckResult:
    return CheckResult(name=name, url="", ok=True, status_code=None, detail=f"SKIPPED: {detail}")


def _failed_check(name: str, *, detail: str) -> CheckResult:
    return CheckResult(name=name, url="", ok=False, status_code=None, detail=detail)


def main() -> int:
    argv = sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)
    backend_url = str(args.backend_url).strip().rstrip("/")
    frontend_url = str(args.frontend_url).strip().rstrip("/")
    timeout = max(float(args.timeout), 1.0)
    backend_client = SmokeClient(timeout=timeout)
    frontend_client = SmokeClient(timeout=timeout)
    admin_client = SmokeClient(timeout=timeout)
    try:
        resolved_target = _resolve_smoke_target(args, argv)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    smoke_email = resolved_target.otp_email
    admin_smoke_email = str(args.admin_otp_email or "").strip()
    switch_smoke_email = str(args.switch_otp_email or "").strip()
    support_target_email = str(args.support_target_email or "").strip() or smoke_email
    require_auth_flow = bool(args.require_auth_flow or resolved_target.scenario is not None)
    require_provider_validation_ready = bool(args.require_provider_validation_ready)
    require_admin_flow = bool(args.require_admin_flow or require_provider_validation_ready)
    require_switch_flow = bool(args.require_switch_flow)
    check_billing_flow = bool(args.check_billing_flow or args.require_billing_flow)
    require_billing_flow = bool(args.require_billing_flow)
    verification_hygiene = _build_verification_hygiene(
        backend_url=backend_url,
        resolved_target=resolved_target,
    )

    liveness_result = _check_json_endpoint(
        name="backend_liveness",
        url=_join_url(backend_url, "/health/live"),
        client=backend_client,
        required_key="status",
    )
    readiness_result, readiness_payload = _json_check_result(
        name="backend_readiness",
        url=_join_url(backend_url, "/health/ready"),
        method="GET",
        client=backend_client,
        required_keys=("ready",),
    )
    checks: list[CheckResult] = [
        liveness_result,
        readiness_result,
        _check_json_endpoint(
            name="auth_me_requires_session",
            url=_join_url(backend_url, "/api/auth/me"),
            client=backend_client,
            expected_status=401,
            required_key="detail",
        ),
    ]
    checks.extend(_check_admin_requires_auth(backend_url=backend_url, client=backend_client))

    if not args.skip_frontend:
        checks.append(_check_html_endpoint(name="frontend_auth", url=_join_url(frontend_url, "/auth"), client=frontend_client))
        checks.extend(_check_public_launch_routes(frontend_url=frontend_url, client=frontend_client))
        checks.extend(_check_learner_surface_cleanliness(frontend_url=frontend_url, client=frontend_client))

    session_transport_check, session_transport_ok = _check_session_cookie_transport(
        backend_url=backend_url,
        readiness_payload=readiness_payload,
        auth_requested=bool(smoke_email or require_auth_flow),
    )
    if session_transport_check is not None:
        checks.append(session_transport_check)

    auth_flow_checked = False
    product_flow_checked = False
    scenario_baseline_checked = False
    billing_state_checked = False
    billing_flow_checked = False
    admin_protection_checked = True
    learner_admin_separation_checked = False
    account_switch_checked = False
    admin_flow_checked = False
    provider_validation_checked = False
    if not smoke_email:
        if require_auth_flow:
            checks.append(_failed_check("auth_flow", detail="--otp-email or STAGING_SMOKE_EMAIL is required for authenticated smoke checks."))
        else:
            checks.append(_skipped_check("auth_flow", detail="No smoke email configured. Set STAGING_SMOKE_EMAIL to verify OTP/auth/product flows."))
        if switch_smoke_email:
            detail = "Same-browser account switching needs a primary learner smoke account first. Set --otp-email before using --switch-otp-email."
            checks.append(
                _failed_check("account_switch_flow", detail=detail)
                if require_switch_flow
                else _skipped_check("account_switch_flow", detail=detail)
            )
        elif require_switch_flow:
            checks.append(
                _failed_check(
                    "account_switch_flow",
                    detail="--switch-otp-email or STAGING_SMOKE_SWITCH_EMAIL is required when --require-switch-flow is enabled.",
                )
            )
    else:
        otp_result, dev_otp_code = _check_otp_request(backend_url=backend_url, email=smoke_email, client=backend_client)
        checks.append(otp_result)
        otp_code = _resolve_otp_code(configured_code=str(args.otp_code or ""), dev_otp_code=dev_otp_code, interactive=bool(args.interactive_otp))
        if otp_result.ok and not session_transport_ok:
            detail = "OTP request succeeded, but authenticated checks need an HTTPS backend URL because staging/prod cookies are Secure."
            checks.append(_failed_check("auth_flow", detail=detail) if require_auth_flow else _skipped_check("auth_flow", detail=detail))
        elif otp_result.ok and otp_code:
            verify_result = _check_auth_verify(backend_url=backend_url, email=smoke_email, code=otp_code, client=backend_client)
            checks.append(verify_result)
            auth_flow_checked = verify_result.ok
            if verify_result.ok:
                auth_me_result, auth_me_payload = _check_auth_me_payload(backend_url=backend_url, client=backend_client)
                if auth_me_result.ok and isinstance(auth_me_payload, dict):
                    auth_me_result.detail = json.dumps(
                        {
                            "authenticated": bool(auth_me_payload.get("authenticated")),
                            "preferred_exam": (auth_me_payload.get("settings") or {}).get("preferred_exam"),
                            "preferred_subject": (auth_me_payload.get("settings") or {}).get("preferred_subject"),
                        },
                        sort_keys=True,
                    )
                checks.append(auth_me_result)
                if auth_me_result.ok:
                    billing_state_result = _check_billing_account_state(backend_url=backend_url, auth_payload=auth_me_payload)
                    checks.append(billing_state_result)
                    billing_state_checked = billing_state_result.ok

                    learner_admin_checks = _check_learner_admin_separation(
                        backend_url=backend_url,
                        client=backend_client,
                        learner_email=support_target_email or smoke_email,
                    )
                    checks.extend(learner_admin_checks)
                    learner_admin_separation_checked = all(check.ok for check in learner_admin_checks)

                    if check_billing_flow:
                        user_payload = _extract_authenticated_user(auth_me_payload) or {}
                        billing_payload = user_payload.get("billing") if isinstance(user_payload, dict) else {}
                        lifecycle_payload = billing_payload.get("subscription_lifecycle") if isinstance(billing_payload, dict) else {}
                        lifecycle_state = (
                            str(lifecycle_payload.get("state") or "").strip().lower()
                            if isinstance(lifecycle_payload, dict)
                            else ""
                        )
                        checkout_ready = bool(billing_payload.get("checkout_ready")) if isinstance(billing_payload, dict) else False
                        portal_ready = bool(billing_payload.get("portal_ready")) if isinstance(billing_payload, dict) else False

                        if checkout_ready and lifecycle_state in {"free", "expired"}:
                            checkout_flow_result = _check_billing_checkout_start(backend_url=backend_url, client=backend_client)
                            checks.append(checkout_flow_result)
                            billing_flow_checked = checkout_flow_result.ok
                        elif portal_ready and lifecycle_state in {"active", "trialing", "canceling", "past_due"}:
                            portal_flow_result = _check_billing_portal_start(backend_url=backend_url, client=backend_client)
                            checks.append(portal_flow_result)
                            billing_flow_checked = portal_flow_result.ok
                        else:
                            detail = (
                                f"No live billing action was ready for lifecycle_state={lifecycle_state or 'unknown'} "
                                f"(checkout_ready={checkout_ready}, portal_ready={portal_ready})."
                            )
                            checks.append(
                                _failed_check("billing_flow", detail=detail)
                                if require_billing_flow
                                else _skipped_check("billing_flow", detail=detail)
                            )
                if resolved_target.scenario is not None:
                    scenario_checks = _check_scenario_baseline(
                        backend_url=backend_url,
                        client=backend_client,
                        scenario=resolved_target.scenario,
                    )
                    checks.extend(scenario_checks)
                    scenario_baseline_checked = all(check.ok for check in scenario_checks)
                if args.skip_product_flow:
                    checks.append(_skipped_check("product_flow", detail="Skipped by --skip-product-flow."))
                else:
                    settings_target = _resolve_settings_persistence_target(resolved_target=resolved_target)
                    checks.append(
                        _check_settings_persistence(
                            backend_url=backend_url,
                            client=backend_client,
                            preferred_exam=settings_target["preferred_exam"],
                            preferred_subject=settings_target["preferred_subject"],
                            current_exam=settings_target["current_exam"],
                            current_subject=settings_target["current_subject"],
                        )
                    )
                    checks.append(_check_profile_persistence(backend_url=backend_url, client=backend_client))
                    checks.append(
                        _check_tutor_slice(
                            backend_url=backend_url,
                            client=backend_client,
                            exam=resolved_target.exam,
                            subject=resolved_target.subject,
                            topic=resolved_target.topic,
                        )
                    )
                    checks.extend(
                        _check_quiz_and_progress_slice(
                            backend_url=backend_url,
                            client=backend_client,
                            exam=resolved_target.exam,
                            subject=resolved_target.subject,
                            topic=resolved_target.topic,
                        )
                    )
                    checks.extend(
                        _check_plan_revision_coach_slice(
                            backend_url=backend_url,
                            client=backend_client,
                            exam=resolved_target.exam,
                            subject=resolved_target.subject,
                        )
                    )
                    required_product_checks = {
                        "settings_persistence",
                        "profile_persistence",
                        "tutor_explain",
                        "quiz_generate",
                        "quiz_submit",
                        "progress_summary",
                        "today_plan",
                        "revision_due",
                        "coach_summary",
                    }
                    product_results = {check.name: check for check in checks if check.name in required_product_checks}
                    product_flow_checked = required_product_checks.issubset(product_results) and all(
                        check.ok for check in product_results.values()
                    )
                if not switch_smoke_email:
                    if require_switch_flow:
                        checks.append(
                            _failed_check(
                                "account_switch_flow",
                                detail="--switch-otp-email or STAGING_SMOKE_SWITCH_EMAIL is required when --require-switch-flow is enabled.",
                            )
                        )
                    checks.extend(_check_logout(backend_url=backend_url, client=backend_client))
                elif switch_smoke_email.strip().lower() == smoke_email.strip().lower():
                    detail = "Same-browser account-switch validation needs a second learner email that is different from the primary smoke account."
                    checks.append(
                        _failed_check("account_switch_flow", detail=detail)
                        if require_switch_flow
                        else _skipped_check("account_switch_flow", detail=detail)
                    )
                    checks.extend(_check_logout(backend_url=backend_url, client=backend_client))
                else:
                    switch_checks = _check_account_switch_flow(
                        backend_url=backend_url,
                        client=backend_client,
                        current_email=smoke_email,
                        switch_email=switch_smoke_email,
                        switch_code=str(args.switch_otp_code or ""),
                        interactive=bool(args.switch_interactive_otp),
                        learner_email=support_target_email or switch_smoke_email,
                    )
                    checks.extend(switch_checks)
                    account_switch_checked = all(check.ok for check in switch_checks)
        elif otp_result.ok:
            detail = "OTP request succeeded, but no OTP code was available. Use --interactive-otp or --otp-code to run authenticated checks."
            checks.append(_failed_check("auth_flow", detail=detail) if require_auth_flow else _skipped_check("auth_flow", detail=detail))

    if not admin_smoke_email:
        if require_admin_flow:
            checks.append(_failed_check("admin_flow", detail="--admin-otp-email or STAGING_SMOKE_ADMIN_EMAIL is required for admin-authenticated launch QA checks."))
        else:
            checks.append(_skipped_check("admin_flow", detail="No admin smoke email configured. Set STAGING_SMOKE_ADMIN_EMAIL to validate real admin access."))
    else:
        admin_otp_result, admin_dev_otp_code = _check_otp_request(backend_url=backend_url, email=admin_smoke_email, client=admin_client)
        admin_otp_result.name = "admin_otp_request"
        checks.append(admin_otp_result)
        admin_otp_code = _resolve_otp_code(
            configured_code=str(args.admin_otp_code or ""),
            dev_otp_code=admin_dev_otp_code,
            interactive=bool(args.admin_interactive_otp),
        )
        if admin_otp_result.ok and not session_transport_ok:
            detail = "Admin OTP request succeeded, but authenticated admin checks need an HTTPS backend URL because staging/prod cookies are Secure."
            checks.append(_failed_check("admin_flow", detail=detail) if require_admin_flow else _skipped_check("admin_flow", detail=detail))
        elif admin_otp_result.ok and admin_otp_code:
            admin_verify_result = _check_auth_verify(backend_url=backend_url, email=admin_smoke_email, code=admin_otp_code, client=admin_client)
            admin_verify_result.name = "admin_auth_verify_otp"
            checks.append(admin_verify_result)
            if admin_verify_result.ok:
                admin_checks = _check_admin_authenticated_flow(
                    backend_url=backend_url,
                    client=admin_client,
                    learner_email=support_target_email,
                    require_provider_validation_ready=require_provider_validation_ready,
                )
                checks.extend(admin_checks)
                admin_flow_checked = all(check.ok for check in admin_checks)
                provider_validation_checked = any(
                    check.name == "admin_billing_overview" and check.ok for check in admin_checks
                )
                checks.extend(_check_logout(backend_url=backend_url, client=admin_client))
        elif admin_otp_result.ok:
            detail = "Admin OTP request succeeded, but no admin OTP code was available. Use --admin-interactive-otp or --admin-otp-code to run admin checks."
            checks.append(_failed_check("admin_flow", detail=detail) if require_admin_flow else _skipped_check("admin_flow", detail=detail))

    admin_protection_checked = all(
        check.ok
        for check in checks
        if check.name in {"admin_ops_requires_auth", "admin_content_requires_auth"}
    )
    ok = all(check.ok for check in checks)
    launch_workflow = _build_launch_workflow_summary(
        checks=checks,
        skip_frontend=bool(args.skip_frontend),
        require_auth_flow=require_auth_flow,
        product_flow_requested=bool((smoke_email or require_auth_flow) and not args.skip_product_flow),
        scenario_requested=resolved_target.scenario is not None,
        check_billing_flow=check_billing_flow,
        require_switch_flow=require_switch_flow,
        admin_flow_requested=bool(admin_smoke_email or require_admin_flow or require_provider_validation_ready),
        require_provider_validation_ready=require_provider_validation_ready,
        auth_flow_checked=auth_flow_checked,
        product_flow_checked=product_flow_checked,
        scenario_baseline_checked=scenario_baseline_checked,
        learner_admin_separation_checked=learner_admin_separation_checked,
        account_switch_checked=account_switch_checked,
        admin_flow_checked=admin_flow_checked,
    )
    summary = {
        "ok": ok,
        "backend_url": backend_url,
        "frontend_url": None if args.skip_frontend else frontend_url,
        "otp_request_checked": bool(smoke_email),
        "auth_flow_checked": auth_flow_checked,
        "scenario": resolved_target.scenario.key if resolved_target.scenario is not None else None,
        "scenario_baseline_checked": scenario_baseline_checked,
        "product_flow_checked": product_flow_checked,
        "billing_state_checked": billing_state_checked,
        "billing_flow_checked": billing_flow_checked,
        "admin_protection_checked": admin_protection_checked,
        "learner_admin_separation_checked": learner_admin_separation_checked,
        "account_switch_checked": account_switch_checked,
        "admin_flow_checked": admin_flow_checked,
        "provider_validation_checked": provider_validation_checked,
        "launch_workflow": launch_workflow,
        "verification_hygiene": verification_hygiene,
        "exam": resolved_target.exam,
        "subject": resolved_target.subject,
        "topic": resolved_target.topic,
        "smoke_email": _mask_email(smoke_email),
        "switch_smoke_email": _mask_email(switch_smoke_email),
        "admin_smoke_email": _mask_email(admin_smoke_email),
        "support_target_email": _mask_email(support_target_email),
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
