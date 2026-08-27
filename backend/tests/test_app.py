from __future__ import annotations

from io import BytesIO
import json
import logging
from pathlib import Path
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / ".deps"))

from backend.config import Settings, get_active_sqlite_db_path, get_demo_seed_marker_path, get_settings
from backend.db import Base, get_db
from backend import main as main_module
from backend.main import app
from backend.models import AnalyticsEvent, BillingEventReceipt, ContentItem, EmailOtpChallenge, MediaRenderJob, Quiz, QuizAttempt, TopicProgress, TopicStudy, UsageConsumptionRecord, UserAccount, UserProfile, UserSession, UserSetting
from backend.services.analytics_service import build_analytics_foundation_snapshot, deserialize_analytics_event_metadata, record_analytics_event
from backend.services.demo_seed_service import (
    build_demo_learning_scenario_plan,
    default_demo_seed_anchor,
    list_demo_smoke_scenarios,
    seed_demo_accounts,
    seed_demo_scenarios,
)
from backend.services.lesson_export_service import build_audio_script_export_payload
from backend.services.mail_service import EmailDeliveryError, build_sign_in_otp_email
from backend.services.media_render_service import (
    cancel_media_render_job,
    claim_media_render_job_for_worker,
    cleanup_expired_media_render_artifacts,
    create_media_render_job,
    defer_claimable_media_render_jobs_for_pipeline_issue,
    get_media_render_job_dispatch_payload,
    get_media_render_job_for_user,
    mark_exhausted_retryable_media_render_jobs_failed,
    list_claimable_media_render_jobs,
    list_dispatchable_media_render_jobs,
    list_media_render_jobs_for_user,
    mark_media_render_artifact_cleanup_failed,
    mark_media_render_job_abandoned,
    mark_media_render_job_failed,
    mark_media_render_job_running,
    mark_media_render_job_retryable_failed,
    mark_media_render_job_succeeded,
    mark_stale_media_render_jobs_abandoned,
    recover_stale_queued_media_render_jobs,
    requeue_media_render_job,
    resolve_media_render_asset_path,
    serialize_media_render_job,
)
from backend.services.media_render_dispatch_service import (
    build_audio_render_dispatch_payload,
    build_video_render_dispatch_payload,
    run_media_render_worker_forever,
    run_media_render_worker_once,
    stop_media_render_dispatcher,
)
from backend.services.runtime_process_service import MEDIA_RENDER_WORKER_SERVICE_NAME, upsert_runtime_process_heartbeat
from backend.services.tts_service import render_audio_job_from_audio_script
from backend.services.progress_service import mark_topic_studied, record_attempt
from scripts.staging_smoke import ResolvedSmokeTarget, _resolve_settings_persistence_target
from scripts import local_db_tools


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = testing_session
    with TestClient(app) as test_client:
        stop_media_render_dispatcher(test_client.app)
        yield test_client
    app.dependency_overrides.clear()
    app.state.testing_session_factory = None
    Base.metadata.drop_all(bind=engine)


def get_private_quiz_questions(client: TestClient, quiz_id: int) -> list[dict]:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
        assert quiz is not None
        return json.loads(quiz.questions_json)
    finally:
        db.close()


def get_aligned_private_quiz_questions(client: TestClient, quiz: dict) -> list[dict]:
    private_questions = get_private_quiz_questions(client, quiz["quiz_id"])
    private_by_id = {question["question_id"]: question for question in private_questions}
    return [private_by_id[question["question_id"]] for question in quiz["questions"]]


def get_correct_answers(client: TestClient, quiz: dict) -> list[str]:
    return [question["correct_answer"] for question in get_aligned_private_quiz_questions(client, quiz)]


def get_mixed_answers(client: TestClient, quiz: dict, correct_indexes: set[int]) -> list[str]:
    aligned_private_questions = get_aligned_private_quiz_questions(client, quiz)
    answers: list[str] = []
    for index, (public_question, private_question) in enumerate(zip(quiz["questions"], aligned_private_questions, strict=False)):
        if index in correct_indexes:
            answers.append(private_question["correct_answer"])
        else:
            answers.append(next(option for option in public_question["options"] if option != private_question["correct_answer"]))
    return answers


def get_analytics_events(
    client: TestClient,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    event_name: str | None = None,
) -> list[AnalyticsEvent]:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        query = db.query(AnalyticsEvent)
        if user_id is not None:
            query = query.filter(AnalyticsEvent.user_id == user_id)
        if exam is not None:
            query = query.filter(AnalyticsEvent.exam == exam)
        if event_name is not None:
            query = query.filter(AnalyticsEvent.event_name == event_name)
        return query.order_by(AnalyticsEvent.created_at.asc(), AnalyticsEvent.id.asc()).all()
    finally:
        db.close()


def get_billing_event_receipts(
    client: TestClient,
    *,
    provider_name: str | None = None,
    provider_event_id: str | None = None,
) -> list[BillingEventReceipt]:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        query = db.query(BillingEventReceipt)
        if provider_name is not None:
            query = query.filter(BillingEventReceipt.provider_name == provider_name)
        if provider_event_id is not None:
            query = query.filter(BillingEventReceipt.provider_event_id == provider_event_id)
        return query.order_by(BillingEventReceipt.created_at.asc(), BillingEventReceipt.id.asc()).all()
    finally:
        db.close()


def wait_for_media_render_event_names(
    client: TestClient,
    *,
    user_id: int | None = None,
    exam: str | None = None,
    expected_event_names: list[str],
    timeout_seconds: float = 5.0,
) -> list[str]:
    deadline = time.monotonic() + max(float(timeout_seconds or 0), 0.1)
    last_event_names: list[str] = []
    while time.monotonic() < deadline:
        media_events = get_analytics_events(client, user_id=user_id, exam=exam)
        last_event_names = [event.event_name for event in media_events if event.feature_area == "media_render"]
        if last_event_names == expected_event_names:
            return last_event_names
        time.sleep(0.02)
    raise AssertionError(
        f"Media render events did not reach {expected_event_names!r} in time. Last events: {last_event_names!r}"
    )


def get_usage_consumption_records(
    client: TestClient,
    *,
    user_id: int | None = None,
    limit_key: str | None = None,
) -> list[UsageConsumptionRecord]:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        query = db.query(UsageConsumptionRecord)
        if user_id is not None:
            query = query.filter(UsageConsumptionRecord.user_id == user_id)
        if limit_key is not None:
            query = query.filter(UsageConsumptionRecord.limit_key == limit_key)
        return query.order_by(UsageConsumptionRecord.created_at.asc(), UsageConsumptionRecord.id.asc()).all()
    finally:
        db.close()


def wait_for_usage_consumption_count(
    client: TestClient,
    *,
    user_id: int | None = None,
    limit_key: str | None = None,
    expected_count: int,
    timeout_seconds: float = 5.0,
) -> list[UsageConsumptionRecord]:
    deadline = time.monotonic() + max(float(timeout_seconds or 0), 0.1)
    last_records: list[UsageConsumptionRecord] = []
    while time.monotonic() < deadline:
        last_records = get_usage_consumption_records(client, user_id=user_id, limit_key=limit_key)
        if len(last_records) == expected_count:
            return last_records
        time.sleep(0.02)
    raise AssertionError(
        f"Usage consumption count did not reach {expected_count} in time. Last count: {len(last_records)}"
    )


def wait_for_media_render_job_terminal_state(
    client: TestClient,
    *,
    job_id: int,
    timeout_seconds: float = 5.0,
) -> SimpleNamespace:
    session_factory = client.app.state.testing_session_factory
    deadline = time.monotonic() + max(float(timeout_seconds or 0), 0.1)
    last_state: str | None = None
    last_public_state: str | None = None
    while time.monotonic() < deadline:
        dispatcher = getattr(getattr(client, "app", None), "state", None)
        embedded_dispatcher = getattr(dispatcher, "media_render_dispatcher", None) if dispatcher is not None else None
        if not getattr(embedded_dispatcher, "is_running", False):
            run_media_render_worker_once(client.app.state.testing_session_factory)
        db = session_factory()
        try:
            job = (
                db.query(
                    MediaRenderJob.id,
                    MediaRenderJob.lifecycle_state,
                    MediaRenderJob.render_type,
                    MediaRenderJob.attempt_count,
                    MediaRenderJob.status_note,
                    MediaRenderJob.failure_code,
                )
                .filter(MediaRenderJob.id == job_id)
                .first()
            )
            if job is not None:
                last_state = str(job.lifecycle_state or "").strip().lower() or None
                if last_state in {"succeeded", "failed", "canceled"}:
                    status_path: str | None = None
                    if job.render_type == "audio":
                        status_path = f"/api/tutor/render/audio/{job.id}"
                    elif job.render_type in {"narrated_video", "slide_video"}:
                        status_path = f"/api/tutor/render/video/{job.id}"

                    if status_path:
                        status_response = client.get(status_path)
                        if status_response.status_code == 200:
                            last_public_state = str(status_response.json().get("lifecycle_state") or "").strip().lower() or None
                            expected_public_state = "failed" if last_state in {"failed", "canceled"} else last_state
                            if last_public_state != expected_public_state:
                                time.sleep(0.02)
                                continue

                    return SimpleNamespace(
                        id=job.id,
                        lifecycle_state=job.lifecycle_state,
                        render_type=job.render_type,
                        attempt_count=job.attempt_count,
                        status_note=job.status_note,
                        failure_code=job.failure_code,
                    )
        finally:
            db.close()
        time.sleep(0.02)

    raise AssertionError(
        f"Media render job {job_id} did not reach a terminal state in time. "
        f"Last state: {last_state!r}. Last public state: {last_public_state!r}"
    )


def normalize_test_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def create_attempt_record(
    client: TestClient,
    *,
    topic: str,
    score: int,
    total_questions: int = 5,
    difficulty: str = "medium",
    subject: str = "polity",
    chapter: str = "General",
    exam: str = "upsc",
    user_id: int | None = None,
) -> None:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        quiz = Quiz(
            user_id=user_id,
            exam=exam,
            topic=topic,
            chapter=chapter,
            subject=subject,
            difficulty=difficulty,
            question_count=total_questions,
            questions_json="[]",
        )
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
        record_attempt(
            db=db,
            quiz_id=quiz.id,
            topic=topic,
            difficulty=difficulty,
            answers=[f"Answer {index}" for index in range(total_questions)],
            score=score,
            total_questions=total_questions,
            incorrect_questions=[],
            weak_areas=[] if score == total_questions else [topic],
            next_recommendation="Review the topic once and try another quiz.",
            subject=subject,
            chapter=chapter,
            exam=exam,
            user_id=user_id,
        )
    finally:
        db.close()


def authenticate_test_user(
    client: TestClient,
    *,
    email: str = "learner@example.com",
    display_name: str = "Learner One",
) -> dict:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": email, "display_name": display_name},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()
    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200
    return verify_response.json()


def authenticate_premium_test_user(
    client: TestClient,
    *,
    email: str = "premium@example.com",
    display_name: str = "Premium Learner",
) -> dict:
    authenticate_test_user(client, email=email, display_name=display_name)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == email).first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "active"
        db.add(user)
        db.commit()
    finally:
        db.close()

    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    return current_user_response.json()


def grant_admin_role(
    client: TestClient,
    *,
    email: str,
    role: str = "content_admin",
    privileges: list[str] | None = None,
) -> dict:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == email).first()
        assert user is not None
        user.account_role = role
        user.admin_privileges_json = json.dumps(privileges or [])
        db.add(user)
        db.commit()
    finally:
        db.close()

    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    return current_user_response.json()


def test_phase35_auth_billing_overview_hides_unavailable_billing_actions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    authenticate_test_user(
        client,
        email="phase35-auth-billing-hidden@example.com",
        display_name="Phase 35 Billing Hidden",
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase35-auth-billing-hidden@example.com").first()
        assert user is not None
        user.subscription_customer_ref = "cus_hidden_phase35"
        db.add(user)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        auth_service,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="disabled",
            payment_premium_price_id="",
        ),
    )

    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    billing = current_user_response.json()["user"]["billing"]
    assert billing["checkout_ready"] is False
    assert billing["portal_ready"] is False


def test_phase35_auth_billing_overview_exposes_ready_actions_only_when_supported(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    authenticate_test_user(
        client,
        email="phase35-auth-billing-ready@example.com",
        display_name="Phase 35 Billing Ready",
    )

    monkeypatch.setattr(
        auth_service,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )

    initial_response = client.get("/api/auth/me")
    assert initial_response.status_code == 200
    initial_billing = initial_response.json()["user"]["billing"]
    assert initial_billing["checkout_ready"] is True
    assert initial_billing["portal_ready"] is False

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase35-auth-billing-ready@example.com").first()
        assert user is not None
        user.subscription_customer_ref = "cus_ready_phase35"
        db.add(user)
        db.commit()
    finally:
        db.close()

    updated_response = client.get("/api/auth/me")
    assert updated_response.status_code == 200
    updated_billing = updated_response.json()["user"]["billing"]
    assert updated_billing["checkout_ready"] is True
    assert updated_billing["portal_ready"] is True


def test_phase37_auth_billing_overview_keeps_razorpay_checkout_ready_but_hides_portal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    authenticate_test_user(
        client,
        email="phase37-auth-billing-razorpay@example.com",
        display_name="Phase 37 Billing Razorpay",
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase37-auth-billing-razorpay@example.com").first()
        assert user is not None
        user.subscription_customer_ref = "cust_razorpay_phase37"
        db.add(user)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        auth_service,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_test_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )

    response = client.get("/api/auth/me")
    assert response.status_code == 200
    billing = response.json()["user"]["billing"]
    assert billing["checkout_ready"] is True
    assert billing["portal_ready"] is False


def test_phase37_auth_billing_overview_hides_razorpay_checkout_during_payment_recovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    authenticate_test_user(
        client,
        email="phase37-auth-billing-razorpay-recovery@example.com",
        display_name="Phase 37 Billing Razorpay Recovery",
    )

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase37-auth-billing-razorpay-recovery@example.com").first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "past_due"
        user.subscription_customer_ref = "cust_razorpay_phase37_recovery"
        user.subscription_provider_ref = "sub_razorpay_phase37_recovery"
        user.subscription_price_id = "plan_premium_monthly"
        user.subscription_current_period_end = now + timedelta(days=5)
        db.add(user)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        auth_service,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_test_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )

    response = client.get("/api/auth/me")
    assert response.status_code == 200
    billing = response.json()["user"]["billing"]
    assert billing["subscription_lifecycle"]["state"] == "past_due"
    assert billing["checkout_ready"] is False
    assert billing["portal_ready"] is False


def test_phase35_checkout_route_creates_owned_premium_checkout_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_test_user(client, email="phase35-checkout@example.com", display_name="Phase 35 Checkout")
    user_id = auth["user"]["id"]
    captured_request: dict[str, Any] = {}

    class FakeProvider:
        def create_checkout_session(self, request):
            captured_request["request"] = request
            return SimpleNamespace(checkout_url="https://checkout.stripe.example/session/cs_test_phase35")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/checkout",
        json={
            "plan_tier": "premium",
            "return_path": "/settings",
            "source": "settings_account",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "redirect_required"
    assert body["plan_tier"] == "premium"
    assert body["checkout_url"] == "https://checkout.stripe.example/session/cs_test_phase35"
    assert body["return_path"] == "/settings"

    checkout_request = captured_request["request"]
    assert checkout_request.success_url == "https://app.adhyantra.example/settings?billing=success"
    assert checkout_request.cancel_url == "https://app.adhyantra.example/settings?billing=cancel"
    assert checkout_request.customer_ref is None
    assert checkout_request.customer_email == "phase35-checkout@example.com"
    assert checkout_request.client_reference_id == str(user_id)
    assert checkout_request.line_items[0].price_id == "price_premium_monthly"
    assert checkout_request.metadata["user_id"] == str(user_id)
    assert checkout_request.metadata["source"] == "settings_account"
    assert checkout_request.subscription_metadata["plan_tier"] == "premium"

    events = get_analytics_events(client, user_id=user_id, event_name="billing.checkout_started")
    assert len(events) == 1
    assert events[0].feature_area == "billing"
    metadata = deserialize_analytics_event_metadata(events[0])
    assert metadata["source"] == "settings_account"
    assert metadata["customer_ref_present"] is False


def test_phase35_checkout_route_reuses_existing_customer_reference(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.routes import account_billing_routes
    from backend.services import billing_service

    authenticate_test_user(client, email="phase35-customer@example.com", display_name="Phase 35 Customer")
    captured_request: dict[str, Any] = {}

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase35-customer@example.com").first()
        assert user is not None
        user.subscription_customer_ref = "cus_existing_123"
        db.add(user)
        db.commit()
    finally:
        db.close()

    class FakeProvider:
        def create_checkout_session(self, request):
            captured_request["request"] = request
            return SimpleNamespace(checkout_url="https://checkout.stripe.example/session/cs_existing_customer")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post("/api/account/billing/checkout", json={})

    assert response.status_code == 200
    checkout_request = captured_request["request"]
    assert checkout_request.customer_ref == "cus_existing_123"
    assert checkout_request.customer_email is None
    assert checkout_request.metadata["existing_customer_ref"] == "cus_existing_123"


def test_phase37_razorpay_checkout_route_creates_owned_subscription_and_persists_refs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_test_user(client, email="phase37-razorpay-checkout@example.com", display_name="Phase 37 Razorpay")
    user_id = auth["user"]["id"]
    captured_request: dict[str, Any] = {}

    class FakeProvider:
        def create_checkout_session(self, request):
            captured_request["request"] = request
            return SimpleNamespace(
                checkout_url="https://rzp.io/i/adhyantra-premium",
                customer_ref="cust_razorpay_phase37",
                subscription_ref="sub_razorpay_phase37",
            )

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_test_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/checkout",
        json={
            "plan_tier": "premium",
            "return_path": "/settings",
            "source": "settings_account",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "redirect_required"
    assert body["plan_tier"] == "premium"
    assert body["checkout_url"] == "https://rzp.io/i/adhyantra-premium"
    assert body["return_path"] == "/settings"

    checkout_request = captured_request["request"]
    assert checkout_request.customer_ref is None
    assert checkout_request.customer_email == "phase37-razorpay-checkout@example.com"
    assert checkout_request.customer_name == "Phase 37 Razorpay"
    assert checkout_request.client_reference_id == str(user_id)
    assert checkout_request.line_items[0].price_id == "plan_premium_monthly"
    assert checkout_request.metadata["user_id"] == str(user_id)
    assert checkout_request.subscription_metadata["plan_tier"] == "premium"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        assert user.subscription_customer_ref == "cust_razorpay_phase37"
        assert user.subscription_provider_ref == "sub_razorpay_phase37"
        assert user.subscription_price_id == "plan_premium_monthly"
        assert user.billing_email == "phase37-razorpay-checkout@example.com"
    finally:
        db.close()

    events = get_analytics_events(client, user_id=user_id, event_name="billing.checkout_started")
    assert len(events) == 1
    metadata = deserialize_analytics_event_metadata(events[0])
    assert metadata["source"] == "settings_account"
    assert metadata["customer_ref_present"] is True


def test_phase37_razorpay_checkout_route_blocks_payment_recovery_duplicates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_test_user(
        client,
        email="phase37-razorpay-recovery-checkout@example.com",
        display_name="Phase 37 Razorpay Recovery",
    )
    user_id = auth["user"]["id"]
    provider_calls = {"count": 0}

    class FakeProvider:
        def create_checkout_session(self, request):
            provider_calls["count"] += 1
            raise AssertionError("Checkout creation should be blocked before the provider is called.")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_test_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "past_due"
        user.subscription_customer_ref = "cust_razorpay_phase37_recovery_checkout"
        user.subscription_provider_ref = "sub_razorpay_phase37_recovery_checkout"
        user.subscription_price_id = "plan_premium_monthly"
        user.subscription_current_period_end = now + timedelta(days=4)
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/account/billing/checkout",
        json={
            "plan_tier": "premium",
            "return_path": "/settings",
            "source": "settings_account",
        },
    )

    assert response.status_code == 409
    assert "payment recovery" in response.json()["detail"].lower()
    assert provider_calls["count"] == 0

    events = get_analytics_events(client, user_id=user_id, event_name="billing.checkout_blocked")
    assert len(events) == 1
    metadata = deserialize_analytics_event_metadata(events[0])
    assert metadata["provider_name"] == "razorpay"
    assert metadata["outcome_code"] == "payment_recovery"
    assert metadata["subscription_ref_present"] is True


def test_phase35_active_premium_account_does_not_create_duplicate_checkout_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_premium_test_user(client, email="phase35-active@example.com", display_name="Phase 35 Active")
    user_id = auth["user"]["id"]
    provider_called = {"value": False}

    class FakeProvider:
        def create_checkout_session(self, request):
            provider_called["value"] = True
            raise AssertionError("Checkout provider should not be called for an already active premium account.")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post("/api/account/billing/checkout", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Premium is already active on this account."
    assert provider_called["value"] is False
    events = get_analytics_events(client, user_id=user_id, event_name="billing.checkout_blocked")
    assert len(events) == 1
    assert deserialize_analytics_event_metadata(events[0])["outcome_code"] == "already_active"


def test_phase35_checkout_route_fails_safely_when_checkout_is_not_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.routes import account_billing_routes

    auth = authenticate_test_user(client, email="phase35-unavailable@example.com", display_name="Phase 35 Unavailable")
    user_id = auth["user"]["id"]

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )

    response = client.post("/api/account/billing/checkout", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "Premium checkout is not available right now. Please try again later."
    events = get_analytics_events(client, user_id=user_id, event_name="billing.checkout_unavailable")
    assert len(events) == 1
    assert deserialize_analytics_event_metadata(events[0])["outcome_code"] == "missing_price_id"


def test_phase35_billing_portal_route_creates_owned_manage_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_premium_test_user(
        client,
        email="phase35-portal@example.com",
        display_name="Phase 35 Portal",
    )
    user_id = auth["user"]["id"]
    captured_request: dict[str, Any] = {}

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_customer_ref = "cus_portal_123"
        db.add(user)
        db.commit()
    finally:
        db.close()

    class FakeProvider:
        def create_customer_portal_session(self, request):
            captured_request["request"] = request
            return SimpleNamespace(portal_url="https://billing.stripe.example/session/bps_test_phase35")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/portal",
        json={
            "return_path": "/settings",
            "source": "settings_account",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "redirect_required"
    assert body["portal_url"] == "https://billing.stripe.example/session/bps_test_phase35"
    assert body["return_path"] == "/settings"

    portal_request = captured_request["request"]
    assert portal_request.customer_ref == "cus_portal_123"
    assert portal_request.return_url == "https://app.adhyantra.example/settings?billing=manage"

    events = get_analytics_events(client, user_id=user_id, event_name="billing.portal_started")
    assert len(events) == 1
    assert events[0].feature_area == "billing"
    metadata = deserialize_analytics_event_metadata(events[0])
    assert metadata["source"] == "settings_account"
    assert metadata["existing_customer_ref"] == "cus_portal_123"


def test_phase35_billing_portal_route_requires_customer_reference(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.routes import account_billing_routes
    from backend.services import billing_service

    auth = authenticate_premium_test_user(
        client,
        email="phase35-portal-missing@example.com",
        display_name="Phase 35 Portal Missing",
    )
    user_id = auth["user"]["id"]
    provider_called = {"value": False}

    class FakeProvider:
        def create_customer_portal_session(self, request):
            provider_called["value"] = True
            raise AssertionError("Billing portal provider should not be called without a customer reference.")

    monkeypatch.setattr(
        account_billing_routes,
        "settings",
        Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(billing_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post("/api/account/billing/portal", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Billing management is not ready on this account yet."
    assert provider_called["value"] is False
    events = get_analytics_events(client, user_id=user_id, event_name="billing.portal_blocked")
    assert len(events) == 1
    assert deserialize_analytics_event_metadata(events[0])["outcome_code"] == "missing_customer_ref"


def test_phase35_billing_portal_route_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/account/billing/portal", json={})

    assert response.status_code == 401


def test_phase35_billing_webhook_checkout_completion_syncs_owned_premium_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_test_user(
        client,
        email="phase35-webhook-checkout@example.com",
        display_name="Phase 35 Webhook Checkout",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    subscription_period_end = event_created_at + timedelta(days=30)
    event_payload = {
        "id": "evt_phase35_checkout_complete",
        "type": "checkout.session.completed",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "checkout.session",
                "mode": "subscription",
                "status": "complete",
                "client_reference_id": str(user_id),
                "customer": "cus_phase35_checkout",
                "subscription": "sub_phase35_checkout",
                "customer_email": "phase35-webhook-checkout@example.com",
                "metadata": {
                    "user_id": str(user_id),
                    "plan_tier": "premium",
                    "source": "settings_account",
                },
            }
        },
    }

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            assert payload == json.dumps(event_payload).encode("utf-8")
            assert signature_header == "test-signature"
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id="evt_phase35_checkout_complete",
                event_type="checkout.session.completed",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cus_phase35_checkout",
                subscription_ref="sub_phase35_checkout",
                payload=event_payload,
            )

        def lookup_subscription(self, subscription_ref):
            assert subscription_ref == "sub_phase35_checkout"
            return PaymentSubscriptionSummary(
                provider_name="stripe",
                subscription_ref="sub_phase35_checkout",
                customer_ref="cus_phase35_checkout",
                status="active",
                cancel_at_period_end=False,
                current_period_end=subscription_period_end,
                trial_ends_at=None,
                price_id="price_premium_monthly",
                product_id="prod_premium_monthly",
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(event_payload),
        headers={"stripe-signature": "test-signature"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_plan"] == "premium"
    assert me_body["subscription_status"] == "active"
    assert me_body["billing"]["customer_ref"] == "cus_phase35_checkout"
    assert me_body["billing"]["price_id"] == "price_premium_monthly"
    assert me_body["billing"]["product_id"] == "prod_premium_monthly"
    assert me_body["billing"]["portal_ready"] is False
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "active"
    assert me_body["feature_access"]["lesson_exports"] is True

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        assert user.subscription_provider_ref == "sub_phase35_checkout"
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert quota_snapshot.plan_current is True
    assert quota_snapshot.entitlement_enabled is True
    assert quota_snapshot.limit_value == 100

    receipts = get_billing_event_receipts(
        client,
        provider_name="stripe",
        provider_event_id="evt_phase35_checkout_complete",
    )
    assert len(receipts) == 1
    assert receipts[0].processing_state == "processed"
    assert receipts[0].user_id == user_id
    assert receipts[0].customer_ref == "cus_phase35_checkout"
    assert receipts[0].subscription_ref == "sub_phase35_checkout"


def test_phase35_duplicate_billing_webhook_event_is_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent

    auth = authenticate_test_user(
        client,
        email="phase35-webhook-duplicate@example.com",
        display_name="Phase 35 Webhook Duplicate",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 15, 13, 0, 0, tzinfo=UTC)
    event_payload = {
        "id": "evt_phase35_duplicate",
        "type": "checkout.session.completed",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "checkout.session",
                "mode": "subscription",
                "status": "complete",
                "client_reference_id": str(user_id),
                "customer": "cus_phase35_duplicate",
                "subscription": "sub_phase35_duplicate",
                "customer_email": "phase35-webhook-duplicate@example.com",
                "metadata": {"user_id": str(user_id)},
            }
        },
    }
    lookup_calls = {"count": 0}

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id="evt_phase35_duplicate",
                event_type="checkout.session.completed",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cus_phase35_duplicate",
                subscription_ref="sub_phase35_duplicate",
                payload=event_payload,
            )

        def lookup_subscription(self, subscription_ref):
            lookup_calls["count"] += 1
            return PaymentSubscriptionSummary(
                provider_name="stripe",
                subscription_ref="sub_phase35_duplicate",
                customer_ref="cus_phase35_duplicate",
                status="active",
                cancel_at_period_end=False,
                current_period_end=event_created_at + timedelta(days=30),
                trial_ends_at=None,
                price_id="price_premium_monthly",
                product_id="prod_premium_monthly",
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    first = client.post("/api/account/billing/webhook", content=json.dumps(event_payload), headers={"stripe-signature": "dup"})
    second = client.post("/api/account/billing/webhook", content=json.dumps(event_payload), headers={"stripe-signature": "dup"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert lookup_calls["count"] == 1

    receipts = get_billing_event_receipts(
        client,
        provider_name="stripe",
        provider_event_id="evt_phase35_duplicate",
    )
    assert len(receipts) == 1
    assert receipts[0].processing_state == "processed"
    assert receipts[0].delivery_attempt_count == 2
    assert receipts[0].duplicate_delivery_count == 1
    assert receipts[0].last_received_at is not None

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["billing"]["customer_ref"] == "cus_phase35_duplicate"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "active"


def test_phase35_invoice_payment_failure_and_renewal_events_reconcile_subscription_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_premium_test_user(
        client,
        email="phase35-webhook-renewal@example.com",
        display_name="Phase 35 Webhook Renewal",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_customer_ref = "cus_phase35_renewal"
        user.subscription_price_id = "price_premium_monthly"
        user.subscription_product_id = "prod_premium_monthly"
        db.add(user)
        db.commit()
    finally:
        db.close()

    event_created_at = datetime(2026, 5, 15, 14, 0, 0, tzinfo=UTC)
    failed_payload = {
        "id": "evt_phase35_invoice_failed",
        "type": "invoice.payment_failed",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "invoice",
                "customer": "cus_phase35_renewal",
                "subscription": "sub_phase35_renewal",
                "customer_email": "phase35-webhook-renewal@example.com",
            }
        },
    }
    paid_payload = {
        "id": "evt_phase35_invoice_paid",
        "type": "invoice.payment_succeeded",
        "created": int((event_created_at + timedelta(minutes=5)).timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "invoice",
                "customer": "cus_phase35_renewal",
                "subscription": "sub_phase35_renewal",
                "customer_email": "phase35-webhook-renewal@example.com",
            }
        },
    }

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def __init__(self):
            self.current_payload = failed_payload
            self.current_event_type = "invoice.payment_failed"
            self.lookup_status = "past_due"

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id=self.current_payload["id"],
                event_type=self.current_event_type,
                created_at=event_created_at if self.current_event_type == "invoice.payment_failed" else event_created_at + timedelta(minutes=5),
                livemode=False,
                customer_ref="cus_phase35_renewal",
                subscription_ref="sub_phase35_renewal",
                payload=self.current_payload,
            )

        def lookup_subscription(self, subscription_ref):
            return PaymentSubscriptionSummary(
                provider_name="stripe",
                subscription_ref="sub_phase35_renewal",
                customer_ref="cus_phase35_renewal",
                status=self.lookup_status,
                cancel_at_period_end=False,
                current_period_end=event_created_at + timedelta(days=30),
                trial_ends_at=None,
                price_id="price_premium_monthly",
                product_id="prod_premium_monthly",
                metadata={"user_id": str(user_id)},
            )

    provider = FakeProvider()
    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: provider)

    failed_response = client.post("/api/account/billing/webhook", content=json.dumps(failed_payload), headers={"stripe-signature": "fail"})
    assert failed_response.status_code == 200

    failed_me = client.get("/api/auth/me").json()["user"]
    assert failed_me["subscription_status"] == "past_due"
    assert failed_me["billing"]["subscription_lifecycle"]["state"] == "past_due"
    assert failed_me["billing"]["subscription_lifecycle"]["requires_payment_action"] is True
    assert failed_me["entitlements"]["plan_current"] is False

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        assert user.subscription_provider_ref == "sub_phase35_renewal"
        failed_quota = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert failed_quota.plan_current is False
    assert failed_quota.entitlement_enabled is False
    assert failed_quota.limit_value == 0

    provider.current_payload = paid_payload
    provider.current_event_type = "invoice.payment_succeeded"
    provider.lookup_status = "active"

    paid_response = client.post("/api/account/billing/webhook", content=json.dumps(paid_payload), headers={"stripe-signature": "paid"})
    assert paid_response.status_code == 200

    paid_me = client.get("/api/auth/me").json()["user"]
    assert paid_me["subscription_status"] == "active"
    assert paid_me["billing"]["subscription_lifecycle"]["state"] == "active"
    assert paid_me["billing"]["subscription_lifecycle"]["requires_payment_action"] is False
    assert paid_me["entitlements"]["plan_current"] is True

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        renewed_quota = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert renewed_quota.plan_current is True
    assert renewed_quota.entitlement_enabled is True
    assert renewed_quota.limit_value == 100


def test_phase35_subscription_updated_canceling_state_keeps_premium_entitlements_and_quota_current(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_premium_test_user(
        client,
        email="phase35-webhook-canceling@example.com",
        display_name="Phase 35 Webhook Canceling",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime.now(UTC).replace(microsecond=0)
    future_period_end = event_created_at + timedelta(days=14)
    payload = {
        "id": "evt_phase35_subscription_updated_canceling",
        "type": "customer.subscription.updated",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_phase35_canceling",
                "customer": "cus_phase35_canceling",
                "status": "active",
                "cancel_at_period_end": True,
                "current_period_end": int(future_period_end.timestamp()),
                "trial_end": None,
                "metadata": {"user_id": str(user_id)},
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_premium_monthly",
                                "product": "prod_premium_monthly",
                            }
                        }
                    ]
                },
            }
        },
    }

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def verify_webhook_signature(self, raw_payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id="evt_phase35_subscription_updated_canceling",
                event_type="customer.subscription.updated",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cus_phase35_canceling",
                subscription_ref="sub_phase35_canceling",
                payload=payload,
            )

        def lookup_subscription(self, subscription_ref):
            raise AssertionError("Subscription lookup should not be required for subscription.updated payload sync.")

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={"stripe-signature": "canceling"},
    )
    assert response.status_code == 200

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "active"
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "canceling"
    assert me_body["entitlements"]["plan_current"] is True
    assert me_body["feature_access"]["lesson_exports"] is True
    assert me_body["billing"]["subscription_lifecycle"]["cancel_at_period_end"] is True

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        assert user.subscription_provider_ref == "sub_phase35_canceling"
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert quota_snapshot.plan_current is True
    assert quota_snapshot.entitlement_enabled is True
    assert quota_snapshot.limit_value == 100


def test_phase35_subscription_deleted_webhook_syncs_expired_premium_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import VerifiedPaymentWebhookEvent

    auth = authenticate_premium_test_user(
        client,
        email="phase35-webhook-cancel@example.com",
        display_name="Phase 35 Webhook Cancel",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_customer_ref = "cus_phase35_cancel"
        user.subscription_price_id = "price_premium_monthly"
        user.subscription_product_id = "prod_premium_monthly"
        db.add(user)
        db.commit()
    finally:
        db.close()

    event_created_at = datetime(2026, 5, 15, 15, 0, 0, tzinfo=UTC)
    canceled_period_end = event_created_at - timedelta(days=1)
    canceled_payload = {
        "id": "evt_phase35_subscription_deleted",
        "type": "customer.subscription.deleted",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_phase35_cancel",
                "customer": "cus_phase35_cancel",
                "status": "canceled",
                "cancel_at_period_end": True,
                "current_period_end": int(canceled_period_end.timestamp()),
                "trial_end": None,
                "metadata": {"user_id": str(user_id)},
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_premium_monthly",
                                "product": "prod_premium_monthly",
                            }
                        }
                    ]
                },
            }
        },
    }

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id="evt_phase35_subscription_deleted",
                event_type="customer.subscription.deleted",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cus_phase35_cancel",
                subscription_ref="sub_phase35_cancel",
                payload=canceled_payload,
            )

        def lookup_subscription(self, subscription_ref):
            raise AssertionError("Subscription lookup should not be required for deleted subscription payload sync.")

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(canceled_payload),
        headers={"stripe-signature": "cancel"},
    )

    assert response.status_code == 200
    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "canceled"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "expired"
    assert me_body["entitlements"]["plan_current"] is False


def test_phase37_razorpay_billing_webhook_activation_syncs_owned_premium_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent

    auth = authenticate_test_user(
        client,
        email="phase37-razorpay-webhook-activate@example.com",
        display_name="Phase 37 Razorpay Activate",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 17, 10, 0, 0, tzinfo=UTC)
    subscription_period_end = event_created_at + timedelta(days=30)
    event_payload = {
        "entity": "event",
        "event": "subscription.activated",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_activate",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_activate",
                    "status": "active",
                    "plan_id": "plan_premium_monthly",
                    "current_start": int(event_created_at.timestamp()),
                    "current_end": int(subscription_period_end.timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {
                        "user_id": str(user_id),
                        "plan_tier": "premium",
                        "source": "settings_account",
                    },
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            assert payload == json.dumps(event_payload).encode("utf-8")
            assert signature_header == "razorpay-signature"
            assert event_id_header == "evt_razorpay_phase37_activate"
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_activate",
                event_type="subscription.activated",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_activate",
                subscription_ref="sub_razorpay_phase37_activate",
                payload=event_payload,
            )

        def lookup_subscription(self, subscription_ref):
            assert subscription_ref == "sub_razorpay_phase37_activate"
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_activate",
                customer_ref="cust_razorpay_phase37_activate",
                status="active",
                cancel_at_period_end=False,
                current_period_end=subscription_period_end,
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(event_payload),
        headers={
            "x-razorpay-signature": "razorpay-signature",
            "x-razorpay-event-id": "evt_razorpay_phase37_activate",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_plan"] == "premium"
    assert me_body["subscription_status"] == "active"
    assert me_body["billing"]["customer_ref"] == "cust_razorpay_phase37_activate"
    assert me_body["billing"]["price_id"] == "plan_premium_monthly"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "active"
    assert me_body["billing"]["portal_ready"] is False
    assert me_body["feature_access"]["lesson_exports"] is True

    receipts = get_billing_event_receipts(
        client,
        provider_name="razorpay",
        provider_event_id="evt_razorpay_phase37_activate",
    )
    assert len(receipts) == 1
    assert receipts[0].processing_state == "processed"
    assert receipts[0].user_id == user_id
    assert receipts[0].customer_ref == "cust_razorpay_phase37_activate"
    assert receipts[0].subscription_ref == "sub_razorpay_phase37_activate"


def test_phase37_razorpay_subscription_authenticated_state_stays_pending_without_premium_access(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_test_user(
        client,
        email="phase37-razorpay-authenticated@example.com",
        display_name="Phase 37 Razorpay Authenticated",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime.now(UTC).replace(microsecond=0)
    activation_at = event_created_at + timedelta(days=5)
    event_payload = {
        "entity": "event",
        "event": "subscription.authenticated",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_authenticated",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_authenticated",
                    "status": "authenticated",
                    "plan_id": "plan_premium_monthly",
                    "charge_at": int(activation_at.timestamp()),
                    "start_at": int(activation_at.timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_authenticated",
                event_type="subscription.authenticated",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_authenticated",
                subscription_ref="sub_razorpay_phase37_authenticated",
                payload=event_payload,
            )

        def lookup_subscription(self, subscription_ref):
            assert subscription_ref == "sub_razorpay_phase37_authenticated"
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_authenticated",
                customer_ref="cust_razorpay_phase37_authenticated",
                status="authenticated",
                cancel_at_period_end=False,
                current_period_end=None,
                trial_ends_at=activation_at,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(event_payload),
        headers={"x-razorpay-signature": "authenticated", "x-razorpay-event-id": "evt_razorpay_phase37_authenticated"},
    )
    assert response.status_code == 200

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_plan"] == "premium"
    assert me_body["subscription_status"] == "inactive"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "pending"
    assert me_body["billing"]["subscription_lifecycle"]["access_active"] is False
    assert me_body["entitlements"]["plan_current"] is False
    assert me_body["feature_access"]["lesson_exports"] is False

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert quota_snapshot.plan_current is False
    assert quota_snapshot.entitlement_enabled is False


def test_phase37_duplicate_razorpay_billing_webhook_event_is_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent

    auth = authenticate_test_user(
        client,
        email="phase37-razorpay-webhook-duplicate@example.com",
        display_name="Phase 37 Razorpay Duplicate",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 17, 11, 0, 0, tzinfo=UTC)
    event_payload = {
        "entity": "event",
        "event": "subscription.charged",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_duplicate",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_duplicate",
                    "status": "active",
                    "plan_id": "plan_premium_monthly",
                    "current_start": int(event_created_at.timestamp()),
                    "current_end": int((event_created_at + timedelta(days=30)).timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }
    lookup_calls = {"count": 0}

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_duplicate",
                event_type="subscription.charged",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_duplicate",
                subscription_ref="sub_razorpay_phase37_duplicate",
                payload=event_payload,
            )

        def lookup_subscription(self, subscription_ref):
            lookup_calls["count"] += 1
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_duplicate",
                customer_ref="cust_razorpay_phase37_duplicate",
                status="active",
                cancel_at_period_end=False,
                current_period_end=event_created_at + timedelta(days=30),
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    first = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(event_payload),
        headers={"x-razorpay-signature": "dup", "x-razorpay-event-id": "evt_razorpay_phase37_duplicate"},
    )
    second = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(event_payload),
        headers={"x-razorpay-signature": "dup", "x-razorpay-event-id": "evt_razorpay_phase37_duplicate"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert lookup_calls["count"] == 1

    receipts = get_billing_event_receipts(
        client,
        provider_name="razorpay",
        provider_event_id="evt_razorpay_phase37_duplicate",
    )
    assert len(receipts) == 1
    assert receipts[0].processing_state == "processed"
    assert receipts[0].delivery_attempt_count == 2
    assert receipts[0].duplicate_delivery_count == 1


def test_phase37_razorpay_payment_failure_and_renewal_events_reconcile_subscription_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_premium_test_user(
        client,
        email="phase37-razorpay-renewal@example.com",
        display_name="Phase 37 Razorpay Renewal",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_customer_ref = "cust_razorpay_phase37_renewal"
        user.subscription_provider_ref = "sub_razorpay_phase37_renewal"
        user.subscription_price_id = "plan_premium_monthly"
        db.add(user)
        db.commit()
    finally:
        db.close()

    event_created_at = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    pending_payload = {
        "entity": "event",
        "event": "subscription.pending",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_renewal",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_renewal",
                    "status": "pending",
                    "plan_id": "plan_premium_monthly",
                    "current_end": int((event_created_at + timedelta(days=30)).timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }
    charged_payload = {
        "entity": "event",
        "event": "subscription.charged",
        "created_at": int((event_created_at + timedelta(minutes=5)).timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_renewal",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_renewal",
                    "status": "active",
                    "plan_id": "plan_premium_monthly",
                    "current_end": int((event_created_at + timedelta(days=30)).timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def __init__(self):
            self.current_payload = pending_payload
            self.current_event_type = "subscription.pending"
            self.lookup_status = "pending"

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            created_at = event_created_at if self.current_event_type == "subscription.pending" else event_created_at + timedelta(minutes=5)
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id=str(event_id_header or self.current_payload["event"]),
                event_type=self.current_event_type,
                created_at=created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_renewal",
                subscription_ref="sub_razorpay_phase37_renewal",
                payload=self.current_payload,
            )

        def lookup_subscription(self, subscription_ref):
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_renewal",
                customer_ref="cust_razorpay_phase37_renewal",
                status=self.lookup_status,
                cancel_at_period_end=False,
                current_period_end=event_created_at + timedelta(days=30),
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    provider = FakeProvider()
    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: provider)

    failed_response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(pending_payload),
        headers={"x-razorpay-signature": "pending", "x-razorpay-event-id": "evt_razorpay_phase37_pending"},
    )
    assert failed_response.status_code == 200

    failed_me = client.get("/api/auth/me").json()["user"]
    assert failed_me["subscription_status"] == "past_due"
    assert failed_me["billing"]["subscription_lifecycle"]["state"] == "past_due"
    assert failed_me["billing"]["subscription_lifecycle"]["requires_payment_action"] is True
    assert failed_me["entitlements"]["plan_current"] is False

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        failed_quota = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert failed_quota.plan_current is False
    assert failed_quota.entitlement_enabled is False

    provider.current_payload = charged_payload
    provider.current_event_type = "subscription.charged"
    provider.lookup_status = "active"

    paid_response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(charged_payload),
        headers={"x-razorpay-signature": "charged", "x-razorpay-event-id": "evt_razorpay_phase37_charged"},
    )
    assert paid_response.status_code == 200

    paid_me = client.get("/api/auth/me").json()["user"]
    assert paid_me["subscription_status"] == "active"
    assert paid_me["billing"]["subscription_lifecycle"]["state"] == "active"
    assert paid_me["entitlements"]["plan_current"] is True


def test_phase37_razorpay_subscription_updated_canceling_state_keeps_premium_entitlements_and_quota_current(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_premium_test_user(
        client,
        email="phase37-razorpay-canceling@example.com",
        display_name="Phase 37 Razorpay Canceling",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime.now(UTC).replace(microsecond=0)
    future_period_end = event_created_at + timedelta(days=14)
    payload = {
        "entity": "event",
        "event": "subscription.updated",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_canceling",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_canceling",
                    "status": "active",
                    "plan_id": "plan_premium_monthly",
                    "current_end": int(future_period_end.timestamp()),
                    "has_scheduled_changes": True,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, raw_payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_canceling",
                event_type="subscription.updated",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_canceling",
                subscription_ref="sub_razorpay_phase37_canceling",
                payload=payload,
            )

        def lookup_subscription(self, subscription_ref):
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_canceling",
                customer_ref="cust_razorpay_phase37_canceling",
                status="active",
                cancel_at_period_end=True,
                current_period_end=future_period_end,
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={"x-razorpay-signature": "canceling", "x-razorpay-event-id": "evt_razorpay_phase37_canceling"},
    )
    assert response.status_code == 200

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "active"
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "canceling"
    assert me_body["entitlements"]["plan_current"] is True
    assert me_body["billing"]["subscription_lifecycle"]["cancel_at_period_end"] is True

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert quota_snapshot.plan_current is True
    assert quota_snapshot.entitlement_enabled is True


def test_phase37_razorpay_subscription_paused_state_disables_premium_entitlements_and_quota(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent
    from backend.services.usage_metering_service import build_usage_quota_snapshot

    auth = authenticate_premium_test_user(
        client,
        email="phase37-razorpay-paused@example.com",
        display_name="Phase 37 Razorpay Paused",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 17, 13, 30, 0, tzinfo=UTC)
    future_period_end = event_created_at + timedelta(days=10)
    payload = {
        "entity": "event",
        "event": "subscription.paused",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_paused",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_paused",
                    "status": "paused",
                    "plan_id": "plan_premium_monthly",
                    "current_end": int(future_period_end.timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, raw_payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_paused",
                event_type="subscription.paused",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_paused",
                subscription_ref="sub_razorpay_phase37_paused",
                payload=payload,
            )

        def lookup_subscription(self, subscription_ref):
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_paused",
                customer_ref="cust_razorpay_phase37_paused",
                status="paused",
                cancel_at_period_end=False,
                current_period_end=future_period_end,
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={"x-razorpay-signature": "paused", "x-razorpay-event-id": "evt_razorpay_phase37_paused"},
    )
    assert response.status_code == 200

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "suspended"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "suspended"
    assert me_body["billing"]["subscription_lifecycle"]["access_active"] is False
    assert me_body["entitlements"]["plan_current"] is False
    assert me_body["feature_access"]["lesson_exports"] is False

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert quota_snapshot.plan_current is False
    assert quota_snapshot.entitlement_enabled is False


def test_phase37_razorpay_subscription_completed_webhook_syncs_expired_premium_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service
    from backend.services.payment_provider_service import PaymentSubscriptionSummary, VerifiedPaymentWebhookEvent

    auth = authenticate_premium_test_user(
        client,
        email="phase37-razorpay-completed@example.com",
        display_name="Phase 37 Razorpay Completed",
    )
    user_id = auth["user"]["id"]
    event_created_at = datetime(2026, 5, 17, 14, 0, 0, tzinfo=UTC)
    completed_period_end = event_created_at - timedelta(days=1)
    payload = {
        "entity": "event",
        "event": "subscription.completed",
        "created_at": int(event_created_at.timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_phase37_completed",
                    "entity": "subscription",
                    "customer_id": "cust_razorpay_phase37_completed",
                    "status": "completed",
                    "plan_id": "plan_premium_monthly",
                    "current_end": int(completed_period_end.timestamp()),
                    "ended_at": int(completed_period_end.timestamp()),
                    "has_scheduled_changes": False,
                    "notes": {"user_id": str(user_id)},
                }
            }
        },
    }

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, payload_bytes, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="razorpay",
                event_id="evt_razorpay_phase37_completed",
                event_type="subscription.completed",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cust_razorpay_phase37_completed",
                subscription_ref="sub_razorpay_phase37_completed",
                payload=payload,
            )

        def lookup_subscription(self, subscription_ref):
            return PaymentSubscriptionSummary(
                provider_name="razorpay",
                subscription_ref="sub_razorpay_phase37_completed",
                customer_ref="cust_razorpay_phase37_completed",
                status="completed",
                cancel_at_period_end=False,
                current_period_end=completed_period_end,
                trial_ends_at=None,
                price_id="plan_premium_monthly",
                product_id=None,
                metadata={"user_id": str(user_id)},
            )

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={"x-razorpay-signature": "completed", "x-razorpay-event-id": "evt_razorpay_phase37_completed"},
    )

    assert response.status_code == 200
    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "canceled"
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "expired"
    assert me_body["entitlements"]["plan_current"] is False


def test_phase35_provider_backed_expired_premium_keeps_old_render_assets_visible_but_blocks_new_premium_actions(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_webhook_service, tts_service, video_render_service
    from backend.services.payment_provider_service import VerifiedPaymentWebhookEvent

    auth = authenticate_premium_test_user(
        client,
        email="phase35-provider-expired-assets@example.com",
        display_name="Phase 35 Provider Expired Assets",
    )
    user_id = auth["user"]["id"]

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "phase35-provider-expired-assets"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert create_response.status_code == 200
    created_job = create_response.json()
    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=created_job["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/video/{created_job['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["output"]["download_path"]

    event_created_at = datetime(2026, 5, 15, 17, 0, 0, tzinfo=UTC)
    expired_period_end = event_created_at - timedelta(days=1)
    payload = {
        "id": "evt_phase35_provider_expired_assets",
        "type": "customer.subscription.deleted",
        "created": int(event_created_at.timestamp()),
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_phase35_provider_expired_assets",
                "customer": "cus_phase35_provider_expired_assets",
                "status": "canceled",
                "cancel_at_period_end": True,
                "current_period_end": int(expired_period_end.timestamp()),
                "trial_end": None,
                "metadata": {"user_id": str(user_id)},
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_premium_monthly",
                                "product": "prod_premium_monthly",
                            }
                        }
                    ]
                },
            }
        },
    }

    class FakeProvider:
        provider_name = "stripe"
        enabled = True

        def verify_webhook_signature(self, raw_payload, *, signature_header, event_id_header=None):
            return VerifiedPaymentWebhookEvent(
                provider_name="stripe",
                event_id="evt_phase35_provider_expired_assets",
                event_type="customer.subscription.deleted",
                created_at=event_created_at,
                livemode=False,
                customer_ref="cus_phase35_provider_expired_assets",
                subscription_ref="sub_phase35_provider_expired_assets",
                payload=payload,
            )

        def lookup_subscription(self, subscription_ref):
            raise AssertionError("Subscription lookup should not be required for deleted subscription payload sync.")

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    webhook_response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={"stripe-signature": "provider-expired"},
    )
    assert webhook_response.status_code == 200

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "expired"
    assert me_body["feature_access"]["lesson_exports"] is False
    assert me_body["feature_access"]["premium_lesson_modes"] is False

    assets_response = client.get("/api/tutor/render/assets?render_type=slide_video")
    assert assets_response.status_code == 200
    assets_body = assets_response.json()
    assert [item["id"] for item in assets_body] == [created_job["id"]]

    download_response = client.get(status_body["output"]["download_path"])
    assert download_response.status_code == 200

    blocked_create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
        },
    )
    assert blocked_create_response.status_code == 403
    detail = blocked_create_response.json()["detail"]
    assert detail["feature_key"] == "lesson_exports"
    assert detail["required_plan"] == "premium"


def test_seed_demo_accounts_creates_predictable_profiles_settings_and_history(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        anchor = datetime(2026, 4, 20, 9, 0, 0, tzinfo=UTC)
        summaries = seed_demo_accounts(db, anchor_time=anchor)
        summary_by_key = {item["key"]: item for item in summaries}

        assert list(summary_by_key) == [
            "fresh_user",
            "recovering_user",
            "strong_user",
            "overloaded_user",
            "multi_exam_user",
        ]

        fresh_user = summary_by_key["fresh_user"]
        assert fresh_user["current_exam"] == "upsc"
        assert fresh_user["current_subject"] == "polity"
        assert fresh_user["mentor_mode"] == "normal"
        assert fresh_user["history"]["quiz_attempts"] == 0
        assert fresh_user["onboarding_state"] == "new"

        recovering_user = summary_by_key["recovering_user"]
        assert recovering_user["history"]["quiz_attempts"] == 3
        assert recovering_user["current_exam"] == "upsc"
        assert recovering_user["current_subject"] == "history"
        assert recovering_user["study_state"]["weak_topics"]

        strong_user = summary_by_key["strong_user"]
        assert strong_user["history"]["quiz_attempts"] == 5
        assert strong_user["mentor_mode"] == "strict"
        assert strong_user["current_subject"] == "polity"
        assert strong_user["study_state"]["recommended_next_topic"]

        overloaded_user = summary_by_key["overloaded_user"]
        assert overloaded_user["history"]["quiz_attempts"] == 7
        assert overloaded_user["current_subject"] == "geography"
        assert overloaded_user["study_state"]["weak_topics"]

        multi_exam_user = summary_by_key["multi_exam_user"]
        assert multi_exam_user["preferred_exam"] == "upsc"
        assert multi_exam_user["current_exam"] == "banking"
        assert multi_exam_user["current_subject"] == "regulatory_basics"
        assert multi_exam_user["current_content_subject"] == "polity"
        assert multi_exam_user["history"]["attempts_by_exam"] == {"banking": 2, "upsc": 2}

        user = db.query(UserAccount).filter(UserAccount.email == "multi_exam_user@adhyantra.test").first()
        assert user is not None
        assert user.settings is not None
        assert user.settings.preferred_exam == "upsc"
        assert user.settings.current_exam == "banking"
        assert user.settings.current_subject == "regulatory_basics"
        assert user.profile is not None
        assert user.profile.onboarding_state == "completed"
        assert user.last_active_at is not None
    finally:
        db.close()


def test_seed_demo_accounts_refreshes_known_state_without_duplicating_history(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = datetime(2026, 4, 20, 9, 0, 0, tzinfo=UTC)

    db = session_factory()
    try:
        seed_demo_accounts(db, account_keys=["recovering_user", "multi_exam_user"], anchor_time=anchor)
        recovering_user = db.query(UserAccount).filter(UserAccount.email == "recovering_user@adhyantra.test").first()
        assert recovering_user is not None
        recovering_user_id = recovering_user.id
    finally:
        db.close()

    create_attempt_record(
        client,
        topic="Federalism",
        score=5,
        user_id=recovering_user_id,
    )

    db = session_factory()
    try:
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == recovering_user_id).count() == 4
        refreshed_summaries = seed_demo_accounts(db, account_keys=["recovering_user", "multi_exam_user"], anchor_time=anchor)
        refreshed_by_key = {item["key"]: item for item in refreshed_summaries}

        assert refreshed_by_key["recovering_user"]["history"]["quiz_attempts"] == 3
        assert refreshed_by_key["multi_exam_user"]["history"]["attempts_by_exam"] == {"banking": 2, "upsc": 2}
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == recovering_user_id).count() == 3
    finally:
        db.close()


def test_seed_demo_accounts_can_apply_named_learning_scenarios(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import adaptive_service, coach_service, progress_service

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        anchor = datetime(2026, 4, 20, 9, 0, 0, tzinfo=UTC)
        evaluation_time = anchor + timedelta(hours=12)
        monkeypatch.setattr(adaptive_service, "utc_now", lambda: evaluation_time)
        monkeypatch.setattr(coach_service, "utc_now", lambda: evaluation_time)
        monkeypatch.setattr(progress_service, "utc_now", lambda: evaluation_time)
        scenarios = {
            "fresh_start": {
                "account_key": "fresh_user",
                "recommended_mode": "study",
                "warning_level": "quiet",
                "revision_due_count": 0,
            },
            "weak_topic_repair": {
                "account_key": "recovering_user",
                "recommended_mode": "revise",
                "focus_topic": "Federalism",
                "warning_level": "quiet",
            },
            "revision_heavy": {
                "account_key": "multi_exam_user",
                "recommended_mode": "revise",
                "current_exam": "banking",
                "current_subject": "regulatory_basics",
                "missed_revision_signal": "missed",
            },
            "recovery_after_slippage": {
                "account_key": "recovering_user",
                "recommended_mode": "revise",
                "focus_topic": "Indian National Congress",
                "consistency_status": "slipping",
            },
            "strong_challenge_ready": {
                "account_key": "strong_user",
                "recommended_mode": "study",
                "warning_level": "quiet",
                "motivation_state": "stable",
                "revision_due_count": 0,
            },
            "overloaded_accountability_pressure": {
                "account_key": "overloaded_user",
                "recommended_mode": "revise",
                "warning_level": "warning",
                "motivation_state": "overloaded",
            },
        }

        for scenario_key, expected in scenarios.items():
            summaries = seed_demo_accounts(db, scenario_key=scenario_key, anchor_time=anchor)
            assert len(summaries) == 1
            summary = summaries[0]
            assert summary["key"] == expected["account_key"]
            assert summary["scenario"]["key"] == scenario_key
            assert summary["scenario"]["source"] == "learning_scenario"
            assert summary["study_state"]["recommended_mode"] == expected["recommended_mode"]

            if "focus_topic" in expected:
                assert summary["study_state"]["plan_focus_topic"] == expected["focus_topic"]
                assert summary["study_state"]["coach_study_today"] == expected["focus_topic"]
            if "warning_level" in expected:
                assert summary["study_state"]["warning_level"] == expected["warning_level"]
            if "motivation_state" in expected:
                assert summary["study_state"]["motivation_state"] == expected["motivation_state"]
            if "revision_due_count" in expected:
                assert summary["study_state"]["revision_due_count"] == expected["revision_due_count"]
            if "current_exam" in expected:
                assert summary["current_exam"] == expected["current_exam"]
            if "current_subject" in expected:
                assert summary["current_subject"] == expected["current_subject"]
            if "missed_revision_signal" in expected:
                assert summary["study_state"]["missed_revision_signal"] == expected["missed_revision_signal"]
            if "consistency_status" in expected:
                assert summary["study_state"]["consistency_status"] == expected["consistency_status"]

        strong_summary = seed_demo_accounts(db, scenario_key="strong_challenge_ready", anchor_time=anchor)[0]
        assert strong_summary["study_state"]["weak_topics"] == []
    finally:
        db.close()


def test_seed_demo_accounts_can_place_same_demo_user_into_different_scenarios(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        anchor = default_demo_seed_anchor(datetime.now(UTC))

        repair_summary = seed_demo_accounts(
            db,
            account_keys=["strong_user"],
            scenario_key="weak_topic_repair",
            anchor_time=anchor,
        )[0]
        assert repair_summary["key"] == "strong_user"
        assert repair_summary["scenario"]["key"] == "weak_topic_repair"
        assert repair_summary["study_state"]["recommended_mode"] == "revise"
        assert "Federalism" in repair_summary["study_state"]["weak_topics"]
        assert repair_summary["history"]["quiz_attempts"] == 3

        challenge_summary = seed_demo_accounts(
            db,
            account_keys=["strong_user"],
            scenario_key="strong_challenge_ready",
            anchor_time=anchor,
        )[0]
        assert challenge_summary["key"] == "strong_user"
        assert challenge_summary["scenario"]["key"] == "strong_challenge_ready"
        assert challenge_summary["study_state"]["recommended_mode"] == "study"
        assert challenge_summary["study_state"]["warning_level"] == "quiet"
        assert challenge_summary["study_state"]["weak_topics"] == []
        assert challenge_summary["history"]["quiz_attempts"] == 5

        user = db.query(UserAccount).filter(UserAccount.email == "strong_user@adhyantra.test").first()
        assert user is not None
        assert user.settings is not None
        assert user.settings.current_exam == "upsc"
        assert user.settings.current_subject == "polity"
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == user.id).count() == 5
        assert db.query(TopicStudy).filter(TopicStudy.user_id == user.id).count() >= 5
        assert db.query(TopicProgress).filter(TopicProgress.user_id == user.id).count() >= 5
    finally:
        db.close()


def test_seed_demo_scenarios_loads_multiple_disjoint_scenarios(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        anchor = default_demo_seed_anchor(datetime.now(UTC))
        summaries = seed_demo_scenarios(
            db,
            scenario_keys=["fresh_start", "strong_challenge_ready", "revision_heavy"],
            anchor_time=anchor,
        )
        summary_by_key = {item["key"]: item for item in summaries}

        assert set(summary_by_key) == {"fresh_user", "strong_user", "multi_exam_user"}
        assert summary_by_key["fresh_user"]["scenario"]["key"] == "fresh_start"
        assert summary_by_key["strong_user"]["scenario"]["key"] == "strong_challenge_ready"
        assert summary_by_key["strong_user"]["study_state"]["recommended_mode"] == "study"
        assert summary_by_key["multi_exam_user"]["scenario"]["key"] == "revision_heavy"
        assert summary_by_key["multi_exam_user"]["study_state"]["missed_revision_signal"] == "missed"
    finally:
        db.close()


def test_demo_learning_scenario_plan_rejects_default_account_collisions() -> None:
    with pytest.raises(ValueError) as excinfo:
        build_demo_learning_scenario_plan(["weak_topic_repair", "recovery_after_slippage"])

    assert "recovering_user" in str(excinfo.value)
    assert "load them separately" in str(excinfo.value).lower()


def test_demo_smoke_scenarios_align_with_seeded_runtime_state(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = default_demo_seed_anchor(datetime.now(UTC))

    for smoke_scenario in list_demo_smoke_scenarios():
        db = session_factory()
        try:
            seeded_accounts = seed_demo_accounts(
                db,
                account_keys=[smoke_scenario.account_key],
                scenario_key=smoke_scenario.scenario_key,
                anchor_time=anchor,
            )
            assert len(seeded_accounts) == 1
            seeded_account = seeded_accounts[0]
        finally:
            db.close()

        authenticate_test_user(
            client,
            email=seeded_account["email"],
            display_name=seeded_account["display_name"],
        )

        me_body = client.get("/api/auth/me").json()
        settings = me_body["settings"]
        if smoke_scenario.expected_preferred_exam is not None:
            assert settings["preferred_exam"] == smoke_scenario.expected_preferred_exam
        if smoke_scenario.expected_preferred_subject is not None:
            assert settings["preferred_subject"] == smoke_scenario.expected_preferred_subject
        if smoke_scenario.expected_current_exam is not None:
            assert settings["current_exam"] == smoke_scenario.expected_current_exam
        if smoke_scenario.expected_current_subject is not None:
            assert settings["current_subject"] == smoke_scenario.expected_current_subject

        summary_body = client.get("/api/progress/summary").json()
        plan_body = client.get("/api/plan/today").json()
        revision_body = client.get("/api/revision/due").json()
        coach_body = client.get("/api/coach/summary").json()
        history_body = client.get("/api/progress/history").json()

        for payload in (summary_body, plan_body, revision_body, coach_body, history_body):
            if smoke_scenario.expected_current_exam is not None:
                assert payload["exam"] == smoke_scenario.expected_current_exam
            if smoke_scenario.expected_current_subject is not None:
                assert payload["subject"] == smoke_scenario.expected_current_subject
            if smoke_scenario.expected_content_subject is not None:
                assert payload["content_subject"] == smoke_scenario.expected_content_subject

        if smoke_scenario.expected_recommended_mode is not None:
            assert summary_body["recommended_mode"] == smoke_scenario.expected_recommended_mode
            assert plan_body["recommended_mode"] == smoke_scenario.expected_recommended_mode
            assert coach_body["recommended_mode"] == smoke_scenario.expected_recommended_mode

        if smoke_scenario.expected_plan_focus_topic is not None:
            assert plan_body["focus_topic"] == smoke_scenario.expected_plan_focus_topic
            assert coach_body["study_today"] == smoke_scenario.expected_plan_focus_topic

        accountability_summary = summary_body["accountability_summary"]
        coach_accountability = coach_body["accountability_summary"]
        if smoke_scenario.expected_warning_level is not None:
            assert accountability_summary["warning_level"] == smoke_scenario.expected_warning_level
            assert coach_accountability["warning_level"] == smoke_scenario.expected_warning_level
        if smoke_scenario.expected_consistency_status is not None:
            assert accountability_summary["consistency_status"] == smoke_scenario.expected_consistency_status
            assert coach_accountability["consistency_status"] == smoke_scenario.expected_consistency_status
        if smoke_scenario.expected_missed_revision_signal is not None:
            assert accountability_summary["missed_revision_signal"] == smoke_scenario.expected_missed_revision_signal
            assert coach_accountability["missed_revision_signal"] == smoke_scenario.expected_missed_revision_signal
        if smoke_scenario.expected_motivation_state is not None:
            assert accountability_summary["motivation_summary"]["motivation_state"] == smoke_scenario.expected_motivation_state
            assert coach_accountability["motivation_summary"]["motivation_state"] == smoke_scenario.expected_motivation_state

        if smoke_scenario.expected_revision_due_min is not None:
            assert revision_body["total_due_count"] >= smoke_scenario.expected_revision_due_min
        if smoke_scenario.expected_revision_due_max is not None:
            assert revision_body["total_due_count"] <= smoke_scenario.expected_revision_due_max

        history_items = history_body["history"]
        if smoke_scenario.expected_history_count_min is not None:
            assert len(history_items) >= smoke_scenario.expected_history_count_min
        if smoke_scenario.expected_history_count_max is not None:
            assert len(history_items) <= smoke_scenario.expected_history_count_max
        for item in history_items:
            if smoke_scenario.expected_current_exam is not None:
                assert item["exam"] == smoke_scenario.expected_current_exam
            if smoke_scenario.expected_current_subject is not None:
                assert item["subject"] == smoke_scenario.expected_current_subject

        logout_response = client.post("/api/auth/logout")
        assert logout_response.status_code == 200


def test_smoke_settings_target_preserves_multi_exam_scenario_distinction() -> None:
    multi_exam_scenario = next(
        scenario
        for scenario in list_demo_smoke_scenarios()
        if scenario.key == "multi_exam_path"
    )
    resolved_target = ResolvedSmokeTarget(
        otp_email="multi_exam_user@adhyantra.test",
        exam=multi_exam_scenario.exam,
        subject=multi_exam_scenario.subject,
        topic=multi_exam_scenario.topic,
        scenario=multi_exam_scenario,
        email_source="scenario_default",
    )

    settings_target = _resolve_settings_persistence_target(resolved_target=resolved_target)

    assert settings_target == {
        "preferred_exam": "upsc",
        "preferred_subject": "polity",
        "current_exam": "banking",
        "current_subject": "regulatory_basics",
    }


def test_settings_update_can_preserve_multi_exam_seeded_context_split(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = default_demo_seed_anchor(datetime.now(UTC))

    db = session_factory()
    try:
        seeded_account = seed_demo_accounts(
            db,
            account_keys=["multi_exam_user"],
            anchor_time=anchor,
        )[0]
    finally:
        db.close()

    authenticate_test_user(
        client,
        email=seeded_account["email"],
        display_name=seeded_account["display_name"],
    )

    settings_payload = {
        "theme_preference": "light",
        "mentor_mode": "strict",
        "preferred_exam": "upsc",
        "preferred_subject": "polity",
        "current_exam": "banking",
        "current_subject": "regulatory_basics",
        "timezone": "Asia/Calcutta",
        "study_reminders_enabled": True,
        "marketing_emails_enabled": False,
        "progress_digest_frequency": "important_only",
        "billing_notifications_enabled": True,
    }
    update_response = client.put("/api/settings", json=settings_payload)
    assert update_response.status_code == 200
    assert update_response.json()["preferred_exam"] == "upsc"
    assert update_response.json()["current_exam"] == "banking"

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_settings = me_response.json()["settings"]
    assert me_settings["preferred_exam"] == "upsc"
    assert me_settings["preferred_subject"] == "polity"
    assert me_settings["current_exam"] == "banking"
    assert me_settings["current_subject"] == "regulatory_basics"

    summary_response = client.get("/api/progress/summary")
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert summary_body["exam"] == "banking"
    assert summary_body["subject"] == "regulatory_basics"
    assert summary_body["content_subject"] == "polity"


def test_reset_local_db_surfaces_locked_sqlite_state_helpfully(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePath:
        def __init__(self, raw_path: str, *, exists: bool = True, locked: bool = False):
            self.raw_path = raw_path
            self._exists = exists
            self._locked = locked

        def exists(self) -> bool:
            return self._exists

        def unlink(self) -> None:
            if self._locked:
                raise PermissionError(32, "The process cannot access the file because it is being used by another process")
            self._exists = False

        def as_posix(self) -> str:
            return self.raw_path.replace("\\", "/")

        def __str__(self) -> str:
            return self.raw_path

    active_db = _FakePath(r"C:\new project\exam-guru\exam_guru.db", locked=True)
    legacy_db = _FakePath(r"C:\new project\exam-guru\backend\exam_guru.db", exists=False)
    backup_path = _FakePath(r"C:\new project\exam-guru\backups\exam_guru-backup.sqlite3", exists=False)

    monkeypatch.setattr(local_db_tools, "require_sqlite_db_path", lambda: active_db)
    monkeypatch.setattr(local_db_tools.engine, "dispose", lambda: None)
    monkeypatch.setattr(local_db_tools, "backup_sqlite_db", lambda **kwargs: backup_path)
    monkeypatch.setattr(local_db_tools, "clear_demo_seed_marker", lambda: False)
    monkeypatch.setattr(local_db_tools, "init_db", lambda: None)
    monkeypatch.setattr(local_db_tools, "LEGACY_BACKEND_DB_FILE_PATH", legacy_db)

    with pytest.raises(RuntimeError) as excinfo:
        local_db_tools.reset_local_db()

    message = str(excinfo.value).lower()
    assert "locked by another process" in message
    assert "stop any running adhyantra backend/frontend server" in message


def test_seeded_revision_scenario_auto_selects_revision_quiz_mode_when_omitted(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = default_demo_seed_anchor(datetime.now(UTC))

    db = session_factory()
    try:
        seeded_account = seed_demo_accounts(
            db,
            scenario_key="weak_topic_repair",
            anchor_time=anchor,
        )[0]
    finally:
        db.close()

    authenticate_test_user(
        client,
        email=seeded_account["email"],
        display_name=seeded_account["display_name"],
    )

    summary_body = client.get("/api/progress/summary").json()
    assert summary_body["recommended_mode"] == "revise"
    focus_topic = summary_body["recommended_next_topic"]
    assert focus_topic == "Federalism"

    response = client.post(
        "/api/test/generate",
        json={"topic": focus_topic, "question_count": 5},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "revision"
    assert body["exam"] == summary_body["exam"]
    assert body["subject"] == summary_body["subject"]
    assert body["content_subject"] == summary_body["content_subject"]
    assert focus_topic in body["covered_topics"]
    assert "no quiz mode was specified" in body["quiz_mode_note"].lower()


def test_explicit_quiz_mode_still_overrides_seeded_revision_state(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = default_demo_seed_anchor(datetime.now(UTC))

    db = session_factory()
    try:
        seeded_account = seed_demo_accounts(
            db,
            scenario_key="weak_topic_repair",
            anchor_time=anchor,
        )[0]
    finally:
        db.close()

    authenticate_test_user(
        client,
        email=seeded_account["email"],
        display_name=seeded_account["display_name"],
    )

    response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5, "quiz_mode": "test"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "test"
    assert body["revision_targets"] == []
    assert "no quiz mode was specified" not in body["quiz_mode_note"].lower()


def test_multi_exam_seeded_revision_context_stays_aligned_through_quiz_submit(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    anchor = default_demo_seed_anchor(datetime.now(UTC))

    db = session_factory()
    try:
        seeded_account = seed_demo_accounts(
            db,
            scenario_key="revision_heavy",
            anchor_time=anchor,
        )[0]
    finally:
        db.close()

    authenticate_test_user(
        client,
        email=seeded_account["email"],
        display_name=seeded_account["display_name"],
    )

    me_body = client.get("/api/auth/me").json()
    assert me_body["settings"]["current_exam"] == "banking"
    assert me_body["settings"]["current_subject"] == "regulatory_basics"

    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5},
    )
    assert generate_response.status_code == 200
    generated_quiz = generate_response.json()

    assert generated_quiz["quiz_mode"] == "revision"
    assert generated_quiz["exam"] == "banking"
    assert generated_quiz["subject"] == "regulatory_basics"
    assert generated_quiz["content_subject"] == "polity"
    assert "no quiz mode was specified" in generated_quiz["quiz_mode_note"].lower()

    submit_response = client.post(
        "/api/test/submit",
        json={
            "quiz_id": generated_quiz["quiz_id"],
            "answers": get_correct_answers(client, generated_quiz),
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()

    assert submit_body["exam"] == "banking"
    assert submit_body["subject"] == "regulatory_basics"
    assert submit_body["content_subject"] == "polity"
    assert submit_body["progress_summary"]["exam"] == "banking"
    assert submit_body["progress_summary"]["subject"] == "regulatory_basics"
    assert submit_body["today_plan"]["exam"] == "banking"
    assert submit_body["today_plan"]["subject"] == "regulatory_basics"
    assert submit_body["coach_summary"]["exam"] == "banking"
    assert submit_body["coach_summary"]["subject"] == "regulatory_basics"


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["exam"] == "upsc"
    assert body["subject"] == "polity"
    assert body["environment"] == "development"
    assert body["version"]
    assert body["boot"]["status"] == "ready"
    assert body["readiness_endpoint"] == "/health/ready"
    assert body["mock_mode"] is True
    assert body["ai_mode"] == "mock"
    assert "mock fallback" in body["ai_note"].lower()
    assert body["security"]["secure_session_cookies"] is False
    assert body["security"]["session_cookie_samesite"] == "lax"
    assert body["security"]["session_ttl_seconds"] == 30 * 24 * 60 * 60
    assert body["security"]["session_idle_timeout_seconds"] == 0
    assert body["security"]["cors_origin_count"] >= 1
    assert body["security"]["cors_methods_wildcard"] is True
    assert body["security"]["cors_headers_wildcard"] is True
    assert body["security"]["trusted_host_count"] == 0
    assert body["security"]["config_validation"]["ok"] is True
    assert body["security"]["dev_otp_return_enabled"] is True
    assert body["database_type"] == "sqlite"
    active_db_path = get_active_sqlite_db_path()
    assert active_db_path is not None
    assert Path(body["db_path"]).resolve() == active_db_path.resolve()
    assert isinstance(body["demo_seeded"], bool)
    assert body["debug_runtime_context"] is None
    assert "demo" in body["data_note"].lower()


def test_health_redacts_deployed_database_locator(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    deployed_settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-live",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:super-secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        secure_session_cookies=True,
        media_render_worker_mode="external",
        media_storage_backend="supabase",
        supabase_url="https://storage.adhyantra.example",
        supabase_service_role_key="test-service-role-key",
        supabase_media_bucket="private-media",
        allow_sqlite_in_production=True,
    )
    monkeypatch.setattr(main_module, "settings", deployed_settings)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "production"
    assert body["database_type"] == "postgresql"
    assert body["db_path"] == "redacted"
    assert body["debug_runtime_context"] is None
    serialized = json.dumps(body).lower()
    assert "postgresql://adhyantra:super-secret@db.example.com/adhyantra" not in serialized
    assert "super-secret" not in serialized


def test_health_surfaces_demo_seed_debug_context_when_marker_matches_runtime_db(client: TestClient) -> None:
    marker_path = get_demo_seed_marker_path()
    original_marker = marker_path.read_text(encoding="utf-8") if marker_path.exists() else None
    sqlite_db_path = get_active_sqlite_db_path(get_settings().db_url)
    assert sqlite_db_path is not None

    marker_payload = {
        "db_path": sqlite_db_path.as_posix(),
        "mode": "demo_learning_scenario_seed",
        "scenario": "weak_topic_repair",
        "scenarios": ["weak_topic_repair"],
        "seeded_at": "2026-04-23T12:00:00+00:00",
        "note": "Deterministic Adhyantra learning scenario 'weak_topic_repair' was intentionally loaded for local QA/demo use.",
        "accounts": [
            {
                "key": "recovering_user",
            }
        ],
    }

    try:
        marker_path.write_text(json.dumps(marker_payload), encoding="utf-8")

        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["demo_seeded"] is True
        debug_context = body["debug_runtime_context"]
        assert debug_context is not None
        assert debug_context["visible"] is True
        assert debug_context["mode"] == "demo_learning_scenario_seed"
        assert debug_context["scenario"] == "weak_topic_repair"
        assert debug_context["scenarios"] == ["weak_topic_repair"]
        assert debug_context["account_keys"] == ["recovering_user"]
        assert debug_context["account_count"] == 1
        assert "qa/demo" in debug_context["note"].lower()
    finally:
        if original_marker is None:
            if marker_path.exists():
                marker_path.unlink()
        else:
            marker_path.write_text(original_marker, encoding="utf-8")


def test_auth_dev_otp_return_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.config import Settings

    monkeypatch.delenv("AUTH_DEV_RETURN_OTP", raising=False)

    local_settings = Settings(email_otp_delivery_mode="console")

    assert local_settings.auth_dev_return_otp is False
    assert local_settings.effective_dev_otp_return_enabled is False


def test_email_delivery_mode_never_enables_dev_otp_return() -> None:
    from backend.config import Settings

    local_settings = Settings(
        email_otp_delivery_mode="email",
        email_transport="smtp",
        email_from_address="hello@example.com",
        smtp_host="smtp.example.com",
        auth_dev_return_otp=True,
    )

    assert local_settings.effective_email_delivery_mode == "email"
    assert local_settings.effective_email_transport == "smtp"
    assert local_settings.effective_dev_otp_return_enabled is False


def test_liveness_endpoint_is_lightweight_and_backward_safe(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "adhyantra-api"
    assert body["environment"] == "development"
    assert body["boot"]["status"] == "ready"
    assert "checks" not in body
    assert "db_path" not in body


def test_readiness_endpoint_reports_boot_db_and_config_without_secrets(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["ready"] is True
    assert body["checks"]["boot"]["ok"] is True
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["ping"] == "ok"
    assert body["checks"]["database"]["schema"]["required_tables_present"] is True
    assert body["checks"]["database"]["schema_management"]["strategy"] == "local_sqlite_bootstrap_or_read_only_alembic_validation"
    assert body["checks"]["database"]["schema_management"]["destructive_auto_migrations"] is False
    assert body["checks"]["configuration"]["ok"] is True
    assert body["checks"]["media_render_worker"]["mode"] in {"embedded", "external", "disabled"}
    assert body["checks"]["media_render_worker"]["required_for_readiness"] is False
    assert isinstance(body["checks"]["media_render_worker"]["ready"], bool)
    assert "fresh_worker_count" not in body["checks"]["media_render_worker"]
    assert "latest_heartbeat_at" not in body["checks"]["media_render_worker"]
    assert body["checks"]["media_render_pipeline"]["mode"] in {"embedded", "external", "disabled"}
    assert body["checks"]["media_render_pipeline"]["required_for_readiness"] is False
    assert isinstance(body["checks"]["media_render_pipeline"]["ready"], bool)
    assert isinstance(body["checks"]["media_render_pipeline"]["storage_ready"], bool)
    assert "storage_root" not in body["checks"]["media_render_pipeline"]
    assert "storage_root_is_directory" not in body["checks"]["media_render_pipeline"]
    assert body["summary"]["ready"] is True
    assert body["summary"]["failure_reasons"] == []
    assert body["summary"]["boot_status"] == "ready"
    assert body["summary"]["database_status"] == "ready"
    assert body["summary"]["media_render_worker_required"] is False
    assert body["summary"]["media_render_pipeline_required"] is False
    assert body["summary"]["config_error_count"] == 0
    assert body["summary"]["email_delivery_mode"] in {"console", "email"}
    assert body["summary"]["email_transport"] in {"console", "smtp"}
    assert body["summary"]["secure_session_cookies"] is False
    assert body["runtime"]["email"]["delivery_mode"] in {"console", "email"}
    assert body["runtime"]["email"]["transport"] in {"console", "smtp"}
    assert body["runtime"]["email"]["external_delivery"] is False
    assert body["runtime"]["email"]["smtp_host_configured"] is False
    assert body["runtime"]["ai"]["mock_mode"] is True
    assert body["runtime"]["security"]["cors_methods_wildcard"] is True
    assert body["runtime"]["security"]["cors_headers_wildcard"] is True
    assert body["runtime"]["security"]["trusted_host_count"] == 0

    serialized = json.dumps(body).lower()
    assert "openai_api_key" not in serialized
    assert "smtp_password" not in serialized
    assert "session_token" not in serialized
    assert "sk-test" not in serialized


def test_readiness_failure_logs_safe_operational_summary(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="adhyantra.events")
    previous_status = client.app.state.boot_status
    previous_failed_at = client.app.state.boot_failed_at
    previous_failure_type = client.app.state.boot_failure_type
    client.app.state.boot_status = "failed"
    client.app.state.boot_failed_at = datetime.now(UTC).isoformat()
    client.app.state.boot_failure_type = "RuntimeError"

    try:
        response = client.get("/health/ready")
    finally:
        client.app.state.boot_status = previous_status
        client.app.state.boot_failed_at = previous_failed_at
        client.app.state.boot_failure_type = previous_failure_type

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["summary"]["failure_reasons"] == ["boot:failed"]

    log_text = "\n".join(record.getMessage() for record in caplog.records if record.name == "adhyantra.events")
    assert "event=ops.readiness_failed" in log_text
    assert "boot:failed" in log_text
    assert "session_token" not in log_text
    assert "smtp_password" not in log_text


def test_ready_alias_matches_readiness_contract(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["checks"]["database"]["ok"] is True


def test_readiness_requires_fresh_external_worker_in_deployed_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed_settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-live",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        secure_session_cookies=True,
        media_render_worker_mode="external",
        allow_sqlite_in_production=True,
    )
    monkeypatch.setattr(main_module, "settings", deployed_settings)
    monkeypatch.setattr(
        main_module,
        "database_readiness_snapshot",
        lambda: {
            "ok": True,
            "status": "ready",
            "database_type": "postgresql",
            "ping": "ok",
            "schema_management": {"strategy": "test"},
            "schema": {"required_tables_present": True},
        },
    )
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["summary"]["media_render_worker_required"] is True
    assert body["summary"]["media_render_worker_ready"] is False
    assert body["summary"]["media_render_pipeline_required"] is True
    assert body["summary"]["media_render_pipeline_ready"] is False
    assert "media_render_worker:unavailable" in body["summary"]["failure_reasons"]
    assert body["checks"]["media_render_worker"]["mode"] == "external"
    assert body["checks"]["media_render_worker"]["required_for_readiness"] is True
    assert "fresh_worker_count" not in body["checks"]["media_render_worker"]
    assert "latest_heartbeat_at" not in body["checks"]["media_render_worker"]
    assert body["checks"]["media_render_pipeline"]["required_for_readiness"] is True
    assert body["checks"]["media_render_pipeline"]["ready"] is False
    assert "worker_unavailable" in body["checks"]["media_render_pipeline"]["degraded_reasons"]


def test_readiness_accepts_fresh_external_worker_heartbeat_in_deployed_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed_settings = Settings(
        app_env="production",
        ai_provider="openai",
        ai_provider_chain="openai",
        openai_api_key="sk-live",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        tts_provider="gemini",
        gemini_api_key="unit-test-nonsecret-gemini-material",
        tts_gemini_model="gemini-2.5-flash-preview-tts",
        tts_gemini_voice="Kore",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        secure_session_cookies=True,
        media_render_worker_mode="external",
        media_storage_backend="supabase",
        supabase_url="https://storage.adhyantra.example",
        supabase_service_role_key="test-service-role-key",
        supabase_media_bucket="private-media",
        allow_sqlite_in_production=True,
    )
    monkeypatch.setattr(main_module, "settings", deployed_settings)
    monkeypatch.setattr(
        main_module,
        "database_readiness_snapshot",
        lambda: {
            "ok": True,
            "status": "ready",
            "database_type": "postgresql",
            "ping": "ok",
            "schema_management": {"strategy": "test"},
            "schema": {"required_tables_present": True},
        },
    )

    monkeypatch.setattr(
        main_module,
        "build_media_render_pipeline_snapshot",
        lambda *args, **kwargs: {
            "required_for_readiness": True,
            "ready": True,
            "submission_ready": True,
            "storage_ready": True,
        },
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        upsert_runtime_process_heartbeat(
            db,
            service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
            process_role="worker",
            runtime_instance_id="external-worker-1",
            environment="production",
            worker_mode="external",
            status="running",
            metadata={"source": "test"},
        )
    finally:
        db.close()

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["summary"]["media_render_worker_required"] is True
    assert body["summary"]["media_render_worker_ready"] is True
    assert body["summary"]["media_render_pipeline_required"] is True
    assert body["summary"]["media_render_pipeline_ready"] is True
    assert "fresh_worker_count" not in body["checks"]["media_render_worker"]
    assert "latest_heartbeat_at" not in body["checks"]["media_render_worker"]
    assert body["checks"]["media_render_pipeline"]["required_for_readiness"] is True
    assert body["checks"]["media_render_pipeline"]["ready"] is True


def test_readiness_requires_embedded_worker_in_deployed_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from backend.services.media_storage_service import initialize_media_render_storage

    deployed_settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-live",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        secure_session_cookies=True,
        media_render_worker_mode="embedded",
        media_render_output_dir=str(tmp_path / "embedded-render-output"),
        allow_sqlite_in_production=True,
    )
    initialize_media_render_storage(deployed_settings)
    monkeypatch.setattr(main_module, "settings", deployed_settings)
    monkeypatch.setattr(
        main_module,
        "database_readiness_snapshot",
        lambda: {
            "ok": True,
            "status": "ready",
            "database_type": "postgresql",
            "ping": "ok",
            "schema_management": {"strategy": "test"},
            "schema": {"required_tables_present": True},
        },
    )
    previous_dispatcher = client.app.state.media_render_dispatcher
    client.app.state.media_render_dispatcher = None

    try:
        response = client.get("/health/ready")
    finally:
        client.app.state.media_render_dispatcher = previous_dispatcher

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["summary"]["media_render_worker_required"] is True
    assert body["summary"]["media_render_worker_ready"] is False
    assert body["summary"]["media_render_pipeline_required"] is True
    assert body["summary"]["media_render_pipeline_ready"] is False
    assert "media_render_worker:unavailable" in body["summary"]["failure_reasons"]
    assert body["checks"]["media_render_worker"]["mode"] == "embedded"
    assert body["checks"]["media_render_worker"]["required_for_readiness"] is True
    assert body["checks"]["media_render_pipeline"]["required_for_readiness"] is True
    assert body["checks"]["media_render_pipeline"]["storage_ready"] is True
    assert "worker_unavailable" in body["checks"]["media_render_pipeline"]["degraded_reasons"]


def test_readiness_requires_media_pipeline_storage_in_deployed_embedded_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked_storage_root = tmp_path / "blocked-render-output"
    blocked_storage_root.write_text("not-a-directory", encoding="utf-8")
    deployed_settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-live",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        trusted_hosts="api.adhyantra.example",
        secure_session_cookies=True,
        media_render_worker_mode="embedded",
        media_render_output_dir=str(blocked_storage_root),
        allow_sqlite_in_production=True,
    )
    monkeypatch.setattr(main_module, "settings", deployed_settings)
    monkeypatch.setattr(
        main_module,
        "database_readiness_snapshot",
        lambda: {
            "ok": True,
            "status": "ready",
            "database_type": "postgresql",
            "ping": "ok",
            "schema_management": {"strategy": "test"},
            "schema": {"required_tables_present": True},
        },
    )
    previous_dispatcher = client.app.state.media_render_dispatcher
    client.app.state.media_render_dispatcher = SimpleNamespace(is_running=True, worker_id="embedded-health-test")

    try:
        response = client.get("/health/ready")
    finally:
        client.app.state.media_render_dispatcher = previous_dispatcher

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["summary"]["media_render_worker_ready"] is True
    assert body["summary"]["media_render_pipeline_required"] is True
    assert body["summary"]["media_render_pipeline_ready"] is False
    assert body["summary"]["media_render_pipeline_storage_ready"] is False
    assert "media_render_pipeline:storage_unavailable" in body["summary"]["failure_reasons"]
    assert body["checks"]["media_render_pipeline"]["required_for_readiness"] is True
    assert body["checks"]["media_render_pipeline"]["submission_ready"] is False
    assert body["checks"]["media_render_pipeline"]["storage_ready"] is False
    assert "storage_root_is_directory" not in body["checks"]["media_render_pipeline"]
    assert "storage_unavailable" in body["checks"]["media_render_pipeline"]["degraded_reasons"]


def test_structured_logger_redacts_secret_shaped_fields(caplog: pytest.LogCaptureFixture) -> None:
    from backend.services.ops_logging import log_event

    test_logger = logging.getLogger("adhyantra.events")
    caplog.set_level(logging.INFO, logger="adhyantra.events")

    log_event(
        test_logger,
        logging.INFO,
        "ops.redaction_test",
        session_token="super-secret-session-token",
        smtp_password="smtp-secret",
        openai_api_key="sk-test-secret",
        otp_code="123456",
        token_fingerprint="safe-fingerprint",
        email_hash="safe-email-hash",
        status_code=200,
    )

    log_text = "\n".join(record.getMessage() for record in caplog.records if record.name == "adhyantra.events")
    assert "super-secret-session-token" not in log_text
    assert "smtp-secret" not in log_text
    assert "sk-test-secret" not in log_text
    assert "123456" not in log_text
    assert "session_token=\"[redacted]\"" in log_text
    assert "smtp_password=\"[redacted]\"" in log_text
    assert "openai_api_key=\"[redacted]\"" in log_text
    assert "otp_code=\"[redacted]\"" in log_text
    assert "token_fingerprint=\"safe-fingerprint\"" in log_text
    assert "email_hash=\"safe-email-hash\"" in log_text
    assert "status_code=200" in log_text


def test_development_config_validation_keeps_local_defaults_easy() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="development",
        ai_provider="mock",
        db_url="sqlite:///./exam_guru.db",
        email_otp_delivery_mode="console",
        frontend_origin="http://localhost:3000",
    )

    result = settings.validate_runtime_config()

    assert result.ok is True
    assert not result.errors


def test_run_staging_backend_invokes_uvicorn_directly_with_forwarded_allow_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_staging_backend

    recorded: dict[str, Any] = {}

    monkeypatch.setattr(run_staging_backend, "_validate_config", lambda: 0)
    monkeypatch.setattr(run_staging_backend, "_load_optional_env_file", lambda env_file, override: None)

    def fake_uvicorn_run(app: str, **kwargs: Any) -> None:
        recorded["app"] = app
        recorded.update(kwargs)

    monkeypatch.setattr(run_staging_backend.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_staging_backend.py",
            "--host",
            "127.0.0.1",
            "--port",
            "8014",
        ],
    )

    exit_code = run_staging_backend.main()

    assert exit_code == 0
    assert recorded["app"] == "backend.main:app"
    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 8014
    assert recorded["proxy_headers"] is True
    assert recorded["forwarded_allow_ips"] == "*"


def test_mistral_is_testing_only_and_not_in_default_live_chain() -> None:
    from backend.config import Settings

    default_live_settings = Settings(
        app_env="development",
        ai_provider="gemini",
        ai_provider_chain="",
        gemini_api_key="gemini-key",
        groq_api_key="groq-key",
    )
    qa_settings = Settings(
        app_env="development",
        ai_provider="mistral",
        ai_provider_chain="mistral,mock",
        mistral_api_key="mistral-key",
    )
    staging_settings = Settings(
        app_env="staging",
        ai_provider="mistral",
        ai_provider_chain="mistral,mock",
        mistral_api_key="mistral-key",
    )

    assert default_live_settings.effective_ai_provider_chain == ("gemini", "groq", "mock")
    assert "mistral" not in default_live_settings.effective_ai_provider_chain
    assert qa_settings.validate_runtime_config().ok is True
    assert qa_settings.effective_ai_provider_chain == ("mistral", "mock")

    staging_result = staging_settings.validate_runtime_config()
    assert "mistral_testing_only" in {issue.code for issue in staging_result.errors}


def test_environment_policy_aliases_are_canonical_and_explicit() -> None:
    from backend.config import Settings

    development = Settings(app_env="dev", frontend_origin="http://localhost:3000")
    staging = Settings(app_env="stage", frontend_origin="https://staging.adhyantra.example")
    production = Settings(app_env="prod", frontend_origin="https://app.adhyantra.example")

    assert development.environment_name == "development"
    assert development.environment_policy.name == "development"
    assert development.environment_policy.include_dev_cors_origins is True
    assert development.deployed_mode is False

    assert staging.environment_name == "staging"
    assert staging.environment_policy.name == "staging"
    assert staging.staging_mode is True
    assert staging.deployed_mode is True
    assert staging.effective_secure_session_cookies is True
    assert staging.environment_policy_summary()["require_real_email_delivery"] is True

    assert production.environment_name == "production"
    assert production.environment_policy.name == "production"
    assert production.production_mode is True
    assert production.deployed_mode is True
    assert production.environment_policy_summary()["mock_ai_issue_severity"] == "error"


def test_staging_config_validation_uses_deployed_safety_rules() -> None:
    from backend.config import ConfigValidationError, Settings

    settings = Settings(
        app_env="staging",
        ai_provider="mock",
        db_url="sqlite:///./exam_guru.db",
        email_otp_delivery_mode="console",
        frontend_origin="http://localhost:3000",
    )

    result = settings.validate_runtime_config()
    error_codes = {issue.code for issue in result.errors}
    warning_codes = {issue.code for issue in result.warnings}

    assert result.ok is False
    assert result.staging is True
    assert result.deployed is True
    assert settings.effective_secure_session_cookies is True
    assert "http://127.0.0.1:3000" not in settings.effective_cors_allowed_origins
    assert "*" not in settings.effective_cors_allowed_methods
    assert "*" not in settings.effective_cors_allowed_headers
    assert "console_email_in_staging" in error_codes
    assert "localhost_frontend_origin" in error_codes
    assert "mock_ai_in_staging" in warning_codes
    assert "sqlite_in_staging" in warning_codes

    with pytest.raises(ConfigValidationError):
        settings.enforce_startup_config()


def test_production_config_validation_blocks_unsafe_defaults() -> None:
    from backend.config import ConfigValidationError, Settings

    settings = Settings(
        app_env="production",
        ai_provider="mock",
        db_url="sqlite:///./exam_guru.db",
        email_otp_delivery_mode="console",
        frontend_origin="http://localhost:3000",
    )

    result = settings.validate_runtime_config()
    error_codes = {issue.code for issue in result.errors}

    assert result.ok is False
    assert "mock_ai_in_production" in error_codes
    assert "console_email_in_production" in error_codes
    assert "sqlite_in_production" in error_codes
    assert "localhost_frontend_origin" in error_codes

    with pytest.raises(ConfigValidationError):
        settings.enforce_production_config()


def test_production_config_validation_accepts_explicit_safe_config() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="production",
        ai_provider="openai",
        ai_provider_chain="openai",
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        tts_provider="gemini",
        gemini_api_key="unit-test-nonsecret-gemini-material",
        tts_gemini_model="gemini-2.5-flash-preview-tts",
        tts_gemini_voice="Kore",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        auth_dev_return_otp=False,
        media_storage_backend="supabase",
        supabase_url="https://storage.adhyantra.example",
        supabase_service_role_key="test-service-role-key",
        supabase_media_bucket="private-media",
    )

    result = settings.enforce_production_config()

    assert result.ok is True
    assert not result.errors
    assert settings.effective_email_delivery_mode == "email"
    assert settings.effective_email_transport == "smtp"
    assert settings.effective_cors_allowed_origins == ("https://app.adhyantra.example",)
    assert settings.effective_cors_allowed_methods == ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
    assert settings.effective_cors_allowed_headers == ("Accept", "Authorization", "Content-Type", "X-Requested-With", "X-Request-ID")
    assert settings.effective_trusted_hosts == ("api.adhyantra.example",)


def test_production_api_config_requires_backend_public_url_for_deployed_startup() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
        openai_base_url="https://api.openai.com/v1",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="smtp",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_timeout_seconds=15,
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="",
        auth_dev_return_otp=False,
    )

    result = settings.validate_runtime_config(process_role="api")
    error_codes = {issue.code for issue in result.errors}

    assert "missing_backend_public_url" in error_codes
    assert "missing_trusted_hosts" in error_codes


def test_worker_config_validation_skips_api_only_deployed_checks_but_rejects_placeholder_worker_secrets() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="production",
        ai_provider="mock",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="console",
        frontend_origin="http://localhost:3000",
        backend_public_url="",
        tts_provider="openai",
        tts_openai_api_key="replace-me",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_base_url="https://api.openai.com/v1",
        tts_openai_voice="alloy",
        media_render_worker_mode="external",
    )

    result = settings.validate_runtime_config(process_role="worker")
    error_codes = {issue.code for issue in result.errors}

    assert "console_email_in_production" not in error_codes
    assert "localhost_frontend_origin" not in error_codes
    assert "missing_backend_public_url" not in error_codes
    assert "mock_ai_in_production" not in error_codes
    assert "placeholder_tts_openai_key" in error_codes


def test_deployed_worker_process_rejects_disabled_worker_mode() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="production",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        media_render_worker_mode="disabled",
    )

    result = settings.validate_runtime_config(process_role="worker")
    error_codes = {issue.code for issue in result.errors}

    assert "worker_mode_disabled" in error_codes


def test_deployed_config_rejects_wildcard_cors_methods_and_headers() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="production",
        ai_provider="openai",
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
        db_url="postgresql://adhyantra:secret@db.example.com/adhyantra",
        email_otp_delivery_mode="email",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        frontend_origin="https://app.adhyantra.example",
        backend_public_url="https://api.adhyantra.example",
        cors_allowed_methods="*",
        cors_allowed_headers="*",
        auth_dev_return_otp=False,
    )

    result = settings.validate_runtime_config()
    error_codes = {issue.code for issue in result.errors}

    assert "wildcard_cors_methods_in_deployed" in error_codes
    assert "wildcard_cors_headers_in_deployed" in error_codes


def test_invalid_session_cookie_domain_is_rejected() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="development",
        db_url="sqlite:///./exam_guru.db",
        frontend_origin="http://localhost:3000",
        session_cookie_domain="https://adhyantra.example/app",
    )

    result = settings.validate_runtime_config()
    error_codes = {issue.code for issue in result.errors}

    assert "invalid_cookie_domain" in error_codes


def test_real_email_config_rejects_unsupported_transport() -> None:
    from backend.config import Settings

    settings = Settings(
        app_env="staging",
        ai_provider="mock",
        db_url="sqlite:///./exam_guru.db",
        email_otp_delivery_mode="email",
        email_transport="sendgrid",
        email_from_address="hello@adhyantra.example",
        smtp_host="smtp.example.com",
        frontend_origin="https://staging.adhyantra.example",
        backend_public_url="https://api-staging.adhyantra.example",
    )

    result = settings.validate_runtime_config()
    error_codes = {issue.code for issue in result.errors}

    assert "unsupported_email_transport" in error_codes


def test_request_and_verify_otp_create_user_session_and_profile(client: TestClient) -> None:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "learner@example.com", "display_name": "Learner One"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()

    assert request_body["email"] == "learner@example.com"
    assert request_body["masked_email"].endswith("@example.com")
    assert request_body["delivery_mode"] == "console"
    assert request_body["dev_otp_code"]
    assert request_body["is_new_user"] is True

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "learner@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200
    verify_body = verify_response.json()

    assert verify_body["authenticated"] is True
    assert verify_body["user"]["email"] == "learner@example.com"
    assert verify_body["user"]["display_name"] == "Learner One"
    assert verify_body["user"]["email_verified"] is True
    assert verify_body["user"]["subscription_plan"] == "free"
    assert verify_body["user"]["subscription_status"] == "inactive"
    assert verify_body["user"]["last_active_at"] is not None
    assert verify_body["user"]["account_role"] == "student"
    assert verify_body["user"]["admin_access"]["is_admin"] is False
    assert verify_body["user"]["admin_access"]["privileges"] == []
    assert verify_body["user"]["billing"]["billing_email"] == "learner@example.com"
    assert verify_body["user"]["billing"]["portal_ready"] is False
    assert verify_body["user"]["feature_access"]["advanced_analytics"] is False
    assert verify_body["user"]["feature_access"]["team_management"] is False
    assert verify_body["settings"]["theme_preference"] == "system"
    assert verify_body["settings"]["mentor_mode"] == "normal"
    assert verify_body["settings"]["preferred_exam"] == "upsc"
    assert verify_body["settings"]["preferred_subject"] == "polity"
    assert verify_body["settings"]["progress_digest_frequency"] == "important_only"
    assert verify_body["settings"]["billing_notifications_enabled"] is True
    assert client.cookies.get("exam_guru_session")

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["user"]["email"] == "learner@example.com"
    assert me_body["settings"]["preferred_exam"] == "upsc"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "learner@example.com").first()
        assert user is not None
        assert user.email_verified_at is not None
        assert user.auth_status == "verified"
        assert user.primary_auth_method == "email_otp"
        assert user.billing_email == "learner@example.com"
        assert user.settings is not None
        assert user.settings.study_reminders_enabled is True
        assert user.settings.marketing_emails_enabled is False
        assert user.settings.progress_digest_frequency == "important_only"
        assert user.settings.billing_notifications_enabled is True
        profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        assert profile is not None
        assert profile.avatar_initials == "LO"
        assert profile.onboarding_state == "new"
        assert profile.onboarding_completed_at is None
        assert user.last_active_at is not None
        assert user.feature_access_overrides_json == "{}"
        assert user.account_role == "student"
        assert user.admin_privileges_json == "[]"
        assert db.query(UserSession).count() == 1
        session = db.query(UserSession).first()
        assert session is not None
        assert session.auth_method == "email_otp"
        assert session.last_authenticated_at is not None
        challenge = db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "learner@example.com").first()
        assert challenge is not None
        assert challenge.verified_at is not None
        assert challenge.consumed_at is not None
    finally:
        db.close()


def test_admin_content_routes_reject_anonymous_and_student_users(client: TestClient) -> None:
    anonymous_response = client.get("/api/admin/content/access")
    assert anonymous_response.status_code == 401

    authenticate_test_user(client, email="student-admin-check@example.com")

    access_response = client.get("/api/admin/content/access")
    assert access_response.status_code == 403
    detail = access_response.json()["detail"]
    assert detail["required_privilege"] == "content_read"
    assert detail["account_role"] == "student"
    assert detail["admin_access"] is False

    subjects_response = client.get("/api/subjects")
    assert subjects_response.status_code == 200


def test_admin_content_routes_allow_backend_admin_role(client: TestClient) -> None:
    email = "content-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Content Admin")
    assert auth_body["user"]["admin_access"]["is_admin"] is False

    refreshed_auth = grant_admin_role(client, email=email, role="content_admin")
    assert refreshed_auth["user"]["account_role"] == "content_admin"
    assert refreshed_auth["user"]["admin_access"]["is_admin"] is True
    assert "content_publish" in refreshed_auth["user"]["admin_access"]["privileges"]

    access_response = client.get("/api/admin/content/access")
    assert access_response.status_code == 200
    access_body = access_response.json()
    assert access_body["role"] == "content_admin"
    assert access_body["can_manage_content"] is True

    overview_response = client.get("/api/admin/content/overview")
    assert overview_response.status_code == 200
    overview_body = overview_response.json()
    assert overview_body["status"] == "admin_content_foundation_ready"
    assert "published" in overview_body["lifecycle_states"]
    assert any(item["exam"] == "upsc" for item in overview_body["corpora"])
    assert "content_insights" in overview_body
    assert overview_body["content_insights"]["window_days"] == 30


def test_admin_media_ops_routes_reject_anonymous_and_student_users(client: TestClient) -> None:
    anonymous_response = client.get("/api/admin/ops/media-render")
    assert anonymous_response.status_code == 401

    authenticate_test_user(client, email="student-media-ops@example.com")

    access_response = client.get("/api/admin/ops/media-render")
    assert access_response.status_code == 403
    detail = access_response.json()["detail"]
    assert detail["required_privilege"] == "content_qa"
    assert detail["account_role"] == "student"
    assert detail["admin_access"] is False


def test_admin_ops_overview_routes_reject_anonymous_and_student_users(client: TestClient) -> None:
    anonymous_response = client.get("/api/admin/ops/overview")
    assert anonymous_response.status_code == 401

    authenticate_test_user(client, email="student-ops-overview@example.com")

    access_response = client.get("/api/admin/ops/overview")
    assert access_response.status_code == 403
    detail = access_response.json()["detail"]
    assert detail["required_privilege"] == "content_qa"
    assert detail["account_role"] == "student"
    assert detail["admin_access"] is False


def test_admin_billing_ops_routes_reject_anonymous_and_student_users(client: TestClient) -> None:
    anonymous_response = client.get("/api/admin/ops/billing")
    assert anonymous_response.status_code == 401

    authenticate_test_user(client, email="student-billing-ops@example.com")

    access_response = client.get("/api/admin/ops/billing")
    assert access_response.status_code == 403
    detail = access_response.json()["detail"]
    assert detail["required_privilege"] == "content_qa"
    assert detail["account_role"] == "student"
    assert detail["admin_access"] is False


def test_admin_support_ops_routes_reject_anonymous_and_student_users(client: TestClient) -> None:
    anonymous_response = client.get("/api/admin/ops/support?email=student-support-ops@example.com")
    assert anonymous_response.status_code == 401

    authenticate_test_user(client, email="student-support-ops@example.com")

    access_response = client.get("/api/admin/ops/support?email=student-support-ops@example.com")
    assert access_response.status_code == 403
    detail = access_response.json()["detail"]
    assert detail["required_privilege"] == "content_qa"
    assert detail["account_role"] == "student"
    assert detail["admin_access"] is False


def test_admin_billing_ops_overview_exposes_checkout_portal_webhook_and_subscription_visibility(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_ops_service

    admin_auth = authenticate_test_user(client, email="billing-ops-admin@example.com", display_name="Billing Ops Admin")
    grant_admin_role(client, email="billing-ops-admin@example.com", role="content_admin")
    admin_user_id = admin_auth["user"]["id"]
    admin_session_cookie = client.cookies.get(get_settings().session_cookie_name)
    assert admin_session_cookie
    free_auth = authenticate_test_user(client, email="billing-ops-free@example.com", display_name="Billing Ops Free")
    free_user_id = free_auth["user"]["id"]
    premium_auth = authenticate_premium_test_user(client, email="billing-ops-premium@example.com", display_name="Billing Ops Premium")
    premium_user_id = premium_auth["user"]["id"]

    monkeypatch.setattr(
        billing_ops_service,
        "get_settings",
        lambda: Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="stripe",
            payment_premium_price_id="price_premium_monthly",
            payment_stripe_secret_key="sk_test_adhyantra",
            payment_stripe_webhook_secret="whsec_adhyantra",
        ),
    )
    monkeypatch.setattr(
        billing_ops_service,
        "get_payment_provider",
        lambda: SimpleNamespace(provider_name="stripe", enabled=True),
    )

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        premium_user = db.query(UserAccount).filter(UserAccount.id == premium_user_id).first()
        assert premium_user is not None
        premium_user.subscription_customer_ref = "cus_billing_ops_123"
        premium_user.subscription_provider_ref = "sub_billing_ops_123"
        premium_user.subscription_status = "past_due"
        premium_user.subscription_plan = "premium"
        premium_user.subscription_current_period_end = now + timedelta(days=3)
        db.add(premium_user)

        admin_user = db.query(UserAccount).filter(UserAccount.id == admin_user_id).first()
        assert admin_user is not None
        admin_user.subscription_customer_ref = "cus_admin_ops_123"
        admin_user.subscription_provider_ref = "sub_admin_ops_123"
        admin_user.subscription_status = "active"
        admin_user.subscription_plan = "premium"
        admin_user.subscription_cancel_at_period_end = True
        admin_user.subscription_current_period_end = now + timedelta(days=10)
        db.add(admin_user)

        db.add_all(
            [
                BillingEventReceipt(
                    provider_name="stripe",
                    provider_event_id="evt_billing_ops_processed",
                    event_type="checkout.session.completed",
                    livemode=False,
                    processing_state="processed",
                    user_id=free_user_id,
                    customer_ref="cus_billing_ops_processed",
                    subscription_ref="sub_billing_ops_processed",
                    payload_json="{}",
                    delivery_attempt_count=1,
                    duplicate_delivery_count=0,
                    processing_attempt_count=1,
                    event_created_at=now - timedelta(minutes=18),
                    first_received_at=now - timedelta(minutes=17),
                    last_received_at=now - timedelta(minutes=17),
                    processed_at=now - timedelta(minutes=16),
                    resolved_lifecycle_state="active",
                    resolved_plan_tier="premium",
                    resolved_subscription_status="active",
                    resolved_premium_quota_state="current",
                    resolution_note="Checkout completion synced premium subscription state.",
                ),
                BillingEventReceipt(
                    provider_name="stripe",
                    provider_event_id="evt_billing_ops_duplicate",
                    event_type="invoice.payment_failed",
                    livemode=False,
                    processing_state="processed",
                    user_id=premium_user_id,
                    customer_ref="cus_billing_ops_123",
                    subscription_ref="sub_billing_ops_123",
                    payload_json="{}",
                    delivery_attempt_count=3,
                    duplicate_delivery_count=2,
                    processing_attempt_count=1,
                    event_created_at=now - timedelta(minutes=12),
                    first_received_at=now - timedelta(minutes=11),
                    last_received_at=now - timedelta(minutes=9),
                    processed_at=now - timedelta(minutes=10),
                    resolved_lifecycle_state="past_due",
                    resolved_plan_tier="premium",
                    resolved_subscription_status="past_due",
                    resolved_premium_quota_state="payment_recovery",
                    resolution_note="Invoice payment failure moved the subscription into payment-recovery state.",
                ),
                BillingEventReceipt(
                    provider_name="stripe",
                    provider_event_id="evt_billing_ops_failed",
                    event_type="customer.subscription.updated",
                    livemode=False,
                    processing_state="failed",
                    user_id=admin_user_id,
                    customer_ref="cus_admin_ops_123",
                    subscription_ref="sub_admin_ops_123",
                    payload_json="{}",
                    delivery_attempt_count=1,
                    duplicate_delivery_count=0,
                    processing_attempt_count=2,
                    event_created_at=now - timedelta(minutes=8),
                    first_received_at=now - timedelta(minutes=7),
                    last_received_at=now - timedelta(minutes=7),
                    failed_at=now - timedelta(minutes=6),
                    processing_error="RuntimeError: webhook_processing_failed",
                ),
            ]
        )

        record_analytics_event(
            db,
            event_name="billing.checkout_started",
            feature_area="billing",
            user_id=free_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "started",
                "customer_ref_present": False,
                "return_path": "/settings",
                "plan_tier": "premium",
            },
        )
        record_analytics_event(
            db,
            event_name="billing.checkout_blocked",
            feature_area="billing",
            user_id=admin_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "already_active",
                "customer_ref_present": True,
                "return_path": "/settings",
            },
        )
        record_analytics_event(
            db,
            event_name="billing.portal_started",
            feature_area="billing",
            user_id=admin_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "started",
                "existing_customer_ref": "cus_admin_ops_123",
                "return_path": "/settings",
            },
        )
        record_analytics_event(
            db,
            event_name="billing.portal_unavailable",
            feature_area="billing",
            user_id=premium_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "provider_error",
                "customer_ref_present": True,
                "return_path": "/settings",
            },
        )
        db.commit()
    finally:
        db.close()

    client.cookies.set(get_settings().session_cookie_name, admin_session_cookie)

    response = client.get("/api/admin/ops/billing?sample_limit=5&window_days=7")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "admin_billing_ops_ready"
    assert body["admin_access"]["is_admin"] is True
    assert "content_qa" in body["admin_access"]["privileges"]
    assert body["provider"]["provider_name"] == "stripe"
    assert body["provider"]["provider_enabled"] is True
    assert body["provider"]["checkout_configured"] is True
    assert body["provider"]["portal_configured"] is True
    assert body["provider"]["webhook_configured"] is True
    assert body["validation"]["validation_state"] == "blocked"
    assert body["validation"]["provider_config_ready"] is True
    assert body["validation"]["checkout_ready"] is True
    assert body["validation"]["webhook_ready"] is False
    assert body["validation"]["subscription_sync_ready"] is False
    assert body["validation"]["blocker_count"] >= 2
    assert any("processing" in item.lower() for item in body["validation"]["blockers"])
    assert any("payment-recovery learners" in item.lower() for item in body["validation"]["recommended_checks"])

    assert body["checkout"]["successful_count"] >= 1
    assert body["checkout"]["blocked_count"] >= 1
    assert body["checkout"]["ready_account_count"] == 1
    assert body["checkout"]["recent_outcome_counts"]["billing.checkout_started"] >= 1
    assert body["checkout"]["recent_outcome_counts"]["billing.checkout_blocked"] >= 1

    assert body["portal"]["successful_count"] >= 1
    assert body["portal"]["unavailable_count"] >= 1
    assert body["portal"]["customer_linked_account_count"] >= 2

    assert body["webhook"]["receipt_counts"]["processed"] >= 2
    assert body["webhook"]["receipt_counts"]["failed"] >= 1
    assert body["webhook"]["duplicate_receipt_count"] >= 1
    assert body["webhook"]["duplicate_delivery_count"] >= 2
    webhook_ids = {item["provider_event_id"] for item in body["webhook"]["samples"]}
    assert "evt_billing_ops_duplicate" in webhook_ids
    assert "evt_billing_ops_failed" in webhook_ids

    assert body["subscriptions"]["tracked_account_count"] >= 2
    assert body["subscriptions"]["customer_linked_account_count"] >= 2
    assert body["subscriptions"]["provider_linked_account_count"] >= 2
    assert body["subscriptions"]["lifecycle_state_counts"]["past_due"] >= 1
    assert body["subscriptions"]["lifecycle_state_counts"]["canceling"] >= 1
    assert body["subscriptions"]["payment_action_required_count"] >= 1
    assert body["subscriptions"]["canceling_count"] >= 1
    assert body["subscriptions"]["attention_account_count"] >= 1
    assert "Internal billing operations visibility only" in body["route_note"]


def test_phase37_invalid_razorpay_webhook_signature_is_captured_for_admin_ops(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import billing_ops_service, billing_webhook_service
    from backend.services.payment_provider_service import PaymentSignatureVerificationError

    authenticate_test_user(client, email="phase37-razorpay-webhook-admin@example.com", display_name="Phase 37 Razorpay Webhook Admin")
    grant_admin_role(client, email="phase37-razorpay-webhook-admin@example.com", role="content_admin")
    admin_session_cookie = client.cookies.get(get_settings().session_cookie_name)
    assert admin_session_cookie

    monkeypatch.setattr(
        billing_ops_service,
        "get_settings",
        lambda: Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_live_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )
    monkeypatch.setattr(
        billing_ops_service,
        "get_payment_provider",
        lambda: SimpleNamespace(provider_name="razorpay", enabled=True),
    )

    class FakeProvider:
        provider_name = "razorpay"
        enabled = True

        def verify_webhook_signature(self, payload, *, signature_header, event_id_header=None):
            raise PaymentSignatureVerificationError("invalid signature")

    monkeypatch.setattr(billing_webhook_service, "get_payment_provider", lambda: FakeProvider())

    payload = {
        "entity": "event",
        "event": "subscription.activated",
        "created_at": int(datetime.now(UTC).timestamp()),
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_razorpay_invalid_signature",
                    "customer_id": "cust_razorpay_invalid_signature",
                }
            }
        },
    }

    response = client.post(
        "/api/account/billing/webhook",
        content=json.dumps(payload),
        headers={
            "x-razorpay-signature": "bad-signature",
            "x-razorpay-event-id": "evt_razorpay_invalid_signature",
        },
    )
    assert response.status_code == 400

    receipts = get_billing_event_receipts(
        client,
        provider_name="razorpay",
        provider_event_id="evt_razorpay_invalid_signature",
    )
    assert len(receipts) == 1
    assert receipts[0].processing_state == "verification_failed"
    assert receipts[0].event_type == "subscription.activated"
    assert receipts[0].customer_ref is None
    assert receipts[0].subscription_ref is None

    client.cookies.set(get_settings().session_cookie_name, admin_session_cookie)

    billing_response = client.get("/api/admin/ops/billing")
    assert billing_response.status_code == 200
    billing_body = billing_response.json()
    assert billing_body["provider"]["provider_name"] == "razorpay"
    assert billing_body["provider"]["portal_configured"] is False
    assert billing_body["validation"]["validation_state"] == "blocked"
    assert billing_body["validation"]["webhook_ready"] is False
    assert billing_body["validation"]["subscription_sync_ready"] is False
    assert billing_body["validation"]["blocker_count"] >= 1
    assert billing_body["webhook"]["verification_failed_count"] >= 1
    assert billing_body["webhook"]["verification_recent_outcome_counts"]["verification_failed"] >= 1
    assert billing_body["webhook"]["latest_verification_failed_at"] is not None
    webhook_ids = {item["provider_event_id"] for item in billing_body["webhook"]["samples"]}
    assert "evt_razorpay_invalid_signature" in webhook_ids


def test_admin_observability_surfaces_reconcile_time_based_subscription_state(client: TestClient) -> None:
    authenticate_test_user(client, email="ops-reconcile-admin@example.com", display_name="Ops Reconcile Admin")
    grant_admin_role(client, email="ops-reconcile-admin@example.com", role="content_admin")
    admin_session_cookie = client.cookies.get(get_settings().session_cookie_name)
    assert admin_session_cookie

    learner_email = "ops-reconcile-learner@example.com"
    learner_auth = authenticate_test_user(client, email=learner_email, display_name="Ops Reconcile Learner")
    learner_user_id = learner_auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        learner = db.query(UserAccount).filter(UserAccount.id == learner_user_id).first()
        assert learner is not None
        learner.billing_email = learner_email
        learner.subscription_plan = "premium"
        learner.subscription_status = "active"
        learner.subscription_customer_ref = "cus_ops_reconcile"
        learner.subscription_provider_ref = "sub_ops_reconcile"
        learner.subscription_current_period_end = now - timedelta(days=2)
        learner.subscription_cancel_at_period_end = True
        db.add(learner)
        db.commit()
    finally:
        db.close()

    client.cookies.set(get_settings().session_cookie_name, admin_session_cookie)

    billing_response = client.get("/api/admin/ops/billing")
    assert billing_response.status_code == 200
    billing_body = billing_response.json()
    assert billing_body["subscriptions"]["lifecycle_state_counts"].get("expired", 0) >= 1
    assert billing_body["subscriptions"]["raw_status_counts"].get("canceled", 0) >= 1
    stale_subscription_sample = next(
        sample for sample in billing_body["subscriptions"]["samples"] if sample["user_id"] == learner_user_id
    )
    assert stale_subscription_sample["lifecycle_state"] == "expired"
    assert stale_subscription_sample["subscription_status"] == "canceled"

    support_response = client.get(f"/api/admin/ops/support?user_id={learner_user_id}")
    assert support_response.status_code == 200
    support_body = support_response.json()
    assert support_body["user"]["lifecycle_state"] == "expired"
    assert support_body["user"]["subscription_status"] == "canceled"
    assert support_body["billing"]["activation_state"] == "expired"
    assert support_body["quotas"]["plan_current"] is False
    assert "Billing activation is not currently in a premium-active state" in support_body["billing"]["note"]


def test_phase37_admin_support_ops_exposes_razorpay_refs_and_payment_failure_cues(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import support_ops_service

    admin_auth = authenticate_test_user(client, email="phase37-support-ops-admin@example.com", display_name="Phase 37 Support Ops Admin")
    grant_admin_role(client, email="phase37-support-ops-admin@example.com", role="content_admin")
    admin_session_cookie = client.cookies.get(get_settings().session_cookie_name)
    assert admin_session_cookie

    learner_email = "phase37-support-razorpay@example.com"
    learner_auth = authenticate_test_user(client, email=learner_email, display_name="Phase 37 Support Razorpay")
    learner_user_id = learner_auth["user"]["id"]

    monkeypatch.setattr(
        support_ops_service,
        "get_settings",
        lambda: Settings(
            frontend_origin="https://app.adhyantra.example",
            payment_provider="razorpay",
            payment_premium_price_id="plan_premium_monthly",
            payment_razorpay_key_id="rzp_live_adhyantra",
            payment_razorpay_key_secret="razorpay_secret",
            payment_razorpay_webhook_secret="razorpay_webhook_secret",
            payment_razorpay_total_count=12,
        ),
    )

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        learner = db.query(UserAccount).filter(UserAccount.id == learner_user_id).first()
        assert learner is not None
        learner.billing_email = learner_email
        learner.subscription_plan = "premium"
        learner.subscription_status = "past_due"
        learner.subscription_customer_ref = "cust_support_razorpay_123"
        learner.subscription_provider_ref = "sub_support_razorpay_123"
        learner.subscription_price_id = "plan_premium_monthly"
        learner.subscription_current_period_end = now + timedelta(days=5)
        db.add(learner)

        db.add(
            BillingEventReceipt(
                provider_name="razorpay",
                provider_event_id="evt_support_razorpay_pending",
                event_type="subscription.pending",
                livemode=True,
                processing_state="processed",
                user_id=learner_user_id,
                customer_ref="cust_support_razorpay_123",
                subscription_ref="sub_support_razorpay_123",
                payload_json="{}",
                delivery_attempt_count=2,
                duplicate_delivery_count=1,
                processing_attempt_count=1,
                event_created_at=now - timedelta(minutes=12),
                first_received_at=now - timedelta(minutes=11),
                last_received_at=now - timedelta(minutes=10),
                processed_at=now - timedelta(minutes=9),
                resolved_lifecycle_state="past_due",
                resolved_plan_tier="premium",
                resolved_subscription_status="past_due",
                resolved_premium_quota_state="payment_recovery",
                resolution_note="Subscription payment issue moved the account into recovery state.",
            )
        )
        record_analytics_event(
            db,
            event_name="billing.checkout_started",
            feature_area="billing",
            user_id=learner_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "started",
                "provider_name": "razorpay",
                "customer_ref_present": True,
                "subscription_ref_present": True,
                "return_path": "/settings",
            },
        )
        db.commit()
    finally:
        db.close()

    client.cookies.set(get_settings().session_cookie_name, admin_session_cookie)

    response = client.get(f"/api/admin/ops/support?email={learner_email}&sample_limit=5")
    assert response.status_code == 200
    body = response.json()

    assert body["user"]["customer_ref"] == "cust_support_razorpay_123"
    assert body["user"]["subscription_ref"] == "sub_support_razorpay_123"
    assert body["user"]["price_id"] == "plan_premium_monthly"
    assert body["billing"]["provider_name"] == "razorpay"
    assert body["billing"]["checkout_ready"] is False
    assert body["billing"]["customer_ref"] == "cust_support_razorpay_123"
    assert body["billing"]["subscription_ref"] == "sub_support_razorpay_123"
    assert body["billing"]["price_id"] == "plan_premium_monthly"
    assert body["billing"]["latest_receipt_event_type"] == "subscription.pending"
    assert body["billing"]["latest_resolved_lifecycle_state"] == "past_due"
    assert body["billing"]["latest_resolved_subscription_status"] == "past_due"
    assert "recovery" in body["billing"]["latest_resolution_note"].lower()
    assert "Confirm the latest provider receipt" in body["billing"]["suggested_next_step"]
    assert body["billing"]["recent_checkout_events"][0]["provider_name"] == "razorpay"
    assert body["billing"]["recent_checkout_events"][0]["subscription_ref_present"] is True
    assert body["billing"]["recent_webhook_receipts"][0]["customer_ref"] == "cust_support_razorpay_123"
    assert body["billing"]["recent_webhook_receipts"][0]["subscription_ref"] == "sub_support_razorpay_123"

    cue_by_key = {item["key"]: item for item in body["investigation_cues"]}
    assert "payment_failure_support_needed" in cue_by_key
    assert "latest provider receipt" in cue_by_key["payment_failure_support_needed"]["next_step"].lower()


def test_admin_support_ops_snapshot_exposes_safe_account_level_investigation_cues(client: TestClient) -> None:
    admin_auth = authenticate_test_user(client, email="support-ops-admin@example.com", display_name="Support Ops Admin")
    grant_admin_role(client, email="support-ops-admin@example.com", role="content_admin")
    admin_session_cookie = client.cookies.get(get_settings().session_cookie_name)
    assert admin_session_cookie

    learner_email = "support-learner@example.com"
    learner_auth = authenticate_test_user(client, email=learner_email, display_name="Support Learner")
    learner_user_id = learner_auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        learner = db.query(UserAccount).filter(UserAccount.id == learner_user_id).first()
        assert learner is not None
        learner.billing_email = learner_email
        learner.subscription_customer_ref = "cus_support_pending"
        learner.last_active_at = now - timedelta(minutes=8)
        db.add(learner)
        db.commit()

        stale_job = create_media_render_job(
            db,
            user_id=learner_user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        stale_job.queued_at = now - timedelta(minutes=45)
        db.add(stale_job)

        record_analytics_event(
            db,
            event_name="billing.checkout_started",
            feature_area="billing",
            user_id=learner_user_id,
            exam="upsc",
            subject="polity",
            metadata={
                "source": "settings_account",
                "outcome_code": "started",
                "existing_customer_ref": "cus_support_pending",
                "return_path": "/settings",
            },
        )
        record_analytics_event(
            db,
            event_name="lesson.audio_render_download_unavailable",
            feature_area="media_render",
            user_id=learner_user_id,
            exam="upsc",
            subject="polity",
            topic="Directive Principles",
            metadata={
                "job_id": stale_job.id,
                "render_type": "audio",
                "delivery_status": "unavailable",
                "status_code": 410,
                "reason": "artifact_expired",
                "job_lifecycle_state": "succeeded",
                "asset_filename": "directive-principles-audio.zip",
            },
        )
        db.add_all(
            [
                UsageConsumptionRecord(
                    user_id=learner_user_id,
                    limit_key="media_render_creations",
                    source_action="media_render.audio_create",
                    units_consumed=60,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic="Directive Principles",
                ),
                UsageConsumptionRecord(
                    user_id=learner_user_id,
                    limit_key="advanced_lesson_exports",
                    source_action="lesson.export",
                    units_consumed=12,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic="Parliament",
                    export_format="audio_script_export",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    client.cookies.set(get_settings().session_cookie_name, admin_session_cookie)

    response = client.get(f"/api/admin/ops/support?email={learner_email}&sample_limit=5")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "admin_support_ops_ready"
    assert body["admin_access"]["is_admin"] is True
    assert "content_qa" in body["admin_access"]["privileges"]
    assert body["lookup_value"] == learner_email
    assert body["user"]["user_id"] == learner_user_id
    assert body["user"]["email"] == learner_email
    assert body["user"]["customer_ref_present"] is True
    assert body["user"]["provider_ref_present"] is False

    assert body["billing"]["missing_webhook_sync"] is True
    assert "admin billing ops" in body["billing"]["suggested_next_step"].lower()
    assert body["billing"]["latest_checkout_event_name"] == "billing.checkout_started"
    assert body["billing"]["latest_checkout_at"] is not None
    assert body["billing"]["recent_receipt_count"] == 0
    assert body["billing"]["recent_checkout_events"][0]["event_name"] == "billing.checkout_started"

    assert body["media"]["stuck_job_count"] >= 1
    assert body["media"]["blocked_download_count"] >= 1
    assert body["media"]["recent_jobs"][0]["topic"] == "Directive Principles"
    assert body["media"]["blocked_downloads"][0]["reason"] == "artifact_expired"

    quota_limits = {item["limit_key"]: item for item in body["quotas"]["limits"]}
    assert "media_render_creations" in quota_limits
    assert "advanced_lesson_exports" in quota_limits
    assert quota_limits["media_render_creations"]["consumed_units"] >= 60
    assert quota_limits["media_render_creations"]["remaining_units"] == 0
    assert quota_limits["media_render_creations"]["entitlement_enabled"] is False
    assert body["quotas"]["recent_usage"][0]["limit_key"] in {"media_render_creations", "advanced_lesson_exports"}

    cue_by_key = {item["key"]: item for item in body["investigation_cues"]}
    assert "missing_webhook_sync" in cue_by_key
    assert "stuck_media_jobs" in cue_by_key
    assert "blocked_downloads" in cue_by_key
    assert "quota_limit_reached" in cue_by_key
    assert "provider subscription ref" in cue_by_key["missing_webhook_sync"]["next_step"].lower()
    assert "Internal support visibility only" in body["route_note"]


def test_admin_ops_overview_aggregates_runtime_media_billing_and_analytics(client: TestClient) -> None:
    email = "ops-overview-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Ops Overview Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]
    stop_media_render_dispatcher(client.app)

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        queued_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Separation of Powers",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        queued_job.queued_at = now - timedelta(minutes=18)
        db.add(queued_job)

        db.add_all(
            [
                BillingEventReceipt(
                    provider_name="stripe",
                    provider_event_id="evt_ops_processed",
                    event_type="checkout.session.completed",
                    livemode=False,
                    processing_state="processed",
                    user_id=user_id,
                    customer_ref="cus_ops_processed",
                    subscription_ref="sub_ops_processed",
                    payload_json="{}",
                    processing_attempt_count=1,
                    event_created_at=now - timedelta(minutes=12),
                    first_received_at=now - timedelta(minutes=11),
                    processed_at=now - timedelta(minutes=10),
                    resolution_note="Checkout completion synced premium subscription state.",
                ),
                BillingEventReceipt(
                    provider_name="stripe",
                    provider_event_id="evt_ops_failed",
                    event_type="invoice.payment_failed",
                    livemode=False,
                    processing_state="failed",
                    user_id=user_id,
                    customer_ref="cus_ops_failed",
                    subscription_ref="sub_ops_failed",
                    payload_json="{}",
                    processing_attempt_count=2,
                    event_created_at=now - timedelta(minutes=8),
                    first_received_at=now - timedelta(minutes=7),
                    failed_at=now - timedelta(minutes=6),
                    processing_error="RuntimeError: processor_unavailable",
                ),
            ]
        )

        record_analytics_event(
            db,
            event_name="billing.checkout_started",
            feature_area="billing",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            metadata={"source": "ops_overview_test"},
        )
        record_analytics_event(
            db,
            event_name="media.render.completed",
            feature_area="media_render",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            metadata={"render_type": "audio"},
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/ops/overview?sample_limit=5&analytics_window_days=7")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "admin_ops_overview_ready"
    assert body["admin_access"]["is_admin"] is True
    assert "content_qa" in body["admin_access"]["privileges"]

    assert body["runtime"]["status"] in {"ready", "degraded"}
    assert isinstance(body["runtime"]["ready"], bool)
    assert body["runtime"]["environment"] in {"development", "test", "staging", "production"}
    assert body["runtime"]["database_status"] in {"ready", "schema_incomplete", "unavailable"}

    assert body["worker"]["mode"] in {"embedded", "external", "disabled"}
    assert isinstance(body["media_pipeline"]["storage_ready"], bool)
    assert isinstance(body["media_pipeline"]["degraded_reasons"], list)

    assert body["media_render"]["job_counts"]["queued"] >= 1
    assert body["media_render"]["queue"]["ready_to_claim_count"] >= 1

    assert body["billing"]["provider_name"] in {"disabled", "stripe"}
    assert body["billing"]["receipt_counts"]["processed"] >= 1
    assert body["billing"]["receipt_counts"]["failed"] >= 1
    assert body["billing"]["failed_count"] >= 1
    assert body["billing"]["unresolved_count"] >= 1
    sample_event_ids = {item["provider_event_id"] for item in body["billing"]["samples"]}
    assert "evt_ops_processed" in sample_event_ids
    assert "evt_ops_failed" in sample_event_ids
    assert all("payload_json" not in item for item in body["billing"]["samples"])

    assert body["analytics_activity"]["window_days"] == 7
    assert body["analytics_activity"]["recent_event_count"] >= 2
    assert body["analytics_activity"]["feature_area_counts"]["billing"] >= 1
    assert body["analytics_activity"]["feature_area_counts"]["media_render"] >= 1
    assert "Internal operations overview only" in body["route_note"]


def test_admin_media_ops_overview_exposes_queue_retry_cleanup_and_worker_visibility(client: TestClient) -> None:
    email = "media-ops-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Media Ops Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]
    stop_media_render_dispatcher(client.app)
    current_environment = get_settings().environment_name

    session_factory = client.app.state.testing_session_factory
    now = datetime.now(UTC)
    db = session_factory()
    try:
        queued_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        queued_job.queued_at = now - timedelta(minutes=25)
        db.add(queued_job)
        db.commit()
        queued_job_id = queued_job.id

        stale_running_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="narrated_video",
            dispatch_payload={"dispatch_kind": "video", "render_type": "narrated_video"},
            status_note="Queued for narrated scene rendering.",
        )
        claim_media_render_job_for_worker(
            db,
            job=stale_running_job,
            worker_id="worker-stale",
            lease_seconds=60,
            occurred_at=now - timedelta(minutes=12),
            status_note="Narrated scene rendering is in progress.",
        )
        stale_running_job_id = stale_running_job.id

        active_running_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Parliament",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        claim_media_render_job_for_worker(
            db,
            job=active_running_job,
            worker_id="worker-active",
            lease_seconds=900,
            occurred_at=now - timedelta(minutes=3),
            status_note="Audio generation is in progress.",
        )
        active_running_job_id = active_running_job.id

        retry_waiting_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Federalism",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        claim_media_render_job_for_worker(
            db,
            job=retry_waiting_job,
            worker_id="worker-retry",
            lease_seconds=300,
            occurred_at=now - timedelta(minutes=2),
            status_note="Audio generation is in progress.",
        )
        mark_media_render_job_retryable_failed(
            db,
            job=retry_waiting_job,
            failure_code="tts_render_retryable",
            failure_message="Temporary upstream timeout.",
            retry_after_at=now + timedelta(minutes=15),
            status_note="Audio generation hit a temporary issue. Trying again soon.",
            occurred_at=now - timedelta(minutes=1),
        )
        retry_waiting_job_id = retry_waiting_job.id

        terminal_failed_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Citizenship",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_failed(
            db,
            job=terminal_failed_job,
            failure_code="dispatch_payload_invalid",
            failure_message="Queued media payload could not be executed.",
            status_note="Media generation could not start from the queued job payload.",
            occurred_at=now - timedelta(minutes=4),
        )
        terminal_failed_job_id = terminal_failed_job.id

        active_asset_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Union Executive",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="slide_video",
            status_note="Queued for scene rendering.",
        )
        mark_media_render_job_succeeded(
            db,
            job=active_asset_job,
            output_metadata={"format": "zip"},
            output_asset_filename="union-executive-scene.zip",
            output_asset_path="backend/media_render_output/tests/union-executive-scene.zip",
            output_content_type="application/zip",
            output_file_size_bytes=4096,
            artifact_retention_expires_at=now + timedelta(days=3),
            status_note="Scene package is ready.",
            occurred_at=now - timedelta(minutes=10),
        )

        missing_artifact_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Emergency Provisions",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=missing_artifact_job,
            output_metadata={"format": "zip"},
            output_asset_filename="emergency-provisions-audio.zip",
            output_asset_path="backend/media_render_output/tests/emergency-provisions-audio.zip",
            output_content_type="application/zip",
            output_file_size_bytes=2048,
            artifact_retention_expires_at=now + timedelta(days=2),
            status_note="Audio is ready to download.",
            occurred_at=now - timedelta(minutes=9),
        )
        missing_artifact_job_id = missing_artifact_job.id

        cleanup_due_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Judiciary",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=cleanup_due_job,
            output_metadata={"format": "zip"},
            output_asset_filename="judiciary-audio.zip",
            output_asset_path="backend/media_render_output/tests/judiciary-audio.zip",
            output_content_type="application/zip",
            output_file_size_bytes=2048,
            artifact_retention_expires_at=now - timedelta(hours=4),
            status_note="Audio is ready to download.",
            occurred_at=now - timedelta(days=2),
        )
        cleanup_due_job_id = cleanup_due_job.id

        cleanup_failed_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Constitutional Amendments",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=cleanup_failed_job,
            output_metadata={"format": "zip"},
            output_asset_filename="constitutional-amendments-audio.zip",
            output_asset_path="backend/media_render_output/tests/constitutional-amendments-audio.zip",
            output_content_type="application/zip",
            output_file_size_bytes=1024,
            artifact_retention_expires_at=now - timedelta(hours=2),
            status_note="Audio is ready to download.",
            occurred_at=now - timedelta(days=1),
        )
        mark_media_render_artifact_cleanup_failed(
            db,
            job=cleanup_failed_job,
            cleanup_error="cleanup target is locked",
            retry_after_at=now + timedelta(hours=2),
            occurred_at=now - timedelta(minutes=30),
        )
        cleanup_failed_job_id = cleanup_failed_job.id

        recovered_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Fundamental Rights",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            dispatch_payload={"dispatch_kind": "audio", "render_type": "audio"},
            status_note="Queued for audio generation.",
        )
        recovered_job.queued_at = now - timedelta(hours=3)
        db.add(recovered_job)
        db.commit()
        recovered_job_id = recovered_job.id

        recovered_jobs = recover_stale_queued_media_render_jobs(
            db,
            now=now,
            stale_after_seconds=7200,
        )
        assert recovered_job_id in {job.id for job in recovered_jobs}

        fresh_worker = upsert_runtime_process_heartbeat(
            db,
            service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
            process_role="worker",
            runtime_instance_id="worker-fresh",
            environment=current_environment,
            status="running",
            worker_mode="external",
            metadata={"job_id": active_running_job_id},
            started_at=now - timedelta(minutes=15),
            heartbeat_at=now - timedelta(seconds=20),
        )
        stale_worker = upsert_runtime_process_heartbeat(
            db,
            service_name=MEDIA_RENDER_WORKER_SERVICE_NAME,
            process_role="worker",
            runtime_instance_id="worker-stale-heartbeat",
            environment=current_environment,
            status="running",
            worker_mode="external",
            metadata={"job_id": stale_running_job_id},
            started_at=now - timedelta(minutes=25),
            heartbeat_at=now - timedelta(minutes=8),
        )
        assert fresh_worker is not None
        assert stale_worker is not None
    finally:
        db.close()

    failed_download_response = client.get(f"/api/tutor/render/audio/{terminal_failed_job_id}/download")
    assert failed_download_response.status_code == 409

    expired_download_response = client.get(f"/api/tutor/render/audio/{cleanup_due_job_id}/download")
    assert expired_download_response.status_code == 410

    missing_download_response = client.get(f"/api/tutor/render/audio/{missing_artifact_job_id}/download")
    assert missing_download_response.status_code == 410

    response = client.get("/api/admin/ops/media-render?exam=upsc&subject=polity&sample_limit=5")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "admin_media_render_ops_ready"
    assert body["admin_access"]["is_admin"] is True
    assert "content_qa" in body["admin_access"]["privileges"]
    assert body["scoped_exam"] == "upsc"
    assert body["scoped_subject"] == "polity"

    assert body["worker"]["mode"] in {"embedded", "external", "disabled"}
    assert isinstance(body["worker"]["embedded_dispatcher_running"], bool)
    assert isinstance(body["worker"]["ready"], bool)
    assert isinstance(body["worker"]["required_for_readiness"], bool)
    assert body["worker"]["fresh_worker_count"] >= 1
    assert body["worker"]["stale_worker_count"] >= 1
    assert body["worker"]["latest_worker_status"] in {"starting", "running", "stopped"}
    assert body["worker"]["stale_after_seconds"] >= body["worker"]["heartbeat_seconds"]
    assert body["worker"]["claim_lease_seconds"] >= 1
    assert body["worker"]["artifact_retention_hours"] >= 1
    assert body["worker"]["latest_heartbeat_age_seconds"] is not None
    recent_worker_ids = {item["runtime_instance_id"] for item in body["worker"]["recent_workers"]}
    assert "worker-fresh" in recent_worker_ids
    assert "worker-stale-heartbeat" in recent_worker_ids

    assert body["job_counts"]["queued"] >= 1
    assert body["job_counts"]["running"] >= 2
    assert body["job_counts"]["retryable_failed"] >= 2
    assert body["job_counts"]["succeeded"] >= 2
    assert body["job_counts"]["failed"] >= 1

    assert body["queue"]["queued_count"] >= 1
    assert body["queue"]["running_count"] >= 2
    assert body["queue"]["retryable_failed_count"] >= 2
    assert body["queue"]["failed_count"] >= 1
    assert body["queue"]["ready_to_claim_count"] >= 1
    assert body["queue"]["retry_waiting_count"] >= 1
    assert body["queue"]["stale_queued_count"] >= 1
    assert body["queue"]["stale_running_count"] >= 1
    assert body["queue"]["recovery_waiting_count"] >= 1
    assert body["queue"]["oldest_running_age_seconds"] is not None
    assert body["queue"]["oldest_stale_queued_age_seconds"] is not None
    assert body["artifacts"]["created_artifact_count"] >= 4
    assert body["artifacts"]["creation_failed_count"] >= 1
    assert body["artifacts"]["downloadable_artifact_count"] >= 1
    assert body["artifacts"]["expired_artifact_count"] >= 2
    assert body["artifacts"]["missing_artifact_count"] >= 1
    assert body["artifacts"]["deleted_artifact_count"] >= 1
    assert body["artifacts"]["cleanup_attempted_count"] >= 2
    assert body["artifacts"]["cleanup_failed_count"] >= 1
    assert body["artifacts"]["cleanup_completed_count"] >= 1
    assert body["artifacts"]["cleanup_error_counts"]["cleanup target is locked"] >= 1
    assert body["artifacts"]["cleanup_error_counts"]["artifact_file_missing"] >= 1
    assert body["artifacts"]["latest_cleanup_attempted_at"] is not None
    assert body["delivery"]["blocked_download_count"] >= 3
    assert body["delivery"]["blocked_download_reason_counts"]["render_failed"] >= 1
    assert body["delivery"]["blocked_download_reason_counts"]["artifact_expired"] >= 1
    assert body["delivery"]["blocked_download_reason_counts"]["artifact_file_missing"] >= 1
    assert body["delivery"]["blocked_download_status_code_counts"]["409"] >= 1
    assert body["delivery"]["blocked_download_status_code_counts"]["410"] >= 2
    assert body["delivery"]["latest_blocked_download_at"] is not None
    assert body["cleanup"]["downloadable_asset_count"] >= 1
    assert body["cleanup"]["cleanup_due_count"] >= 1
    assert body["cleanup"]["cleanup_waiting_count"] >= 1
    assert body["failures"]["terminal_failed_count"] >= 1
    assert body["failures"]["retryable_failed_count"] >= 2
    assert body["failures"]["current_failure_code_counts"]["dispatch_payload_invalid"] >= 1
    assert body["failures"]["recovery_failure_code_counts"]["queue_start_delayed"] >= 1

    backlog_ids = {item["id"] for item in body["samples"]["backlog"]}
    running_ids = {item["id"] for item in body["samples"]["running"]}
    stale_queued_ids = {item["id"] for item in body["samples"]["stale_queued"]}
    stale_running_ids = {item["id"] for item in body["samples"]["stale_running"]}
    retry_waiting_ids = {item["id"] for item in body["samples"]["retry_waiting"]}
    failed_ids = {item["id"] for item in body["samples"]["failed"]}
    recovered_ids = {item["id"] for item in body["samples"]["recovered"]}
    cleanup_due_ids = {item["id"] for item in body["samples"]["cleanup_due"]}
    artifact_missing_ids = {item["id"] for item in body["samples"]["artifact_missing"]}
    artifact_expired_ids = {item["id"] for item in body["samples"]["artifact_expired"]}
    cleanup_failed_ids = {item["id"] for item in body["samples"]["cleanup_failed"]}
    blocked_download_reasons = {item["reason"] for item in body["samples"]["blocked_downloads"]}

    assert queued_job_id in backlog_ids
    assert active_running_job_id in running_ids
    assert queued_job_id in stale_queued_ids
    assert stale_running_job_id in stale_running_ids
    assert retry_waiting_job_id in retry_waiting_ids
    assert terminal_failed_job_id in failed_ids
    assert recovered_job_id in recovered_ids
    assert cleanup_due_job_id in cleanup_due_ids
    assert missing_artifact_job_id in artifact_missing_ids
    assert cleanup_due_job_id in artifact_expired_ids
    assert cleanup_failed_job_id in cleanup_failed_ids
    assert {"render_failed", "artifact_expired", "artifact_file_missing"}.issubset(blocked_download_reasons)


def test_admin_content_overview_exposes_usage_and_performance_insights(client: TestClient) -> None:
    email = "content-insights-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Content Insights Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        db.add_all(
            [
                ContentItem(
                    exam="upsc",
                    subject="polity",
                    content_subject="polity",
                    chapter="Constitutional Framework",
                    topic="Preamble",
                    slug="phase27-preamble-admin-note",
                    title="Preamble Admin Note",
                    content_type="topic_note",
                    lifecycle_state="published",
                    body_markdown="# Preamble\n\nPublished content.",
                    summary="Published support for Preamble.",
                    source_corpus_id="admin_published_content",
                    author_user_id=user_id,
                    publisher_user_id=user_id,
                    published_at=datetime.now(UTC),
                ),
                ContentItem(
                    exam="upsc",
                    subject="polity",
                    content_subject="polity",
                    chapter="Union Structure",
                    topic="Federalism",
                    slug="phase27-federalism-admin-note",
                    title="Federalism Admin Note",
                    content_type="topic_note",
                    lifecycle_state="published",
                    body_markdown="# Federalism\n\nPublished content.",
                    summary="Published but quiet support for Federalism.",
                    source_corpus_id="admin_published_content",
                    author_user_id=user_id,
                    publisher_user_id=user_id,
                    published_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()

        record_analytics_event(
            db,
            event_name="tutor.explained",
            feature_area="tutor",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            chapter="Constitutional Framework",
            topic="Preamble",
            lesson_mode="mini_lesson",
            content_corpus_id="admin_published_content",
            content_source_scope="published_admin_content",
        )
        record_analytics_event(
            db,
            event_name="quiz.generated",
            feature_area="quiz",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            chapter="Constitutional Framework",
            topic="Preamble",
            quiz_mode="test",
            question_count=5,
            content_corpus_id="admin_published_content",
            content_source_scope="published_admin_content",
        )
        record_analytics_event(
            db,
            event_name="lesson.exported",
            feature_area="lesson_export",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            chapter="Constitutional Framework",
            topic="Preamble",
            lesson_mode="video_lecture",
            export_format="markdown_export",
            content_corpus_id="admin_published_content",
            content_source_scope="published_admin_content",
        )
        record_analytics_event(
            db,
            event_name="tutor.explained",
            feature_area="tutor",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            chapter="Directive Principles",
            topic="Directive Principles",
            lesson_mode="revision_video",
            content_corpus_id="upsc_legacy_shared",
            content_source_scope="legacy_default",
        )

        db.add(
            QuizAttempt(
                user_id=user_id,
                exam="upsc",
                subject="polity",
                chapter="Directive Principles",
                topic="Directive Principles",
                difficulty="medium",
                quiz_mode="revision",
                submitted_answers_json="[]",
                score=1,
                total_questions=5,
                accuracy=20.0,
                incorrect_questions_json='["Q1"]',
                weak_areas_json='["Directive Principles"]',
                topic_breakdown_json='[]',
                next_recommendation="Revise Directive Principles again.",
                created_at=datetime.now(UTC),
            )
        )
        db.add(
            TopicProgress(
                user_id=user_id,
                exam="upsc",
                subject="polity",
                chapter="Directive Principles",
                topic="Directive Principles",
                attempts_count=3,
                correct_answers=2,
                total_answers=10,
                accuracy=20.0,
                difficulty_band="medium",
                weak_topic=True,
                last_attempt_at=datetime.now(UTC),
            )
        )
        db.commit()
    finally:
        db.close()

    overview_response = client.get("/api/admin/content/overview?exam=upsc&subject=polity")
    assert overview_response.status_code == 200
    insights = overview_response.json()["content_insights"]
    assert insights["scoped_exam"] == "upsc"
    assert insights["scoped_subject"] == "polity"
    assert "last 30 days" in insights["summary"]

    high_usage_topics = {item["topic"]: item for item in insights["high_usage_topics"]}
    assert "Preamble" in high_usage_topics
    assert high_usage_topics["Preamble"]["usage_count"] >= 3

    low_usage_topics = {item["topic"]: item for item in insights["low_usage_topics"]}
    assert "Federalism" in low_usage_topics
    assert low_usage_topics["Federalism"]["published_content_count"] == 1

    repeated_weak_topics = {item["topic"]: item for item in insights["repeated_weak_outcome_topics"]}
    assert "Directive Principles" in repeated_weak_topics
    assert repeated_weak_topics["Directive Principles"]["weak_outcome_count"] >= 2

    thin_content_topics = {item["topic"]: item for item in insights["thin_content_topics"]}
    assert "Directive Principles" in thin_content_topics
    assert thin_content_topics["Directive Principles"]["thin_content_signal"] == "no_published_support"

    export_usage = {item["key"]: item for item in insights["export_usage_by_format"]}
    assert export_usage["markdown_export"]["count"] == 1

    media_mode_usage = {item["key"]: item for item in insights["media_mode_usage"]}
    assert media_mode_usage["mini_lesson"]["count"] == 1
    assert media_mode_usage["video_lecture"]["count"] == 1
    assert media_mode_usage["revision_video"]["count"] == 1


def test_admin_content_listing_filters_inventory(client: TestClient) -> None:
    email = "content-list-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Content List Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        db.add_all(
            [
                ContentItem(
                    exam="upsc",
                    subject="polity",
                    content_subject="polity",
                    chapter="Constitutional Framework",
                    topic="Preamble",
                    slug="preamble-topic-note",
                    title="Preamble Topic Note",
                    content_type="topic_note",
                    lifecycle_state="published",
                    body_markdown="# Preamble",
                    summary="Published UPSC polity note.",
                    metadata_json='{"scenario": "listing_filter"}',
                    source_corpus_id="upsc_legacy_shared",
                    author_user_id=user_id,
                    publisher_user_id=user_id,
                    published_at=datetime.now(UTC),
                ),
                ContentItem(
                    exam="upsc",
                    subject="history",
                    content_subject="history",
                    chapter="Modern India",
                    topic="Civil Disobedience Movement",
                    slug="civil-disobedience-lesson-seed",
                    title="Civil Disobedience Lesson Seed",
                    content_type="lesson_seed",
                    lifecycle_state="draft",
                    body_markdown="# Civil Disobedience",
                    summary="Draft lesson seed.",
                    source_corpus_id="upsc_legacy_shared",
                    author_user_id=user_id,
                ),
                ContentItem(
                    exam="banking",
                    subject="regulatory_basics",
                    content_subject="regulatory_basics",
                    chapter="Banking Basics",
                    topic="RBI Monetary Policy",
                    slug="rbi-monetary-policy-revision-note",
                    title="RBI Monetary Policy Revision Note",
                    content_type="revision_note",
                    lifecycle_state="in_review",
                    body_markdown="# RBI Monetary Policy",
                    summary="Banking review content.",
                    source_corpus_id="banking_shared_alias",
                    author_user_id=user_id,
                    reviewer_user_id=user_id,
                    submitted_for_review_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    list_response = client.get("/api/admin/content/items")
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["total_count"] == 3
    assert list_body["returned_count"] == 3
    assert {item["title"] for item in list_body["items"]} == {
        "Preamble Topic Note",
        "Civil Disobedience Lesson Seed",
        "RBI Monetary Policy Revision Note",
    }

    published_response = client.get("/api/admin/content/items?lifecycle_state=published")
    assert published_response.status_code == 200
    published_body = published_response.json()
    assert published_body["total_count"] == 1
    assert published_body["items"][0]["title"] == "Preamble Topic Note"
    assert published_body["filters"]["lifecycle_state"] == "published"

    subject_response = client.get("/api/admin/content/items?exam=banking&subject=regulatory_basics")
    assert subject_response.status_code == 200
    subject_body = subject_response.json()
    assert subject_body["total_count"] == 1
    assert subject_body["items"][0]["exam"] == "banking"
    assert subject_body["items"][0]["subject"] == "regulatory_basics"

    topic_response = client.get("/api/admin/content/items?topic=pream")
    assert topic_response.status_code == 200
    topic_body = topic_response.json()
    assert topic_body["total_count"] == 1
    assert topic_body["items"][0]["topic"] == "Preamble"

    type_response = client.get("/api/admin/content/items?content_type=lesson_seed")
    assert type_response.status_code == 200
    type_body = type_response.json()
    assert type_body["total_count"] == 1
    assert type_body["items"][0]["content_type"] == "lesson_seed"

    invalid_response = client.get("/api/admin/content/items?content_type=unknown")
    assert invalid_response.status_code == 400

    authenticate_test_user(client, email="content-list-student@example.com")
    student_response = client.get("/api/admin/content/items")
    assert student_response.status_code == 403


def test_admin_content_edit_updates_scoped_metadata_and_body(client: TestClient) -> None:
    email = "content-edit-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Content Edit Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        content_item = ContentItem(
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Constitutional Framework",
            topic="Preamble",
            slug="preamble-edit-topic-note",
            title="Preamble Draft",
            content_type="topic_note",
            lifecycle_state="draft",
            body_markdown="# Preamble\n\nOld body.",
            summary="Old summary.",
            metadata_json='{"difficulty": "foundation"}',
            source_corpus_id="upsc_legacy_shared",
            author_user_id=user_id,
        )
        db.add(content_item)
        db.commit()
        db.refresh(content_item)
        content_item_id = content_item.id
    finally:
        db.close()

    update_response = client.patch(
        f"/api/admin/content/items/{content_item_id}",
        json={
            "exam": "upsc",
            "subject": "polity",
            "content_subject": "polity",
            "chapter": "Constitutional Framework",
            "topic": "Preamble and Objectives",
            "slug": "preamble-objectives-topic-note",
            "title": "Preamble and Objectives Topic Note",
            "content_type": "topic_note",
            "lifecycle_state": "draft",
            "body_markdown": "# Preamble\n\nUpdated internal teaching body.",
            "summary": "Updated summary.",
            "metadata": {"difficulty": "foundation", "edited": True},
            "source_corpus_id": "upsc_legacy_shared",
            "source_path": "polity/preamble.md",
        },
    )
    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["title"] == "Preamble and Objectives Topic Note"
    assert update_body["topic"] == "Preamble and Objectives"
    assert update_body["slug"] == "preamble-objectives-topic-note"
    assert update_body["lifecycle_state"] == "draft"
    assert update_body["body_markdown"] == "# Preamble\n\nUpdated internal teaching body."
    assert update_body["metadata"]["edited"] is True
    assert update_body["reviewer_user_id"] is None
    assert update_body["submitted_for_review_at"] is None

    listing_response = client.get("/api/admin/content/items?topic=Objectives&lifecycle_state=draft")
    assert listing_response.status_code == 200
    listing_body = listing_response.json()
    assert listing_body["total_count"] == 1
    assert listing_body["items"][0]["id"] == content_item_id

    direct_transition_response = client.patch(
        f"/api/admin/content/items/{content_item_id}",
        json={"lifecycle_state": "in_review"},
    )
    assert direct_transition_response.status_code == 409

    authenticate_test_user(client, email="content-edit-student@example.com")
    student_response = client.patch(
        f"/api/admin/content/items/{content_item_id}",
        json={"title": "Student edit should fail"},
    )
    assert student_response.status_code == 403


def test_admin_content_workflow_transitions_review_publish_and_return(client: TestClient) -> None:
    email = "content-workflow-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Content Workflow Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        content_item = ContentItem(
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Constitutional Framework",
            topic="Fundamental Rights",
            slug="fundamental-rights-workflow-note",
            title="Fundamental Rights Workflow Note",
            content_type="topic_note",
            lifecycle_state="draft",
            body_markdown="# Fundamental Rights\n\nDraft body.",
            summary="Workflow draft.",
            metadata_json="{}",
            author_user_id=user_id,
        )
        db.add(content_item)
        db.commit()
        db.refresh(content_item)
        content_item_id = content_item.id
    finally:
        db.close()

    premature_publish_response = client.post(
        f"/api/admin/content/items/{content_item_id}/workflow",
        json={"action": "publish"},
    )
    assert premature_publish_response.status_code == 409

    review_response = client.post(
        f"/api/admin/content/items/{content_item_id}/workflow",
        json={"action": "submit_for_review", "review_note": "Ready for reviewer check."},
    )
    assert review_response.status_code == 200
    review_body = review_response.json()
    assert review_body["lifecycle_state"] == "in_review"
    assert review_body["submitted_for_review_at"] is not None
    assert review_body["metadata"]["workflow_notes"][-1]["action"] == "submit_for_review"

    publish_response = client.post(
        f"/api/admin/content/items/{content_item_id}/workflow",
        json={"action": "publish", "review_note": "Approved for learner-safe use."},
    )
    assert publish_response.status_code == 200
    publish_body = publish_response.json()
    assert publish_body["lifecycle_state"] == "published"
    assert publish_body["reviewed_at"] is not None
    assert publish_body["published_at"] is not None
    assert publish_body["publisher_user_id"] == user_id
    assert publish_body["metadata"]["workflow_notes"][-1]["action"] == "publish"

    published_listing_response = client.get("/api/admin/content/items?lifecycle_state=published")
    assert published_listing_response.status_code == 200
    published_listing = published_listing_response.json()
    assert any(item["id"] == content_item_id for item in published_listing["items"])

    return_response = client.post(
        f"/api/admin/content/items/{content_item_id}/workflow",
        json={"action": "return_to_draft", "review_note": "Needs another source citation."},
    )
    assert return_response.status_code == 200
    return_body = return_response.json()
    assert return_body["lifecycle_state"] == "draft"
    assert return_body["submitted_for_review_at"] is None
    assert return_body["published_at"] is None
    assert return_body["metadata"]["workflow_notes"][-1]["action"] == "return_to_draft"

    authenticate_test_user(client, email="content-workflow-student@example.com")
    student_response = client.post(
        f"/api/admin/content/items/{content_item_id}/workflow",
        json={"action": "submit_for_review"},
    )
    assert student_response.status_code == 403


def test_admin_content_import_upsert_and_corpus_sync_workflow(client: TestClient) -> None:
    email = "content-import-admin@example.com"
    authenticate_test_user(client, email=email, display_name="Content Import Admin")
    grant_admin_role(client, email=email, role="content_admin")

    import_payload = {
        "mode": "create_only",
        "import_note": "Initial controlled import.",
        "items": [
            {
                "exam": "upsc",
                "subject": "polity",
                "content_subject": "polity",
                "chapter": "Constitutional Framework",
                "topic": "Directive Principles Import",
                "slug": "directive-principles-import-topic-note",
                "title": "Directive Principles Import Note",
                "content_type": "topic_note",
                "body_markdown": "# Directive Principles\n\nImported body.",
                "summary": "Imported summary.",
                "metadata": {"source": "test_import"},
            }
        ],
    }

    create_response = client.post("/api/admin/content/import", json=import_payload)
    assert create_response.status_code == 200
    create_body = create_response.json()
    assert create_body["created_count"] == 1
    assert create_body["updated_count"] == 0
    assert create_body["skipped_count"] == 0
    imported_item = create_body["results"][0]["content_item"]
    assert imported_item["lifecycle_state"] == "draft"
    assert imported_item["metadata"]["source"] == "test_import"
    assert imported_item["metadata"]["import_history"][-1]["mode"] == "create_only"

    skipped_response = client.post("/api/admin/content/import", json=import_payload)
    assert skipped_response.status_code == 200
    skipped_body = skipped_response.json()
    assert skipped_body["created_count"] == 0
    assert skipped_body["skipped_count"] == 1

    upsert_payload = {
        **import_payload,
        "mode": "upsert",
        "items": [
            {
                **import_payload["items"][0],
                "title": "Directive Principles Updated Import Note",
                "body_markdown": "# Directive Principles\n\nUpdated imported body.",
            }
        ],
    }
    update_response = client.post("/api/admin/content/import", json=upsert_payload)
    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["updated_count"] == 1
    assert update_body["results"][0]["content_item"]["title"] == "Directive Principles Updated Import Note"

    sync_response = client.post(
        "/api/admin/content/sync-corpus",
        json={
            "exam": "upsc",
            "subject": "polity",
            "mode": "upsert",
            "content_type": "source_markdown",
            "limit": 1,
            "import_note": "Sync one source markdown item.",
        },
    )
    assert sync_response.status_code == 200
    sync_body = sync_response.json()
    assert sync_body["processed_count"] == 1
    synced_item = sync_body["results"][0]["content_item"]
    assert synced_item["content_type"] == "source_markdown"
    assert synced_item["source_corpus_id"]
    assert synced_item["source_path"]
    assert synced_item["metadata"]["sync_source"] == "knowledge_corpus"

    authenticate_test_user(client, email="content-import-student@example.com")
    student_response = client.post("/api/admin/content/import", json=import_payload)
    assert student_response.status_code == 403


def test_content_item_model_represents_review_publish_lifecycle(client: TestClient) -> None:
    email = "content-lifecycle-admin@example.com"
    auth_body = authenticate_test_user(client, email=email, display_name="Lifecycle Admin")
    grant_admin_role(client, email=email, role="content_admin")
    user_id = auth_body["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        content_item = ContentItem(
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Constitutional Framework",
            topic="Preamble",
            slug="preamble-topic-note",
            title="Preamble Topic Note",
            content_type="topic_note",
            lifecycle_state="draft",
            body_markdown="# Preamble\n\nDraft teaching content.",
            summary="Draft note for internal content review.",
            metadata_json='{"source": "admin_seed", "difficulty": "foundation"}',
            source_corpus_id="upsc_legacy_shared",
            author_user_id=user_id,
        )
        db.add(content_item)
        db.commit()
        db.refresh(content_item)

        assert content_item.lifecycle_state == "draft"
        assert content_item.exam == "upsc"
        assert content_item.subject == "polity"
        assert content_item.topic == "Preamble"

        content_item.lifecycle_state = "in_review"
        content_item.reviewer_user_id = user_id
        content_item.submitted_for_review_at = datetime.now(UTC)
        content_item.reviewed_at = datetime.now(UTC)
        db.add(content_item)
        db.commit()

        content_item.lifecycle_state = "published"
        content_item.publisher_user_id = user_id
        content_item.published_at = datetime.now(UTC)
        db.add(content_item)
        db.commit()
    finally:
        db.close()

    overview_response = client.get("/api/admin/content/overview")
    assert overview_response.status_code == 200
    overview_body = overview_response.json()
    assert overview_body["content_item_count"] == 1
    assert overview_body["state_counts"]["published"] == 1
    assert "topic_note" in overview_body["content_types"]
    assert overview_body["lifecycle_states"] == ["draft", "in_review", "published", "archived"]

    authenticate_test_user(client, email="content-lifecycle-student@example.com")
    subjects_response = client.get("/api/subjects")
    assert subjects_response.status_code == 200
    admin_response = client.get("/api/admin/content/overview")
    assert admin_response.status_code == 403


def test_published_admin_content_surfaces_in_topics_without_draft_leakage(client: TestClient) -> None:
    authenticate_test_user(client, email="content-scope-learner@example.com", display_name="Scoped Learner")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        db.add_all(
            [
                ContentItem(
                    exam="upsc",
                    subject="polity",
                    content_subject="polity",
                    chapter="Admin Curated",
                    topic="Phase 26 Published Topic",
                    slug="phase-26-published-topic-note",
                    title="Phase 26 Published Topic Note",
                    content_type="topic_note",
                    lifecycle_state="published",
                    body_markdown="# Phase 26 Published Topic\n\nPublished learner-safe content.",
                    summary="Published content item for learner discovery.",
                    metadata_json='{"source_scope": "published_admin_content"}',
                    source_corpus_id="admin_published_content",
                    published_at=datetime.now(UTC),
                ),
                ContentItem(
                    exam="upsc",
                    subject="polity",
                    content_subject="polity",
                    chapter="Admin Curated",
                    topic="Phase 26 Draft Topic",
                    slug="phase-26-draft-topic-note",
                    title="Phase 26 Draft Topic Note",
                    content_type="topic_note",
                    lifecycle_state="draft",
                    body_markdown="# Phase 26 Draft Topic\n\nDraft-only content should stay hidden.",
                    summary="Draft content item for admin-only review.",
                    metadata_json='{"source_scope": "published_admin_content"}',
                    source_corpus_id="admin_published_content",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/topics?exam=upsc&subject=polity")
    assert response.status_code == 200
    body = response.json()
    topics_by_name = {item["topic"]: item for item in body["topic_items"]}

    assert "Phase 26 Published Topic" in body["topics"]
    assert "Phase 26 Draft Topic" not in body["topics"]
    assert topics_by_name["Phase 26 Published Topic"]["content_corpus_id"] == "admin_published_content"
    assert topics_by_name["Phase 26 Published Topic"]["content_source_scope"] == "published_admin_content"
    assert topics_by_name["Phase 26 Published Topic"]["fallback_used"] is False


def test_published_admin_content_aligns_tutor_quiz_and_export_routes(client: TestClient) -> None:
    authenticate_test_user(client, email="content-alignment-learner@example.com", display_name="Alignment Learner")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        db.add(
            ContentItem(
                exam="upsc",
                subject="polity",
                content_subject="polity",
                chapter="Admin Curated",
                topic="Preamble",
                slug="phase-26-preamble-admin-topic-note",
                title="Preamble Admin Topic Note",
                content_type="topic_note",
                lifecycle_state="published",
                body_markdown="# Preamble\n\nPublished admin-reviewed content that should drive tutor, quiz, and export flows.",
                summary="Published admin content item overriding the legacy Preamble corpus entry for learner alignment.",
                metadata_json='{"source_scope": "published_admin_content"}',
                source_corpus_id="admin_published_content",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()
    finally:
        db.close()

    tutor_response = client.post(
        "/api/tutor/explain",
        json={"exam": "upsc", "subject": "polity", "topic": "Preamble"},
    )
    assert tutor_response.status_code == 200
    tutor_body = tutor_response.json()
    assert tutor_body["topic"] == "Preamble"
    assert tutor_body["content_corpus_id"] == "admin_published_content"
    assert tutor_body["content_source_scope"] == "published_admin_content"
    assert tutor_body["content_fallback_used"] is False
    assert "published admin-reviewed content" in (tutor_body["content_sourcing_note"] or "").lower()

    quiz_response = client.post(
        "/api/test/generate",
        json={
            "exam": "upsc",
            "subject": "polity",
            "topic": "Preamble",
            "question_count": 5,
        },
    )
    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["topic"] == "Preamble"
    assert quiz_body["content_corpus_id"] == "admin_published_content"
    assert quiz_body["content_source_scope"] == "published_admin_content"
    assert quiz_body["content_fallback_used"] is False

    export_response = client.post(
        "/api/tutor/export/lesson/download",
        json={
            "exam": "upsc",
            "subject": "polity",
            "topic": "Preamble",
            "export_format": "markdown_export",
        },
    )
    assert export_response.status_code == 200
    assert "attachment;" in export_response.headers["content-disposition"].lower()
    assert "preamble" in export_response.headers["content-disposition"].lower()


def test_auth_operational_logs_do_not_expose_otp_or_full_email(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="backend.services.auth_service")
    caplog.set_level(logging.INFO, logger="backend.services.mail_service")

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "privacy-log@example.com", "display_name": "Privacy Log"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()
    otp_code = request_body["dev_otp_code"]
    assert otp_code

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "privacy-log@example.com", "code": otp_code},
    )
    assert verify_response.status_code == 200

    log_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name in {"backend.services.auth_service", "backend.services.mail_service"}
    )

    assert "event=auth.otp_requested" in log_text
    assert "event=auth.otp_verified" in log_text
    assert "event=auth.login_succeeded" in log_text
    assert "event=email.otp_dev_fallback" in log_text
    assert "email_hash=" in log_text
    assert "privacy-log@example.com" not in log_text
    assert otp_code not in log_text


def test_request_id_header_and_validation_errors_are_safe(client: TestClient) -> None:
    response = client.post(
        "/api/auth/request-otp",
        json={},
        headers={"X-Request-ID": "ops-test-123"},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "ops-test-123"
    body = response.json()
    assert body["detail"] == "Request validation failed."
    assert body["errors"]
    assert all("input" not in error for error in body["errors"])


def test_verify_otp_rejects_wrong_code(client: TestClient) -> None:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "wrong-code@example.com"},
    )
    assert request_response.status_code == 200

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "wrong-code@example.com", "code": "000000"},
    )
    assert verify_response.status_code == 401
    assert "incorrect otp" in verify_response.json()["detail"].lower()


def test_verify_otp_locks_challenge_after_max_wrong_attempts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "email_otp_max_attempts", 2)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "lockout@example.com"},
    )
    assert request_response.status_code == 200
    correct_code = request_response.json()["dev_otp_code"]

    first_wrong_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "lockout@example.com", "code": "000000"},
    )
    assert first_wrong_response.status_code == 401

    second_wrong_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "lockout@example.com", "code": "111111"},
    )
    assert second_wrong_response.status_code == 429
    assert "too many attempts" in second_wrong_response.json()["detail"].lower()
    assert int(second_wrong_response.headers["Retry-After"]) >= 1

    retry_correct_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "lockout@example.com", "code": correct_code},
    )
    assert retry_correct_response.status_code == 401
    assert "no active otp" in retry_correct_response.json()["detail"].lower()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        challenge = db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "lockout@example.com").first()
        assert challenge is not None
        assert challenge.attempts_count == 2
        assert challenge.consumed_at is not None
    finally:
        db.close()


def test_verify_otp_enforces_hourly_email_attempt_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "email_otp_max_verify_attempts_per_hour_per_email", 2)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "verify-limit@example.com"},
    )
    assert request_response.status_code == 200

    for wrong_code in ("000000", "111111"):
        wrong_response = client.post(
            "/api/auth/verify-otp",
            json={"email": "verify-limit@example.com", "code": wrong_code},
        )
        assert wrong_response.status_code == 401

    limited_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "verify-limit@example.com", "code": "222222"},
    )
    assert limited_response.status_code == 429
    assert "too many otp verification attempts" in limited_response.json()["detail"].lower()
    assert int(limited_response.headers["Retry-After"]) >= 1


def test_auth_me_requires_active_session(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "sign in" in response.json()["detail"].lower()


def test_phase29_premium_canceling_subscription_stays_current_until_period_end(client: TestClient) -> None:
    authenticate_premium_test_user(client, email="phase29-canceling@example.com", display_name="Phase 29 Canceling")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-canceling@example.com").first()
        assert user is not None
        user.subscription_status = "canceled"
        user.subscription_cancel_at_period_end = True
        user.subscription_current_period_end = datetime.now(UTC) + timedelta(days=10)
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "canceled"
    assert me_body["entitlements"]["plan_current"] is True
    assert me_body["feature_access"]["lesson_exports"] is True
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "canceling"
    assert me_body["entitlements"]["subscription_lifecycle"]["access_active"] is True
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "canceling"


def test_phase29_premium_upgrade_syncs_inactive_status_to_active_from_future_period(client: TestClient) -> None:
    authenticate_test_user(client, email="phase29-upgrade-sync@example.com", display_name="Phase 29 Upgrade Sync")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-upgrade-sync@example.com").first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "inactive"
        user.subscription_current_period_end = datetime.now(UTC) + timedelta(days=14)
        user.subscription_trial_ends_at = None
        user.subscription_started_at = None
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_plan"] == "premium"
    assert me_body["subscription_status"] == "active"
    assert me_body["entitlements"]["plan_current"] is True
    assert me_body["feature_access"]["lesson_exports"] is True
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "active"
    assert me_body["billing"]["subscription_started_at"] is not None

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-upgrade-sync@example.com").first()
        assert user is not None
        assert user.subscription_status == "active"
        assert user.subscription_started_at is not None
    finally:
        db.close()


def test_phase29_entitlement_and_usage_helpers_derive_effective_premium_state_without_persisted_sync(
    client: TestClient,
) -> None:
    auth = authenticate_test_user(
        client,
        email="phase29-derived-entitlement@example.com",
        display_name="Phase 29 Derived Entitlement",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.id == user_id).first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "inactive"
        user.subscription_current_period_end = datetime.now(UTC) + timedelta(days=14)
        user.subscription_trial_ends_at = None
        user.subscription_cancel_at_period_end = False
        db.add(user)
        db.commit()
        db.refresh(user)

        from backend.services.plan_service import build_entitlement_summary
        from backend.services.usage_metering_service import build_usage_quota_snapshot

        entitlement_summary = build_entitlement_summary(user)
        quota_snapshot = build_usage_quota_snapshot(db, user=user, limit_key="advanced_lesson_exports")
    finally:
        db.close()

    assert entitlement_summary["subscription_status"] == "active"
    assert entitlement_summary["subscription_lifecycle"]["state"] == "active"
    assert entitlement_summary["plan_current"] is True
    assert entitlement_summary["feature_access"]["lesson_exports"] is True
    assert quota_snapshot.subscription_status == "active"
    assert quota_snapshot.plan_current is True
    assert quota_snapshot.entitlement_enabled is True
    assert quota_snapshot.limit_value == 100


def test_phase29_expired_premium_falls_back_to_free_access(client: TestClient) -> None:
    authenticate_premium_test_user(client, email="phase29-expired@example.com", display_name="Phase 29 Expired")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-expired@example.com").first()
        assert user is not None
        user.subscription_status = "canceled"
        user.subscription_cancel_at_period_end = True
        user.subscription_current_period_end = datetime.now(UTC) - timedelta(days=2)
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "canceled"
    assert me_body["entitlements"]["plan_current"] is False
    assert me_body["feature_access"]["lesson_exports"] is False
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "expired"
    assert me_body["billing"]["subscription_lifecycle"]["access_active"] is False


def test_phase29_canceling_premium_is_synchronized_to_expired_after_period_end(client: TestClient) -> None:
    authenticate_premium_test_user(
        client,
        email="phase29-canceling-expired-sync@example.com",
        display_name="Phase 29 Canceling Expired Sync",
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-canceling-expired-sync@example.com").first()
        assert user is not None
        user.subscription_status = "active"
        user.subscription_cancel_at_period_end = True
        user.subscription_current_period_end = datetime.now(UTC) - timedelta(days=1)
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "canceled"
    assert me_body["entitlements"]["plan_current"] is False
    assert me_body["feature_access"]["lesson_exports"] is False
    assert me_body["billing"]["subscription_lifecycle"]["state"] == "expired"

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-canceling-expired-sync@example.com").first()
        assert user is not None
        assert user.subscription_status == "canceled"
    finally:
        db.close()


def test_phase29_trialing_subscription_is_current(client: TestClient) -> None:
    auth = authenticate_test_user(client, email="phase29-trial@example.com", display_name="Phase 29 Trial")
    assert auth["user"]["subscription_plan"] == "free"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-trial@example.com").first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "trial"
        user.subscription_trial_ends_at = datetime.now(UTC) + timedelta(days=7)
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "trial"
    assert me_body["entitlements"]["plan_current"] is True
    assert me_body["feature_access"]["lesson_exports"] is True
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "trialing"
    assert me_body["billing"]["subscription_lifecycle"]["trial_ends_at"] is not None


def test_phase29_suspended_subscription_disables_premium_access(client: TestClient) -> None:
    authenticate_premium_test_user(client, email="phase29-suspended@example.com", display_name="Phase 29 Suspended")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-suspended@example.com").first()
        assert user is not None
        user.subscription_status = "suspended"
        user.subscription_cancel_at_period_end = False
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_status"] == "suspended"
    assert me_body["entitlements"]["plan_current"] is False
    assert me_body["feature_access"]["lesson_exports"] is False
    assert me_body["entitlements"]["subscription_lifecycle"]["state"] == "suspended"
    assert me_body["billing"]["subscription_lifecycle"]["requires_payment_action"] is False


def test_phase29_free_downgrade_keeps_old_render_assets_visible_but_blocks_new_premium_actions(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticate_premium_test_user(
        client,
        email="phase29-free-downgrade-assets@example.com",
        display_name="Phase 29 Free Downgrade Assets",
    )

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "phase29-free-downgrade-assets"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert create_response.status_code == 200
    created_job = create_response.json()
    assert created_job["lifecycle_state"] == "queued"
    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=created_job["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/video/{created_job['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["lifecycle_state"] == "succeeded"
    assert status_body["output"]["download_path"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-free-downgrade-assets@example.com").first()
        assert user is not None
        user.subscription_plan = "free"
        user.subscription_status = "active"
        user.subscription_current_period_end = datetime.now(UTC) + timedelta(days=7)
        user.subscription_trial_ends_at = datetime.now(UTC) + timedelta(days=3)
        user.subscription_cancel_at_period_end = True
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_body = client.get("/api/auth/me").json()["user"]
    assert me_body["subscription_plan"] == "free"
    assert me_body["subscription_status"] == "inactive"
    assert me_body["feature_access"]["lesson_exports"] is False
    assert me_body["feature_access"]["premium_lesson_modes"] is False
    assert me_body["billing"]["cancel_at_period_end"] is False
    assert me_body["billing"]["current_period_end"] is None
    assert me_body["billing"]["trial_ends_at"] is None

    assets_response = client.get("/api/tutor/render/assets?render_type=slide_video")
    assert assets_response.status_code == 200
    assets_body = assets_response.json()
    assert [item["id"] for item in assets_body] == [created_job["id"]]

    download_response = client.get(status_body["output"]["download_path"])
    assert download_response.status_code == 200

    blocked_create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
        },
    )
    assert blocked_create_response.status_code == 403
    detail = blocked_create_response.json()["detail"]
    assert detail["feature_key"] == "lesson_exports"
    assert detail["required_plan"] == "premium"

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-free-downgrade-assets@example.com").first()
        assert user is not None
        assert user.subscription_plan == "free"
        assert user.subscription_status == "inactive"
        assert user.subscription_current_period_end is None
        assert user.subscription_trial_ends_at is None
        assert user.subscription_cancel_at_period_end is False
    finally:
        db.close()


def test_phase29_advanced_export_route_records_usage_consumption(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-meter-export@example.com", display_name="Phase 29 Export Meter")
    user_id = auth["user"]["id"]

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": "json_export",
        },
    )
    assert response.status_code == 200

    records = get_usage_consumption_records(client, user_id=user_id, limit_key="advanced_lesson_exports")
    assert len(records) == 1
    assert records[0].source_action == "lesson.export"
    assert records[0].export_format == "json_export"
    assert records[0].topic == "Preamble"


def test_phase29_premium_video_explain_route_records_usage_consumption(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-meter-video@example.com", display_name="Phase 29 Video Meter")
    user_id = auth["user"]["id"]

    response = client.post(
        "/api/tutor/explain",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert response.status_code == 200

    records = get_usage_consumption_records(client, user_id=user_id, limit_key="premium_lesson_mode_generations")
    assert len(records) == 1
    assert records[0].source_action == "tutor.explain"
    assert records[0].lesson_mode == "video_lecture"


def test_phase29_audio_render_route_records_media_usage_consumption(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-meter-render@example.com", display_name="Phase 29 Render Meter")
    user_id = auth["user"]["id"]

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            payload = dict(json or {})
            return FakeResponse(f"PHASE29-AUDIO::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service

    monkeypatch.setattr(
        tts_service,
        "get_settings",
        lambda: Settings(
            tts_provider="openai",
            tts_openai_api_key="test-openai-tts-key",
            tts_openai_model="gpt-4o-mini-tts",
            tts_openai_voice="alloy",
            tts_output_format="mp3",
            media_render_output_dir=str(tmp_path / "phase29-render-output"),
        ),
    )
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert response.status_code == 200
    job_body = response.json()
    assert job_body["lifecycle_state"] == "queued"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "succeeded"

    render_records = get_usage_consumption_records(client, user_id=user_id, limit_key="media_render_creations")
    assert len(render_records) == 1
    assert render_records[0].source_action == "media_render.audio_create"
    assert render_records[0].render_type == "audio"
    assert render_records[0].media_render_job_id == job_body["id"]

    premium_mode_records = get_usage_consumption_records(client, user_id=user_id, limit_key="premium_lesson_mode_generations")
    assert premium_mode_records == []


def test_phase29_audio_and_advanced_exports_can_use_lesson_export_access_without_premium_video_modes(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticate_test_user(
        client,
        email="phase29-exports-only@example.com",
        display_name="Phase 29 Exports Only",
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "phase29-exports-only@example.com").first()
        assert user is not None
        user.feature_access_overrides_json = json.dumps(
            {
                "lesson_exports": True,
                "premium_lesson_modes": False,
            }
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "phase29-exports-only"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    export_response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": "json_export",
        },
    )
    assert export_response.status_code == 200

    audio_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
        },
    )
    assert audio_response.status_code == 200
    assert wait_for_media_render_job_terminal_state(client, job_id=audio_response.json()["id"]).lifecycle_state == "failed"

    video_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "render_type": "slide_video",
        },
    )
    assert video_response.status_code == 403
    detail = video_response.json()["detail"]
    assert detail["feature_key"] == "premium_lesson_modes"
    assert detail["required_plan"] == "premium"


def test_phase29_premium_lesson_mode_quota_is_not_consumed_by_export_or_render_followups(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase29-followup-separation@example.com",
        display_name="Phase 29 Followup Separation",
    )
    user_id = auth["user"]["id"]

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "phase29-followup-separation"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    explain_response = client.post(
        "/api/tutor/explain",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert explain_response.status_code == 200

    export_response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "export_format": "json_export",
        },
    )
    assert export_response.status_code == 200

    video_render_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert video_render_response.status_code == 200
    assert wait_for_media_render_job_terminal_state(client, job_id=video_render_response.json()["id"]).lifecycle_state == "succeeded"

    premium_mode_records = get_usage_consumption_records(
        client,
        user_id=user_id,
        limit_key="premium_lesson_mode_generations",
    )
    advanced_export_records = get_usage_consumption_records(
        client,
        user_id=user_id,
        limit_key="advanced_lesson_exports",
    )
    media_render_records = get_usage_consumption_records(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
    )

    assert len(premium_mode_records) == 1
    assert premium_mode_records[0].source_action == "tutor.explain"
    assert len(advanced_export_records) == 1
    assert advanced_export_records[0].source_action == "lesson.export"
    assert len(media_render_records) == 1
    assert media_render_records[0].source_action == "media_render.video_create"


def test_phase29_advanced_export_limit_blocks_additional_creation(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-limit-export@example.com", display_name="Phase 29 Export Limit")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        for index in range(100):
            db.add(
                UsageConsumptionRecord(
                    user_id=user_id,
                    limit_key="advanced_lesson_exports",
                    source_action="seed.advanced_export",
                    units_consumed=1,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic=f"Seed {index}",
                    metadata_json="{}",
                    created_at=now,
                )
            )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": "json_export",
        },
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["usage_limit_reached"] is True
    assert detail["limit_key"] == "advanced_lesson_exports"
    assert detail["remaining"] == 0


def test_phase29_premium_video_mode_limit_blocks_explain(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-limit-video@example.com", display_name="Phase 29 Video Limit")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        for index in range(120):
            db.add(
                UsageConsumptionRecord(
                    user_id=user_id,
                    limit_key="premium_lesson_mode_generations",
                    source_action="seed.premium_video_mode",
                    units_consumed=1,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic=f"Seed {index}",
                    lesson_mode="video_lecture",
                    metadata_json="{}",
                    created_at=now,
                )
            )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/tutor/explain",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["usage_limit_reached"] is True
    assert detail["limit_key"] == "premium_lesson_mode_generations"
    assert detail["remaining"] == 0


def test_phase29_media_render_limit_blocks_audio_creation(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-limit-audio-render@example.com", display_name="Phase 29 Audio Render Limit")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        for index in range(60):
            db.add(
                UsageConsumptionRecord(
                    user_id=user_id,
                    limit_key="media_render_creations",
                    source_action="seed.media_render",
                    units_consumed=1,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic=f"Seed {index}",
                    render_type="audio",
                    metadata_json="{}",
                    created_at=now,
                )
            )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["usage_limit_reached"] is True
    assert detail["limit_key"] == "media_render_creations"
    assert detail["remaining"] == 0


def test_phase29_media_render_limit_blocks_video_creation(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase29-limit-video-render@example.com", display_name="Phase 29 Video Render Limit")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        for index in range(60):
            db.add(
                UsageConsumptionRecord(
                    user_id=user_id,
                    limit_key="media_render_creations",
                    source_action="seed.media_render",
                    units_consumed=1,
                    plan_tier="premium",
                    subscription_status="active",
                    exam="upsc",
                    subject="polity",
                    topic=f"Seed {index}",
                    render_type="narrated_video",
                    metadata_json="{}",
                    created_at=now,
                )
            )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["usage_limit_reached"] is True
    assert detail["limit_key"] == "media_render_creations"
    assert detail["remaining"] == 0


def test_verify_otp_rejects_expired_code(client: TestClient) -> None:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "expired@example.com"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        challenge = db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "expired@example.com").first()
        assert challenge is not None
        challenge.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.add(challenge)
        db.commit()
    finally:
        db.close()

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "expired@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 401
    assert "expired" in verify_response.json()["detail"].lower()


def test_request_otp_enforces_resend_cooldown(client: TestClient) -> None:
    first_response = client.post(
        "/api/auth/request-otp",
        json={"email": "cooldown@example.com"},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        "/api/auth/request-otp",
        json={"email": "cooldown@example.com"},
    )
    assert second_response.status_code == 429
    assert "wait" in second_response.json()["detail"].lower()
    assert int(second_response.headers["Retry-After"]) >= 1


def test_request_otp_does_not_return_dev_code_without_explicit_opt_in(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "console")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", False)

    response = client.post(
        "/api/auth/request-otp",
        json={"email": "console-hidden@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_mode"] == "console"
    assert body["dev_otp_code"] is None


def test_request_otp_uses_email_delivery_interface_when_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service

    delivered_payload: dict[str, str] = {}
    previous_mode = auth_service.settings.email_otp_delivery_mode
    previous_dev_return = auth_service.settings.auth_dev_return_otp
    auth_service.settings.email_otp_delivery_mode = "email"
    auth_service.settings.auth_dev_return_otp = True

    def fake_deliver_sign_in_otp(**kwargs):
        delivered_payload.update({key: str(value) for key, value in kwargs.items() if value is not None})

    monkeypatch.setattr(auth_service, "deliver_sign_in_otp", fake_deliver_sign_in_otp)

    try:
        response = client.post(
            "/api/auth/request-otp",
            json={"email": "mailmode@example.com", "display_name": "Mail Mode"},
        )
    finally:
        auth_service.settings.email_otp_delivery_mode = previous_mode
        auth_service.settings.auth_dev_return_otp = previous_dev_return

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_mode"] == "email"
    assert body["dev_otp_code"] is None
    assert delivered_payload["recipient_email"] == "mailmode@example.com"
    assert delivered_payload["otp_code"]


def test_request_otp_sends_smtp_email_without_exposing_dev_otp(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service, mail_service

    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, *, host: str, port: int, timeout: int):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout
            sent["started_tls"] = False

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            sent["closed"] = True

        def ehlo(self) -> None:
            sent["ehlo_count"] = int(sent.get("ehlo_count", 0)) + 1

        def starttls(self, *, context: object) -> None:
            sent["started_tls"] = context is not None

        def login(self, username: str, password: str) -> None:
            sent["logged_in"] = (username, password)

        def send_message(self, message) -> None:
            sent["subject"] = message["Subject"]
            sent["from"] = message["From"]
            sent["to"] = message["To"]

    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "email")
    monkeypatch.setattr(auth_service.settings, "email_transport", "smtp")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", False)
    monkeypatch.setattr(auth_service.settings, "email_from_name", "Adhyantra")
    monkeypatch.setattr(auth_service.settings, "email_from_address", "hello@example.com")
    monkeypatch.setattr(auth_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(auth_service.settings, "smtp_port", 2525)
    monkeypatch.setattr(auth_service.settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(auth_service.settings, "smtp_password", "smtp-pass")
    monkeypatch.setattr(auth_service.settings, "smtp_use_tls", True)
    monkeypatch.setattr(auth_service.settings, "smtp_use_ssl", False)
    monkeypatch.setattr(auth_service.settings, "smtp_timeout_seconds", 9)
    monkeypatch.setattr(mail_service.smtplib, "SMTP", FakeSMTP)

    response = client.post(
        "/api/auth/request-otp",
        json={"email": "smtp-login@example.com", "display_name": "SMTP Login"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_mode"] == "email"
    assert body["dev_otp_code"] is None
    assert sent["host"] == "smtp.example.com"
    assert sent["to"] == "smtp-login@example.com"
    assert sent["subject"] == "Your Adhyantra sign-in code"
    assert sent["started_tls"] is True
    assert sent["logged_in"] == ("smtp-user", "smtp-pass")


def test_sign_in_otp_email_template_is_adhyantra_branded() -> None:
    email = build_sign_in_otp_email(
        recipient_email="template@example.com",
        otp_code="123456",
        expires_at=datetime(2026, 4, 20, 12, 30, tzinfo=UTC),
        display_name="<Learner>",
    )

    assert email.recipient_email == "template@example.com"
    assert email.subject == "Your Adhyantra sign-in code"
    assert "Your Adhyantra sign-in code is: 123456" in email.text_body
    assert "We will never ask for this code anywhere else" in email.text_body
    assert "2026-04-20 12:30 UTC" in email.text_body
    assert email.html_body is not None
    assert "Adhyantra" in email.html_body
    assert "&lt;Learner&gt;" in email.html_body
    assert "<Learner>" not in email.html_body


def test_send_email_uses_configured_smtp_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import mail_service

    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, *, host: str, port: int, timeout: int):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout
            sent["started_tls"] = False
            sent["logged_in"] = False

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            sent["closed"] = True

        def ehlo(self) -> None:
            sent["ehlo_count"] = int(sent.get("ehlo_count", 0)) + 1

        def starttls(self, *, context: object) -> None:
            sent["started_tls"] = context is not None

        def login(self, username: str, password: str) -> None:
            sent["logged_in"] = (username, password)

        def send_message(self, message) -> None:
            sent["subject"] = message["Subject"]
            sent["from"] = message["From"]
            sent["to"] = message["To"]
            sent["reply_to"] = message["Reply-To"]

    monkeypatch.setattr(mail_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mail_service.settings, "smtp_port", 2525)
    monkeypatch.setattr(mail_service.settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(mail_service.settings, "smtp_password", "smtp-pass")
    monkeypatch.setattr(mail_service.settings, "smtp_use_tls", True)
    monkeypatch.setattr(mail_service.settings, "smtp_use_ssl", False)
    monkeypatch.setattr(mail_service.settings, "smtp_timeout_seconds", 9)
    monkeypatch.setattr(mail_service.settings, "email_transport", "smtp")
    monkeypatch.setattr(mail_service.settings, "email_from_name", "Adhyantra")
    monkeypatch.setattr(mail_service.settings, "email_from_address", "hello@example.com")
    monkeypatch.setattr(mail_service.settings, "email_reply_to_address", "support@example.com")
    monkeypatch.setattr(mail_service.smtplib, "SMTP", FakeSMTP)

    email = build_sign_in_otp_email(
        recipient_email="smtp-recipient@example.com",
        otp_code="654321",
        expires_at=datetime(2026, 4, 20, 12, 30, tzinfo=UTC),
        display_name="SMTP Learner",
    )
    result = mail_service.send_email(email, delivery_mode="email")

    assert result.delivery_mode == "email"
    assert result.transport == "smtp"
    assert result.external_delivery is True
    assert sent["host"] == "smtp.example.com"
    assert sent["port"] == 2525
    assert sent["timeout"] == 9
    assert sent["started_tls"] is True
    assert sent["logged_in"] == ("smtp-user", "smtp-pass")
    assert sent["subject"] == "Your Adhyantra sign-in code"
    assert sent["from"] == "Adhyantra <hello@example.com>"
    assert sent["to"] == "smtp-recipient@example.com"
    assert sent["reply_to"] == "support@example.com"


def test_send_email_can_use_smtp_ssl_without_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import mail_service

    sent: dict[str, object] = {}

    class FakeSMTPSSL:
        def __init__(self, *, host: str, port: int, timeout: int, context: object):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout
            sent["context_configured"] = context is not None
            sent["started_tls"] = False

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            sent["closed"] = True

        def ehlo(self) -> None:
            sent["ehlo_count"] = int(sent.get("ehlo_count", 0)) + 1

        def starttls(self, *, context: object) -> None:
            sent["started_tls"] = context is not None

        def login(self, username: str, password: str) -> None:
            sent["logged_in"] = (username, password)

        def send_message(self, message) -> None:
            sent["subject"] = message["Subject"]
            sent["to"] = message["To"]

    monkeypatch.setattr(mail_service.settings, "smtp_host", "smtp-ssl.example.com")
    monkeypatch.setattr(mail_service.settings, "smtp_port", 465)
    monkeypatch.setattr(mail_service.settings, "smtp_username", "")
    monkeypatch.setattr(mail_service.settings, "smtp_password", "")
    monkeypatch.setattr(mail_service.settings, "smtp_use_tls", True)
    monkeypatch.setattr(mail_service.settings, "smtp_use_ssl", True)
    monkeypatch.setattr(mail_service.settings, "smtp_timeout_seconds", 11)
    monkeypatch.setattr(mail_service.settings, "email_transport", "smtp")
    monkeypatch.setattr(mail_service.settings, "email_from_name", "Adhyantra")
    monkeypatch.setattr(mail_service.settings, "email_from_address", "hello@example.com")
    monkeypatch.setattr(mail_service.settings, "email_reply_to_address", "")
    monkeypatch.setattr(mail_service.smtplib, "SMTP_SSL", FakeSMTPSSL)

    email = build_sign_in_otp_email(
        recipient_email="smtp-ssl-recipient@example.com",
        otp_code="654321",
        expires_at=datetime(2026, 4, 20, 12, 30, tzinfo=UTC),
        display_name="SMTP SSL Learner",
    )
    result = mail_service.send_email(email, delivery_mode="smtp")

    assert result.transport == "smtp"
    assert sent["host"] == "smtp-ssl.example.com"
    assert sent["port"] == 465
    assert sent["timeout"] == 11
    assert sent["context_configured"] is True
    assert sent["started_tls"] is False
    assert sent["subject"] == "Your Adhyantra sign-in code"
    assert sent["to"] == "smtp-ssl-recipient@example.com"


def test_request_otp_blocks_console_delivery_in_production(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "app_env", "production")
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "console")

    response = client.post(
        "/api/auth/request-otp",
        json={"email": "console-production@example.com"},
    )
    assert response.status_code == 503
    assert "could not deliver" in response.json()["detail"].lower()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        assert db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "console-production@example.com").count() == 0
    finally:
        db.close()


def test_request_otp_blocks_console_delivery_in_staging(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "app_env", "staging")
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "console")

    response = client.post(
        "/api/auth/request-otp",
        json={"email": "console-staging@example.com"},
    )
    assert response.status_code == 503
    assert "could not deliver" in response.json()["detail"].lower()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        assert db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "console-staging@example.com").count() == 0
    finally:
        db.close()


def test_request_otp_rejects_unsupported_delivery_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "sendgrid")

    response = client.post(
        "/api/auth/request-otp",
        json={"email": "unsupported-delivery@example.com"},
    )
    assert response.status_code == 503
    assert "delivery is not configured" in response.json()["detail"].lower()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        assert db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "unsupported-delivery@example.com").count() == 0
    finally:
        db.close()


def test_production_mode_suppresses_dev_otp_and_sets_secure_session_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "app_env", "production")
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "email")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", True)
    monkeypatch.setattr(auth_service.settings, "secure_session_cookies", False)
    monkeypatch.setattr(auth_service, "_generate_otp_code", lambda: "123456")
    monkeypatch.setattr(auth_service, "deliver_sign_in_otp", lambda **_: None)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "production-cookie@example.com", "display_name": "Production Learner"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()
    assert request_body["delivery_mode"] == "email"
    assert request_body["dev_otp_code"] is None

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "production-cookie@example.com", "code": "123456"},
    )
    assert verify_response.status_code == 200
    assert "Secure" in verify_response.headers["set-cookie"]


def test_staging_mode_suppresses_dev_otp_and_sets_secure_session_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "app_env", "staging")
    monkeypatch.setattr(auth_service.settings, "email_otp_delivery_mode", "email")
    monkeypatch.setattr(auth_service.settings, "auth_dev_return_otp", True)
    monkeypatch.setattr(auth_service.settings, "secure_session_cookies", False)
    monkeypatch.setattr(auth_service, "_generate_otp_code", lambda: "123456")
    monkeypatch.setattr(auth_service, "deliver_sign_in_otp", lambda **_: None)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "staging-cookie@example.com", "display_name": "Staging Learner"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()
    assert request_body["delivery_mode"] == "email"
    assert request_body["dev_otp_code"] is None

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "staging-cookie@example.com", "code": "123456"},
    )
    assert verify_response.status_code == 200
    assert "Secure" in verify_response.headers["set-cookie"]


def test_session_cookie_policy_is_config_driven(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "secure_session_cookies", True)
    monkeypatch.setattr(auth_service.settings, "session_cookie_samesite", "strict")
    monkeypatch.setattr(auth_service.settings, "session_cookie_domain", "adhyantra.test")
    monkeypatch.setattr(auth_service.settings, "session_cookie_path", "/app")
    monkeypatch.setattr(auth_service.settings, "session_ttl_days", 2)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "cookie-policy@example.com"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "cookie-policy@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200

    cookie_header = verify_response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "domain=adhyantra.test" in cookie_header
    assert "path=/app" in cookie_header
    assert "max-age=172800" in cookie_header


def test_cross_site_session_cookie_uses_none_and_host_only_domain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.routes import auth_routes
    from backend.services import auth_service

    monkeypatch.setattr(auth_service.settings, "frontend_origin", "https://adhyantra-ui.netlify.app")
    monkeypatch.setattr(auth_service.settings, "backend_public_url", "https://adhyantra-api.onrender.com")
    monkeypatch.setattr(auth_service.settings, "session_cookie_samesite", "lax")
    monkeypatch.setattr(auth_service.settings, "session_cookie_domain", "adhyantra.test")
    monkeypatch.setattr(auth_service.settings, "secure_session_cookies", False)
    monkeypatch.setattr(auth_routes.settings, "frontend_origin", "https://adhyantra-ui.netlify.app")
    monkeypatch.setattr(auth_routes.settings, "backend_public_url", "https://adhyantra-api.onrender.com")
    monkeypatch.setattr(auth_routes.settings, "session_cookie_samesite", "lax")
    monkeypatch.setattr(auth_routes.settings, "session_cookie_domain", "adhyantra.test")
    monkeypatch.setattr(auth_routes.settings, "secure_session_cookies", False)

    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "cross-site-cookie@example.com"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "cross-site-cookie@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200

    cookie_header = verify_response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=none" in cookie_header
    assert "domain=" not in cookie_header


def test_auth_me_without_cookie_does_not_emit_cookie_clear_header(client: TestClient) -> None:
    client.cookies.clear()

    me_response = client.get("/api/auth/me")

    assert me_response.status_code == 401
    assert me_response.headers.get("set-cookie") is None


def test_request_otp_returns_service_unavailable_when_email_delivery_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services import auth_service

    previous_mode = auth_service.settings.email_otp_delivery_mode
    auth_service.settings.email_otp_delivery_mode = "email"

    def failing_deliver_sign_in_otp(**_: object) -> None:
        raise EmailDeliveryError("boom")

    monkeypatch.setattr(auth_service, "deliver_sign_in_otp", failing_deliver_sign_in_otp)

    try:
        response = client.post(
            "/api/auth/request-otp",
            json={"email": "failure@example.com"},
        )
    finally:
        auth_service.settings.email_otp_delivery_mode = previous_mode

    assert response.status_code == 503
    assert "could not deliver" in response.json()["detail"].lower()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        assert db.query(EmailOtpChallenge).filter(EmailOtpChallenge.email == "failure@example.com").count() == 0
    finally:
        db.close()


def test_settings_persist_mentor_mode_theme_and_exam_preferences(client: TestClient) -> None:
    authenticate_test_user(client)

    update_response = client.put(
        "/api/settings",
        json={
            "theme_preference": "dark",
            "mentor_mode": "strict",
            "preferred_exam": "banking",
            "preferred_subject": "regulatory_basics",
            "timezone": "Asia/Calcutta",
            "study_reminders_enabled": False,
            "marketing_emails_enabled": True,
            "progress_digest_frequency": "weekly",
            "billing_notifications_enabled": False,
        },
    )
    assert update_response.status_code == 200
    update_body = update_response.json()

    assert update_body["theme_preference"] == "dark"
    assert update_body["mentor_mode"] == "strict"
    assert update_body["preferred_exam"] == "banking"
    assert update_body["preferred_subject"] == "regulatory_basics"
    assert update_body["current_exam"] == "banking"
    assert update_body["current_subject"] == "regulatory_basics"
    assert update_body["timezone"] == "Asia/Calcutta"
    assert update_body["study_reminders_enabled"] is False
    assert update_body["marketing_emails_enabled"] is True
    assert update_body["progress_digest_frequency"] == "weekly"
    assert update_body["billing_notifications_enabled"] is False

    settings_response = client.get("/api/settings")
    assert settings_response.status_code == 200
    settings_body = settings_response.json()
    assert settings_body == update_body

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["settings"] == update_body

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "learner@example.com").first()
        assert user is not None
        user_settings = db.query(UserSetting).filter(UserSetting.user_id == user.id).first()
        assert user_settings is not None
        assert user_settings.mentor_mode == "strict"
        assert user_settings.theme_preference == "dark"
        assert user_settings.preferred_exam == "banking"
        assert user_settings.preferred_subject == "regulatory_basics"
        assert user_settings.current_exam == "banking"
        assert user_settings.current_subject == "regulatory_basics"
        assert user_settings.study_reminders_enabled is False
        assert user_settings.marketing_emails_enabled is True
        assert user_settings.progress_digest_frequency == "weekly"
        assert user_settings.billing_notifications_enabled is False
    finally:
        db.close()


def test_profile_settings_update_and_session_reflect_display_name(client: TestClient) -> None:
    authenticate_test_user(client, email="profile@example.com", display_name="Profile Learner")

    update_response = client.put(
        "/api/profile",
        json={
            "display_name": "Asha Verma",
            "avatar_url": "https://example.com/avatar.png",
            "bio": "Focused on polity and revision discipline.",
            "locale": "en-IN",
            "onboarding_completed": True,
        },
    )
    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["display_name"] == "Asha Verma"
    assert update_body["avatar_url"] == "https://example.com/avatar.png"
    assert update_body["avatar_initials"] == "AV"
    assert update_body["bio"] == "Focused on polity and revision discipline."
    assert update_body["locale"] == "en-IN"
    assert update_body["onboarding_completed"] is True
    assert update_body["onboarding_completed_at"] is not None

    profile_response = client.get("/api/profile")
    assert profile_response.status_code == 200
    assert profile_response.json() == update_body

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["display_name"] == "Asha Verma"
    assert me_response.json()["profile"]["display_name"] == "Asha Verma"
    assert me_response.json()["profile"]["onboarding_completed"] is True

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "profile@example.com").first()
        assert user is not None
        assert user.display_name == "Asha Verma"
        profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        assert profile is not None
        assert profile.avatar_url == "https://example.com/avatar.png"
        assert profile.avatar_initials == "AV"
        assert profile.bio == "Focused on polity and revision discipline."
        assert profile.locale == "en-IN"
        assert profile.onboarding_state == "completed"
        assert profile.onboarding_completed_at is not None
    finally:
        db.close()


def test_verify_otp_and_current_session_include_profile_onboarding_state(client: TestClient) -> None:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "onboarding-session@example.com", "display_name": "Onboarding Learner"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()
    assert request_body["is_new_user"] is True

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "onboarding-session@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200
    verify_body = verify_response.json()
    assert verify_body["profile"]["display_name"] == "Onboarding Learner"
    assert verify_body["profile"]["onboarding_state"] == "new"
    assert verify_body["profile"]["onboarding_completed"] is False

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["profile"]["display_name"] == "Onboarding Learner"
    assert me_body["profile"]["onboarding_state"] == "new"
    assert me_body["profile"]["onboarding_completed"] is False


def test_verify_otp_and_current_session_include_activation_milestones(client: TestClient) -> None:
    request_response = client.post(
        "/api/auth/request-otp",
        json={"email": "activation-session@example.com", "display_name": "Activation Learner"},
    )
    assert request_response.status_code == 200
    request_body = request_response.json()

    verify_response = client.post(
        "/api/auth/verify-otp",
        json={"email": "activation-session@example.com", "code": request_body["dev_otp_code"]},
    )
    assert verify_response.status_code == 200
    verify_body = verify_response.json()
    activation = verify_body["user"]["activation"]
    conversion = verify_body["user"]["conversion"]

    assert activation["state"] == "otp_verified"
    assert activation["status_label"] == "OTP verified"
    assert activation["progress_count"] == 2
    assert activation["total_milestones"] == 7
    assert activation["activated"] is False
    assert activation["latest_milestone_key"] == "otp_verified"
    assert activation["next_milestone_key"] == "onboarding_completed"
    assert activation["next_milestone_label"] == "Setup completed"

    milestone_map = {item["key"]: item for item in activation["milestones"]}
    assert milestone_map["account_created"]["completed"] is True
    assert milestone_map["account_created"]["achieved_at"] is not None
    assert milestone_map["otp_verified"]["completed"] is True
    assert milestone_map["otp_verified"]["achieved_at"] is not None
    assert milestone_map["onboarding_completed"]["completed"] is False
    assert milestone_map["first_study_session_completed"]["completed"] is False
    assert conversion["eligible"] is False
    assert conversion["moment_key"] is None

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["user"]["activation"]["state"] == "otp_verified"
    assert me_body["user"]["activation"]["progress_count"] == 2
    assert me_body["user"]["conversion"]["eligible"] is False


def test_activation_milestones_reach_first_real_study_session(client: TestClient) -> None:
    authenticate_test_user(client, email="activation-study@example.com", display_name="Activation Study")

    profile_response = client.put(
        "/api/profile",
        json={
            "display_name": "Activation Study",
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["onboarding_completed"] is True

    lesson_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism"},
    )
    assert lesson_response.status_code == 200

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5},
    )
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_correct_answers(client, quiz)},
    )
    assert submit_response.status_code == 200

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    activation = me_response.json()["user"]["activation"]
    milestone_map = {item["key"]: item for item in activation["milestones"]}

    assert activation["state"] == "first_study_session_completed"
    assert activation["status_label"] == "First study session completed"
    assert activation["progress_count"] == 7
    assert activation["total_milestones"] == 7
    assert activation["activated"] is True
    assert activation["latest_milestone_key"] == "first_study_session_completed"
    assert activation["next_milestone_key"] is None
    assert activation["next_milestone_label"] is None

    assert milestone_map["onboarding_completed"]["completed"] is True
    assert milestone_map["first_topic_selected"]["completed"] is True
    assert milestone_map["first_lesson_generated"]["completed"] is True
    assert milestone_map["first_quiz_completed"]["completed"] is True
    assert milestone_map["first_study_session_completed"]["completed"] is True
    assert milestone_map["first_lesson_generated"]["achieved_at"] is not None
    assert milestone_map["first_quiz_completed"]["achieved_at"] is not None
    assert milestone_map["first_study_session_completed"]["achieved_at"] is not None


def test_conversion_summary_marks_export_engaged_activated_user(client: TestClient) -> None:
    authenticate_test_user(client, email="conversion-export@example.com", display_name="Conversion Export")

    profile_response = client.put(
        "/api/profile",
        json={
            "display_name": "Conversion Export",
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200

    lesson_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism"},
    )
    assert lesson_response.status_code == 200

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5},
    )
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_correct_answers(client, quiz)},
    )
    assert submit_response.status_code == 200

    export_response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Federalism",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "lecture_outline",
            "export_format": "markdown_export",
        },
    )
    assert export_response.status_code == 200

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    conversion = me_response.json()["user"]["conversion"]

    assert conversion["eligible"] is True
    assert conversion["moment_key"] == "export_engaged"
    assert conversion["feature_focus"] == "lesson_exports"
    assert conversion["title"] == "Premium fits better once you're already reusing lessons"
    assert "ready-made audio" in conversion["message"]
    assert conversion["action_label"] == "See Premium"


def test_conversion_summary_marks_paused_premium_user_for_resume(client: TestClient) -> None:
    authenticate_test_user(client, email="conversion-paused@example.com", display_name="Conversion Paused")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "conversion-paused@example.com").first()
        assert user is not None
        user.subscription_plan = "premium"
        user.subscription_status = "suspended"
        user.subscription_started_at = datetime.now(UTC) - timedelta(days=45)
        user.subscription_current_period_end = datetime.now(UTC) - timedelta(days=2)
        user.subscription_cancel_at_period_end = False
        db.add(user)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    conversion = me_response.json()["user"]["conversion"]

    assert conversion["eligible"] is True
    assert conversion["moment_key"] == "resume_premium"
    assert conversion["action_label"] == "Review plan"
    assert conversion["feature_focus"] in {"lesson_exports", "premium_lesson_modes"}
    assert conversion["title"] == "Premium can pick up where you left off"


def test_activation_summary_marks_verified_idle_user_for_recovery(client: TestClient) -> None:
    authenticate_test_user(client, email="verified-idle@example.com", display_name="Verified Idle")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "verified-idle@example.com").first()
        assert user is not None
        stale_verified_at = datetime.now(UTC) - timedelta(days=3)
        user.email_verified_at = stale_verified_at
        user.last_login_at = stale_verified_at
        user.last_active_at = stale_verified_at
        assert user.profile is not None
        user.profile.onboarding_state = "new"
        user.profile.onboarding_completed_at = None
        user.profile.updated_at = stale_verified_at
        db.add(user)
        db.add(user.profile)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    activation = me_response.json()["user"]["activation"]

    assert activation["journey_stage"] == "setup_incomplete"
    assert activation["needs_recovery"] is True
    assert activation["recovery_variant"] == "verified_idle"
    assert activation["guidance_title"] == "Finish your setup"
    assert activation["next_step_key"] == "complete_setup"
    assert activation["next_step_label"] == "Finish setup"
    assert activation["days_since_last_progress_signal"] >= 3


def test_activation_summary_marks_context_ready_idle_user_for_recovery(client: TestClient) -> None:
    authenticate_test_user(client, email="context-idle@example.com", display_name="Context Idle")

    profile_response = client.put(
        "/api/profile",
        json={
            "display_name": "Context Idle",
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "context-idle@example.com").first()
        assert user is not None
        assert user.profile is not None
        stale_setup_at = datetime.now(UTC) - timedelta(days=2)
        user.profile.onboarding_completed_at = stale_setup_at
        user.profile.updated_at = stale_setup_at
        user.last_login_at = stale_setup_at
        user.last_active_at = stale_setup_at
        db.add(user)
        db.add(user.profile)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    activation = me_response.json()["user"]["activation"]

    assert activation["journey_stage"] == "ready_to_start"
    assert activation["needs_recovery"] is True
    assert activation["recovery_variant"] == "context_ready_idle"
    assert activation["guidance_title"] == "Start the first study step"
    assert activation["next_step_key"] == "start_first_lesson"
    assert activation["next_step_label"] == "Start first lesson"
    assert activation["days_since_last_progress_signal"] >= 2


def test_activation_summary_marks_incomplete_first_session_for_recovery(client: TestClient) -> None:
    authenticate_test_user(client, email="partial-session@example.com", display_name="Partial Session")

    profile_response = client.put(
        "/api/profile",
        json={
            "display_name": "Partial Session",
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200

    lesson_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism"},
    )
    assert lesson_response.status_code == 200

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "partial-session@example.com").first()
        assert user is not None
        stale_lesson_at = datetime.now(UTC) - timedelta(days=2)
        assert user.profile is not None
        user.profile.onboarding_completed_at = stale_lesson_at
        user.profile.updated_at = stale_lesson_at
        lesson_event = (
            db.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == user.id,
                AnalyticsEvent.event_name == "tutor.explained",
            )
            .order_by(AnalyticsEvent.created_at.asc(), AnalyticsEvent.id.asc())
            .first()
        )
        assert lesson_event is not None
        lesson_event.created_at = stale_lesson_at
        user.last_login_at = stale_lesson_at
        user.last_active_at = stale_lesson_at
        db.add(user)
        db.add(user.profile)
        db.add(lesson_event)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    activation = me_response.json()["user"]["activation"]

    assert activation["journey_stage"] == "first_session_incomplete"
    assert activation["needs_recovery"] is True
    assert activation["recovery_variant"] == "first_session_incomplete"
    assert activation["guidance_title"] == "Finish the first study loop"
    assert activation["next_step_key"] == "take_first_quiz"
    assert activation["next_step_label"] == "Take first quiz"
    assert activation["days_since_last_progress_signal"] >= 2


def test_activation_summary_marks_low_momentum_after_first_study_session(client: TestClient) -> None:
    authenticate_test_user(client, email="low-momentum@example.com", display_name="Low Momentum")

    profile_response = client.put(
        "/api/profile",
        json={
            "display_name": "Low Momentum",
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200

    lesson_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism"},
    )
    assert lesson_response.status_code == 200

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5},
    )
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_correct_answers(client, quiz)},
    )
    assert submit_response.status_code == 200

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "low-momentum@example.com").first()
        assert user is not None
        stale_progress_at = datetime.now(UTC) - timedelta(days=3)
        assert user.profile is not None
        user.profile.onboarding_completed_at = stale_progress_at
        user.profile.updated_at = stale_progress_at
        user.last_login_at = stale_progress_at
        user.last_active_at = stale_progress_at
        lesson_event = (
            db.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == user.id,
                AnalyticsEvent.event_name == "tutor.explained",
            )
            .order_by(AnalyticsEvent.created_at.asc(), AnalyticsEvent.id.asc())
            .first()
        )
        quiz_event = (
            db.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == user.id,
                AnalyticsEvent.event_name == "quiz.submitted",
            )
            .order_by(AnalyticsEvent.created_at.asc(), AnalyticsEvent.id.asc())
            .first()
        )
        assert lesson_event is not None
        assert quiz_event is not None
        lesson_event.created_at = stale_progress_at
        quiz_event.created_at = stale_progress_at
        db.add(user)
        db.add(user.profile)
        db.add(lesson_event)
        db.add(quiz_event)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    me_body = me_response.json()["user"]
    activation = me_body["activation"]
    conversion = me_body["conversion"]

    assert activation["activated"] is True
    assert activation["journey_stage"] == "activated_low_momentum"
    assert activation["needs_recovery"] is True
    assert activation["recovery_variant"] == "activated_low_momentum"
    assert activation["guidance_title"] == "Keep the study rhythm moving"
    assert activation["next_step_key"] == "continue_with_next_lesson"
    assert activation["next_step_label"] == "Open Tutor"
    assert activation["days_since_last_progress_signal"] >= 3
    assert conversion["eligible"] is False
    assert conversion["moment_key"] is None


def test_authenticated_settings_drive_default_platform_context_when_request_omits_scope(client: TestClient) -> None:
    authenticate_test_user(client, email="banking-defaults@example.com", display_name="Banking Learner")

    settings_response = client.put(
        "/api/settings",
        json={
            "mentor_mode": "strict",
            "preferred_exam": "banking",
            "preferred_subject": "regulatory_basics",
        },
    )
    assert settings_response.status_code == 200

    summary_response = client.get("/api/progress/summary")
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert summary_body["exam"] == "banking"
    assert summary_body["subject"] == "regulatory_basics"
    assert summary_body["content_subject"] == "polity"
    assert summary_body["mentor_mode"] == "strict"

    plan_response = client.get("/api/plan/today")
    assert plan_response.status_code == 200
    plan_body = plan_response.json()
    assert plan_body["exam"] == "banking"
    assert plan_body["subject"] == "regulatory_basics"
    assert plan_body["content_subject"] == "polity"
    assert plan_body["mentor_mode"] == "strict"

    coach_response = client.get("/api/coach/summary")
    assert coach_response.status_code == 200
    coach_body = coach_response.json()
    assert coach_body["exam"] == "banking"
    assert coach_body["subject"] == "regulatory_basics"
    assert coach_body["content_subject"] == "polity"
    assert coach_body["mentor_mode"] == "strict"

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5},
    )
    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["exam"] == "banking"
    assert quiz_body["subject"] == "regulatory_basics"
    assert quiz_body["content_subject"] == "polity"

    explain_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism"},
    )
    assert explain_response.status_code == 200
    explain_body = explain_response.json()
    assert explain_body["exam"] == "banking"
    assert explain_body["subject"] == "regulatory_basics"
    assert explain_body["content_subject"] == "polity"


def test_persisted_current_exam_context_drives_omitted_scope_without_overwriting_preference(client: TestClient) -> None:
    authenticate_test_user(client, email="current-context@example.com", display_name="Current Context")

    settings_response = client.put(
        "/api/settings",
        json={
            "preferred_exam": "upsc",
            "preferred_subject": "polity",
            "current_exam": "banking",
            "current_subject": "regulatory_basics",
        },
    )
    assert settings_response.status_code == 200
    settings_body = settings_response.json()
    assert settings_body["preferred_exam"] == "upsc"
    assert settings_body["preferred_subject"] == "polity"
    assert settings_body["current_exam"] == "banking"
    assert settings_body["current_subject"] == "regulatory_basics"

    default_summary_response = client.get("/api/progress/summary")
    assert default_summary_response.status_code == 200
    default_summary = default_summary_response.json()
    assert default_summary["exam"] == "banking"
    assert default_summary["subject"] == "regulatory_basics"
    assert default_summary["content_subject"] == "polity"

    explicit_current_exam_response = client.get("/api/progress/summary?exam=banking")
    assert explicit_current_exam_response.status_code == 200
    explicit_current_exam_summary = explicit_current_exam_response.json()
    assert explicit_current_exam_summary["exam"] == "banking"
    assert explicit_current_exam_summary["subject"] == "regulatory_basics"
    assert explicit_current_exam_summary["content_subject"] == "polity"

    subjects_response = client.get("/api/subjects")
    assert subjects_response.status_code == 200
    subjects_body = subjects_response.json()
    assert subjects_body["default_exam"] == "banking"
    assert subjects_body["default_subject"] == "regulatory_basics"
    assert {item["code"] for item in subjects_body["subjects"]} >= {"financial_awareness", "regulatory_basics"}

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics_body = topics_response.json()
    assert topics_body["exam"] == "banking"
    assert topics_body["subject"] == "regulatory_basics"
    assert topics_body["content_subject"] == "polity"

    revision_response = client.get("/api/revision/due")
    assert revision_response.status_code == 200
    revision_body = revision_response.json()
    assert revision_body["exam"] == "banking"
    assert revision_body["subject"] == "regulatory_basics"
    assert revision_body["content_subject"] == "polity"

    plan_response = client.get("/api/plan/today")
    assert plan_response.status_code == 200
    plan_body = plan_response.json()
    assert plan_body["exam"] == "banking"
    assert plan_body["subject"] == "regulatory_basics"
    assert plan_body["content_subject"] == "polity"

    coach_response = client.get("/api/coach/summary")
    assert coach_response.status_code == 200
    coach_body = coach_response.json()
    assert coach_body["exam"] == "banking"
    assert coach_body["subject"] == "regulatory_basics"
    assert coach_body["content_subject"] == "polity"

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5},
    )
    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["exam"] == "banking"
    assert quiz_body["subject"] == "regulatory_basics"
    assert quiz_body["content_subject"] == "polity"

    explicit_exam_quiz_response = client.post(
        "/api/test/generate",
        json={"exam": "banking", "topic": "Federalism", "question_count": 5},
    )
    assert explicit_exam_quiz_response.status_code == 200
    explicit_exam_quiz_body = explicit_exam_quiz_response.json()
    assert explicit_exam_quiz_body["exam"] == "banking"
    assert explicit_exam_quiz_body["subject"] == "regulatory_basics"
    assert explicit_exam_quiz_body["content_subject"] == "polity"

    tutor_response = client.post("/api/tutor/explain", json={"topic": "Federalism"})
    assert tutor_response.status_code == 200
    tutor_body = tutor_response.json()
    assert tutor_body["exam"] == "banking"
    assert tutor_body["subject"] == "regulatory_basics"
    assert tutor_body["content_subject"] == "polity"

    doubt_response = client.post(
        "/api/tutor/doubt",
        json={"topic": "Federalism", "question": "How should I revise this for my current exam?"},
    )
    assert doubt_response.status_code == 200
    doubt_body = doubt_response.json()
    assert doubt_body["exam"] == "banking"
    assert doubt_body["subject"] == "regulatory_basics"
    assert doubt_body["content_subject"] == "polity"

    explicit_summary_response = client.get("/api/progress/summary?exam=upsc&subject=polity")
    assert explicit_summary_response.status_code == 200
    explicit_summary = explicit_summary_response.json()
    assert explicit_summary["exam"] == "upsc"
    assert explicit_summary["subject"] == "polity"
    assert explicit_summary["content_subject"] == "polity"

    authenticate_test_user(client, email="current-context-other@example.com", display_name="Other Context")
    other_summary_response = client.get("/api/progress/summary")
    assert other_summary_response.status_code == 200
    other_summary = other_summary_response.json()
    assert other_summary["exam"] == "upsc"
    assert other_summary["subject"] == "polity"


def test_progress_history_uses_authenticated_preferences_without_cross_user_leakage(client: TestClient) -> None:
    authenticate_test_user(client, email="history-owner@example.com", display_name="History Owner")

    update_response = client.put(
        "/api/settings",
        json={
            "preferred_exam": "banking",
            "preferred_subject": "regulatory_basics",
        },
    )
    assert update_response.status_code == 200

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    owner_id: int | None = None
    other_user_id: int | None = None
    try:
        owner = db.query(UserAccount).filter(UserAccount.email == "history-owner@example.com").first()
        assert owner is not None
        owner_id = owner.id

        other_user = UserAccount(
            email="history-other@example.com",
            display_name="History Other",
            is_active=True,
            auth_status="verified",
            primary_auth_method="email_otp",
            billing_email="history-other@example.com",
            subscription_plan="free",
            subscription_status="inactive",
            feature_access_overrides_json="{}",
            email_verified_at=datetime.now(UTC),
        )
        db.add(other_user)
        db.commit()
        db.refresh(other_user)
        other_user_id = other_user.id
    finally:
        db.close()

    assert owner_id is not None
    assert other_user_id is not None

    create_attempt_record(client, topic="Federalism", score=4, subject="polity", exam="banking", user_id=owner_id)
    create_attempt_record(client, topic="Federalism", score=1, subject="polity", exam="banking", user_id=other_user_id)

    history_response = client.get("/api/progress/history")
    assert history_response.status_code == 200
    history_body = history_response.json()
    assert history_body["exam"] == "banking"
    assert history_body["subject"] == "regulatory_basics"
    assert history_body["content_subject"] == "polity"
    assert len(history_body["history"]) == 1
    assert history_body["history"][0]["score"] == 4
    assert history_body["history"][0]["subject"] == "regulatory_basics"


def test_logout_revokes_current_session(client: TestClient) -> None:
    authenticate_test_user(client)

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["success"] is True

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401
    assert "sign in" in me_response.json()["detail"].lower()


def test_expired_session_is_revoked_and_cookie_is_cleared(client: TestClient) -> None:
    authenticate_test_user(client, email="expired-session@example.com")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "expired-session@example.com").first()
        assert user is not None
        session = db.query(UserSession).filter(UserSession.user_id == user.id).first()
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.add(session)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401
    assert "max-age=0" in me_response.headers.get("set-cookie", "").lower()

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "expired-session@example.com").first()
        assert user is not None
        session = db.query(UserSession).filter(UserSession.user_id == user.id).first()
        assert session is not None
        assert session.revoked_at is not None
        assert session.revoke_reason == "session_expired"
    finally:
        db.close()


def test_idle_session_timeout_revokes_session_when_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import auth_service

    authenticate_test_user(client, email="idle-session@example.com")
    monkeypatch.setattr(auth_service.settings, "session_idle_timeout_minutes", 1)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "idle-session@example.com").first()
        assert user is not None
        session = db.query(UserSession).filter(UserSession.user_id == user.id).first()
        assert session is not None
        session.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)
        db.add(session)
        db.commit()
    finally:
        db.close()

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401

    db = session_factory()
    try:
        user = db.query(UserAccount).filter(UserAccount.email == "idle-session@example.com").first()
        assert user is not None
        session = db.query(UserSession).filter(UserSession.user_id == user.id).first()
        assert session is not None
        assert session.revoked_at is not None
        assert session.revoke_reason == "session_idle_timeout"
    finally:
        db.close()


def test_user_scoped_quiz_history_and_progress_do_not_leak_between_users(client: TestClient) -> None:
    authenticate_test_user(client, email="learner.one@example.com", display_name="Learner One")

    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5, "subject": "polity"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_correct_answers(client, quiz), "subject": "polity"},
    )
    assert submit_response.status_code == 200

    history_response = client.get("/api/progress/history?subject=polity")
    assert history_response.status_code == 200
    assert len(history_response.json()["history"]) == 1

    summary_response = client.get("/api/progress/summary?subject=polity")
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert len(summary_body["recent_quizzes"]) == 1
    assert summary_body["topic_accuracy"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user_one = db.query(UserAccount).filter(UserAccount.email == "learner.one@example.com").first()
        assert user_one is not None
        quiz_row = db.query(Quiz).filter(Quiz.id == quiz["quiz_id"]).first()
        assert quiz_row is not None
        assert quiz_row.user_id == user_one.id
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == user_one.id).count() == 1
        assert db.query(TopicProgress).filter(TopicProgress.user_id == user_one.id).count() >= 1
        assert db.query(TopicStudy).filter(TopicStudy.user_id == user_one.id).count() >= 1
    finally:
        db.close()

    second_client = TestClient(app)
    try:
        authenticate_test_user(second_client, email="learner.two@example.com", display_name="Learner Two")

        second_history_response = second_client.get("/api/progress/history?subject=polity")
        assert second_history_response.status_code == 200
        assert second_history_response.json()["history"] == []

        second_summary_response = second_client.get("/api/progress/summary?subject=polity")
        assert second_summary_response.status_code == 200
        second_summary_body = second_summary_response.json()
        assert second_summary_body["recent_quizzes"] == []
        assert second_summary_body["topic_accuracy"] == []
    finally:
        second_client.close()

    history_again_response = client.get("/api/progress/history?subject=polity")
    assert history_again_response.status_code == 200
    assert len(history_again_response.json()["history"]) == 1


def test_user_scoped_tutor_study_activity_stays_separate_per_user(client: TestClient) -> None:
    authenticate_test_user(client, email="tutor.one@example.com", display_name="Tutor One")

    explain_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity"},
    )
    assert explain_response.status_code == 200

    second_client = TestClient(app)
    try:
        authenticate_test_user(second_client, email="tutor.two@example.com", display_name="Tutor Two")
        second_explain_response = second_client.post(
            "/api/tutor/explain",
            json={"topic": "Fundamental Rights", "subject": "polity"},
        )
        assert second_explain_response.status_code == 200
    finally:
        second_client.close()

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        user_one = db.query(UserAccount).filter(UserAccount.email == "tutor.one@example.com").first()
        user_two = db.query(UserAccount).filter(UserAccount.email == "tutor.two@example.com").first()
        assert user_one is not None
        assert user_two is not None

        user_one_topics = {
            study.topic
            for study in db.query(TopicStudy).filter(TopicStudy.user_id == user_one.id).all()
        }
        user_two_topics = {
            study.topic
            for study in db.query(TopicStudy).filter(TopicStudy.user_id == user_two.id).all()
        }

        assert "Preamble" in user_one_topics
        assert "Fundamental Rights" not in user_one_topics
        assert "Fundamental Rights" in user_two_topics
        assert "Preamble" not in user_two_topics
    finally:
        db.close()


def test_phase39_same_client_account_switch_keeps_auth_context_and_progress_user_scoped(client: TestClient) -> None:
    first_email = "phase39-switch-first@example.com"
    second_email = "phase39-switch-second@example.com"

    authenticate_test_user(client, email=first_email, display_name="Phase 39 Switch First")

    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5, "subject": "polity", "exam": "upsc"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={
            "quiz_id": quiz["quiz_id"],
            "answers": get_correct_answers(client, quiz),
            "subject": "polity",
            "exam": "upsc",
        },
    )
    assert submit_response.status_code == 200

    first_me_response = client.get("/api/auth/me")
    assert first_me_response.status_code == 200
    first_user = first_me_response.json()["user"]
    assert first_user["email"] == first_email
    assert first_user["account_role"] == "student"

    first_history_response = client.get("/api/progress/history?subject=polity&exam=upsc")
    assert first_history_response.status_code == 200
    assert len(first_history_response.json()["history"]) == 1

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    authenticate_test_user(client, email=second_email, display_name="Phase 39 Switch Second")

    second_me_response = client.get("/api/auth/me")
    assert second_me_response.status_code == 200
    second_user = second_me_response.json()["user"]
    assert second_user["email"] == second_email
    assert second_user["id"] != first_user["id"]
    assert second_user["account_role"] == "student"

    second_history_response = client.get("/api/progress/history?subject=polity&exam=upsc")
    assert second_history_response.status_code == 200
    assert second_history_response.json()["history"] == []

    second_summary_response = client.get("/api/progress/summary?subject=polity&exam=upsc")
    assert second_summary_response.status_code == 200
    second_summary_body = second_summary_response.json()
    assert second_summary_body["recent_quizzes"] == []
    assert second_summary_body["topic_accuracy"] == []

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        first_user_row = db.query(UserAccount).filter(UserAccount.email == first_email).first()
        second_user_row = db.query(UserAccount).filter(UserAccount.email == second_email).first()
        assert first_user_row is not None
        assert second_user_row is not None
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == first_user_row.id).count() == 1
        assert db.query(TopicProgress).filter(TopicProgress.user_id == first_user_row.id).count() >= 1
        assert db.query(TopicStudy).filter(TopicStudy.user_id == first_user_row.id).count() >= 1
        assert db.query(QuizAttempt).filter(QuizAttempt.user_id == second_user_row.id).count() == 0
    finally:
        db.close()


def test_phase39_session_switch_from_admin_to_learner_removes_admin_route_access(client: TestClient) -> None:
    admin_email = "phase39-admin-switch@example.com"
    learner_email = "phase39-learner-switch@example.com"

    authenticate_test_user(client, email=admin_email, display_name="Phase 39 Admin Switch")
    grant_admin_role(client, email=admin_email, role="content_admin")

    admin_me_response = client.get("/api/auth/me")
    assert admin_me_response.status_code == 200
    admin_user = admin_me_response.json()["user"]
    assert admin_user["email"] == admin_email
    assert admin_user["account_role"] == "content_admin"
    assert admin_user["admin_access"]["is_admin"] is True

    admin_ops_response = client.get("/api/admin/ops/overview")
    assert admin_ops_response.status_code == 200

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    authenticate_test_user(client, email=learner_email, display_name="Phase 39 Learner Switch")

    learner_me_response = client.get("/api/auth/me")
    assert learner_me_response.status_code == 200
    learner_user = learner_me_response.json()["user"]
    assert learner_user["email"] == learner_email
    assert learner_user["account_role"] == "student"
    assert learner_user["admin_access"]["is_admin"] is False

    learner_ops_response = client.get("/api/admin/ops/overview")
    assert learner_ops_response.status_code == 403
    learner_ops_detail = learner_ops_response.json()["detail"]
    assert learner_ops_detail["required_privilege"] == "content_qa"
    assert learner_ops_detail["account_role"] == "student"
    assert learner_ops_detail["admin_access"] is False

    learner_support_response = client.get(f"/api/admin/ops/support?email={learner_email}")
    assert learner_support_response.status_code == 403
    learner_support_detail = learner_support_response.json()["detail"]
    assert learner_support_detail["required_privilege"] == "content_qa"
    assert learner_support_detail["account_role"] == "student"
    assert learner_support_detail["admin_access"] is False


def test_phase39_session_switch_from_free_to_premium_updates_product_and_billing_access(client: TestClient) -> None:
    free_email = "phase39-free-switch@example.com"
    premium_email = "phase39-premium-switch@example.com"

    authenticate_test_user(client, email=free_email, display_name="Phase 39 Free Switch")

    free_me_response = client.get("/api/auth/me")
    assert free_me_response.status_code == 200
    free_user = free_me_response.json()["user"]
    assert free_user["email"] == free_email
    assert free_user["subscription_plan"] == "free"
    assert free_user["subscription_status"] == "inactive"
    assert free_user["feature_access"]["premium_lesson_modes"] is False
    assert free_user["billing"]["subscription_lifecycle"]["state"] == "free"

    blocked_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": "video_lecture"},
    )
    assert blocked_response.status_code == 403
    blocked_detail = blocked_response.json()["detail"]
    assert blocked_detail["feature_key"] == "premium_lesson_modes"
    assert blocked_detail["required_plan"] == "premium"
    assert blocked_detail["upgrade_required"] is True

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    authenticate_premium_test_user(client, email=premium_email, display_name="Phase 39 Premium Switch")

    premium_me_response = client.get("/api/auth/me")
    assert premium_me_response.status_code == 200
    premium_user = premium_me_response.json()["user"]
    assert premium_user["email"] == premium_email
    assert premium_user["subscription_plan"] == "premium"
    assert premium_user["subscription_status"] == "active"
    assert premium_user["feature_access"]["premium_lesson_modes"] is True
    assert premium_user["billing"]["subscription_lifecycle"]["state"] == "active"

    allowed_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": "video_lecture"},
    )
    assert allowed_response.status_code == 200
    allowed_body = allowed_response.json()
    assert allowed_body["lesson_mode"] == "video_lecture"
    assert allowed_body["video_lesson_script"]["video_mode"] == "video_lecture"


def test_get_subjects_returns_clean_subject_registry(client: TestClient) -> None:
    response = client.get("/api/subjects")
    assert response.status_code == 200
    body = response.json()
    assert body["default_exam"] == "upsc"
    assert body["default_subject"] == "polity"
    exam_codes = {exam["code"] for exam in body["exams"]}
    assert {"upsc", "state_psc", "ssc", "banking"}.issubset(exam_codes)
    subject_codes = {item["code"] for item in body["subjects"]}
    assert {"polity", "economy", "history", "geography", "environment"}.issubset(subject_codes)

    upsc = next(item for item in body["exams"] if item["code"] == "upsc")
    polity = next(item for item in body["subjects"] if item["code"] == "polity")
    economy = next(item for item in body["subjects"] if item["code"] == "economy")

    assert upsc["label"] == "UPSC CSE"
    assert upsc["default_subject"] == "polity"
    assert upsc["default_subject_map"]["gs_polity"] == "polity"
    assert upsc["teaching_style_hint"]
    assert upsc["quiz_style_hint"]
    assert "upsc_cse" in upsc["aliases"]
    assert polity["label"] == "Polity"
    assert polity["id"] == "polity"
    assert polity["description"]
    assert polity["available"] is True
    assert "upsc" in polity["supported_exams"]
    assert polity["content_subject"] == "polity"
    assert polity["content_label"] == "Polity"
    assert polity["topic_count"] >= 13
    assert polity["chapter_count"] >= 1
    assert economy["label"] == "Economy"
    assert economy["id"] == "economy"
    assert economy["description"]
    assert "upsc" in economy["supported_exams"]
    assert economy["content_subject"] == "economy"
    assert economy["available"] is False
    assert economy["topic_count"] == 0
    assert economy["chapter_count"] == 0


def test_get_subjects_accepts_legacy_upsc_exam_alias(client: TestClient) -> None:
    response = client.get("/api/subjects?exam=upsc_cse")
    assert response.status_code == 200
    body = response.json()
    assert body["default_exam"] == "upsc"
    assert any(exam["code"] == "upsc" for exam in body["exams"])


def test_get_subjects_returns_exam_specific_subject_mappings(client: TestClient) -> None:
    response = client.get("/api/subjects?exam=banking")
    assert response.status_code == 200
    body = response.json()
    assert body["default_exam"] == "banking"
    assert body["default_subject"] == "financial_awareness"
    subject_codes = {item["code"] for item in body["subjects"]}
    assert subject_codes == {
        "financial_awareness",
        "banking_awareness",
        "regulatory_basics",
        "sustainability_awareness",
    }

    regulatory = next(item for item in body["subjects"] if item["code"] == "regulatory_basics")
    financial = next(item for item in body["subjects"] if item["code"] == "financial_awareness")

    assert regulatory["content_subject"] == "polity"
    assert regulatory["content_label"] == "Polity"
    assert regulatory["available"] is True
    assert regulatory["topic_count"] >= 13
    assert "polity" in regulatory["aliases"]
    assert financial["content_subject"] == "economy"
    assert financial["available"] is False


def test_get_subjects_exposes_exam_content_registry_metadata(client: TestClient) -> None:
    response = client.get("/api/subjects?exam=ssc")
    assert response.status_code == 200
    body = response.json()

    ssc_profile = next(item for item in body["exams"] if item["code"] == "ssc")
    history = next(item for item in body["subjects"] if item["code"] == "general_awareness_history")

    assert ssc_profile["content_corpus_id"] == "ssc_primary"
    assert ssc_profile["content_root"] == "knowledge_base/exams/ssc"
    assert ssc_profile["content_fallback_corpus_ids"] == ["upsc_legacy_shared"]
    assert ssc_profile["content_retrieval_hint"]
    assert history["content_corpus_id"] == "ssc_primary"
    assert history["content_root"] == "knowledge_base/exams/ssc"
    assert history["content_fallback_corpus_ids"] == ["upsc_legacy_shared"]
    assert history["content_source_scope"] == "shared_content_alias"
    assert history["shared_content_subject"] == "history"
    assert history["retrieval_hint"]


def test_exam_specific_knowledge_roots_keep_primary_boundary_when_primary_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    primary_root = tmp_path / "knowledge_base" / "exams" / "ssc" / "history"
    shared_root = tmp_path / "knowledge_base" / "history"
    primary_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    (primary_root / "ssc_specific_topic.md").write_text(
        "---\nchapter: SSC General Awareness\ntitle: SSC-Specific Topic\n---\n\n# SSC-Specific Topic\n\nPrimary SSC corpus note.",
        encoding="utf-8",
    )
    (shared_root / "shared_topic.md").write_text(
        "---\nchapter: Shared History\ntitle: Shared Topic\n---\n\n# Shared Topic\n\nShared fallback note.",
        encoding="utf-8",
    )

    documents = knowledge_service.list_topic_documents(subject="general_awareness_history", exam="ssc")
    documents_by_topic = {document.topic: document for document in documents}

    assert set(documents_by_topic) == {"SSC-Specific Topic"}
    assert documents_by_topic["SSC-Specific Topic"].corpus_id == "ssc_primary"
    assert documents_by_topic["SSC-Specific Topic"].content_root == "knowledge_base/exams/ssc"
    assert documents_by_topic["SSC-Specific Topic"].fallback_used is False
    assert knowledge_service.find_topic_document("Shared Topic", subject="general_awareness_history", exam="ssc") is None


def test_exam_specific_knowledge_roots_use_shared_fallback_only_when_primary_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    shared_root = tmp_path / "knowledge_base" / "history"
    shared_root.mkdir(parents=True)
    (shared_root / "shared_topic.md").write_text(
        "---\nchapter: Shared History\ntitle: Shared Topic\n---\n\n# Shared Topic\n\nShared fallback note.",
        encoding="utf-8",
    )

    documents = knowledge_service.list_topic_documents(subject="general_awareness_history", exam="ssc")
    documents_by_topic = {document.topic: document for document in documents}

    assert set(documents_by_topic) == {"Shared Topic"}
    assert documents_by_topic["Shared Topic"].corpus_id == "upsc_legacy_shared"
    assert documents_by_topic["Shared Topic"].source_scope == "shared_fallback"
    assert documents_by_topic["Shared Topic"].fallback_used is True


def test_get_topics_exposes_exam_aware_topic_items_and_source_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    primary_root = tmp_path / "knowledge_base" / "exams" / "ssc" / "history"
    shared_root = tmp_path / "knowledge_base" / "history"
    primary_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    (primary_root / "ssc_quick_revision.md").write_text(
        (
            "---\n"
            "chapter: SSC General Awareness\n"
            "title: SSC Quick Revision\n"
            "aliases: SSC Speed Notes, Quick GA Revision\n"
            "exam_emphasis: Fast recall and elimination-friendly framing.\n"
            "---\n\n"
            "# SSC Quick Revision\n\n"
            "Primary SSC corpus note."
        ),
        encoding="utf-8",
    )
    (shared_root / "shared_history_anchor.md").write_text(
        "---\nchapter: Modern History\ntitle: Shared History Anchor\n---\n\n# Shared History Anchor\n\nShared fallback note.",
        encoding="utf-8",
    )

    response = client.get("/api/topics?exam=ssc&subject=general_awareness_history")
    assert response.status_code == 200
    body = response.json()
    topics_by_name = {item["topic"]: item for item in body["topic_items"]}

    assert body["exam"] == "ssc"
    assert body["subject"] == "general_awareness_history"
    assert body["content_subject"] == "history"
    assert body["topics"] == ["SSC Quick Revision"]
    assert body["topic_count"] == 1
    assert body["primary_topic_count"] == 1
    assert body["fallback_topic_count"] == 0
    assert topics_by_name["SSC Quick Revision"]["content_corpus_id"] == "ssc_primary"
    assert topics_by_name["SSC Quick Revision"]["content_source_scope"] == "shared_content_alias"
    assert topics_by_name["SSC Quick Revision"]["fallback_used"] is False
    assert topics_by_name["SSC Quick Revision"]["aliases"] == ["SSC Speed Notes", "Quick GA Revision"]
    assert topics_by_name["SSC Quick Revision"]["emphasis_hint"] == "Fast recall and elimination-friendly framing."
    assert "Shared History Anchor" not in topics_by_name


def test_tutor_and_quiz_respect_primary_exam_boundary_before_shared_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    primary_root = tmp_path / "knowledge_base" / "exams" / "ssc" / "history"
    shared_root = tmp_path / "knowledge_base" / "history"
    primary_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    (primary_root / "ssc_census_drill.md").write_text(
        "---\nchapter: SSC General Awareness\ntitle: SSC Census Drill\n---\n\n# SSC Census Drill\n\nDedicated SSC note.",
        encoding="utf-8",
    )
    (shared_root / "legacy_congress_anchor.md").write_text(
        "---\nchapter: Modern History\ntitle: Legacy Congress Anchor\n---\n\n# Legacy Congress Anchor\n\nShared fallback note.",
        encoding="utf-8",
    )

    tutor_response = client.post(
        "/api/tutor/explain",
        json={"exam": "ssc", "subject": "general_awareness_history", "topic": "Legacy Congress Anchor"},
    )
    quiz_response = client.post(
        "/api/test/generate",
        json={
            "exam": "ssc",
            "subject": "general_awareness_history",
            "topic": "Legacy Congress Anchor",
            "question_count": 5,
        },
    )
    primary_quiz_response = client.post(
        "/api/test/generate",
        json={
            "exam": "ssc",
            "subject": "general_awareness_history",
            "topic": "SSC Census Drill",
            "question_count": 5,
        },
    )

    assert tutor_response.status_code == 200
    tutor_body = tutor_response.json()
    assert tutor_body["exam"] == "ssc"
    assert tutor_body["subject"] == "general_awareness_history"
    assert tutor_body["content_corpus_id"] == "ssc_primary"
    assert tutor_body["content_fallback_policy"] == "when_primary_empty"
    assert tutor_body["content_fallback_used"] is False
    assert tutor_body["structured_teaching_content"]["content_corpus_id"] == "ssc_primary"
    assert tutor_body["context_status"] == "no_knowledge_base_context"
    assert "Legacy Congress Anchor" == tutor_body["topic"]

    assert quiz_response.status_code == 404
    assert primary_quiz_response.status_code == 200
    primary_quiz_body = primary_quiz_response.json()
    assert primary_quiz_body["exam"] == "ssc"
    assert primary_quiz_body["topic"] == "SSC Census Drill"
    assert primary_quiz_body["content_corpus_id"] == "ssc_primary"
    assert primary_quiz_body["content_source_corpus_ids"] == ["ssc_primary"]
    assert primary_quiz_body["content_fallback_policy"] == "when_primary_empty"
    assert primary_quiz_body["content_fallback_used"] is False


def test_progress_and_plan_use_active_exam_primary_corpus_before_shared_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    primary_root = tmp_path / "knowledge_base" / "exams" / "ssc" / "history"
    shared_root = tmp_path / "knowledge_base" / "history"
    primary_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    (primary_root / "ssc_census_drill.md").write_text(
        "---\nchapter: SSC General Awareness\ntitle: SSC Census Drill\n---\n\n# SSC Census Drill\n\nDedicated SSC note.",
        encoding="utf-8",
    )
    (shared_root / "legacy_congress_anchor.md").write_text(
        "---\nchapter: Modern History\ntitle: Legacy Congress Anchor\n---\n\n# Legacy Congress Anchor\n\nShared fallback note.",
        encoding="utf-8",
    )

    summary_response = client.get("/api/progress/summary?exam=ssc&subject=general_awareness_history")
    plan_response = client.get("/api/plan/today?exam=ssc&subject=general_awareness_history")
    coach_response = client.get("/api/coach/summary?exam=ssc&subject=general_awareness_history")
    revision_response = client.get("/api/revision/due?exam=ssc&subject=general_awareness_history")
    trends_response = client.get("/api/performance/trends?exam=ssc&subject=general_awareness_history")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["exam"] == "ssc"
    assert summary["subject"] == "general_awareness_history"
    assert summary["content_subject"] == "history"
    assert summary["recommended_next_topic"] == "SSC Census Drill"
    assert summary["sequence_next_topic"] == "SSC Census Drill"
    assert all(item["topic"] != "Legacy Congress Anchor" for item in summary["priority_topics"])

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["exam"] == "ssc"
    assert plan["subject"] == "general_awareness_history"
    assert plan["content_subject"] == "history"
    assert plan["focus_topic"] == "SSC Census Drill"
    assert "Legacy Congress Anchor" not in plan["focus_topic"]

    assert coach_response.status_code == 200
    coach = coach_response.json()
    assert coach["exam"] == "ssc"
    assert coach["subject"] == "general_awareness_history"
    assert coach["content_subject"] == "history"
    assert coach["study_today"] == "SSC Census Drill"
    assert coach["next_best_topic"] == "SSC Census Drill"
    assert "Legacy Congress Anchor" not in coach["study_today"]

    assert revision_response.status_code == 200
    revision = revision_response.json()
    assert revision["exam"] == "ssc"
    assert revision["subject"] == "general_awareness_history"
    assert revision["content_subject"] == "history"
    assert revision["overdue"] == []
    assert revision["due_now"] == []
    assert revision["due_soon"] == []

    assert trends_response.status_code == 200
    trends = trends_response.json()
    assert trends["exam"] == "ssc"
    assert trends["subject"] == "general_awareness_history"
    assert trends["content_subject"] == "history"
    assert trends["topics"] == []


def test_lesson_and_quiz_use_explicit_shared_fallback_when_primary_exam_corpus_empty(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from backend.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_backend_root", lambda: tmp_path)
    shared_root = tmp_path / "knowledge_base" / "history"
    shared_root.mkdir(parents=True)
    (shared_root / "shared_history_fallback.md").write_text(
        (
            "---\n"
            "chapter: Shared History\n"
            "title: Shared History Fallback\n"
            "---\n\n"
            "# Shared History Fallback\n\n"
            "Shared fallback note for explicit empty-primary routing."
        ),
        encoding="utf-8",
    )

    tutor_response = client.post(
        "/api/tutor/explain",
        json={"exam": "ssc", "subject": "general_awareness_history", "topic": "Shared History Fallback"},
    )
    quiz_response = client.post(
        "/api/test/generate",
        json={
            "exam": "ssc",
            "subject": "general_awareness_history",
            "topic": "Shared History Fallback",
            "question_count": 5,
        },
    )

    assert tutor_response.status_code == 200
    tutor_body = tutor_response.json()
    assert tutor_body["exam"] == "ssc"
    assert tutor_body["content_subject"] == "history"
    assert tutor_body["content_corpus_id"] == "upsc_legacy_shared"
    assert tutor_body["content_source_scope"] == "shared_fallback"
    assert tutor_body["content_fallback_policy"] == "when_primary_empty"
    assert tutor_body["content_fallback_used"] is True
    assert tutor_body["structured_teaching_content"]["content_corpus_id"] == "upsc_legacy_shared"
    assert tutor_body["structured_teaching_content"]["content_fallback_used"] is True

    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["exam"] == "ssc"
    assert quiz_body["topic"] == "Shared History Fallback"
    assert quiz_body["content_corpus_id"] == "upsc_legacy_shared"
    assert quiz_body["content_source_corpus_ids"] == ["upsc_legacy_shared"]
    assert quiz_body["content_source_scope"] == "shared_fallback"
    assert quiz_body["content_fallback_policy"] == "when_primary_empty"
    assert quiz_body["content_fallback_used"] is True


def test_get_topics_returns_dynamic_topic_list(client: TestClient) -> None:
    response = client.get("/api/topics")
    assert response.status_code == 200
    body = response.json()
    assert body["exam"] == "upsc"
    assert body["content_subject"] == "polity"
    assert body["content_corpus_id"] == "upsc_legacy_shared"
    assert body["content_root"] == "knowledge_base"
    assert body["content_source_scope"] == "legacy_default"
    assert body["topic_count"] == len(body["topics"])
    assert body["primary_topic_count"] == len(body["topics"])
    assert body["fallback_topic_count"] == 0
    assert body["topic_items"]
    assert body["topic_items"][0]["exam"] == "upsc"
    assert body["topic_items"][0]["content_subject"] == "polity"
    assert "Fundamental Rights" in body["topics"]
    assert "Preamble" in body["topics"]
    assert len(body["topics"]) >= 13


def test_get_topics_supports_explicit_subject_selection(client: TestClient) -> None:
    response = client.get("/api/topics?subject=economy")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "economy"
    assert body["content_subject"] == "economy"
    assert body["topics"] == []


def test_get_topics_resolves_exam_subject_mapping_to_content_subject(client: TestClient) -> None:
    response = client.get("/api/topics?exam=banking&subject=regulatory_basics")
    assert response.status_code == 200
    body = response.json()
    assert body["exam"] == "banking"
    assert body["subject"] == "regulatory_basics"
    assert body["content_subject"] == "polity"
    assert body["content_corpus_id"] == "banking_primary"
    assert body["content_root"] == "knowledge_base/exams/banking"
    assert body["content_fallback_corpus_ids"] == ["upsc_legacy_shared"]
    assert body["content_source_scope"] == "shared_content_alias"
    assert "Preamble" in body["topics"]
    assert "Fundamental Rights" in body["topics"]


def test_get_topics_keeps_legacy_content_subject_lookup_working_inside_exam_scope(client: TestClient) -> None:
    response = client.get("/api/topics?exam=banking&subject=economy")
    assert response.status_code == 200
    body = response.json()
    assert body["exam"] == "banking"
    assert body["subject"] == "financial_awareness"
    assert body["content_subject"] == "economy"
    assert body["topics"] == []


def test_exam_aware_planning_and_coaching_keep_upsc_default_behavior(client: TestClient) -> None:
    default_summary = client.get("/api/progress/summary?subject=polity")
    explicit_summary = client.get("/api/progress/summary?subject=polity&exam=upsc")
    default_plan = client.get("/api/plan/today?subject=polity")
    explicit_plan = client.get("/api/plan/today?subject=polity&exam=upsc")
    default_coach = client.get("/api/coach/summary?subject=polity")
    explicit_coach = client.get("/api/coach/summary?subject=polity&exam=upsc")

    assert default_summary.status_code == 200
    assert explicit_summary.status_code == 200
    assert default_plan.status_code == 200
    assert explicit_plan.status_code == 200
    assert default_coach.status_code == 200
    assert explicit_coach.status_code == 200

    default_summary_body = default_summary.json()
    explicit_summary_body = explicit_summary.json()
    default_plan_body = default_plan.json()
    explicit_plan_body = explicit_plan.json()
    default_coach_body = default_coach.json()
    explicit_coach_body = explicit_coach.json()

    assert default_summary_body["exam"] == "upsc"
    assert explicit_summary_body["exam"] == "upsc"
    assert default_summary_body["content_subject"] == "polity"
    assert explicit_summary_body["content_subject"] == "polity"
    assert default_summary_body["recommended_next_topic"] == explicit_summary_body["recommended_next_topic"]
    assert default_plan_body["focus_topic"] == explicit_plan_body["focus_topic"]
    assert default_plan_body["focus_reason"] == explicit_plan_body["focus_reason"]
    assert default_coach_body["coach_note"] == explicit_coach_body["coach_note"]
    assert default_coach_body["study_reason"] == explicit_coach_body["study_reason"]


def test_exam_aware_planning_and_coaching_can_reframe_mapped_banking_subjects(client: TestClient) -> None:
    upsc_summary = client.get("/api/progress/summary?subject=polity&exam=upsc")
    banking_summary = client.get("/api/progress/summary?subject=regulatory_basics&exam=banking")
    upsc_plan = client.get("/api/plan/today?subject=polity&exam=upsc")
    banking_plan = client.get("/api/plan/today?subject=regulatory_basics&exam=banking")
    upsc_coach = client.get("/api/coach/summary?subject=polity&exam=upsc")
    banking_coach = client.get("/api/coach/summary?subject=regulatory_basics&exam=banking")

    assert upsc_summary.status_code == 200
    assert banking_summary.status_code == 200
    assert upsc_plan.status_code == 200
    assert banking_plan.status_code == 200
    assert upsc_coach.status_code == 200
    assert banking_coach.status_code == 200

    upsc_summary_body = upsc_summary.json()
    banking_summary_body = banking_summary.json()
    upsc_plan_body = upsc_plan.json()
    banking_plan_body = banking_plan.json()
    upsc_coach_body = upsc_coach.json()
    banking_coach_body = banking_coach.json()

    assert banking_summary_body["exam"] == "banking"
    assert banking_summary_body["subject"] == "regulatory_basics"
    assert banking_summary_body["content_subject"] == "polity"
    assert banking_plan_body["exam"] == "banking"
    assert banking_plan_body["content_subject"] == "polity"
    assert banking_coach_body["exam"] == "banking"
    assert banking_coach_body["content_subject"] == "polity"

    assert banking_summary_body["recommended_next_topic"] == upsc_summary_body["recommended_next_topic"]
    assert banking_summary_body["accountability_summary"]["warning_level"] == upsc_summary_body["accountability_summary"]["warning_level"]
    assert banking_plan_body["focus_topic"] == upsc_plan_body["focus_topic"]
    assert banking_coach_body["study_today"] == upsc_coach_body["study_today"]

    assert "accuracy-first" in banking_plan_body["focus_reason"]
    assert "accuracy-first" in banking_coach_body["coach_note"]
    assert "accuracy-first" not in upsc_plan_body["focus_reason"]
    assert "accuracy-first" not in upsc_coach_body["coach_note"]


def test_exam_aware_quiz_generation_keeps_upsc_default_behavior(client: TestClient) -> None:
    default_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "polity", "quiz_mode": "test"},
    )
    explicit_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "polity", "exam": "upsc", "quiz_mode": "test"},
    )

    assert default_response.status_code == 200
    assert explicit_response.status_code == 200

    default_body = default_response.json()
    explicit_body = explicit_response.json()

    assert default_body["exam"] == "upsc"
    assert explicit_body["exam"] == "upsc"
    assert default_body["subject"] == "polity"
    assert explicit_body["subject"] == "polity"
    assert default_body["content_subject"] == "polity"
    assert explicit_body["content_subject"] == "polity"
    assert default_body["quiz_mode_note"] == explicit_body["quiz_mode_note"]
    assert default_body["difficulty_reason"] == explicit_body["difficulty_reason"]
    assert default_body["difficulty_emphasis"] == explicit_body["difficulty_emphasis"]
    assert default_body["balance_style"] == explicit_body["balance_style"]
    assert default_body["exam_focus_note"] == explicit_body["exam_focus_note"]
    assert all("correct_answer" not in question for question in default_body["questions"])
    assert all("explanation" not in question for question in default_body["questions"])


def test_exam_aware_quiz_generation_can_reframe_mapped_banking_subjects(client: TestClient) -> None:
    upsc_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "polity", "exam": "upsc", "quiz_mode": "test"},
    )
    banking_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "regulatory_basics", "exam": "banking", "quiz_mode": "test"},
    )

    assert upsc_response.status_code == 200
    assert banking_response.status_code == 200

    upsc_body = upsc_response.json()
    banking_body = banking_response.json()

    assert banking_body["exam"] == "banking"
    assert banking_body["subject"] == "regulatory_basics"
    assert banking_body["content_subject"] == "polity"
    assert banking_body["difficulty_emphasis"] == "speed-and-accuracy under practical awareness pressure"
    assert banking_body["balance_style"] != upsc_body["balance_style"]
    assert banking_body["exam_focus_note"] is not None
    assert "banking quiz framing" in banking_body["exam_focus_note"].lower()
    assert "regulatory" in banking_body["exam_focus_note"].lower()
    assert "speed-and-accuracy" in banking_body["difficulty_reason"].lower()
    assert "banking quiz framing" in banking_body["quiz_mode_note"].lower()
    assert all("correct_answer" not in question for question in banking_body["questions"])
    assert all("explanation" not in question for question in banking_body["questions"])


def test_exam_aware_quiz_submit_preserves_mapped_exam_context(client: TestClient) -> None:
    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "regulatory_basics", "exam": "banking", "quiz_mode": "test"},
    )
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={
            "quiz_id": quiz["quiz_id"],
            "answers": get_correct_answers(client, quiz),
            "subject": "regulatory_basics",
            "exam": "banking",
        },
    )

    assert submit_response.status_code == 200
    body = submit_response.json()

    assert body["exam"] == "banking"
    assert body["subject"] == "regulatory_basics"
    assert body["content_subject"] == "polity"
    assert body["progress_summary"]["exam"] == "banking"
    assert body["progress_summary"]["subject"] == "regulatory_basics"
    assert body["progress_summary"]["content_subject"] == "polity"
    assert body["today_plan"]["exam"] == "banking"
    assert body["today_plan"]["subject"] == "regulatory_basics"
    assert body["today_plan"]["content_subject"] == "polity"
    assert body["coach_summary"]["exam"] == "banking"
    assert body["coach_summary"]["subject"] == "regulatory_basics"
    assert body["coach_summary"]["content_subject"] == "polity"
    assert body["result_analysis"]["topic_breakdown"]
    assert body["result_analysis"]["topic_breakdown"][0]["subject"] == "regulatory_basics"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        quiz_row = db.query(Quiz).filter(Quiz.id == quiz["quiz_id"]).first()
        attempt_row = db.query(QuizAttempt).filter(QuizAttempt.quiz_id == quiz["quiz_id"]).first()
        progress_row = db.query(TopicProgress).filter(
            TopicProgress.exam == "banking",
            TopicProgress.subject == "polity",
            TopicProgress.topic == "Preamble",
        ).first()
        study_row = db.query(TopicStudy).filter(
            TopicStudy.exam == "banking",
            TopicStudy.subject == "polity",
            TopicStudy.topic == "Preamble",
        ).first()
        assert quiz_row is not None
        assert attempt_row is not None
        assert progress_row is not None
        assert study_row is not None
        assert quiz_row.exam == "banking"
        assert attempt_row.exam == "banking"
        assert progress_row.exam == "banking"
        assert study_row.exam == "banking"
    finally:
        db.close()


def test_exam_aware_progress_history_preserves_mapped_context(client: TestClient) -> None:
    user = authenticate_test_user(client, email="exam-partition@example.com", display_name="Exam Partition")
    user_id = user["user"]["id"]

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "regulatory_basics", "exam": "banking", "quiz_mode": "test"},
    )
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={
          "quiz_id": quiz["quiz_id"],
          "answers": get_correct_answers(client, quiz),
          "subject": "regulatory_basics",
          "exam": "banking",
        },
    )
    assert submit_response.status_code == 200

    history_response = client.get("/api/progress/history?subject=regulatory_basics&exam=banking")
    assert history_response.status_code == 200
    body = history_response.json()

    assert body["exam"] == "banking"
    assert body["subject"] == "regulatory_basics"
    assert body["content_subject"] == "polity"
    assert body["history"]
    assert body["history"][0]["exam"] == "banking"
    assert body["history"][0]["subject"] == "regulatory_basics"
    assert body["history"][0]["content_subject"] == "polity"

    upsc_history_response = client.get("/api/progress/history?subject=polity&exam=upsc")
    assert upsc_history_response.status_code == 200
    upsc_history = upsc_history_response.json()
    assert upsc_history["exam"] == "upsc"
    assert upsc_history["history"] == []

    create_attempt_record(client, topic="Preamble", score=5, subject="polity", exam="upsc", user_id=user_id)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        for model in (Quiz, QuizAttempt, TopicProgress, TopicStudy):
            for row in db.query(model).filter(model.user_id == user_id, model.exam == "upsc").all():
                row.exam = ""
        db.commit()
    finally:
        db.close()

    upsc_history_after_response = client.get("/api/progress/history?subject=polity&exam=upsc")
    assert upsc_history_after_response.status_code == 200
    upsc_history_after = upsc_history_after_response.json()
    assert upsc_history_after["exam"] == "upsc"
    assert len(upsc_history_after["history"]) == 1
    assert upsc_history_after["history"][0]["exam"] == "upsc"
    assert upsc_history_after["history"][0]["subject"] == "polity"

    banking_history_again_response = client.get("/api/progress/history?subject=regulatory_basics&exam=banking")
    assert banking_history_again_response.status_code == 200
    banking_history_again = banking_history_again_response.json()
    assert banking_history_again["exam"] == "banking"
    assert len(banking_history_again["history"]) == 1
    assert banking_history_again["history"][0]["exam"] == "banking"

    banking_summary_response = client.get("/api/progress/summary?subject=regulatory_basics&exam=banking")
    upsc_summary_response = client.get("/api/progress/summary?subject=polity&exam=upsc")
    assert banking_summary_response.status_code == 200
    assert upsc_summary_response.status_code == 200
    banking_summary = banking_summary_response.json()
    upsc_summary = upsc_summary_response.json()
    assert banking_summary["exam"] == "banking"
    assert upsc_summary["exam"] == "upsc"
    assert banking_summary["recent_quizzes"][0]["exam"] == "banking"
    assert upsc_summary["recent_quizzes"][0]["exam"] == "upsc"
    assert banking_summary["topic_accuracy"][0]["exam"] == "banking"
    assert upsc_summary["topic_accuracy"][0]["exam"] == "upsc"


def test_exam_aware_teaching_keeps_upsc_default_behavior(client: TestClient) -> None:
    default_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity"},
    )
    explicit_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc"},
    )

    assert default_response.status_code == 200
    assert explicit_response.status_code == 200

    default_body = default_response.json()
    explicit_body = explicit_response.json()

    assert default_body["exam"] == "upsc"
    assert explicit_body["exam"] == "upsc"
    assert default_body["subject"] == "polity"
    assert explicit_body["subject"] == "polity"
    assert default_body["content_subject"] == "polity"
    assert explicit_body["content_subject"] == "polity"
    assert default_body["explanation_depth_reason"]
    assert explicit_body["explanation_depth_reason"]
    assert default_body["teaching_mode_reason"]
    assert explicit_body["teaching_mode_reason"]
    assert default_body["lesson_mode_reason"]
    assert explicit_body["lesson_mode_reason"]

    for field in ("explanation_depth_reason", "teaching_mode_reason", "lesson_mode_reason", "exam_relevance"):
        default_text = default_body[field].lower()
        explicit_text = explicit_body[field].lower()
        assert "ssc" not in default_text
        assert "banking" not in default_text
        assert "state psc" not in default_text
        assert "ssc" not in explicit_text
        assert "banking" not in explicit_text
        assert "state psc" not in explicit_text


def test_exam_aware_teaching_can_reframe_mapped_banking_subjects(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "regulatory_basics", "exam": "banking"},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["exam"] == "banking"
    assert body["subject"] == "regulatory_basics"
    assert body["content_subject"] == "polity"
    assert body["structured_teaching_content"]["subject"] == "regulatory_basics"
    assert "banking" in body["teaching_mode_reason"].lower()
    assert "banking" in body["lesson_mode_reason"].lower()
    assert (
        "practical" in body["teaching_mode_reason"].lower()
        or "practical" in body["exam_relevance"].lower()
        or "regulatory" in body["exam_relevance"].lower()
    )


def test_exam_aware_teaching_can_compact_mapped_ssc_history_topics(client: TestClient) -> None:
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=4, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history", exam="ssc")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history", exam="ssc")
    create_attempt_record(client, topic="Indian National Congress", score=4, subject="history", exam="ssc")

    upsc_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Indian National Congress", "subject": "history", "exam": "upsc"},
    )
    ssc_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Indian National Congress", "subject": "general_awareness_history", "exam": "ssc"},
    )

    assert upsc_response.status_code == 200
    assert ssc_response.status_code == 200

    upsc_body = upsc_response.json()
    ssc_body = ssc_response.json()

    assert ssc_body["exam"] == "ssc"
    assert ssc_body["subject"] == "general_awareness_history"
    assert ssc_body["content_subject"] == "history"
    assert ssc_body["structured_teaching_content"]["subject"] == "general_awareness_history"
    assert ssc_body["teaching_pacing"] == "accelerated"
    assert ssc_body["conceptual_density"] == "medium"
    assert "ssc" in ssc_body["teaching_mode_reason"].lower()
    assert (
        "high-yield" in ssc_body["teaching_mode_reason"].lower()
        or "recall-forward" in ssc_body["teaching_mode_reason"].lower()
    )
    assert ssc_body["teaching_mode_reason"] != upsc_body["teaching_mode_reason"]


def test_exam_aware_banking_revision_loop_stays_aligned_across_summary_plan_quiz_and_tutor(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=1, subject="polity", exam="banking")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity", exam="banking")

    summary_response = client.get("/api/progress/summary?subject=regulatory_basics&exam=banking")
    revision_response = client.get("/api/revision/due?subject=regulatory_basics&exam=banking")
    plan_response = client.get("/api/plan/today?subject=regulatory_basics&exam=banking")
    coach_response = client.get("/api/coach/summary?subject=regulatory_basics&exam=banking")
    quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Preamble",
            "question_count": 5,
            "subject": "regulatory_basics",
            "exam": "banking",
            "quiz_mode": "revision",
        },
    )
    tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "regulatory_basics", "exam": "banking"},
    )

    assert summary_response.status_code == 200
    assert revision_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert quiz_response.status_code == 200
    assert tutor_response.status_code == 200

    summary = summary_response.json()
    revision = revision_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    quiz = quiz_response.json()
    tutor = tutor_response.json()

    for payload in (summary, revision, plan, coach, quiz, tutor):
        assert payload["exam"] == "banking"
        assert payload["subject"] == "regulatory_basics"
        assert payload["content_subject"] == "polity"

    assert summary["recommended_next_topic"] == "Preamble"
    assert summary["recommended_mode"] == "revise"
    assert plan["focus_topic"] == "Preamble"
    assert "accuracy-first" in plan["focus_reason"].lower()
    assert "accuracy-first" in coach["coach_note"].lower()
    assert revision["subject"] == "regulatory_basics"
    assert revision["content_subject"] == "polity"

    assert quiz["topic"] == "Preamble"
    assert quiz["quiz_mode"] == "revision"
    assert quiz["revision_targets"]
    assert quiz["revision_targets"][0] == "Preamble"
    assert "banking quiz framing" in quiz["quiz_mode_note"].lower()
    assert "speed-and-accuracy" in quiz["difficulty_reason"].lower()

    assert tutor["topic"] == "Preamble"
    assert tutor["lesson_mode"] == "revision_lesson"
    assert tutor["lesson_outline_state"] == "revision_reinforcement"
    assert tutor["structured_teaching_content"]["lesson_mode"] == "revision_lesson"
    assert "banking" in tutor["lesson_mode_reason"].lower()
    assert "practical" in tutor["teaching_mode_reason"].lower() or "regulatory" in tutor["exam_relevance"].lower()


def test_exam_aware_shared_content_keeps_upsc_and_banking_framing_distinct(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity", exam="banking")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity", exam="banking")

    upsc_plan_response = client.get("/api/plan/today?subject=polity&exam=upsc")
    banking_plan_response = client.get("/api/plan/today?subject=regulatory_basics&exam=banking")
    upsc_coach_response = client.get("/api/coach/summary?subject=polity&exam=upsc")
    banking_coach_response = client.get("/api/coach/summary?subject=regulatory_basics&exam=banking")
    upsc_quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "polity", "exam": "upsc", "quiz_mode": "revision"},
    )
    banking_quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Preamble",
            "question_count": 5,
            "subject": "regulatory_basics",
            "exam": "banking",
            "quiz_mode": "revision",
        },
    )
    upsc_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc"},
    )
    banking_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "regulatory_basics", "exam": "banking"},
    )

    assert upsc_plan_response.status_code == 200
    assert banking_plan_response.status_code == 200
    assert upsc_coach_response.status_code == 200
    assert banking_coach_response.status_code == 200
    assert upsc_quiz_response.status_code == 200
    assert banking_quiz_response.status_code == 200
    assert upsc_tutor_response.status_code == 200
    assert banking_tutor_response.status_code == 200

    upsc_plan = upsc_plan_response.json()
    banking_plan = banking_plan_response.json()
    upsc_coach = upsc_coach_response.json()
    banking_coach = banking_coach_response.json()
    upsc_quiz = upsc_quiz_response.json()
    banking_quiz = banking_quiz_response.json()
    upsc_tutor = upsc_tutor_response.json()
    banking_tutor = banking_tutor_response.json()

    assert upsc_plan["focus_topic"] == banking_plan["focus_topic"] == "Preamble"
    assert upsc_quiz["topic"] == banking_quiz["topic"] == "Preamble"
    assert upsc_tutor["topic"] == banking_tutor["topic"] == "Preamble"

    assert "accuracy-first" in banking_plan["focus_reason"].lower()
    assert "accuracy-first" not in upsc_plan["focus_reason"].lower()
    assert "accuracy-first" in banking_coach["coach_note"].lower()
    assert "accuracy-first" not in upsc_coach["coach_note"].lower()

    assert banking_quiz["difficulty_emphasis"] != upsc_quiz["difficulty_emphasis"]
    assert "banking quiz framing" in banking_quiz["quiz_mode_note"].lower()
    assert "banking" not in upsc_quiz["quiz_mode_note"].lower()

    assert "banking" in banking_tutor["lesson_mode_reason"].lower()
    assert "banking" in banking_tutor["teaching_mode_reason"].lower()
    assert "banking" not in upsc_tutor["lesson_mode_reason"].lower()
    assert "banking" not in upsc_tutor["teaching_mode_reason"].lower()


def test_exam_switch_after_banking_submit_keeps_upsc_guidance_quiz_and_tutor_clean(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")

    banking_quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "regulatory_basics", "exam": "banking", "quiz_mode": "revision"},
    )
    assert banking_quiz_response.status_code == 200
    banking_quiz = banking_quiz_response.json()

    banking_submit_response = client.post(
        "/api/test/submit",
        json={
            "quiz_id": banking_quiz["quiz_id"],
            "answers": get_correct_answers(client, banking_quiz),
            "subject": "regulatory_basics",
            "exam": "banking",
        },
    )
    assert banking_submit_response.status_code == 200
    banking_submit = banking_submit_response.json()

    upsc_summary_response = client.get("/api/progress/summary?subject=polity&exam=upsc")
    upsc_plan_response = client.get("/api/plan/today?subject=polity&exam=upsc")
    upsc_coach_response = client.get("/api/coach/summary?subject=polity&exam=upsc")
    upsc_quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "subject": "polity", "exam": "upsc", "quiz_mode": "revision"},
    )
    upsc_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc"},
    )

    assert upsc_summary_response.status_code == 200
    assert upsc_plan_response.status_code == 200
    assert upsc_coach_response.status_code == 200
    assert upsc_quiz_response.status_code == 200
    assert upsc_tutor_response.status_code == 200

    upsc_summary = upsc_summary_response.json()
    upsc_plan = upsc_plan_response.json()
    upsc_coach = upsc_coach_response.json()
    upsc_quiz = upsc_quiz_response.json()
    upsc_tutor = upsc_tutor_response.json()

    assert banking_submit["exam"] == "banking"
    assert banking_submit["subject"] == "regulatory_basics"
    assert banking_submit["content_subject"] == "polity"

    for payload in (upsc_summary, upsc_plan, upsc_coach, upsc_quiz, upsc_tutor):
        assert payload["exam"] == "upsc"

    assert upsc_summary["subject"] == "polity"
    assert upsc_summary["content_subject"] == "polity"
    assert upsc_plan["subject"] == "polity"
    assert upsc_coach["subject"] == "polity"
    assert upsc_quiz["subject"] == "polity"
    assert upsc_tutor["subject"] == "polity"

    assert "banking" not in upsc_plan["focus_reason"].lower()
    assert "banking" not in upsc_coach["coach_note"].lower()
    assert "banking" not in upsc_quiz["quiz_mode_note"].lower()
    assert "banking" not in upsc_quiz["difficulty_reason"].lower()
    assert "banking" not in upsc_tutor["lesson_mode_reason"].lower()
    assert "banking" not in upsc_tutor["teaching_mode_reason"].lower()
    assert "banking" not in upsc_tutor["exam_relevance"].lower()


def test_exam_aware_mixed_exam_subjects_stay_clean_between_banking_and_ssc(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=1, subject="polity")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")

    banking_summary_response = client.get("/api/progress/summary?subject=regulatory_basics&exam=banking")
    ssc_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Indian National Congress", "subject": "general_awareness_history", "exam": "ssc"},
    )
    ssc_quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Indian National Congress",
            "question_count": 5,
            "subject": "general_awareness_history",
            "exam": "ssc",
            "quiz_mode": "test",
        },
    )

    assert banking_summary_response.status_code == 200
    assert ssc_tutor_response.status_code == 200
    assert ssc_quiz_response.status_code == 200

    banking_summary = banking_summary_response.json()
    ssc_tutor = ssc_tutor_response.json()
    ssc_quiz = ssc_quiz_response.json()

    assert banking_summary["exam"] == "banking"
    assert banking_summary["subject"] == "regulatory_basics"
    assert banking_summary["content_subject"] == "polity"
    assert banking_summary["recommended_next_topic"] == "Preamble"

    assert ssc_tutor["exam"] == "ssc"
    assert ssc_tutor["subject"] == "general_awareness_history"
    assert ssc_tutor["content_subject"] == "history"
    assert ssc_tutor["topic"] == "Indian National Congress"
    assert "banking" not in ssc_tutor["teaching_mode_reason"].lower()
    assert "banking" not in ssc_tutor["lesson_mode_reason"].lower()

    assert ssc_quiz["exam"] == "ssc"
    assert ssc_quiz["subject"] == "general_awareness_history"
    assert ssc_quiz["content_subject"] == "history"
    assert ssc_quiz["topic"] == "Indian National Congress"
    assert "banking" not in ssc_quiz["quiz_mode_note"].lower()
    assert "preamble" not in ssc_quiz["topic"].lower()


def test_progress_summary_starts_empty_for_fresh_database(client: TestClient) -> None:
    response = client.get("/api/progress/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["topic_accuracy"] == []
    assert body["recent_quizzes"] == []
    assert body["weak_topics"] == []


def test_progress_summary_exposes_adaptive_fields(client: TestClient) -> None:
    response = client.get("/api/progress/summary")
    assert response.status_code == 200
    body = response.json()
    assert "recent_weak_areas" in body
    assert "strong_topics" in body
    assert "recommended_action" in body
    assert "recommended_mode" in body
    assert "recommendation_source" in body
    assert "recommended_next_reason" in body
    assert "priority_topics" in body
    assert "ranked_weak_topics" in body
    assert "revision_recommendations" in body
    assert body["recommended_action"]
    assert body["recommended_mode"] in {"study", "revise", "quiz"}
    assert body["recommendation_source"]
    assert body["recommended_next_topic"]
    assert body["recommended_next_reason"]
    assert body["recommended_difficulty_band"] in {"easy", "medium", "hard"}
    assert body["recommended_adaptive_state"] in {"recovery", "steady", "challenge"}
    assert body["recommended_difficulty_reason"]
    assert body["recommended_explanation_depth"] in {"foundational", "standard", "advanced"}
    assert body["recommended_explanation_depth_reason"]
    assert body["primary_study_signal"] in {"continue_topic", "next_best_topic", "priority_fix", "no_content"}
    assert body["continuation_status"] in {"none", "available", "recommended"}
    assert body["subject_difficulty_band"] in {"easy", "medium", "hard"}
    assert body["subject_adaptive_state"] in {"recovery", "steady", "challenge"}
    assert isinstance(body["recovery_topics"], list)
    assert isinstance(body["challenge_topics"], list)
    assert body["subject_difficulty_reason"]
    assert "progress_insights" in body
    assert body["progress_insights"]["momentum_status"] in {"improving", "stable", "declining"}
    assert body["progress_insights"]["movement_headline"]
    assert body["progress_insights"]["momentum_summary"]
    assert body["progress_insights"]["movement_next_step"]
    assert isinstance(body["progress_insights"]["improving_topics"], list)
    assert isinstance(body["progress_insights"]["slipping_topics"], list)
    assert isinstance(body["progress_insights"]["stable_strengths"], list)
    assert isinstance(body["progress_insights"]["persistent_weak_areas"], list)
    assert body["progress_insights"]["revision_effectiveness"]["status"] in {"improving", "stable", "declining"}
    assert body["progress_insights"]["revision_effectiveness"]["headline"]
    assert body["progress_insights"]["revision_effectiveness"]["summary"]
    assert body["progress_insights"]["revision_effectiveness"]["next_step"]
    assert isinstance(body["progress_insights"]["revision_effectiveness"]["revision_helped_topics"], list)
    assert isinstance(body["progress_insights"]["revision_effectiveness"]["revision_still_weak_topics"], list)
    assert isinstance(body["progress_insights"]["revision_effectiveness"]["urgent_recurring_weak_areas"], list)
    assert body["progress_insights"]["recovery_drift"]["status"] in {"improving", "stable", "declining"}
    assert body["progress_insights"]["recovery_drift"]["headline"]
    assert body["progress_insights"]["recovery_drift"]["summary"]
    assert body["progress_insights"]["recovery_drift"]["next_step"]
    assert isinstance(body["progress_insights"]["recovery_drift"]["recovering_topics"], list)
    assert isinstance(body["progress_insights"]["recovery_drift"]["drifting_topics"], list)
    assert "continue_study_topic" in body
    assert "continue_study_reason" in body
    assert isinstance(body["recent_weak_areas"], list)
    if body["topic_accuracy"]:
        topic_item = body["topic_accuracy"][0]
        assert "recent_accuracy" in topic_item
        assert "recent_failed_attempts" in topic_item
        assert "repeated_mistakes" in topic_item
        assert "recommended_difficulty_band" in topic_item
        assert topic_item["recommended_difficulty_band"] in {"easy", "medium", "hard"}
        assert topic_item["adaptive_state"] in {"recovery", "steady", "challenge"}
        assert topic_item["adaptive_difficulty_reason"]
        assert "revision_status" in topic_item
    assert isinstance(body["ranked_weak_topics"], list)
    if body["priority_topics"]:
        priority_item = body["priority_topics"][0]
        assert "topic" in priority_item
        assert "recommended_action" in priority_item
        assert "reason" in priority_item
        assert priority_item["recommended_mode"] in {"study", "revise", "quiz"}
        assert priority_item["recommended_difficulty_band"] in {"easy", "medium", "hard"}
        assert priority_item["recommended_adaptive_state"] in {"recovery", "steady", "challenge"}
        assert priority_item["recommended_difficulty_reason"]
        assert priority_item["recommended_explanation_depth"] in {"foundational", "standard", "advanced"}
        assert priority_item["recommended_explanation_depth_reason"]


def test_progress_summary_exposes_movement_insights_from_stored_history(client: TestClient) -> None:
    for score in (1, 2, 2, 4, 4, 5):
        create_attempt_record(client, topic="Federalism", score=score, subject="polity")
    for score in (5, 5, 5, 4, 4, 4):
        create_attempt_record(client, topic="Fundamental Rights", score=score, subject="polity")
    for score in (5, 4, 5, 5, 4, 5):
        create_attempt_record(client, topic="Parliament", score=score, subject="polity")
    for score in (1, 1, 2, 2, 1, 1):
        create_attempt_record(client, topic="Preamble", score=score, subject="polity")
    for score in (5, 5, 4, 5):
        create_attempt_record(client, topic="Indian National Congress", score=score, subject="history")

    response = client.get("/api/progress/summary?subject=polity")
    assert response.status_code == 200
    body = response.json()
    insights = body["progress_insights"]

    assert insights["momentum_status"] in {"improving", "stable", "declining"}
    assert insights["movement_headline"]
    assert insights["momentum_summary"]
    assert insights["movement_next_step"]

    improving_topics = {item["topic"] for item in insights["improving_topics"]}
    slipping_topics = {item["topic"] for item in insights["slipping_topics"]}
    stable_strengths = {item["topic"] for item in insights["stable_strengths"]}
    persistent_weak_areas = {item["topic"] for item in insights["persistent_weak_areas"]}
    all_topics = improving_topics | slipping_topics | stable_strengths | persistent_weak_areas

    assert "Federalism" in improving_topics
    assert "Fundamental Rights" in slipping_topics
    assert "Parliament" in stable_strengths
    assert "Preamble" in persistent_weak_areas
    assert "Indian National Congress" not in all_topics

    for group_name in ("improving_topics", "slipping_topics", "stable_strengths", "persistent_weak_areas"):
        for item in insights[group_name]:
            assert item["subject"] == "polity"
            assert item["movement"]
            assert item["summary"]
            assert item["trend"] in {"improving", "stable", "declining"}
            assert item["revision_signal"] in {"stable", "due_soon", "due_now", "at_risk"}
            assert item["retention_risk"] in {"low", "moderate", "high"}


def test_progress_summary_exposes_revision_effectiveness_and_recovery_drift_insights(client: TestClient) -> None:
    for score in (1, 1, 5, 5, 5, 5, 5):
        create_attempt_record(client, topic="Federalism", score=score, subject="polity")
    for score in (1, 1, 2, 2, 2, 3, 2):
        create_attempt_record(client, topic="Directive Principles", score=score, subject="polity")
    for score in (1, 5):
        create_attempt_record(client, topic="Cabinet Committees", score=score, subject="polity")
    for score in (1, 1, 4, 4, 5):
        create_attempt_record(client, topic="Fundamental Duties", score=score, subject="polity")
    for score in (1, 1, 1, 2, 1):
        create_attempt_record(client, topic="Preamble", score=score, subject="polity")
    for score in (5, 5, 5, 4, 4, 4):
        create_attempt_record(client, topic="Parliament", score=score, subject="polity")
    for score in (5, 4, 5, 5):
        create_attempt_record(client, topic="Indian National Congress", score=score, subject="history")

    response = client.get("/api/progress/summary?subject=polity")
    assert response.status_code == 200
    body = response.json()
    insights = body["progress_insights"]
    revision_effectiveness = insights["revision_effectiveness"]
    recovery_drift = insights["recovery_drift"]

    assert revision_effectiveness["status"] in {"improving", "stable", "declining"}
    assert revision_effectiveness["headline"]
    assert revision_effectiveness["summary"]
    assert revision_effectiveness["next_step"]
    assert recovery_drift["status"] in {"improving", "stable", "declining"}
    assert recovery_drift["headline"]
    assert recovery_drift["summary"]
    assert recovery_drift["next_step"]

    helped_topics = {item["topic"] for item in revision_effectiveness["revision_helped_topics"]}
    still_weak_topics = {item["topic"] for item in revision_effectiveness["revision_still_weak_topics"]}
    urgent_topics = {item["topic"] for item in revision_effectiveness["urgent_recurring_weak_areas"]}
    recovering_topics = {item["topic"] for item in recovery_drift["recovering_topics"]}
    drifting_topics = {item["topic"] for item in recovery_drift["drifting_topics"]}
    all_insight_topics = helped_topics | still_weak_topics | urgent_topics | recovering_topics | drifting_topics

    assert "Federalism" in helped_topics
    assert "Directive Principles" in still_weak_topics
    assert "Preamble" in urgent_topics
    assert "Directive Principles" in recovering_topics
    assert "Parliament" in drifting_topics
    assert "Indian National Congress" not in all_insight_topics

    for group_name, allowed_signals in (
        ("revision_helped_topics", {"revision_helped"}),
        ("revision_still_weak_topics", {"revision_still_weak"}),
        ("urgent_recurring_weak_areas", {"urgent_recurring_weak_area"}),
    ):
        for item in revision_effectiveness[group_name]:
            assert item["subject"] == "polity"
            assert item["signal"] in allowed_signals
            assert item["summary"]
            assert item["trend"] in {"improving", "stable", "declining"}
            assert item["revision_signal"] in {"stable", "due_soon", "due_now", "at_risk"}
            assert item["retention_risk"] in {"low", "moderate", "high"}

    for group_name, allowed_signals in (
        ("recovering_topics", {"recovering_after_slippage"}),
        ("drifting_topics", {"drifting_despite_activity"}),
    ):
        for item in recovery_drift[group_name]:
            assert item["subject"] == "polity"
            assert item["signal"] in allowed_signals
            assert item["summary"]
            assert item["trend"] in {"improving", "stable", "declining"}
            assert item["revision_signal"] in {"stable", "due_soon", "due_now", "at_risk"}
            assert item["retention_risk"] in {"low", "moderate", "high"}


def test_explain_topic_falls_back_without_context(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Mars Colony Separation Doctrine"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "polity"
    assert body["chapter"] == "General"
    assert body["generation_mode"] == "mock"
    assert "mock fallback" in body["generation_note"].lower()
    assert body["context_status"] == "no_knowledge_base_context"
    assert body["response_provenance"] == "mock_general_fallback"
    assert body["explanation_depth"] == "foundational"
    assert body["explanation_depth_reason"]
    assert body["explanation_style"] == "simple"
    assert body["teaching_support"] == "supportive"
    assert body["teaching_pacing"] == "gentle"
    assert body["conceptual_density"] == "low"
    assert body["teaching_mode"] == "step_by_step"
    assert body["teaching_mode_reason"]
    assert body["teaching_shape_reason"]
    assert len(body["teaching_steps"]) >= 4
    assert len(body["clarification_prompts"]) >= 3
    assert body["topic"] == "Mars Colony Separation Doctrine"
    assert body["simple_explanation"]
    assert body["detailed_explanation"]
    assert len(body["detailed_explanation"]) > len(body["simple_explanation"])
    assert len(body["key_points"]) >= 3
    assert len(body["examples"]) >= 3
    assert len(body["common_traps"]) >= 3
    assert len(body["memory_hooks"]) >= 3
    assert len(body["practice_questions"]) >= 5
    assert body["lesson_mode"] == "mini_lesson"
    assert body["lesson_mode_reason"]
    assert body["lesson_outline_state"] == "foundational_recovery"
    assert body["lesson_outline_reason"]
    assert body["lesson_script_type"] == "mini_lesson"
    assert body["lesson_script_reason"]
    assert body["mini_lesson_content"]["title"] == "Mars Colony Separation Doctrine"
    assert body["mini_lesson_content"]["direct_explanation"]
    assert len(body["mini_lesson_content"]["key_ideas"]) >= 2
    assert body["mini_lesson_content"]["simple_example_or_anchor"]
    assert len(body["mini_lesson_content"]["what_to_remember"]) >= 2
    assert body["revision_lesson_content"] is None
    assert body["structured_teaching_content"]["title"] == "Mars Colony Separation Doctrine"
    assert body["structured_teaching_content"]["subject"] == "polity"
    assert body["structured_teaching_content"]["lesson_mode"] == "mini_lesson"
    assert len(body["structured_teaching_content"]["sections"]) >= 2
    assert body["structured_teaching_content"]["sections"][0]["title"] == "Topic framing"
    assert body["structured_teaching_content"]["sections"][1]["title"] == "Mini lesson block"
    assert len(body["lecture_outline"]) >= 4
    assert len(body["lesson_script_blocks"]) >= 4
    assert "Mars Colony Separation Doctrine" in body["export_ready_lesson"]
    assert "Lecture Outline" in body["export_ready_lesson"]


def test_explain_topic_uses_foundational_depth_for_weak_topic_history(client: TestClient) -> None:
    create_attempt_record(client, topic="Directive Principles", score=1, total_questions=5)
    create_attempt_record(client, topic="Directive Principles", score=2, total_questions=5)

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Directive Principles", "subject": "polity"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["subject"] == "polity"
    assert body["topic"] == "Directive Principles"
    assert body["generation_mode"] == "mock"
    assert body["explanation_depth"] == "foundational"
    assert "foundational explanation" in body["explanation_depth_reason"].lower()
    assert body["explanation_style"] == "simple"
    assert body["teaching_support"] == "supportive"
    assert body["teaching_pacing"] == "gentle"
    assert body["conceptual_density"] == "low"
    assert body["teaching_mode"] == "step_by_step"
    assert body["teaching_shape_reason"]
    assert len(body["teaching_steps"]) >= 4
    assert body["lesson_mode"] == "revision_lesson"
    assert body["lesson_mode_reason"]
    assert body["lesson_outline_state"] == "revision_reinforcement"
    assert body["lesson_outline_reason"]
    assert body["lesson_script_type"] == "revision_lecture"
    assert body["lesson_script_reason"]
    assert body["revision_lesson_content"]["title"] == "Directive Principles"
    assert body["revision_lesson_content"]["weak_due_topic_reminder"]
    assert body["revision_lesson_content"]["key_correction"]
    assert body["revision_lesson_content"]["recall_explanation"]
    assert len(body["revision_lesson_content"]["remember_this"]) >= 2
    assert body["mini_lesson_content"] is None
    assert body["structured_teaching_content"]["lesson_mode"] == "revision_lesson"
    assert any(section["title"] == "Revision reinforcement" for section in body["structured_teaching_content"]["sections"])
    assert len(body["lecture_outline"]) >= 4
    assert len(body["lesson_script_blocks"]) >= 4
    assert "Revision Lesson" in body["export_ready_lesson"]



def test_explain_topic_uses_advanced_depth_for_strong_stable_topic_history(client: TestClient) -> None:
    for _ in range(3):
        create_attempt_record(client, topic="Fundamental Rights", score=5, total_questions=5)
        create_attempt_record(client, topic="Preamble", score=5, total_questions=5)

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Fundamental Rights", "subject": "polity"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["subject"] == "polity"
    assert body["topic"] == "Fundamental Rights"
    assert body["generation_mode"] == "mock"
    assert body["explanation_depth"] == "advanced"
    assert "advanced explanation" in body["explanation_depth_reason"].lower()
    assert body["explanation_style"] == "advanced"
    assert body["teaching_support"] == "stretch"
    assert body["teaching_pacing"] == "accelerated"
    assert body["conceptual_density"] == "high"
    assert body["teaching_mode"] == "exam_focused"
    assert body["teaching_shape_reason"]
    assert len(body["teaching_steps"]) >= 4
    assert body["lesson_mode"] == "crash_course"
    assert body["lesson_mode_reason"]
    assert body["lesson_outline_state"] == "exam_consolidation"
    assert body["lesson_outline_reason"]
    assert body["lesson_script_type"] == "crash_course"
    assert body["lesson_script_reason"]
    assert body["crash_course_content"]["title"] == "Fundamental Rights"
    assert body["crash_course_content"]["concise_topic_framing"]
    assert len(body["crash_course_content"]["key_exam_points"]) >= 2
    assert body["crash_course_content"]["likely_asked_angle"]
    assert body["crash_course_content"]["recall_angle"]
    assert len(body["crash_course_content"]["must_remember"]) >= 2
    assert body["structured_teaching_content"]["lesson_mode"] == "crash_course"
    assert any(section["title"] == "Crash course script" for section in body["structured_teaching_content"]["sections"])
    assert len(body["lecture_outline"]) >= 4
    assert len(body["lesson_script_blocks"]) >= 4
    assert "Crash Course" in body["export_ready_lesson"]


def test_explain_topic_supports_structured_teaching_modes(client: TestClient) -> None:
    expected_first_steps = {
        "concept_overview": "Start with the core concept",
        "step_by_step": "Start with the core idea",
        "example_driven": "Start with one clear example",
        "exam_focused": "Frame the exam-safe definition",
    }

    for teaching_mode, expected_title in expected_first_steps.items():
        response = client.post(
            "/api/tutor/explain",
            json={"topic": "Fundamental Rights", "subject": "polity", "teaching_mode": teaching_mode},
        )
        assert response.status_code == 200
        body = response.json()

        assert body["subject"] == "polity"
        assert body["topic"] == "Fundamental Rights"
        assert body["teaching_mode"] == teaching_mode
        assert body["teaching_mode_reason"]
        assert len(body["teaching_steps"]) >= 4
        assert body["teaching_steps"][0]["title"] == expected_title
        assert len(body["clarification_prompts"]) >= 3


def test_explain_topic_supports_structured_lesson_modes(client: TestClient) -> None:
    expected_first_outline_titles = {
        "lecture_outline": ("Parliament", "Safe starting anchor", "topic_lecture", "foundational_recovery"),
        "mini_lesson": ("President", "Re-entry anchor", "mini_lesson", "foundational_recovery"),
        "revision_lesson": ("Governor", "Repair the missed anchor", "revision_lecture", "revision_reinforcement"),
        "crash_course": ("Vice President", "30-second definition", "crash_course", "exam_consolidation"),
    }

    for lesson_mode, (topic, expected_title, expected_legacy_type, expected_outline_state) in expected_first_outline_titles.items():
        response = client.post(
            "/api/tutor/explain",
            json={"topic": topic, "subject": "polity", "lesson_mode": lesson_mode},
        )
        assert response.status_code == 200
        body = response.json()

        assert body["subject"] == "polity"
        assert body["topic"] == topic
        assert body["lesson_mode"] == lesson_mode
        assert body["lesson_mode_reason"]
        assert body["lesson_outline_state"] == expected_outline_state
        assert body["lesson_outline_reason"]
        assert body["lesson_script_type"] == expected_legacy_type
        assert body["structured_teaching_content"] is not None
        assert body["structured_teaching_content"]["topic"] == topic
        assert body["structured_teaching_content"]["lesson_mode"] == lesson_mode
        assert len(body["structured_teaching_content"]["sections"]) >= 2
        if lesson_mode == "mini_lesson":
            assert body["mini_lesson_content"] is not None
            assert body["revision_lesson_content"] is None
        elif lesson_mode == "revision_lesson":
            assert body["revision_lesson_content"] is not None
            assert body["mini_lesson_content"] is None
        elif lesson_mode == "crash_course":
            assert body["crash_course_content"] is not None
            assert body["mini_lesson_content"] is None
            assert body["revision_lesson_content"] is None
        else:
            assert body["mini_lesson_content"] is None
            assert body["revision_lesson_content"] is None
            assert body["crash_course_content"] is None
        assert len(body["lecture_outline"]) >= 4
        assert len(body["lesson_script_blocks"]) >= 4
        assert body["lecture_outline"][0]["title"] == expected_title
        assert body["export_ready_lesson"]
        assert "Outline shape" in body["export_ready_lesson"]


def test_explain_topic_keeps_requested_mode_but_stays_supportive_for_weak_history(client: TestClient) -> None:
    create_attempt_record(client, topic="Directive Principles", score=1, total_questions=5)
    create_attempt_record(client, topic="Directive Principles", score=2, total_questions=5)

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Directive Principles", "subject": "polity", "teaching_mode": "exam_focused"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["topic"] == "Directive Principles"
    assert body["teaching_mode"] == "exam_focused"
    assert body["explanation_depth"] == "foundational"
    assert body["teaching_support"] == "supportive"
    assert body["teaching_pacing"] == "gentle"
    assert body["conceptual_density"] == "low"
    assert body["teaching_shape_reason"]


def test_explain_topic_can_keep_crash_course_compact_but_supportive_for_weak_history(client: TestClient) -> None:
    create_attempt_record(client, topic="Directive Principles", score=1, total_questions=5)
    create_attempt_record(client, topic="Directive Principles", score=2, total_questions=5)

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Directive Principles", "subject": "polity", "lesson_mode": "crash_course"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["topic"] == "Directive Principles"
    assert body["lesson_mode"] == "crash_course"
    assert body["teaching_support"] == "supportive"
    assert body["teaching_pacing"] == "gentle"
    assert body["conceptual_density"] == "low"
    assert body["explanation_depth"] == "foundational"
    assert body["crash_course_content"] is not None
    assert body["crash_course_content"]["concise_topic_framing"]
    assert len(body["crash_course_content"]["must_remember"]) >= 2


def test_doubt_solving_marks_mock_context_summaries_honestly_when_context_exists(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Fundamental Rights",
            "question": "Why is Article 32 important for enforcing rights?",
            "grounding_context": "Focus on enforceability and remedies.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_mode"] == "knowledge_base_context"
    assert body["answer_source"] == "mock_context_summary"
    assert body["context_status"] == "knowledge_base_context"
    assert body["response_provenance"] == "mock_context_summary"
    assert body["generation_mode"] == "mock"
    assert "mock fallback" in body["generation_note"].lower()
    assert body["selected_topic"] == "Fundamental Rights"
    assert body["resolved_topic"]
    assert body["user_doubt"] == "Why is Article 32 important for enforcing rights?"
    assert body["grounding_context"] == "Focus on enforceability and remedies."
    assert body["grounding_note"]
    assert isinstance(body["grounding_topics"], list)
    assert body["direct_answer"]
    assert body["explanation"]
    assert body["related_concept"]
    assert body["correction"]
    assert body["common_confusion"]
    assert body["exam_tip"]
    assert body["follow_up_prompt"]
    assert "Article 32" in body["direct_answer"] or "Supreme Court" in body["direct_answer"]
    assert "For the doubt" not in body["explanation"]


def test_doubt_solving_uses_keyword_matching_without_explicit_topic(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/doubt",
        json={"question": "Why is Article 32 called the heart and soul of the Constitution?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_mode"] == "knowledge_base_context"
    assert body["answer_source"] == "mock_context_summary"
    assert body["context_status"] == "knowledge_base_context"
    assert body["response_provenance"] == "mock_context_summary"
    assert body["selected_topic"] is None
    assert body["resolved_topic"]
    assert body["user_doubt"] == "Why is Article 32 called the heart and soul of the Constitution?"
    assert body["grounding_note"]
    assert body["direct_answer"]
    assert body["explanation"]
    assert body["related_concept"]
    assert body["correction"]
    assert body["exam_tip"]
    assert body["follow_up_prompt"]


def test_doubt_solving_keeps_typed_question_primary_over_selected_topic(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Parliament",
            "question": "Why is Article 32 called the heart and soul of the Constitution?",
            "subject": "polity",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["selected_topic"] == "Parliament"
    assert body["resolved_topic"] != "Parliament"
    assert body["resolved_topic"]
    assert "typed doubt stayed primary" in body["grounding_note"].lower()
    assert "Article 32" in body["direct_answer"] or "Supreme Court" in body["direct_answer"]
    assert body["correction"]


def test_doubt_solving_marks_mock_general_fallback_honestly(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/doubt",
        json={"question": "What is the Mars colony separation doctrine?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_mode"] == "no_knowledge_base_context"
    assert body["answer_source"] == "mock_general_fallback"
    assert body["context_status"] == "no_knowledge_base_context"
    assert body["response_provenance"] == "mock_general_fallback"
    assert body["generation_mode"] == "mock"
    assert "mock fallback" in body["generation_note"].lower()
    assert body["subject"] == "polity"
    assert body["chapter"] == "General"
    assert body["direct_answer"]
    assert body["misconception_signal"] == "none"
    assert body["misconception_reason"] is None
    assert body["what_to_remember"] is None
    assert body["exam_tip"]
    assert body["follow_up_prompt"]
    assert len(body["direct_answer"]) > 20


def test_doubt_solving_surfaces_likely_misconception_for_repeated_topic_struggle(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=1, total_questions=5)
    create_attempt_record(client, topic="Preamble", score=0, total_questions=5)

    response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Preamble",
            "question": "Is liberty basically the same as equality in the Preamble?",
            "subject": "polity",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_topic"] == "Preamble"
    assert body["misconception_signal"] == "likely"
    assert body["misconception_reason"]
    assert "conceptual mix-up" in body["misconception_reason"].lower()
    assert body["what_to_remember"]
    assert "basis of distinction" in body["what_to_remember"].lower()
    assert body["explanation_depth"] == "foundational"
    assert body["teaching_support"] == "supportive"
    assert body["teaching_mode"] == "step_by_step"


def test_doubt_solving_stays_conservative_when_topic_history_is_strong(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=5, total_questions=5)
    create_attempt_record(client, topic="Preamble", score=5, total_questions=5)

    response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Preamble",
            "question": "Why is the Preamble important in constitutional interpretation?",
            "subject": "polity",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_topic"] == "Preamble"
    assert body["misconception_signal"] == "none"
    assert body["misconception_reason"] is None
    assert body["what_to_remember"] is None
    assert body["explanation_depth"] == "advanced"
    assert body["teaching_support"] == "stretch"
    assert body["teaching_mode"] == "exam_focused"


def test_non_polity_subject_fallback_stays_subject_scoped(client: TestClient) -> None:
    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Inflation", "subject": "economy"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "economy"
    assert body["chapter"] == "General"
    assert body["explanation_depth"] == "foundational"
    combined_text = " ".join(
        [
            body["simple_explanation"],
            body["detailed_explanation"],
            body["exam_relevance"],
            *body["key_points"],
            *body["practice_questions"],
        ]
    ).lower()
    assert "upsc polity" not in combined_text


def test_generated_quiz_does_not_pin_all_correct_answers_to_first_option(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()
    private_questions = get_aligned_private_quiz_questions(client, quiz)
    assert all("correct_answer" not in question for question in quiz["questions"])
    assert any(question["options"][0] != private_question["correct_answer"] for question, private_question in zip(quiz["questions"], private_questions, strict=False))



def test_generated_quiz_uses_topic_grounded_plausible_options(client: TestClient) -> None:
    bad_fragments = (
        "geography questions",
        "no connection with the constitution",
        "never appear in prelims or mains",
        "no role in upsc",
    )

    topics = ("Chief Minister", "Federalism", "Fundamental Rights")
    for topic in topics:
        generate_response = client.post(
            "/api/test/generate",
            json={"topic": topic, "question_count": 5},
        )
        assert generate_response.status_code == 200
        quiz = generate_response.json()
        private_questions = get_aligned_private_quiz_questions(client, quiz)

        for question, private_question in zip(quiz["questions"], private_questions, strict=False):
            assert len(question["options"]) == 4
            assert len(set(question["options"])) == 4
            assert "correct_answer" not in question
            assert "explanation" not in question
            assert private_question["correct_answer"] in question["options"]
            assert all(option.strip() for option in question["options"])
            assert all(
                fragment not in option.lower()
                for option in question["options"]
                for fragment in bad_fragments
            )


def test_generated_quiz_does_not_count_as_progress_until_submitted(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "quiz_mode": "revision"},
    )
    assert generate_response.status_code == 200

    summary_response = client.get("/api/progress/summary")
    history_response = client.get("/api/progress/history")
    assert summary_response.status_code == 200
    assert history_response.status_code == 200

    summary_body = summary_response.json()
    history_body = history_response.json()

    assert all(item["topic"] != "Preamble" for item in summary_body["topic_accuracy"])
    assert all(item["topic"] != "Preamble" for item in history_body["history"])

def test_generate_and_submit_quiz_flow(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()
    assert quiz["subject"] == "polity"
    assert quiz["chapter"] == "General"
    assert quiz["generation_mode"] == "mock"
    assert "mock fallback" in quiz["generation_note"].lower()
    assert quiz["quiz_mode"] == "test"
    assert "test mode" in quiz["quiz_mode_note"].lower()
    assert quiz["difficulty"] in {"easy", "medium", "hard"}
    assert len(quiz["questions"]) == 5
    assert all("correct_answer" not in question for question in quiz["questions"])
    assert all("explanation" not in question for question in quiz["questions"])

    answers = get_correct_answers(client, quiz)
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers},
    )
    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["subject"] == "polity"
    assert result["chapter"] == "General"
    assert result["topic"] == "Fundamental Rights"
    assert result["quiz_mode"] == "test"
    assert result["score"] == 5
    assert result["accuracy"] == 100.0
    assert result["incorrect_questions"] == []
    assert len(result["review_questions"]) == 5
    assert result["result_analysis"]
    assert result["result_analysis"]["performance_band"] == "strong"
    assert result["result_analysis"]["topic_breakdown"][0]["topic"] == "Fundamental Rights"
    assert result["result_analysis"]["next_step"]


def test_generate_quiz_defaults_to_test_mode(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "test"
    assert "test mode" in body["quiz_mode_note"].lower()
    assert body["adaptive_state"] in {"recovery", "steady", "challenge"}
    assert body["difficulty_reason"]


def test_generate_quiz_maps_legacy_standard_mode_to_test(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "quiz_mode": "standard"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "test"
    assert "test mode" in body["quiz_mode_note"].lower()


def test_generate_quiz_practice_mode_exposes_learning_oriented_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "quiz_mode": "practice"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "practice"
    assert "practice mode" in body["quiz_mode_note"].lower()
    assert body["covered_topics"]
    assert body["covered_topics"][0] == "Fundamental Rights"
    assert "correct_answer" not in json.dumps(body["questions"])
    assert "explanation" not in json.dumps(body["questions"])


def test_generate_quiz_practice_mode_balances_adjacent_topics_within_subject(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 6, "quiz_mode": "practice"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "practice"
    assert body["topic"] == "Fundamental Rights"
    assert body["covered_topics"][0] == "Fundamental Rights"
    assert len(body["covered_topics"]) >= 2
    assert any(topic in body["covered_topics"] for topic in {"Citizenship", "Directive Principles"})
    assert "broadens into" in body["quiz_mode_note"].lower()


def test_generate_quiz_test_mode_balances_with_ranked_weak_topics(client: TestClient) -> None:
    baseline_generate = client.post(
        "/api/test/generate",
        json={"topic": "Parliament", "question_count": 5},
    )
    assert baseline_generate.status_code == 200
    baseline_quiz = baseline_generate.json()

    mixed_answers = get_mixed_answers(client, baseline_quiz, {0, 1})
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": baseline_quiz["quiz_id"], "answers": mixed_answers},
    )
    assert submit_response.status_code == 200

    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 6, "quiz_mode": "test"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "test"
    assert body["topic"] == "Fundamental Rights"
    assert body["covered_topics"][0] == "Fundamental Rights"
    assert len(body["covered_topics"]) >= 2
    assert "Parliament" in body["covered_topics"]
    assert "weak-topic" in body["quiz_mode_note"].lower() or "recommendation" in body["quiz_mode_note"].lower()

def test_generate_quiz_revision_mode_exposes_only_public_quiz_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "quiz_mode": "revision"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["quiz_mode"] == "revision"
    assert body["quiz_mode_note"]
    assert "correct_answer" not in json.dumps(body["questions"])
    assert "explanation" not in json.dumps(body["questions"])


def test_generate_quiz_revision_mode_targets_due_material(client: TestClient) -> None:
    baseline_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "quiz_mode": "test"},
    )
    assert baseline_generate.status_code == 200
    baseline_quiz = baseline_generate.json()

    mixed_answers = get_mixed_answers(client, baseline_quiz, {0})
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": baseline_quiz["quiz_id"], "answers": mixed_answers},
    )
    assert submit_response.status_code == 200

    response = client.post(
        "/api/test/generate",
        json={"topic": "Parliament", "question_count": 5, "quiz_mode": "revision", "subject": "polity"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["subject"] == "polity"
    assert body["quiz_mode"] == "revision"
    assert body["revision_session_mode"] == "full_revision"
    assert body["revision_session_note"]
    assert body["revision_targets"]
    assert body["topic"] == body["revision_targets"][0]
    assert body["topic"] != "Parliament"
    assert body["covered_topics"] == [body["topic"]]
    assert body["revision_target_reason"]
    assert any(fragment in body["revision_target_reason"].lower() for fragment in ("revision", "due", "weak"))
    assert body["difficulty"] in {"easy", "medium"}
    assert body["adaptive_state"] in {"recovery", "steady"}
    assert "correct_answer" not in json.dumps(body["questions"])
    assert "explanation" not in json.dumps(body["questions"])


def test_generate_quiz_revision_mode_supports_short_revision_sessions(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1, total_questions=5, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, total_questions=5, subject="polity")
    create_attempt_record(client, topic="Parliament", score=2, total_questions=5, subject="polity")

    response = client.post(
        "/api/test/generate",
        json={
            "topic": "Fundamental Rights",
            "question_count": 10,
            "quiz_mode": "revision",
            "subject": "polity",
            "revision_session_mode": "short_revision",
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["subject"] == "polity"
    assert body["quiz_mode"] == "revision"
    assert body["revision_session_mode"] == "short_revision"
    assert body["revision_session_note"]
    assert "short revision session" in body["revision_session_note"].lower()
    assert body["revision_targets"]
    assert body["topic"] == body["revision_targets"][0]
    assert len(body["questions"]) == 5
    assert 1 <= len(body["covered_topics"]) <= 2
    assert "Federalism" in body["revision_targets"] or "Federalism" in body["covered_topics"]
    assert "correct_answer" not in json.dumps(body["questions"])
    assert "explanation" not in json.dumps(body["questions"])


def test_generate_quiz_revision_mode_stays_scoped_to_active_subject(client: TestClient) -> None:
    polity_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert polity_generate.status_code == 200
    polity_quiz = polity_generate.json()
    polity_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": polity_quiz["quiz_id"], "answers": get_mixed_answers(client, polity_quiz, {0})},
    )
    assert polity_submit.status_code == 200

    history_generate = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history"},
    )
    assert history_generate.status_code == 200
    history_quiz = history_generate.json()
    history_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": history_quiz["quiz_id"], "answers": get_mixed_answers(client, history_quiz, {0})},
    )
    assert history_submit.status_code == 200

    history_revision = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history", "quiz_mode": "revision"},
    )
    assert history_revision.status_code == 200
    body = history_revision.json()

    assert body["subject"] == "history"
    assert body["quiz_mode"] == "revision"
    assert body["revision_targets"]
    assert body["topic"] == body["revision_targets"][0]
    assert "Fundamental Rights" not in body["revision_targets"]


def test_generate_quiz_weak_area_drill_uses_recent_topic_mistakes(client: TestClient) -> None:
    baseline_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5},
    )
    assert baseline_generate.status_code == 200
    baseline_quiz = baseline_generate.json()

    mixed_answers = get_mixed_answers(client, baseline_quiz, {0, 1})
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": baseline_quiz["quiz_id"], "answers": mixed_answers},
    )
    assert submit_response.status_code == 200

    drill_generate = client.post(
        "/api/test/generate",
        json={"topic": "Parliament", "question_count": 5, "quiz_mode": "weak_area_drill"},
    )
    assert drill_generate.status_code == 200
    drill_quiz = drill_generate.json()

    assert drill_quiz["quiz_mode"] == "weak_area_drill"
    assert drill_quiz["drill_targets"]
    assert drill_quiz["topic"] == drill_quiz["drill_targets"][0]
    assert drill_quiz["topic"] in baseline_quiz["covered_topics"]
    assert drill_quiz["difficulty"] == "easy"
    assert drill_quiz["adaptive_state"] == "recovery"
    assert drill_quiz["drill_target_reason"]
    assert "correct_answer" not in json.dumps(drill_quiz["questions"])
    assert "explanation" not in json.dumps(drill_quiz["questions"])
    if drill_quiz["focus_concepts"]:
        assert any(
            (question.get("concept") or "") in drill_quiz["focus_concepts"]
            for question in drill_quiz["questions"]
        )



def test_generate_quiz_weak_area_drill_stays_scoped_to_active_subject(client: TestClient) -> None:
    polity_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert polity_generate.status_code == 200
    polity_quiz = polity_generate.json()
    polity_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": polity_quiz["quiz_id"], "answers": get_mixed_answers(client, polity_quiz, {0})},
    )
    assert polity_submit.status_code == 200

    history_generate = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history"},
    )
    assert history_generate.status_code == 200
    history_quiz = history_generate.json()
    history_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": history_quiz["quiz_id"], "answers": get_mixed_answers(client, history_quiz, {0})},
    )
    assert history_submit.status_code == 200

    history_drill = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history", "quiz_mode": "weak_area_drill"},
    )
    assert history_drill.status_code == 200
    history_body = history_drill.json()

    assert history_body["subject"] == "history"
    assert history_body["quiz_mode"] == "weak_area_drill"
    assert history_body["drill_targets"]
    assert history_body["drill_targets"][0] == history_body["topic"]
    assert all(topic in {"Indian National Congress", "Revolt of 1857"} for topic in history_body["drill_targets"])
    assert "Fundamental Rights" not in history_body["drill_targets"]


def test_generate_quiz_history_test_mode_stays_live_for_balanced_subject_batches(client: TestClient) -> None:
    seed_generate = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history", "quiz_mode": "test"},
    )
    assert seed_generate.status_code == 200
    seed_quiz = seed_generate.json()

    seed_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": seed_quiz["quiz_id"], "answers": get_mixed_answers(client, seed_quiz, {0}), "subject": "history"},
    )
    assert seed_submit.status_code == 200

    response = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 6, "subject": "history", "quiz_mode": "test"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["subject"] == "history"
    assert body["quiz_mode"] == "test"
    assert len(body["questions"]) == 6
    assert body["covered_topics"]
    assert all("correct_answer" not in question for question in body["questions"])
    assert all("explanation" not in question for question in body["questions"])




def test_fallback_topic_quiz_uses_topic_grounded_options(client: TestClient) -> None:
    banned_fragments = (
        "defined mainly by personal discretion",
        "works without any real link",
        "identical to its closest constitutional counterpart",
        "relevant only for geography questions",
        "can never appear in prelims or mains",
    )
    cases = [
        (
            "history",
            "Indian National Congress",
            {"congress", "national", "movement", "colonial", "moderate", "extremist", "gandhian", "socialist", "session", "sessions", "nationalist", "organisation", "grievance", "grievances"},
        ),
        (
            "geography",
            "Rivers of India",
            {"river", "rivers", "himalayan", "peninsular", "drainage", "delta", "water", "sediment", "agriculture", "hydroelectric"},
        ),
        (
            "polity",
            "Citizenship",
            {"citizenship", "constitution", "article", "articles", "parliament", "union", "state"},
        ),
    ]

    for subject, topic, domain_keywords in cases:
        response = client.post(
            "/api/test/generate",
            json={"topic": topic, "question_count": 5, "subject": subject, "quiz_mode": "revision"},
        )
        assert response.status_code == 200
        quiz = response.json()
        assert quiz["subject"] == subject
        assert quiz["topic"] == topic
        assert quiz["covered_topics"] == [topic]

        for question in quiz["questions"]:
            assert len(question["options"]) == 4
            for option in question["options"]:
                lowered = option.lower()
                assert option[:1].isupper()
                assert not any(fragment in lowered for fragment in banned_fragments)
                assert any(keyword in lowered for keyword in domain_keywords)

def test_fallback_topic_quiz_reduces_reused_wrong_options(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history", "quiz_mode": "revision"},
    )
    assert response.status_code == 200
    quiz = response.json()

    weak_fragments = (
        "is mainly associated with",
        "primarily framed through",
        "usually explained almost entirely through",
        "in exam terms",
    )
    wrong_options: list[str] = []
    private_questions = get_aligned_private_quiz_questions(client, quiz)
    for public_question, private_question in zip(quiz["questions"], private_questions, strict=False):
        wrong_options.extend(
            option.lower()
            for option in public_question["options"]
            if option != private_question["correct_answer"]
        )

    assert len(set(wrong_options)) >= len(wrong_options) - 4
    assert not any(fragment in option for option in wrong_options for fragment in weak_fragments)


def test_submit_quiz_result_analysis_summarizes_balanced_quiz_topics(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 6, "quiz_mode": "practice"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()
    assert len(quiz["covered_topics"]) >= 2

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_mixed_answers(client, quiz, {0, 2, 4})},
    )
    assert submit_response.status_code == 200
    body = submit_response.json()

    assert body["result_analysis"]
    analysis = body["result_analysis"]
    assert analysis["summary"]
    assert analysis["next_step"]
    assert analysis["next_focus_topic"]
    assert len(analysis["topic_breakdown"]) >= 2
    assert {item["topic"] for item in analysis["topic_breakdown"]}.issubset(set(quiz["covered_topics"]))
    assert {item["topic"] for item in body["review_questions"]}.issubset(set(quiz["covered_topics"]))
    assert all("chapter" in item for item in body["review_questions"])


def test_balanced_test_submission_updates_secondary_topic_guidance(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 6, "quiz_mode": "test", "subject": "polity"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()
    assert len(quiz["covered_topics"]) >= 2

    private_questions = get_aligned_private_quiz_questions(client, quiz)
    secondary_topics = [topic for topic in quiz["covered_topics"] if topic != quiz["topic"]]
    assert secondary_topics
    secondary_topic = secondary_topics[0]

    answers: list[str] = []
    saw_secondary_question = False
    for public_question, private_question in zip(quiz["questions"], private_questions, strict=False):
        if private_question.get("source_topic") == secondary_topic:
            saw_secondary_question = True
            answers.append(next(option for option in public_question["options"] if option != private_question["correct_answer"]))
        else:
            answers.append(private_question["correct_answer"])
    assert saw_secondary_question is True

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers, "subject": "polity"},
    )
    assert submit_response.status_code == 200
    body = submit_response.json()

    summary = body["progress_summary"]
    plan = body["today_plan"]
    coach = body["coach_summary"]
    topic_accuracy = {item["topic"]: item for item in summary["topic_accuracy"]}

    assert body["subject"] == "polity"
    assert summary["subject"] == "polity"
    assert plan["subject"] == "polity"
    assert coach["subject"] == "polity"
    assert secondary_topic in topic_accuracy
    assert topic_accuracy[secondary_topic]["accuracy"] < 50
    assert secondary_topic in summary["recent_weak_areas"] or secondary_topic in summary["weak_topics"]
    assert summary["ranked_weak_topics"]
    assert summary["ranked_weak_topics"][0]["topic"] == secondary_topic
    assert plan["focus_topic"] == secondary_topic
    assert coach["study_today"] == secondary_topic

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        attempt = db.query(QuizAttempt).order_by(QuizAttempt.id.desc()).first()
        assert attempt is not None
        breakdown = json.loads(attempt.topic_breakdown_json)
    finally:
        db.close()

    assert any(item["topic"] == secondary_topic for item in breakdown)


def test_submit_quiz_uses_question_id_mappings_and_reports_real_selected_answers(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submitted_answers = []
    expected_answers_by_id = {}
    wrong_question_ids = set()
    for index, (question, private_question) in enumerate(zip(quiz["questions"], get_aligned_private_quiz_questions(client, quiz), strict=False)):
        question_id = question["question_id"]
        if index < 3:
            selected_answer = private_question["correct_answer"]
        else:
            selected_answer = next(option for option in question["options"] if option != private_question["correct_answer"])
            wrong_question_ids.add(question_id)
        expected_answers_by_id[question_id] = {
            "question": question["question"],
            "selected_answer": selected_answer,
            "correct_answer": private_question["correct_answer"],
        }
        submitted_answers.append(
            {
                "question_id": question_id,
                "selected_answer": selected_answer,
            }
        )

    submitted_answers.reverse()
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": submitted_answers},
    )
    assert submit_response.status_code == 200
    body = submit_response.json()

    assert body["score"] == 3
    assert body["accuracy"] == 60.0
    assert len(body["incorrect_questions"]) == 2
    assert len(body["review_questions"]) == 5
    assert body["result_analysis"]
    assert body["result_analysis"]["performance_band"] == "mixed"
    assert body["result_analysis"]["next_step"]
    assert body["result_analysis"]["topic_breakdown"]

    review_by_id = {item["question_id"]: item for item in body["review_questions"]}
    assert set(review_by_id.keys()) == {question["question_id"] for question in quiz["questions"]}
    for question_id, expected in expected_answers_by_id.items():
        review_item = review_by_id[question_id]
        assert review_item["question"] == expected["question"]
        assert review_item["selected_answer"] == expected["selected_answer"]
        assert review_item["correct_answer"] == expected["correct_answer"]
        assert review_item["is_correct"] is (question_id not in wrong_question_ids)
        assert review_item["explanation"]
        assert review_item["topic"]
        assert review_item["chapter"] == "General"
        assert "review_tags" in review_item

    reported_wrong_answers = {item["selected_answer"] for item in body["incorrect_questions"]}
    assert reported_wrong_answers == {
        expected_answers_by_id[question_id]["selected_answer"]
        for question_id in wrong_question_ids
    }

def test_generate_quiz_for_unknown_topic_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/test/generate",
        json={"topic": "Unknown Galactic Constitution", "question_count": 5},
    )
    assert response.status_code == 404
    body = response.json()
    assert "Topic not found" in body["detail"]


def test_generation_flows_send_grounded_context_to_ai_layer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import test_service, tutor_service

    captured: dict[str, object] = {}
    real_tutor_ai = tutor_service.ai_service
    real_quiz_ai = test_service.ai_service

    class CapturingTutorAI:
        def explain_topic(self, **kwargs) -> dict:
            captured["explain"] = kwargs
            return real_tutor_ai.default_explanation_response(**kwargs)

        def default_explanation_response(self, **kwargs) -> dict:
            return real_tutor_ai.default_explanation_response(**kwargs)

        def solve_doubt(self, **kwargs) -> dict:
            captured["doubt"] = kwargs
            return real_tutor_ai.default_doubt_response(**kwargs)

        def default_doubt_response(self, **kwargs) -> dict:
            return real_tutor_ai.default_doubt_response(**kwargs)

    class CapturingQuizAI:
        def generate_quiz(self, **kwargs) -> dict:
            captured.setdefault("quiz", []).append(kwargs)
            return real_quiz_ai.default_quiz_response(**kwargs)

        def default_quiz_response(self, **kwargs) -> dict:
            return real_quiz_ai.default_quiz_response(**kwargs)

    monkeypatch.setattr(tutor_service, "ai_service", CapturingTutorAI())
    monkeypatch.setattr(test_service, "ai_service", CapturingQuizAI())

    create_attempt_record(client, topic="Federalism", score=1, total_questions=5, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, total_questions=5, subject="polity")

    explain_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism", "subject": "polity", "lesson_mode": "revision_lesson"},
    )
    doubt_response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Parliament",
            "subject": "polity",
            "question": "Why is Article 32 important for enforcing rights?",
            "grounding_context": "Focus on remedies and enforceability.",
        },
    )
    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "subject": "polity", "quiz_mode": "revision", "question_count": 5},
    )

    assert explain_response.status_code == 200
    assert doubt_response.status_code == 200
    assert quiz_response.status_code == 200

    explain_context = str(captured["explain"]["context"])
    assert "## Grounding Control" in explain_context
    assert "Flow: tutor_explanation_and_lesson_seed." in explain_context
    assert "Exam: upsc." in explain_context
    assert "Subject: Polity (polity)." in explain_context
    assert "Target topic: Federalism." in explain_context
    assert "- Requested Lesson Mode: revision_lesson" in explain_context
    assert "- Adaptive State: recovery" in explain_context
    assert "- Topic Strength: weak" in explain_context
    assert "Grounding boundary: stay inside this exam, subject, topic" in explain_context
    assert "backend/knowledge_base" not in explain_context

    doubt_context = str(captured["doubt"]["context"])
    assert "## Grounding Control" in doubt_context
    assert "Flow: doubt_answering." in doubt_context
    assert "Subject: Polity (polity)." in doubt_context
    assert "- Selected Topic: Parliament" in doubt_context
    assert "- Student Doubt: Why is Article 32 important for enforcing rights?" in doubt_context
    assert "- Student Provided Grounding: Focus on remedies and enforceability." in doubt_context
    assert "- Misconception Signal:" in doubt_context
    assert "Grounding boundary: stay inside this exam, subject, topic" in doubt_context

    quiz_payloads = captured["quiz"]
    assert isinstance(quiz_payloads, list)
    assert quiz_payloads
    quiz_context = str(quiz_payloads[0]["context"])
    assert "## Grounding Control" in quiz_context
    assert "Flow: quiz_generation." in quiz_context
    assert "Subject: Polity (polity)." in quiz_context
    assert "- Requested Topic: Preamble" in quiz_context
    assert "- Quiz Mode: revision" in quiz_context
    assert "- Revision Targets:" in quiz_context
    assert "- Adaptive State: recovery" in quiz_context
    assert "- Batch Question Count:" in quiz_context
    assert "Grounding boundary: stay inside this exam, subject, topic" in quiz_context


def test_ai_service_prompts_are_mode_aware_for_lesson_doubt_and_quiz() -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_prompts: list[dict[str, str]] = []

    class FakeProvider:
        provider_name = "fake_live"
        model_name = "fake-mode-model"

        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            captured_prompts.append({"system": system_prompt, "user": user_prompt})
            if "objective MCQ revision questions" in system_prompt:
                return {
                    "topic": "Preamble",
                    "difficulty": "easy",
                    "questions": [
                        {
                            "concept": "Source",
                            "question": "Which phrase anchors the source of authority in the Preamble?",
                            "options": ["We, the People of India", "Council of Ministers", "State Finance Commission", "Election schedules"],
                            "correct_answer": "We, the People of India",
                            "explanation": "The Preamble begins by locating constitutional authority in the people.",
                        },
                        {
                            "concept": "Ideals",
                            "question": "Which ideal pair is associated with the Preamble?",
                            "options": ["Justice and liberty", "Tax and audit", "Rivers and drainage", "Wards and blocks"],
                            "correct_answer": "Justice and liberty",
                            "explanation": "Justice and liberty are among the Preamble's core ideals.",
                        },
                    ],
                }
            if "student's exact doubt" in system_prompt:
                return {
                    "direct_answer": "Article 32 works as a direct route to the Supreme Court for enforcing Fundamental Rights.",
                    "explanation": "It matters because a right becomes meaningful only when there is a remedy. Article 32 gives that remedy constitutional status.",
                    "related_concept": "Writ jurisdiction",
                    "correction": "Do not confuse having a right with having a remedy to enforce it.",
                    "common_confusion": "A possible confusion is treating Article 32 as only symbolic instead of remedial.",
                    "what_to_remember": "Rights need remedies.",
                    "exam_tip": "Compare Article 32 with Article 226 when asked about enforcement.",
                    "follow_up_prompt": "Can you state why Article 32 is called a remedy in one line?",
                }
            return {
                "topic": "Preamble",
                "simple_explanation": "The Preamble introduces the Constitution's guiding values.",
                "detailed_explanation": "The Preamble introduces the Constitution's guiding values and gives students a compact way to frame constitutional ideals. It connects the source of authority with the nature of the state and major goals. In exam answers, it helps organize value-based introductions before moving into articles.",
                "key_points": [
                    "It begins from the authority of the people.",
                    "It identifies the nature of the Indian state.",
                    "It lists core constitutional ideals.",
                ],
                "examples": [
                    "Use it to frame constitutional values.",
                    "Connect amendment-linked words to the 42nd Amendment.",
                    "Use it in mains introductions.",
                ],
                "exam_relevance": "It is useful for constitutional philosophy and value-based questions.",
                "common_traps": [
                    "Do not treat every ideal as directly enforceable.",
                    "Do not forget amendment-linked words.",
                    "Do not replace article-based analysis with only values.",
                ],
                "memory_hooks": [
                    "People, state, ideals.",
                    "Source, nature, objectives.",
                    "Values before provisions.",
                ],
                "practice_questions": [
                    "What is the source phrase in the Preamble?",
                    "Which ideals does it list?",
                    "Why is it useful in interpretation?",
                    "Which amendment changed its wording?",
                    "How can it frame a mains answer?",
                ],
            }

    service = AIService(settings=Settings(ai_provider="mock"), provider=FakeProvider())

    service.explain_topic(
        topic="Preamble",
        context="Topic: Preamble\nLocal context for testing.",
        explanation_depth="advanced",
        teaching_mode="exam_focused",
        lesson_mode="crash_course",
    )
    service.solve_doubt(
        topic="Fundamental Rights",
        question="How does Article 32 work for enforcing rights?",
        context="Topic: Fundamental Rights\nArticle 32 context.",
        misconception_signal="possible",
        teaching_mode="step_by_step",
        explanation_depth="foundational",
    )
    service.generate_quiz(
        topic="Preamble",
        difficulty="easy",
        question_count=2,
        context="Topic: Preamble\nLocal context for testing.",
        quiz_mode="weak_area_drill",
        focus_concepts=["Source phrase"],
    )

    explanation_prompt = captured_prompts[0]["user"]
    doubt_prompt = captured_prompts[1]["user"]
    quiz_prompt = captured_prompts[2]["user"]

    assert "Lesson mode: crash_course" in explanation_prompt
    assert "Lesson-mode contract: shape the explanation as a concise exam crash-course script." in explanation_prompt
    assert "Teach with exam use in mind." in explanation_prompt
    assert "Teach at an advanced depth." in explanation_prompt

    assert "Doubt-mode contract: this is a mechanism doubt." in doubt_prompt
    assert "Because the signal suggests a possible misconception" in doubt_prompt
    assert "Move in small sequential steps." in doubt_prompt
    assert "Stay foundational and reassuring." in doubt_prompt

    assert "Quiz mode: weak_area_drill" in quiz_prompt
    assert "Quiz-mode contract: weak-area drill questions must stay tightly centered" in quiz_prompt
    assert "Difficulty contract: easy means clear recall" in quiz_prompt
    assert "Focus contract: at least some questions must directly exercise the 1 listed focus concept" in quiz_prompt
    assert "Never expose answer keys outside correct_answer in the private provider JSON contract." in quiz_prompt


def test_ai_service_uses_mock_mode_when_openai_key_is_missing() -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    service = AIService(
        settings=Settings(
            ai_provider="openai",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        )
    )

    response = service.explain_topic(topic="Unknown Topic", context="")

    assert service.mock_mode is True
    assert response["topic"] == "Unknown Topic"
    assert response["simple_explanation"]


def test_ai_service_uses_openai_provider_when_key_is_present(monkeypatch) -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "topic": "Preamble",
                                    "simple_explanation": "The Preamble introduces the philosophy and values of the Constitution.",
                                    "detailed_explanation": "The Preamble states the source of authority, the nature of the Indian state, and the constitutional ideals that guide interpretation and governance.",
                                    "key_points": [
                                        "It states the source of authority as the people.",
                                        "It names India as a sovereign, socialist, secular, democratic republic.",
                                        "It highlights justice, liberty, equality, and fraternity.",
                                    ],
                                    "examples": [
                                        "UPSC often asks about the meaning of justice, liberty, equality, and fraternity in constitutional answers.",
                                        "The 42nd Amendment is commonly used to test changes made to the Preamble.",
                                        "A mains answer can use the Preamble to frame constitutional philosophy before discussing detailed provisions.",
                                    ],
                                    "exam_relevance": "UPSC frequently uses the Preamble to test constitutional philosophy and amendment debates.",
                                    "common_traps": [
                                        "Students confuse the Preamble's interpretive value with direct enforceability.",
                                        "Questions often mix original text with the changes introduced by the 42nd Amendment.",
                                        "Learners sometimes quote ideals without linking them to constitutional interpretation.",
                                    ],
                                    "memory_hooks": [
                                        "Remember the Preamble through source, nature of state, and ideals.",
                                        "Link the Preamble to Kesavananda Bharati and constitutional philosophy.",
                                        "Use the sequence people, state, ideals when recalling the Preamble quickly.",
                                    ],
                                    "practice_questions": [
                                        "What values are listed in the Preamble?",
                                        "Why is the Preamble important in constitutional interpretation?",
                                        "Which amendment inserted the words socialist and secular?",
                                        "Why is the Preamble useful in mains answers on constitutional values?",
                                        "How would UPSC test the relation between the Preamble and the basic structure doctrine?",
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["timeout"] = kwargs.get("timeout")

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="openai",
            openai_api_key="test-key",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        )
    )

    response = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")

    assert service.mock_mode is False
    assert response["topic"] == "Preamble"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-4o-mini"


def test_ai_service_uses_gemini_provider_for_explain_doubt_and_quiz(monkeypatch) -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_requests: list[dict[str, object]] = []

    def gemini_body(payload: dict) -> dict:
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": json.dumps(payload)}]},
                    "finishReason": "STOP",
                }
            ]
        }

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return gemini_body(self.payload)

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured_requests.append({"timeout": kwargs.get("timeout")})

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            request_payload = json or {}
            system_text = " ".join(
                str(part.get("text") or "")
                for part in request_payload.get("systemInstruction", {}).get("parts", [])
                if isinstance(part, dict)
            )
            captured_requests.append({"url": url, "headers": headers, "payload": request_payload})
            if "student's exact doubt" in system_text:
                return FakeResponse(
                    {
                        "direct_answer": "The Preamble gives the Constitution its value frame, not a standalone enforceable right.",
                        "explanation": "It helps interpret constitutional ideals and connect provisions to justice, liberty, equality, and fraternity.",
                        "related_concept": "Basic structure doctrine",
                        "correction": "Do not treat interpretive value as direct enforceability.",
                        "common_confusion": "Students often confuse philosophical guidance with enforceable rights.",
                        "what_to_remember": "Use it as a constitutional value anchor.",
                        "exam_tip": "Link it to amendment and interpretation questions.",
                        "follow_up_prompt": "Which Preamble value would you use in a mains answer?",
                    }
                )
            if "objective MCQ revision questions" in system_text:
                questions = [
                    {
                        "concept": f"Preamble concept {index}",
                        "question": f"Which statement about the Preamble is accurate? {index}",
                        "options": [
                            "It frames constitutional values",
                            "It is only a financial schedule",
                            "It appoints constitutional authorities",
                            "It replaces Fundamental Rights",
                        ],
                        "correct_answer": "It frames constitutional values",
                        "explanation": "The Preamble states broad constitutional ideals and interpretive values.",
                    }
                    for index in range(1, 6)
                ]
                return FakeResponse({"topic": "Preamble", "difficulty": "medium", "questions": questions})
            return FakeResponse(
                {
                    "topic": "Preamble",
                    "simple_explanation": "The Preamble introduces the Constitution's guiding ideals.",
                    "detailed_explanation": "The Preamble identifies the source of authority and the broad goals of the constitutional order. It helps students connect provisions with values such as justice, liberty, equality, and fraternity. In exam answers, it works as a concise value frame before moving into articles and cases.",
                    "key_points": [
                        "It starts from the authority of the people.",
                        "It states the nature of the Indian state.",
                        "It lists major constitutional ideals.",
                        "It supports interpretation in constitutional debates.",
                    ],
                    "examples": [
                        "Use it to frame constitutional morality.",
                        "Use the 42nd Amendment as a recall anchor.",
                        "Use ideals in mains introductions.",
                    ],
                    "exam_relevance": "It is frequently useful for constitutional philosophy and amendment-linked questions.",
                    "common_traps": [
                        "Do not treat every ideal as directly enforceable.",
                        "Do not forget amendment-linked words.",
                        "Do not replace article-based analysis with only values.",
                    ],
                    "memory_hooks": [
                        "People, state, ideals.",
                        "Source, nature, objectives.",
                        "Values before provisions.",
                    ],
                    "practice_questions": [
                        "What values appear in the Preamble?",
                        "Why is it useful in interpretation?",
                        "Which amendment added socialist and secular?",
                        "How does it help in mains answers?",
                        "How can it frame constitutional morality?",
                    ],
                }
            )

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,mock",
            gemini_api_key="gemini-key",
            gemini_model="models/gemini-test",
        )
    )

    explanation = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")
    doubt = service.solve_doubt(topic="Preamble", question="Is the Preamble enforceable?", context="Topic: Preamble")
    quiz = service.generate_quiz(topic="Preamble", difficulty="medium", question_count=5, context="Topic: Preamble")

    assert service.mock_mode is False
    assert explanation["generation_mode"] == "gemini"
    assert explanation["generation_provider"] == "gemini"
    assert explanation["generation_model"] == "models/gemini-test"
    assert explanation["provider_chain"] == ["gemini"]
    assert explanation["response_provenance"] == "live_ai_grounded"
    assert doubt["generation_provider"] == "gemini"
    assert doubt["response_provenance"] == "live_ai_grounded"
    assert quiz["generation_provider"] == "gemini"
    assert len(quiz["questions"]) == 5
    urls = [str(item["url"]) for item in captured_requests if "url" in item]
    assert urls
    assert all("/models/gemini-test:generateContent?key=" in url for url in urls)
    assert all("models/models" not in url for url in urls)
    request_payload = next(item["payload"] for item in captured_requests if "payload" in item)
    assert request_payload["generationConfig"]["candidateCount"] == 1
    assert request_payload["generationConfig"]["responseMimeType"] == "application/json"


def test_ai_service_falls_back_to_mock_when_gemini_credentials_are_missing() -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,mock",
            gemini_api_key="",
            gemini_model="gemini-test",
        )
    )

    response = service.explain_topic(topic="Preamble", context="")

    assert service.mock_mode is True
    assert response["generation_mode"] == "mock"
    assert response["generation_provider"] == "mock"
    assert response["provider_chain"] == ["gemini", "mock"]
    assert response["simple_explanation"]


def test_ai_service_uses_groq_provider_for_explain_doubt_and_quiz(monkeypatch) -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_requests: list[dict[str, object]] = []

    def explanation_payload() -> dict:
        return {
            "topic": "Preamble",
            "simple_explanation": "The Preamble introduces the Constitution's guiding values.",
            "detailed_explanation": "The Preamble frames constitutional identity, democratic source, and interpretive direction for exam answers.",
            "key_points": [
                "It begins from the authority of the people.",
                "It names the nature of the Indian state.",
                "It lists core ideals for governance.",
            ],
            "examples": [
                "Questions may ask about constitutional ideals.",
                "The 42nd Amendment is a common recall anchor.",
                "Mains answers can use it for value framing.",
            ],
            "exam_relevance": "It is useful for constitutional philosophy and value-based questions.",
            "common_traps": [
                "Do not treat every ideal as directly enforceable.",
                "Do not forget amendment-linked words.",
                "Do not confuse interpretation with a standalone right.",
            ],
            "memory_hooks": [
                "People, state, ideals.",
                "Source, nature, objectives.",
                "Values before provisions.",
            ],
            "practice_questions": [
                "What values appear in the Preamble?",
                "Why is it useful in interpretation?",
                "Which amendment added socialist and secular?",
                "How does it help in mains answers?",
                "How can it frame constitutional morality?",
            ],
        }

    def doubt_payload() -> dict:
        return {
            "direct_answer": "The Preamble is not directly enforceable, but it guides constitutional interpretation.",
            "explanation": "Courts use it to understand constitutional ideals and resolve ambiguity, while enforceable rights still come from operative provisions.",
            "related_concept": "Constitutional interpretation",
            "correction": "Do not treat the Preamble as a standalone source of enforceable rights.",
            "common_confusion": "Students often confuse interpretive value with direct enforceability.",
            "what_to_remember": "Interpretive guide, not a direct remedy.",
            "exam_tip": "Mention its ideals and its role in interpretation when framing mains answers.",
            "follow_up_prompt": "Can you state the difference between interpretive value and enforceability in one line?",
        }

    def quiz_payload() -> dict:
        return {
            "topic": "Preamble",
            "difficulty": "medium",
            "questions": [
                {
                    "concept": "Source",
                    "question": "Which phrase best captures the source of constitutional authority in the Preamble?",
                    "options": ["We, the People of India", "Council of Ministers", "State legislatures only", "Supreme Court registry"],
                    "correct_answer": "We, the People of India",
                    "explanation": "The Preamble begins with the people as the constitutional source.",
                },
                {
                    "concept": "Ideals",
                    "question": "Which set is most closely associated with Preamble ideals?",
                    "options": ["Justice, liberty, equality, fraternity", "Tax, tariff, customs, currency", "Districts, tehsils, villages, wards", "Mountains, rivers, forests, soils"],
                    "correct_answer": "Justice, liberty, equality, fraternity",
                    "explanation": "These are core ideals named in the Preamble.",
                },
                {
                    "concept": "Amendment",
                    "question": "Which amendment is commonly linked with changes to the Preamble?",
                    "options": ["42nd Amendment", "1st Amendment", "73rd Amendment", "101st Amendment"],
                    "correct_answer": "42nd Amendment",
                    "explanation": "The 42nd Amendment added words such as socialist and secular.",
                },
            ],
        }

    def payload_for_request(request_json: dict) -> dict:
        prompt = str(request_json["messages"][1]["content"])
        if "Student doubt:" in prompt:
            return doubt_payload()
        if "Question count:" in prompt:
            return quiz_payload()
        return explanation_payload()

    class FakeResponse:
        def __init__(self, request_json: dict) -> None:
            self.request_json = request_json

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps(payload_for_request(self.request_json))}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured_requests.append({"timeout": kwargs.get("timeout")})

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            captured_requests.append({"url": url, "headers": headers, "payload": json})
            return FakeResponse(json)

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="groq",
            ai_provider_chain="groq,mock",
            groq_api_key="groq-key",
            groq_model="groq-test",
        )
    )

    explanation = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")
    doubt = service.solve_doubt(topic="Preamble", question="Is the Preamble enforceable?", context="Topic: Preamble")
    quiz = service.generate_quiz(topic="Preamble", difficulty="medium", question_count=3, context="Topic: Preamble")

    assert service.mock_mode is False
    assert explanation["generation_provider"] == "groq"
    assert explanation["generation_model"] == "groq-test"
    assert explanation["provider_chain"] == ["groq"]
    assert explanation["provider_fallback_used"] is False
    assert explanation["response_provenance"] == "live_ai_grounded"
    assert doubt["generation_provider"] == "groq"
    assert doubt["response_provenance"] == "live_ai_grounded"
    assert quiz["generation_provider"] == "groq"
    assert len(quiz["questions"]) == 3

    provider_requests = [item for item in captured_requests if "url" in item]
    assert len(provider_requests) == 3
    assert all(str(item["url"]).endswith("/chat/completions") for item in provider_requests)
    assert all("api.groq.com/openai/v1" in str(item["url"]) for item in provider_requests)
    assert all(item["headers"]["Authorization"] == "Bearer groq-key" for item in provider_requests)
    assert all(item["payload"]["model"] == "groq-test" for item in provider_requests)
    assert all(item["payload"]["response_format"] == {"type": "json_object"} for item in provider_requests)


def test_ai_service_uses_mistral_provider_only_when_explicitly_selected_for_testing(monkeypatch) -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_requests: list[dict[str, object]] = []

    def provider_payload(request_json: dict) -> dict:
        prompt = str(request_json["messages"][1]["content"])
        if "Student doubt:" in prompt:
            return {
                "direct_answer": "The Preamble is an interpretive guide, not a directly enforceable remedy.",
                "explanation": "It helps courts and students understand constitutional values, while operative articles create enforceable rights and duties.",
                "related_concept": "Constitutional interpretation",
                "correction": "Do not treat the Preamble as a standalone source of writ remedies.",
                "common_confusion": "Students may confuse interpretive importance with direct enforceability.",
                "what_to_remember": "Guide for values, not a standalone remedy.",
                "exam_tip": "Use the Preamble to frame values, then anchor the answer in relevant provisions.",
                "follow_up_prompt": "Can you state that distinction in one line?",
            }
        if "Question count:" in prompt:
            return {
                "topic": "Preamble",
                "difficulty": "medium",
                "questions": [
                    {
                        "concept": "Source",
                        "question": "Which phrase anchors popular sovereignty in the Preamble?",
                        "options": ["We, the People of India", "Council of Ministers", "State Finance Commission", "Election schedules"],
                        "correct_answer": "We, the People of India",
                        "explanation": "The phrase identifies the people as the source of constitutional authority.",
                    },
                    {
                        "concept": "Ideals",
                        "question": "Which ideal set is most closely linked with the Preamble?",
                        "options": ["Justice, liberty, equality, fraternity", "Revenue, audit, taxation, borrowing", "Village, district, block, ward", "Monsoon, relief, soil, drainage"],
                        "correct_answer": "Justice, liberty, equality, fraternity",
                        "explanation": "These ideals are directly associated with the Preamble.",
                    },
                ],
            }
        return {
            "topic": "Preamble",
            "simple_explanation": "The Preamble introduces the Constitution's guiding values.",
            "detailed_explanation": "The Preamble introduces the Constitution's guiding values and helps frame democratic source, state character, and interpretive direction for exam answers.",
            "key_points": [
                "It begins from the authority of the people.",
                "It identifies the nature of the Indian state.",
                "It lists major constitutional ideals.",
            ],
            "examples": [
                "Use it when explaining constitutional values.",
                "Connect amendment-linked words to the 42nd Amendment.",
                "Frame mains answers around justice, liberty, equality, and fraternity.",
            ],
            "exam_relevance": "It is high-yield for constitutional philosophy and value framing.",
            "common_traps": [
                "Do not treat it as a standalone writ remedy.",
                "Do not miss amendment-linked words.",
                "Do not confuse ideals with ordinary statutory provisions.",
            ],
            "memory_hooks": [
                "People, state, ideals.",
                "Source, nature, objectives.",
                "Values before provisions.",
            ],
            "practice_questions": [
                "What is the source phrase in the Preamble?",
                "Which ideals does it list?",
                "Why is it useful in interpretation?",
                "Which amendment changed its wording?",
                "How can it frame a mains answer?",
            ],
        }

    class FakeResponse:
        def __init__(self, request_json: dict) -> None:
            self.request_json = request_json

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps(provider_payload(self.request_json))}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured_requests.append({"timeout": kwargs.get("timeout")})

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            captured_requests.append({"url": url, "headers": headers, "payload": json})
            return FakeResponse(json)

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            app_env="development",
            ai_provider="mistral",
            ai_provider_chain="mistral,mock",
            mistral_api_key="mistral-key",
            mistral_model="mistral-test",
        )
    )

    explanation = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")
    doubt = service.solve_doubt(topic="Preamble", question="Is the Preamble enforceable?", context="Topic: Preamble")
    quiz = service.generate_quiz(topic="Preamble", difficulty="medium", question_count=2, context="Topic: Preamble")

    assert service.mock_mode is False
    assert explanation["generation_mode"] == "mistral"
    assert explanation["generation_provider"] == "mistral"
    assert explanation["generation_model"] == "mistral-test"
    assert explanation["provider_chain"] == ["mistral"]
    assert explanation["provider_fallback_used"] is False
    assert doubt["generation_provider"] == "mistral"
    assert doubt["response_provenance"] == "live_ai_grounded"
    assert quiz["generation_provider"] == "mistral"
    assert len(quiz["questions"]) == 2

    provider_requests = [item for item in captured_requests if "url" in item]
    assert len(provider_requests) == 3
    assert all("api.mistral.ai/v1/chat/completions" in str(item["url"]) for item in provider_requests)
    assert all(item["headers"]["Authorization"] == "Bearer mistral-key" for item in provider_requests)
    assert all(item["payload"]["model"] == "mistral-test" for item in provider_requests)
    assert all(item["payload"]["response_format"] == {"type": "json_object"} for item in provider_requests)


def test_ai_service_uses_groq_when_gemini_credentials_are_absent(monkeypatch) -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_urls: list[str] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "direct_answer": "The Preamble guides interpretation but is not directly enforceable.",
                                    "explanation": "It frames constitutional ideals, while enforceable remedies come from operative provisions.",
                                    "related_concept": "Constitutional interpretation",
                                    "correction": "Do not confuse interpretive importance with direct enforceability.",
                                    "common_confusion": "A common confusion is treating every Preamble value as a separate legal remedy.",
                                    "what_to_remember": "Guide for interpretation, not a standalone writ.",
                                    "exam_tip": "Use it to frame values, then anchor the answer in relevant articles.",
                                    "follow_up_prompt": "Can you state its exam role in one line?",
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            captured_urls.append(url)
            return FakeResponse()

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,groq,mock",
            gemini_api_key="",
            gemini_model="gemini-test",
            groq_api_key="groq-key",
            groq_model="groq-test",
        )
    )

    response = service.solve_doubt(topic="Preamble", question="Is the Preamble enforceable?", context="Topic: Preamble")

    assert service.mock_mode is False
    assert response["generation_provider"] == "groq"
    assert response["generation_model"] == "groq-test"
    assert response["provider_chain"] == ["gemini", "groq"]
    assert response["provider_fallback_used"] is True
    assert "gemini: missing API key" in str(response["provider_fallback_reason"])
    assert "groq-key" not in str(response["provider_fallback_reason"])
    assert len(captured_urls) == 1
    assert "api.groq.com/openai/v1/chat/completions" in captured_urls[0]


def test_ai_service_routes_provider_chain_and_preserves_fallback_metadata(monkeypatch) -> None:
    import httpx

    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_urls: list[str] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "topic": "Preamble",
                                    "simple_explanation": "The Preamble introduces the Constitution's guiding values.",
                                    "detailed_explanation": "The Preamble frames constitutional identity, ideals, and interpretive direction for exam answers.",
                                    "key_points": [
                                        "It starts from the authority of the people.",
                                        "It names the nature of the Indian state.",
                                        "It lists core ideals for governance.",
                                    ],
                                    "examples": [
                                        "Questions may ask about constitutional ideals.",
                                        "The 42nd Amendment is a common recall anchor.",
                                        "Mains answers can use it for value framing.",
                                    ],
                                    "exam_relevance": "It is useful for constitutional philosophy and value-based questions.",
                                    "common_traps": [
                                        "Do not treat every ideal as directly enforceable.",
                                        "Do not forget amendment-linked words.",
                                        "Do not confuse interpretation with a standalone right.",
                                    ],
                                    "memory_hooks": [
                                        "People, state, ideals.",
                                        "Source, nature, objectives.",
                                        "Values before provisions.",
                                    ],
                                    "practice_questions": [
                                        "What values appear in the Preamble?",
                                        "Why is it useful in interpretation?",
                                        "Which amendment added socialist and secular?",
                                        "How does it help in mains answers?",
                                        "How can it frame constitutional morality?",
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None) -> FakeResponse:
            captured_urls.append(url)
            if "generativelanguage.googleapis.com" in url:
                raise httpx.ConnectError("simulated gemini outage")
            return FakeResponse()

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,groq,mock",
            gemini_api_key="gemini-key",
            gemini_model="gemini-test",
            groq_api_key="groq-key",
            groq_model="groq-test",
        )
    )

    response = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")

    assert service.mock_mode is False
    assert response["generation_mode"] == "groq"
    assert response["generation_provider"] == "groq"
    assert response["provider_fallback_used"] is True
    assert response["provider_chain"] == ["gemini", "groq"]
    assert "gemini-key" not in str(response["provider_fallback_reason"])
    assert len(captured_urls) == 2


def test_ai_service_degrades_to_mock_when_live_provider_chain_fails(monkeypatch) -> None:
    import httpx

    from backend.config import Settings
    from backend.services.ai_service import AIService

    captured_urls: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, headers=None, json=None):
            captured_urls.append(url)
            raise httpx.ConnectError("simulated provider outage key=secret-value")

    monkeypatch.setattr("backend.ai_client.httpx.Client", FakeClient)

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,groq,mock",
            gemini_api_key="gemini-key",
            gemini_model="gemini-test",
            groq_api_key="groq-key",
            groq_model="groq-test",
        )
    )

    response = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")
    fallback_reason = str(response["provider_fallback_reason"])

    assert service.mock_mode is False
    assert response["generation_mode"] == "mock"
    assert response["generation_provider"] == "mock"
    assert response["provider_chain"] == ["gemini", "groq", "mock"]
    assert response["provider_fallback_used"] is True
    assert "not a live AI call" in response["generation_note"]
    assert "gemini" in fallback_reason
    assert "groq" in fallback_reason
    assert "gemini-key" not in fallback_reason
    assert "groq-key" not in fallback_reason
    assert "secret-value" not in fallback_reason
    assert len(captured_urls) == 2


def test_ai_service_disables_mistral_in_deployed_runtime_and_uses_mock() -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    service = AIService(
        settings=Settings(
            app_env="staging",
            ai_provider="mistral",
            ai_provider_chain="mistral,mock",
            mistral_api_key="mistral-key",
            mistral_model="mistral-test",
        )
    )

    response = service.solve_doubt(topic="Preamble", question="Is the Preamble enforceable?", context="Topic: Preamble")
    fallback_reason = str(response["provider_fallback_reason"])

    assert service.mock_mode is True
    assert response["generation_mode"] == "mock"
    assert response["generation_provider"] == "mock"
    assert response["provider_chain"] == ["mistral", "mock"]
    assert response["provider_fallback_used"] is True
    assert "testing-only provider disabled in deployed environment" in fallback_reason
    assert "mistral-key" not in fallback_reason


def test_ai_service_uses_request_local_provider_metadata_over_shared_router_state() -> None:
    from backend.ai_client import PROVIDER_RUNTIME_METADATA_KEY
    from backend.config import Settings
    from backend.services.ai_service import AIService

    class RaceyProvider:
        provider_name = "router"
        model_name = ""
        last_provider_name = "stale_groq"
        last_model_name = "stale-model"
        last_attempted_provider_names = ["stale_groq"]
        last_fallback_used = True
        last_fallback_reason = "stale fallback reason"

        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            return {
                "topic": "Preamble",
                "simple_explanation": "The Preamble introduces the Constitution's guiding values.",
                "detailed_explanation": "The Preamble frames constitutional identity and interpretive direction.",
                "key_points": [
                    "It starts from the authority of the people.",
                    "It names the nature of the Indian state.",
                    "It lists core ideals for governance.",
                ],
                "examples": [
                    "Questions may ask about constitutional ideals.",
                    "Mains answers may use it to frame values.",
                    "The 42nd Amendment is a common recall anchor.",
                ],
                "exam_relevance": "Useful for constitutional philosophy and value-based answers.",
                "common_traps": [
                    "Do not treat every ideal as directly enforceable.",
                    "Do not confuse interpretation with a standalone right.",
                    "Do not forget amendment-linked words.",
                ],
                "memory_hooks": [
                    "People, state, ideals.",
                    "Source, nature, objectives.",
                    "Values before provisions.",
                ],
                "practice_questions": [
                    "What values appear in the Preamble?",
                    "Why is it useful in interpretation?",
                    "Which amendment added socialist and secular?",
                    "How does it help in mains answers?",
                    "How can it frame constitutional morality?",
                ],
                PROVIDER_RUNTIME_METADATA_KEY: {
                    "provider_name": "gemini",
                    "model_name": "gemini-live",
                    "attempted_provider_chain": ["gemini"],
                    "provider_fallback_used": False,
                    "provider_fallback_reason": None,
                },
            }

    service = AIService(
        settings=Settings(
            ai_provider="gemini",
            ai_provider_chain="gemini,groq,mock",
            gemini_api_key="gemini-key",
            groq_api_key="groq-key",
        ),
        provider=RaceyProvider(),
    )

    response = service.explain_topic(topic="Preamble", context="Topic: Preamble\nLocal context for testing.")

    assert response["generation_provider"] == "gemini"
    assert response["generation_model"] == "gemini-live"
    assert response["provider_chain"] == ["gemini"]
    assert response["provider_fallback_used"] is False
    assert response["provider_fallback_reason"] is None


def test_quiz_generation_metadata_marks_mixed_live_and_mock_batches_honestly() -> None:
    from backend.services.test_service import _merge_generation_metadata, _merge_provider_metadata

    payloads = [
        {
            "generation_mode": "gemini",
            "generation_note": "Live AI used: Gemini using model gemini-test.",
            "generation_provider": "gemini",
            "generation_model": "gemini-test",
            "provider_chain": ["gemini"],
            "provider_fallback_used": False,
            "provider_fallback_reason": None,
        },
        {
            "generation_mode": "mock",
            "generation_note": "Generated by Adhyantra's local mock fallback after live AI was unavailable or failed; not a live AI call.",
            "generation_provider": "mock",
            "generation_model": None,
            "provider_chain": ["gemini", "groq", "mock"],
            "provider_fallback_used": True,
            "provider_fallback_reason": "gemini: HTTP 503; groq: ConnectError",
        },
    ]

    generation_mode, generation_note = _merge_generation_metadata(payloads)
    provider_metadata = _merge_provider_metadata(payloads)

    assert generation_mode == "mock"
    assert "mock-assisted" in generation_note
    assert provider_metadata["generation_provider"] == "mock"
    assert provider_metadata["generation_model"] is None
    assert provider_metadata["provider_chain"] == ["gemini", "groq", "mock"]
    assert provider_metadata["provider_fallback_used"] is True
    assert "gemini: HTTP 503" in str(provider_metadata["provider_fallback_reason"])


def test_ai_service_falls_back_when_provider_returns_invalid_doubt_payload() -> None:
    from backend.config import Settings
    from backend.services.ai_service import AIService

    class FakeProvider:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            return {"direct_answer": "", "explanation": "Only one field returned."}

    service = AIService(
        settings=Settings(
            ai_provider="openai",
            openai_api_key="test-key",
            openai_model="gpt-4o-mini",
            openai_base_url="https://api.openai.com/v1",
        ),
        provider=FakeProvider(),
    )

    response = service.solve_doubt(
        topic="General UPSC Polity",
        question="What is the Mars colony separation doctrine?",
        context="",
    )

    assert response["answer_mode"] == "no_knowledge_base_context"
    assert response["answer_source"] == "mock_general_fallback"
    assert response["context_status"] == "no_knowledge_base_context"
    assert response["response_provenance"] == "mock_general_fallback"
    assert response["direct_answer"]
    assert response["common_confusion"]
    assert response["what_to_remember"]
    assert response["exam_tip"]
    assert response["follow_up_prompt"]
    assert "not a standard syllabus term" in response["direct_answer"]



def test_progress_summary_and_history_stay_consistent_after_submission(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "question_count": 5, "quiz_mode": "revision"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    answers = get_correct_answers(client, quiz)[:4] + ["Totally wrong option"]
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers},
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["score"] == 4
    assert submit_body["accuracy"] == 80.0

    summary_response = client.get("/api/progress/summary")
    history_response = client.get("/api/progress/history")
    assert summary_response.status_code == 200
    assert history_response.status_code == 200

    summary_body = summary_response.json()
    history_body = history_response.json()

    preamble_summary = next(item for item in summary_body["topic_accuracy"] if item["topic"] == "Preamble")
    preamble_history = next(item for item in history_body["history"] if item["topic"] == "Preamble")

    assert preamble_summary["attempts_count"] == 1
    assert preamble_summary["accuracy"] == 80.0
    assert preamble_history["score"] == 4
    assert preamble_history["total_questions"] == 5
    assert preamble_history["accuracy"] == 80.0



def test_quiz_submission_updates_subject_scoped_guidance_after_weak_result(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    wrong_answers = get_mixed_answers(client, quiz, set())
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": wrong_answers, "subject": "history"},
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["subject"] == "history"
    assert submit_body["accuracy"] == 0.0
    assert submit_body["progress_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["subject"] == "history"
    assert submit_body["coach_summary"]["subject"] == "history"

    summary_response = client.get("/api/progress/summary?subject=history")
    plan_response = client.get("/api/plan/today?subject=history")
    coach_response = client.get("/api/coach/summary?subject=history")
    polity_summary_response = client.get("/api/progress/summary?subject=polity")
    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert polity_summary_response.status_code == 200

    summary_body = summary_response.json()
    plan_body = plan_response.json()
    coach_body = coach_response.json()
    polity_summary_body = polity_summary_response.json()

    assert submit_body["progress_summary"]["recommended_next_topic"] == summary_body["recommended_next_topic"]
    assert submit_body["today_plan"]["focus_topic"] == plan_body["focus_topic"]
    assert submit_body["coach_summary"]["study_today"] == coach_body["study_today"]
    assert "Revolt of 1857" in summary_body["weak_topics"]
    assert summary_body["ranked_weak_topics"][0]["topic"] == "Revolt of 1857"
    assert summary_body["recommended_mode"] == "revise"
    assert plan_body["focus_topic"] == "Revolt of 1857"
    assert plan_body["ranked_weak_topics"][0]["topic"] == "Revolt of 1857"
    assert plan_body["recommended_mode"] == "revise"
    assert coach_body["study_today"] == "Revolt of 1857"
    assert coach_body["recommended_mode"] == "revise"
    assert coach_body["ranked_weak_topics"][0]["topic"] == "Revolt of 1857"
    assert "Revolt of 1857" in coach_body["weak_areas"]
    assert "Revolt of 1857" not in polity_summary_body["weak_topics"]


def test_quiz_submission_updates_subject_scoped_guidance_after_strong_result(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    correct_answers = get_correct_answers(client, quiz)
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": correct_answers, "subject": "history"},
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["subject"] == "history"
    assert submit_body["accuracy"] == 100.0
    assert submit_body["progress_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["subject"] == "history"
    assert submit_body["coach_summary"]["subject"] == "history"

    summary_response = client.get("/api/progress/summary?subject=history")
    plan_response = client.get("/api/plan/today?subject=history")
    coach_response = client.get("/api/coach/summary?subject=history")
    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200

    summary_body = summary_response.json()
    plan_body = plan_response.json()
    coach_body = coach_response.json()

    assert submit_body["progress_summary"]["recommended_next_topic"] == summary_body["recommended_next_topic"]
    assert submit_body["today_plan"]["focus_topic"] == plan_body["focus_topic"]
    assert submit_body["coach_summary"]["study_today"] == coach_body["study_today"]
    assert "Indian National Congress" not in summary_body["weak_topics"]
    assert summary_body["recommended_next_topic"] != "Indian National Congress"
    assert plan_body["focus_topic"] != "Indian National Congress"
    assert coach_body["study_today"] != "Indian National Congress"


def test_quiz_submission_returns_aligned_guidance_after_mixed_result(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    mixed_answers = get_mixed_answers(client, quiz, {0, 1, 2})
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": mixed_answers, "subject": "history"},
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()

    assert submit_body["subject"] == "history"
    assert submit_body["accuracy"] == 60.0
    assert submit_body["progress_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["subject"] == "history"
    assert submit_body["coach_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["focus_topic"] == submit_body["progress_summary"]["recommended_next_topic"]
    assert submit_body["coach_summary"]["study_today"] == submit_body["today_plan"]["focus_topic"]
    assert submit_body["coach_summary"]["recommended_mode"] == submit_body["today_plan"]["recommended_mode"]
    assert submit_body["progress_summary"]["recommended_mode"] == submit_body["today_plan"]["recommended_mode"]
    assert submit_body["coach_summary"]["recommended_difficulty_band"] == submit_body["today_plan"]["recommended_difficulty_band"]
    assert submit_body["progress_summary"]["recommended_difficulty_band"] == submit_body["today_plan"]["recommended_difficulty_band"]
    assert submit_body["coach_summary"]["recommended_adaptive_state"] == submit_body["today_plan"]["recommended_adaptive_state"]
    assert submit_body["progress_summary"]["recommended_adaptive_state"] == submit_body["today_plan"]["recommended_adaptive_state"]
    assert submit_body["coach_summary"]["recommended_explanation_depth"] == submit_body["today_plan"]["recommended_explanation_depth"]
    assert submit_body["progress_summary"]["recommended_explanation_depth"] == submit_body["today_plan"]["recommended_explanation_depth"]

    history_summary = client.get("/api/progress/summary?subject=history")
    polity_summary = client.get("/api/progress/summary?subject=polity")
    assert history_summary.status_code == 200
    assert polity_summary.status_code == 200

    history_body = history_summary.json()
    polity_body = polity_summary.json()

    assert history_body["recommended_next_topic"] == submit_body["progress_summary"]["recommended_next_topic"]
    assert all(item["subject"] == "history" for item in submit_body["progress_summary"]["ranked_weak_topics"])
    assert all(item["topic"] != "Revolt of 1857" for item in polity_body["ranked_weak_topics"])


@pytest.mark.parametrize("quiz_mode", ["practice", "test", "revision", "weak_area_drill"])
def test_quiz_mode_submissions_refresh_subject_guidance_consistently(client: TestClient, quiz_mode: str) -> None:
    seed_generate = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history", "quiz_mode": "test"},
    )
    assert seed_generate.status_code == 200
    seed_quiz = seed_generate.json()
    seed_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": seed_quiz["quiz_id"], "answers": get_mixed_answers(client, seed_quiz, {0}), "subject": "history"},
    )
    assert seed_submit.status_code == 200

    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history", "quiz_mode": quiz_mode},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_mixed_answers(client, quiz, {0, 2}), "subject": "history"},
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()

    assert submit_body["subject"] == "history"
    assert submit_body["quiz_mode"] in {quiz_mode, "revision"}
    assert submit_body["progress_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["subject"] == "history"
    assert submit_body["coach_summary"]["subject"] == "history"
    assert submit_body["today_plan"]["focus_topic"] == submit_body["progress_summary"]["recommended_next_topic"]
    assert submit_body["coach_summary"]["study_today"] == submit_body["today_plan"]["focus_topic"]
    assert all(item["subject"] == "history" for item in submit_body["progress_summary"]["ranked_weak_topics"])

    history_summary = client.get("/api/progress/summary?subject=history")
    polity_summary = client.get("/api/progress/summary?subject=polity")
    assert history_summary.status_code == 200
    assert polity_summary.status_code == 200
    history_body = history_summary.json()
    polity_body = polity_summary.json()

    assert history_body["recommended_next_topic"] == submit_body["progress_summary"]["recommended_next_topic"]
    assert all(item["topic"] not in {"Indian National Congress", "Revolt of 1857"} for item in polity_body["ranked_weak_topics"])


def test_plan_today_endpoint_returns_actionable_fields(client: TestClient) -> None:
    response = client.get("/api/plan/today")
    assert response.status_code == 200
    body = response.json()
    assert body["focus_topic"]
    assert "revision_topics" in body
    assert body["practice_action"]
    assert body["quiz_action"]
    assert body["coach_note"]
    assert body["next_action"]
    assert body["next_step_guidance"]
    assert body["recommended_action"]
    assert body["recommended_mode"] in {"study", "revise", "quiz"}
    assert body["recommendation_source"]
    assert body["recommended_difficulty_band"] in {"easy", "medium", "hard"}
    assert body["recommended_adaptive_state"] in {"recovery", "steady", "challenge"}
    assert body["recommended_difficulty_reason"]
    assert body["recommended_explanation_depth"] in {"foundational", "standard", "advanced"}
    assert body["recommended_explanation_depth_reason"]
    assert body["primary_study_signal"] in {"continue_topic", "next_best_topic", "priority_fix", "no_content"}
    assert body["continuation_status"] in {"none", "available", "recommended"}
    assert "continue_study_topic" in body
    assert "continue_study_reason" in body
    assert "ranked_weak_topics" in body
    assert isinstance(body["ranked_weak_topics"], list)
    assert isinstance(body["secondary_suggestions"], list)



def test_plan_today_endpoint_tracks_progress_summary_recommendation(client: TestClient) -> None:
    summary_response = client.get("/api/progress/summary?subject=history")
    plan_response = client.get("/api/plan/today?subject=history")

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200

    summary_body = summary_response.json()
    plan_body = plan_response.json()

    assert plan_body["subject"] == "history"
    assert plan_body["focus_topic"] == summary_body["recommended_next_topic"]
    assert plan_body["focus_reason"] == summary_body["recommended_next_reason"]
    assert plan_body["recommended_action"] == summary_body["recommended_action"]
    assert plan_body["recommended_mode"] == summary_body["recommended_mode"]
    assert plan_body["recommendation_source"] == summary_body["recommendation_source"]
    assert plan_body["recommended_difficulty_band"] == summary_body["recommended_difficulty_band"]
    assert plan_body["recommended_adaptive_state"] == summary_body["recommended_adaptive_state"]
    assert plan_body["recommended_explanation_depth"] == summary_body["recommended_explanation_depth"]



def test_revision_due_endpoint_returns_grouped_buckets(client: TestClient) -> None:
    response = client.get("/api/revision/due")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"exam", "subject", "content_subject", "overdue", "due_now", "due_soon", "total_due_count"}
    assert body["exam"] == "upsc"
    assert body["content_subject"] == body["subject"]
    assert body["subject"] == "polity"
    assert isinstance(body["overdue"], list)
    assert isinstance(body["due_now"], list)
    assert isinstance(body["due_soon"], list)



def test_coach_summary_endpoint_returns_summary_fields(client: TestClient) -> None:
    response = client.get("/api/coach/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["study_today"]
    assert body["study_reason"]
    assert "revise_today" in body
    assert "revise_now" in body
    assert "revise_reason" in body
    assert "weak_areas" in body
    assert body["trend_status"] in {"improving", "stable", "declining"}
    assert body["trend_reason"]
    assert body["coach_note"]
    assert body["next_action"]
    assert body["recommended_action"]
    assert body["recommended_reason"]
    assert body["recommended_mode"] in {"study", "revise", "quiz"}
    assert body["recommendation_source"]
    assert body["recommended_difficulty_band"] in {"easy", "medium", "hard"}
    assert body["recommended_adaptive_state"] in {"recovery", "steady", "challenge"}
    assert body["recommended_difficulty_reason"]
    assert body["recommended_explanation_depth"] in {"foundational", "standard", "advanced"}
    assert body["recommended_explanation_depth_reason"]
    assert body["primary_study_signal"] in {"continue_topic", "next_best_topic", "priority_fix", "no_content"}
    assert body["continuation_status"] in {"none", "available", "recommended"}
    assert "continue_study_topic" in body
    assert "continue_study_reason" in body
    assert "ranked_weak_topics" in body
    assert isinstance(body["ranked_weak_topics"], list)
    assert isinstance(body["warnings"], list)
    assert body["mentor_mode"] == "normal"
    assert body["accountability_summary"]["mentor_mode"] == "normal"
    assert body["accountability_summary"]["warning_severity"] in {"none", "gentle", "moderate", "strong"}
    assert body["accountability_summary"]["motivation_summary"]["motivation_state"] in {"stable", "rebuilding", "slipping", "overloaded", "regaining_momentum"}
    assert body["accountability_summary"]["motivation_summary"]["confidence_state"] in {"steady", "rebuilding"}
    assert body["accountability_summary"]["motivation_summary"]["burnout_signal"] in {"none", "watch"}
    assert body["accountability_summary"]["motivation_summary"]["guidance_mode"] in {"reinforce_progress", "urge_recovery", "calm_overload", "protect_momentum", "rebuild_confidence"}
    assert body["accountability_summary"]["motivation_summary"]["guidance_message"]
    assert "confidence_rebuild_guidance" in body["accountability_summary"]["motivation_summary"]
    assert "overload_guidance" in body["accountability_summary"]["motivation_summary"]
    assert "restart_plan_details" in body["accountability_summary"]
    assert "restart_plan_details" in body
    assert body["accountability_summary"]["motivation_summary"]["encouragement"]
    assert body["accountability_summary"]["motivation_summary"]["motivation_reason"]
    assert all(item["severity"] in {"gentle", "moderate", "strong"} for item in body["warnings"])



def test_coach_summary_endpoint_supports_strict_mentor_mode(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Preamble", score=5)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        federalism_attempt.created_at = now - timedelta(days=4)
        preamble_attempt.created_at = now - timedelta(hours=2)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        assert federalism_study is not None
        assert preamble_study is not None
        federalism_study.last_interaction_at = now - timedelta(days=4)
        preamble_study.last_interaction_at = now - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    response = client.get("/api/coach/summary?mentor_mode=strict")
    assert response.status_code == 200
    body = response.json()

    assert body["mentor_mode"] == "strict"
    assert body["accountability_summary"]["mentor_mode"] == "strict"
    assert body["accountability_summary"]["warning_level"] == "watch"
    assert body["accountability_summary"]["warning_severity"] == "moderate"
    assert any(item["severity"] == "moderate" for item in body["warnings"])
    assert "Treat this as an early correction point in the next session." in body["coach_note"]


def test_progress_plan_and_coach_endpoints_expose_structured_recovery_plan(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Preamble", score=5)
    create_attempt_record(client, topic="Citizenship", score=4)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        citizenship_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Citizenship").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        assert citizenship_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=4)
        preamble_attempt.created_at = now - timedelta(hours=6)
        citizenship_attempt.created_at = now - timedelta(hours=2)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        citizenship_study = db.query(TopicStudy).filter(TopicStudy.topic == "Citizenship").first()
        assert federalism_study is not None
        assert preamble_study is not None
        assert citizenship_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=4)
        preamble_study.last_interaction_at = now - timedelta(hours=6)
        citizenship_study.last_interaction_at = now - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    summary_response = client.get("/api/progress/summary")
    plan_response = client.get("/api/plan/today")
    coach_response = client.get("/api/coach/summary")

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    accountability = summary["accountability_summary"]
    recovery_plan_details = accountability["recovery_plan_details"]

    assert accountability["missed_revision_signal"] in {"watch", "missed"}
    assert recovery_plan_details
    assert recovery_plan_details["immediate_repair_topic"] == "Federalism"
    assert recovery_plan_details["urgent_revision_target"] == "Federalism"
    assert "Federalism" in recovery_plan_details["short_catch_up_step"]
    assert recovery_plan_details["next_stable_step"]
    assert recovery_plan_details["recovery_reason"]
    assert plan["recovery_plan_details"] == recovery_plan_details
    assert coach["recovery_plan_details"] == recovery_plan_details


def test_version12_accountability_recovery_target_keeps_tutor_supportive(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Preamble", score=5)
    create_attempt_record(client, topic="Citizenship", score=4)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        citizenship_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Citizenship").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        assert citizenship_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=4)
        preamble_attempt.created_at = now - timedelta(hours=6)
        citizenship_attempt.created_at = now - timedelta(hours=2)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        citizenship_study = db.query(TopicStudy).filter(TopicStudy.topic == "Citizenship").first()
        assert federalism_study is not None
        assert preamble_study is not None
        assert citizenship_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=4)
        preamble_study.last_interaction_at = now - timedelta(hours=6)
        citizenship_study.last_interaction_at = now - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    summary_response = client.get('/api/progress/summary')
    tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Federalism', 'subject': 'polity'},
    )
    doubt_response = client.post(
        '/api/tutor/doubt',
        json={
            'topic': 'Federalism',
            'question': 'Please bring me back on track with Federalism after I skipped it.',
            'subject': 'polity',
        },
    )

    assert summary_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()
    recovery_plan_details = summary['accountability_summary']['recovery_plan_details']

    assert recovery_plan_details
    assert recovery_plan_details['immediate_repair_topic'] == 'Federalism'
    assert recovery_plan_details['urgent_revision_target'] == 'Federalism'

    assert tutor['topic'] == 'Federalism'
    assert tutor['explanation_depth'] == 'foundational'
    assert tutor['teaching_support'] == 'supportive'
    assert tutor['teaching_mode'] == 'step_by_step'
    assert 'accountability' in tutor['explanation_depth_reason'].lower()

    assert doubt['resolved_topic'] == 'Federalism'
    assert doubt['explanation_depth'] == 'foundational'
    assert doubt['teaching_support'] == 'supportive'
    assert doubt['teaching_mode'] == 'step_by_step'
    assert 'accountability' in doubt['explanation_depth_reason'].lower()



def test_version12_strict_mode_changes_visibility_not_raw_evidence_across_summary_plan_and_coach(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Preamble", score=5)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        federalism_attempt.created_at = now - timedelta(days=4)
        preamble_attempt.created_at = now - timedelta(hours=2)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        assert federalism_study is not None
        assert preamble_study is not None
        federalism_study.last_interaction_at = now - timedelta(days=4)
        preamble_study.last_interaction_at = now - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    normal_summary_response = client.get('/api/progress/summary?mentor_mode=normal')
    strict_summary_response = client.get('/api/progress/summary?mentor_mode=strict')
    normal_plan_response = client.get('/api/plan/today?mentor_mode=normal')
    strict_plan_response = client.get('/api/plan/today?mentor_mode=strict')
    normal_coach_response = client.get('/api/coach/summary?mentor_mode=normal')
    strict_coach_response = client.get('/api/coach/summary?mentor_mode=strict')

    assert normal_summary_response.status_code == 200
    assert strict_summary_response.status_code == 200
    assert normal_plan_response.status_code == 200
    assert strict_plan_response.status_code == 200
    assert normal_coach_response.status_code == 200
    assert strict_coach_response.status_code == 200

    normal_summary = normal_summary_response.json()
    strict_summary = strict_summary_response.json()
    normal_plan = normal_plan_response.json()
    strict_plan = strict_plan_response.json()
    normal_coach = normal_coach_response.json()
    strict_coach = strict_coach_response.json()

    normal_accountability = normal_summary['accountability_summary']
    strict_accountability = strict_summary['accountability_summary']

    assert normal_accountability['mentor_mode'] == 'normal'
    assert strict_accountability['mentor_mode'] == 'strict'
    assert normal_accountability['consistency_status'] == strict_accountability['consistency_status']
    assert normal_accountability['missed_plan_signal'] == strict_accountability['missed_plan_signal']
    assert normal_accountability['missed_revision_signal'] == strict_accountability['missed_revision_signal']
    assert normal_accountability['warning_level'] == strict_accountability['warning_level']
    assert normal_accountability['missed_priority_topic'] == strict_accountability['missed_priority_topic']
    assert normal_accountability['missed_revision_topics'] == strict_accountability['missed_revision_topics']
    assert normal_accountability['recovery_plan_details'] == strict_accountability['recovery_plan_details']
    assert normal_summary['recommended_next_topic'] == strict_summary['recommended_next_topic']
    assert normal_summary['recommended_mode'] == strict_summary['recommended_mode']
    assert normal_accountability['warning_severity'] == 'gentle'
    assert strict_accountability['warning_severity'] == 'moderate'

    assert normal_plan['focus_topic'] == strict_plan['focus_topic'] == normal_summary['recommended_next_topic']
    assert normal_plan['recommended_action'] == strict_plan['recommended_action']
    assert normal_plan['recovery_plan_details'] == strict_plan['recovery_plan_details'] == normal_accountability['recovery_plan_details']

    assert normal_coach['recommended_action'] == strict_coach['recommended_action']
    assert normal_coach['accountability_summary']['warning_level'] == strict_coach['accountability_summary']['warning_level']
    assert normal_coach['recovery_plan_details'] == strict_coach['recovery_plan_details'] == normal_accountability['recovery_plan_details']
    assert normal_coach['coach_note'] != strict_coach['coach_note']
    assert any(item['severity'] == 'moderate' for item in strict_coach['warnings'])



def test_version12_accountability_subject_scope_stays_clean_across_endpoints_and_tutor(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=5, subject="polity")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=4, subject="history")
    create_attempt_record(client, topic="Revolt of 1857", score=4, subject="history")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        inc_attempts = db.query(QuizAttempt).filter(QuizAttempt.topic == "Indian National Congress").order_by(QuizAttempt.id.asc()).all()
        revolt_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Revolt of 1857").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        assert len(inc_attempts) == 2
        assert revolt_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=4)
        preamble_attempt.created_at = now - timedelta(hours=2)
        inc_attempts[0].created_at = now - timedelta(days=2)
        inc_attempts[1].created_at = now - timedelta(days=1)
        revolt_attempt.created_at = now - timedelta(hours=4)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        inc_study = db.query(TopicStudy).filter(TopicStudy.topic == "Indian National Congress").first()
        revolt_study = db.query(TopicStudy).filter(TopicStudy.topic == "Revolt of 1857").first()
        assert federalism_study is not None
        assert preamble_study is not None
        assert inc_study is not None
        assert revolt_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=4)
        preamble_study.last_interaction_at = now - timedelta(hours=2)
        inc_study.last_interaction_at = now - timedelta(hours=12)
        revolt_study.last_interaction_at = now - timedelta(hours=4)
        db.commit()
    finally:
        db.close()

    history_summary_response = client.get('/api/progress/summary?subject=history')
    history_plan_response = client.get('/api/plan/today?subject=history')
    history_coach_response = client.get('/api/coach/summary?subject=history')
    history_tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Indian National Congress', 'subject': 'history'},
    )

    assert history_summary_response.status_code == 200
    assert history_plan_response.status_code == 200
    assert history_coach_response.status_code == 200
    assert history_tutor_response.status_code == 200

    history_summary = history_summary_response.json()
    history_plan = history_plan_response.json()
    history_coach = history_coach_response.json()
    history_tutor = history_tutor_response.json()
    history_accountability = history_summary['accountability_summary']
    history_recovery_plan = history_accountability['recovery_plan_details']

    assert history_accountability['subject'] == 'history'
    assert history_accountability['warning_level'] == 'quiet'
    assert history_accountability['warning_severity'] == 'none'
    assert history_accountability['missed_revision_count'] == 0
    assert 'Federalism' not in history_accountability['missed_revision_topics']
    if history_recovery_plan:
        assert history_recovery_plan.get('immediate_repair_topic') != 'Federalism'
        assert history_recovery_plan.get('urgent_revision_target') != 'Federalism'

    assert history_plan['subject'] == 'history'
    assert history_coach['subject'] == 'history'
    assert history_coach['accountability_summary']['subject'] == 'history'
    assert history_plan['recovery_plan_details'] == history_recovery_plan
    assert 'Federalism' not in str(history_plan['recommended_action'])
    assert 'Federalism' not in str(history_coach['revise_now'])
    assert 'Federalism' not in str(history_coach['coach_note'])

    assert history_tutor['topic'] == 'Indian National Congress'
    assert 'accountability' not in history_tutor['explanation_depth_reason'].lower()



def test_version13_overloaded_motivation_keeps_tutor_narrow_on_repair_topic(client: TestClient) -> None:
    create_attempt_record(client, topic="President", score=5)
    create_attempt_record(client, topic="President", score=4)
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="President", score=2)
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="President", score=2)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        president_attempts = db.query(QuizAttempt).filter(QuizAttempt.topic == "President").order_by(QuizAttempt.id.asc()).all()
        federalism_attempts = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.asc()).all()
        assert len(president_attempts) == 4
        assert len(federalism_attempts) == 2

        president_attempts[0].created_at = now - timedelta(days=6)
        president_attempts[1].created_at = now - timedelta(days=5)
        president_attempts[2].created_at = now - timedelta(days=3)
        president_attempts[3].created_at = now - timedelta(days=1)
        federalism_attempts[0].created_at = now - timedelta(days=4)
        federalism_attempts[1].created_at = now - timedelta(days=2)

        president_study = db.query(TopicStudy).filter(TopicStudy.topic == "President").first()
        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        assert president_study is not None
        assert federalism_study is not None

        president_study.last_interaction_at = now - timedelta(days=1)
        federalism_study.last_interaction_at = now - timedelta(days=2)
        db.commit()
    finally:
        db.close()

    summary_response = client.get('/api/progress/summary')
    plan_response = client.get('/api/plan/today')
    coach_response = client.get('/api/coach/summary')
    tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Federalism', 'subject': 'polity'},
    )
    doubt_response = client.post(
        '/api/tutor/doubt',
        json={
            'topic': 'Federalism',
            'question': 'I feel overloaded. Help me repair Federalism without widening the load.',
            'subject': 'polity',
        },
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()
    accountability = summary['accountability_summary']
    motivation = accountability['motivation_summary']
    overload_guidance = motivation['overload_guidance']

    assert motivation['motivation_state'] == 'overloaded'
    assert overload_guidance
    assert overload_guidance['focus_topic'] == 'Federalism'
    assert summary['recommended_next_topic'] == 'Federalism'
    assert plan['focus_topic'] == 'Federalism'
    assert coach['accountability_summary']['motivation_summary']['overload_guidance'] == overload_guidance

    assert tutor['topic'] == 'Federalism'
    assert tutor['explanation_depth'] == 'foundational'
    assert tutor['teaching_support'] == 'supportive'
    assert tutor['teaching_mode'] == 'step_by_step'
    assert tutor['lesson_mode'] == 'mini_lesson'
    assert tutor['lesson_outline_state'] == 'foundational_recovery'
    assert tutor['structured_teaching_content']['lesson_mode'] == 'mini_lesson'
    assert 'motivation layer' in tutor['explanation_depth_reason'].lower()
    assert 'overloaded' in tutor['explanation_depth_reason'].lower()

    assert doubt['resolved_topic'] == 'Federalism'
    assert doubt['explanation_depth'] == 'foundational'
    assert doubt['teaching_support'] == 'supportive'
    assert doubt['teaching_mode'] == 'step_by_step'
    assert 'motivation layer' in doubt['explanation_depth_reason'].lower()
    assert 'overloaded' in doubt['explanation_depth_reason'].lower()



def test_version13_restart_plan_keeps_tutor_reentry_supportive(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=3)
    create_attempt_record(client, topic="Preamble", score=4)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=8)
        preamble_attempt.created_at = now - timedelta(days=6)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        assert federalism_study is not None
        assert preamble_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=8)
        preamble_study.last_interaction_at = now - timedelta(days=6)
        db.commit()
    finally:
        db.close()

    summary_response = client.get('/api/progress/summary')
    plan_response = client.get('/api/plan/today')
    coach_response = client.get('/api/coach/summary')
    tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Federalism', 'subject': 'polity'},
    )
    doubt_response = client.post(
        '/api/tutor/doubt',
        json={
            'topic': 'Federalism',
            'question': 'Help me restart Federalism after I drifted away from this subject.',
            'subject': 'polity',
        },
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()
    accountability = summary['accountability_summary']
    motivation = accountability['motivation_summary']
    restart_plan_details = accountability['restart_plan_details']
    recovery_plan_details = accountability['recovery_plan_details']

    assert accountability['consistency_status'] == 'slipping'
    assert motivation['motivation_state'] == 'slipping'
    assert restart_plan_details
    assert recovery_plan_details
    assert recovery_plan_details['immediate_repair_topic'] == 'Federalism'
    assert 'stop after' in restart_plan_details['first_step'].lower()
    assert restart_plan_details['next_stable_step'] == recovery_plan_details['next_stable_step']
    assert plan['restart_plan_details'] == restart_plan_details
    assert coach['restart_plan_details'] == restart_plan_details

    assert tutor['topic'] == 'Federalism'
    assert tutor['explanation_depth'] == 'foundational'
    assert tutor['teaching_support'] == 'supportive'
    assert tutor['teaching_mode'] == 'step_by_step'
    assert tutor['lesson_mode'] == 'mini_lesson'
    assert tutor['lesson_outline_state'] == 'foundational_recovery'
    assert tutor['structured_teaching_content']['lesson_mode'] == 'mini_lesson'
    assert 'restart path' in tutor['explanation_depth_reason'].lower()

    assert doubt['resolved_topic'] == 'Federalism'
    assert doubt['explanation_depth'] == 'foundational'
    assert doubt['teaching_support'] == 'supportive'
    assert doubt['teaching_mode'] == 'step_by_step'
    assert any(token in doubt['explanation_depth_reason'].lower() for token in {'restart path', 'accountability'})



def test_version13_motivation_subject_scope_stays_clean_across_summary_and_tutor(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=3, subject="polity")
    create_attempt_record(client, topic="Preamble", score=4, subject="polity")
    create_attempt_record(client, topic="Indian National Congress", score=5, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=4, subject="history")
    create_attempt_record(client, topic="Revolt of 1857", score=4, subject="history")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        inc_attempts = db.query(QuizAttempt).filter(QuizAttempt.topic == "Indian National Congress").order_by(QuizAttempt.id.asc()).all()
        revolt_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Revolt of 1857").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None
        assert len(inc_attempts) == 2
        assert revolt_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=8)
        preamble_attempt.created_at = now - timedelta(days=6)
        inc_attempts[0].created_at = now - timedelta(days=2)
        inc_attempts[1].created_at = now - timedelta(days=1)
        revolt_attempt.created_at = now - timedelta(hours=4)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        inc_study = db.query(TopicStudy).filter(TopicStudy.topic == "Indian National Congress").first()
        revolt_study = db.query(TopicStudy).filter(TopicStudy.topic == "Revolt of 1857").first()
        assert federalism_study is not None
        assert preamble_study is not None
        assert inc_study is not None
        assert revolt_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=8)
        preamble_study.last_interaction_at = now - timedelta(days=6)
        inc_study.last_interaction_at = now - timedelta(hours=12)
        revolt_study.last_interaction_at = now - timedelta(hours=4)
        db.commit()
    finally:
        db.close()

    polity_summary_response = client.get('/api/progress/summary?subject=polity')
    history_summary_response = client.get('/api/progress/summary?subject=history')
    history_tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Indian National Congress', 'subject': 'history'},
    )

    assert polity_summary_response.status_code == 200
    assert history_summary_response.status_code == 200
    assert history_tutor_response.status_code == 200

    polity_summary = polity_summary_response.json()
    history_summary = history_summary_response.json()
    history_tutor = history_tutor_response.json()

    assert polity_summary['accountability_summary']['motivation_summary']['motivation_state'] == 'slipping'
    assert history_summary['accountability_summary']['motivation_summary']['motivation_state'] == 'stable'
    assert history_summary['accountability_summary']['restart_plan_details'] is None
    assert history_tutor['topic'] == 'Indian National Congress'
    assert history_tutor['lesson_mode'] == 'lecture_outline'
    assert history_tutor['lesson_outline_state'] == 'steady_learning'
    assert history_tutor['structured_teaching_content']['lesson_mode'] == 'lecture_outline'
    assert 'motivation layer' not in history_tutor['explanation_depth_reason'].lower()
    assert 'overloaded' not in history_tutor['explanation_depth_reason'].lower()
    assert 'restart path' not in history_tutor['explanation_depth_reason'].lower()


def test_version13_confidence_rebuild_guidance_aligns_with_plan_coach_and_tutor(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Federalism", score=1)
    create_attempt_record(client, topic="Federalism", score=2)
    create_attempt_record(client, topic="Federalism", score=2)
    create_attempt_record(client, topic="Preamble", score=4)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempts = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.asc()).all()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        assert len(federalism_attempts) == 4
        assert preamble_attempt is not None

        federalism_attempts[0].created_at = now - timedelta(days=4)
        federalism_attempts[1].created_at = now - timedelta(days=3)
        federalism_attempts[2].created_at = now - timedelta(days=2)
        federalism_attempts[3].created_at = now - timedelta(hours=8)
        preamble_attempt.created_at = now - timedelta(hours=2)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        assert federalism_study is not None
        assert preamble_study is not None

        federalism_study.last_interaction_at = now - timedelta(hours=8)
        preamble_study.last_interaction_at = now - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    summary_response = client.get('/api/progress/summary')
    plan_response = client.get('/api/plan/today')
    coach_response = client.get('/api/coach/summary')
    tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Federalism', 'subject': 'polity'},
    )
    doubt_response = client.post(
        '/api/tutor/doubt',
        json={
            'topic': 'Federalism',
            'question': 'I keep getting Federalism wrong. Help me rebuild confidence on it step by step.',
            'subject': 'polity',
        },
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()
    accountability = summary['accountability_summary']
    motivation = accountability['motivation_summary']
    confidence_guidance = motivation['confidence_rebuild_guidance']
    recovery_plan_details = accountability['recovery_plan_details']

    assert motivation['confidence_state'] == 'rebuilding'
    assert confidence_guidance
    assert confidence_guidance['focus_topic'] == 'Federalism'
    assert summary['recommended_next_topic'] == 'Federalism'
    assert plan['focus_topic'] == 'Federalism'
    assert coach['accountability_summary']['motivation_summary']['confidence_rebuild_guidance'] == confidence_guidance
    if recovery_plan_details:
        assert recovery_plan_details['immediate_repair_topic'] == 'Federalism'

    assert tutor['topic'] == 'Federalism'
    assert tutor['teaching_support'] == 'supportive'
    assert tutor['teaching_mode'] == 'step_by_step'
    assert any(token in tutor['explanation_depth_reason'].lower() for token in {'repair-focused', 'confidence-rebuild', 'accountability'})

    assert doubt['resolved_topic'] == 'Federalism'
    assert doubt['teaching_support'] == 'supportive'
    assert doubt['teaching_mode'] == 'step_by_step'
    assert any(token in doubt['explanation_depth_reason'].lower() for token in {'repair-focused', 'confidence-rebuild', 'accountability'})



def test_version13_strict_mode_keeps_motivation_restart_evidence_stable_while_tutor_stays_aligned(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=3)
    create_attempt_record(client, topic="Preamble", score=4)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        now = datetime.now(UTC)
        federalism_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").order_by(QuizAttempt.id.desc()).first()
        preamble_attempt = db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").order_by(QuizAttempt.id.desc()).first()
        assert federalism_attempt is not None
        assert preamble_attempt is not None

        federalism_attempt.created_at = now - timedelta(days=8)
        preamble_attempt.created_at = now - timedelta(days=6)

        federalism_study = db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").first()
        preamble_study = db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").first()
        assert federalism_study is not None
        assert preamble_study is not None

        federalism_study.last_interaction_at = now - timedelta(days=8)
        preamble_study.last_interaction_at = now - timedelta(days=6)
        db.commit()
    finally:
        db.close()

    normal_summary_response = client.get('/api/progress/summary?mentor_mode=normal')
    strict_summary_response = client.get('/api/progress/summary?mentor_mode=strict')
    normal_plan_response = client.get('/api/plan/today?mentor_mode=normal')
    strict_plan_response = client.get('/api/plan/today?mentor_mode=strict')
    normal_coach_response = client.get('/api/coach/summary?mentor_mode=normal')
    strict_coach_response = client.get('/api/coach/summary?mentor_mode=strict')
    tutor_response = client.post(
        '/api/tutor/explain',
        json={'topic': 'Federalism', 'subject': 'polity'},
    )

    assert normal_summary_response.status_code == 200
    assert strict_summary_response.status_code == 200
    assert normal_plan_response.status_code == 200
    assert strict_plan_response.status_code == 200
    assert normal_coach_response.status_code == 200
    assert strict_coach_response.status_code == 200
    assert tutor_response.status_code == 200

    normal_summary = normal_summary_response.json()
    strict_summary = strict_summary_response.json()
    normal_plan = normal_plan_response.json()
    strict_plan = strict_plan_response.json()
    normal_coach = normal_coach_response.json()
    strict_coach = strict_coach_response.json()
    tutor = tutor_response.json()

    normal_accountability = normal_summary['accountability_summary']
    strict_accountability = strict_summary['accountability_summary']

    assert normal_accountability['mentor_mode'] == 'normal'
    assert strict_accountability['mentor_mode'] == 'strict'
    assert normal_accountability['consistency_status'] == strict_accountability['consistency_status']
    assert normal_accountability['warning_level'] == strict_accountability['warning_level']
    assert normal_accountability['missed_plan_signal'] == strict_accountability['missed_plan_signal']
    assert normal_accountability['missed_revision_signal'] == strict_accountability['missed_revision_signal']
    assert normal_accountability['recovery_plan_details'] == strict_accountability['recovery_plan_details']
    assert normal_accountability['restart_plan_details'] == strict_accountability['restart_plan_details']
    assert normal_accountability['motivation_summary'] == strict_accountability['motivation_summary']
    assert normal_summary['recommended_next_topic'] == strict_summary['recommended_next_topic'] == 'Federalism'
    assert normal_plan['focus_topic'] == strict_plan['focus_topic'] == 'Federalism'
    assert normal_plan['restart_plan_details'] == strict_plan['restart_plan_details'] == normal_accountability['restart_plan_details']
    assert normal_coach['recovery_plan_details'] == strict_coach['recovery_plan_details'] == normal_accountability['recovery_plan_details']
    assert normal_coach['restart_plan_details'] == strict_coach['restart_plan_details'] == normal_accountability['restart_plan_details']
    assert normal_coach['coach_note'] != strict_coach['coach_note']

    assert tutor['topic'] == 'Federalism'
    assert tutor['explanation_depth'] == 'foundational'
    assert tutor['teaching_support'] == 'supportive'
    assert tutor['teaching_mode'] == 'step_by_step'
    assert any(token in tutor['explanation_depth_reason'].lower() for token in {'restart path', 'accountability'})
    assert 'strict' not in tutor['explanation_depth_reason'].lower()

def test_performance_trends_endpoint_returns_trend_payload(client: TestClient) -> None:
    response = client.get("/api/performance/trends")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_trend"] in {"improving", "stable", "declining"}
    assert body["overall_reason"]
    assert isinstance(body["topics"], list)















def test_get_topics_filters_by_selected_subject(client: TestClient) -> None:
    response = client.get("/api/topics?subject=history")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "history"
    assert "Revolt of 1857" in body["topics"]
    assert "Indian National Congress" in body["topics"]
    assert "Fundamental Rights" not in body["topics"]
def test_progress_summary_is_scoped_by_subject(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    answers = get_correct_answers(client, quiz)
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers, "subject": "polity"},
    )
    assert submit_response.status_code == 200

    polity_summary = client.get("/api/progress/summary?subject=polity")
    history_summary = client.get("/api/progress/summary?subject=history")
    assert polity_summary.status_code == 200
    assert history_summary.status_code == 200

    polity_body = polity_summary.json()
    history_body = history_summary.json()

    assert any(item["topic"] == "Fundamental Rights" for item in polity_body["topic_accuracy"])
    assert history_body["topic_accuracy"] == []
    assert history_body["recent_quizzes"] == []


def test_generate_quiz_respects_history_subject_context(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    assert quiz["subject"] == "history"
    assert quiz["topic"] == "Revolt of 1857"
    combined_text = " ".join(
        [
            quiz["topic"],
            *(question["question"] for question in quiz["questions"]),
            *(option for question in quiz["questions"] for option in question["options"]),
        ]
    ).lower()
    assert "article 32" not in combined_text
    assert "fundamental rights" not in combined_text
    assert "rajya sabha" not in combined_text


def test_submit_quiz_persists_results_by_selected_subject(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Indian National Congress", "question_count": 5, "subject": "history"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    answers = get_correct_answers(client, quiz)
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers, "subject": "history"},
    )
    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["subject"] == "history"
    assert result["topic"] == "Indian National Congress"

    history_summary = client.get("/api/progress/summary?subject=history")
    history_history = client.get("/api/progress/history?subject=history")
    polity_summary = client.get("/api/progress/summary?subject=polity")
    polity_history = client.get("/api/progress/history?subject=polity")

    assert history_summary.status_code == 200
    assert history_history.status_code == 200
    assert polity_summary.status_code == 200
    assert polity_history.status_code == 200

    history_summary_body = history_summary.json()
    history_history_body = history_history.json()
    polity_summary_body = polity_summary.json()
    polity_history_body = polity_history.json()

    assert any(item["topic"] == "Indian National Congress" for item in history_summary_body["topic_accuracy"])
    assert any(item["topic"] == "Indian National Congress" for item in history_history_body["history"])
    assert all(item["topic"] != "Indian National Congress" for item in polity_summary_body["topic_accuracy"])
    assert all(item["topic"] != "Indian National Congress" for item in polity_history_body["history"])


def test_submit_quiz_rejects_cross_subject_submission(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    answers = get_correct_answers(client, quiz)
    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": answers, "subject": "history"},
    )
    assert submit_response.status_code == 400
    assert "does not match the quiz subject" in submit_response.json()["detail"]


def test_progress_summary_priority_topics_stay_scoped_to_selected_subject(client: TestClient) -> None:
    polity_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert polity_generate.status_code == 200
    polity_quiz = polity_generate.json()
    polity_answers = get_mixed_answers(client, polity_quiz, {0})
    polity_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": polity_quiz["quiz_id"], "answers": polity_answers, "subject": "polity"},
    )
    assert polity_submit.status_code == 200

    history_generate = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history"},
    )
    assert history_generate.status_code == 200
    history_quiz = history_generate.json()
    history_answers = get_correct_answers(client, history_quiz)
    history_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": history_quiz["quiz_id"], "answers": history_answers, "subject": "history"},
    )
    assert history_submit.status_code == 200

    polity_summary = client.get("/api/progress/summary?subject=polity")
    history_summary = client.get("/api/progress/summary?subject=history")
    assert polity_summary.status_code == 200
    assert history_summary.status_code == 200

    polity_topics = {item["topic"] for item in polity_summary.json()["priority_topics"]}
    history_topics = {item["topic"] for item in history_summary.json()["priority_topics"]}

    assert "Fundamental Rights" in polity_topics
    assert "Revolt of 1857" in history_topics
    assert "Fundamental Rights" not in history_topics
    assert "Revolt of 1857" not in polity_topics


def test_revision_and_coach_endpoints_stay_scoped_to_selected_subject(client: TestClient) -> None:
    polity_generate = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity"},
    )
    assert polity_generate.status_code == 200
    polity_quiz = polity_generate.json()
    polity_answers = get_correct_answers(client, polity_quiz)
    polity_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": polity_quiz["quiz_id"], "answers": polity_answers, "subject": "polity"},
    )
    assert polity_submit.status_code == 200

    history_generate = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history"},
    )
    assert history_generate.status_code == 200
    history_quiz = history_generate.json()
    history_answers = get_mixed_answers(client, history_quiz, {0})
    history_submit = client.post(
        "/api/test/submit",
        json={"quiz_id": history_quiz["quiz_id"], "answers": history_answers, "subject": "history"},
    )
    assert history_submit.status_code == 200

    history_revision = client.get("/api/revision/due?subject=history")
    history_coach = client.get("/api/coach/summary?subject=history")
    assert history_revision.status_code == 200
    assert history_coach.status_code == 200

    revision_body = history_revision.json()
    coach_body = history_coach.json()
    revision_topics = {
        item["topic"]
        for bucket in ("overdue", "due_now", "due_soon")
        for item in revision_body[bucket]
    }

    assert revision_body["subject"] == "history"
    assert coach_body["subject"] == "history"
    assert "Revolt of 1857" in revision_topics
    assert "Fundamental Rights" not in revision_topics
    assert "Fundamental Rights" not in coach_body["weak_areas"]
    assert coach_body["study_today"] != "Fundamental Rights"


def test_coach_warnings_stay_scoped_to_authenticated_user(client: TestClient) -> None:
    weak_user = authenticate_test_user(
        client,
        email="weak-learner@example.com",
        display_name="Weak Learner",
    )
    weak_user_id = weak_user["user"]["id"]
    create_attempt_record(client, topic="Fundamental Rights", score=0, user_id=weak_user_id)
    create_attempt_record(client, topic="Fundamental Rights", score=1, user_id=weak_user_id)

    steady_user = authenticate_test_user(
        client,
        email="steady-learner@example.com",
        display_name="Steady Learner",
    )
    steady_user_id = steady_user["user"]["id"]
    create_attempt_record(client, topic="Parliament", score=5, user_id=steady_user_id)

    coach_response = client.get("/api/coach/summary?subject=polity")
    assert coach_response.status_code == 200
    coach_body = coach_response.json()
    warning_titles = {warning["title"] for warning in coach_body["warnings"]}

    assert coach_body["subject"] == "polity"
    assert "Low scores are repeating" not in warning_titles
    assert "Fundamental Rights" not in json.dumps(coach_body)


def test_get_topics_filters_for_geography_subject(client: TestClient) -> None:
    response = client.get("/api/topics?subject=geography")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "geography"
    assert "Indian Monsoon" in body["topics"]
    assert "Rivers of India" in body["topics"]
    assert "Fundamental Rights" not in body["topics"]


def test_explain_and_quiz_work_for_seeded_geography_subject(client: TestClient) -> None:
    explain_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Indian Monsoon", "subject": "geography"},
    )
    assert explain_response.status_code == 200
    explain_body = explain_response.json()
    assert explain_body["subject"] == "geography"
    assert explain_body["topic"] == "Indian Monsoon"
    assert explain_body["context_status"] == "knowledge_base_context"
    assert explain_body["response_provenance"] == "mock_context_summary"
    assert explain_body["simple_explanation"]

    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Indian Monsoon", "question_count": 5, "subject": "geography"},
    )
    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["subject"] == "geography"
    assert quiz_body["topic"] == "Indian Monsoon"
    assert len(quiz_body["questions"]) == 5

def test_daily_plan_endpoint_exposes_sequence_and_continuation_fields(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Indian Monsoon", "question_count": 5, "subject": "geography"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submitted_answers = []
    for index, (question, private_question) in enumerate(zip(quiz["questions"], get_aligned_private_quiz_questions(client, quiz), strict=False)):
        selected_answer = private_question["correct_answer"] if index < 3 else next(
            option for option in question["options"] if option != private_question["correct_answer"]
        )
        submitted_answers.append({"question_id": question["question_id"], "selected_answer": selected_answer})

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": submitted_answers, "subject": "geography"},
    )
    assert submit_response.status_code == 200

    response = client.get("/api/plan/today?subject=geography")
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "geography"
    assert body["plan_mode"] in {"revision", "continuation", "sequence", "foundation"}
    assert "continuation_topic" in body
    assert "next_best_topic" in body




def test_subject_guidance_endpoints_ignore_invalid_persisted_topics(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        quiz = Quiz(
            topic="string",
            chapter="General",
            subject="polity",
            difficulty="easy",
            question_count=5,
            questions_json="[]",
        )
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
        db.add(
            QuizAttempt(
                quiz_id=quiz.id,
                topic="string",
                chapter="General",
                subject="polity",
                difficulty="easy",
                submitted_answers_json="[]",
                score=0,
                total_questions=5,
                accuracy=0.0,
                incorrect_questions_json="[]",
                weak_areas_json='["string"]',
                next_recommendation="Review the topic once and try another quiz.",
            )
        )
        db.add(
            TopicStudy(
                topic="string",
                chapter="General",
                subject="polity",
                study_count=1,
            )
        )
        db.commit()
    finally:
        db.close()

    summary_response = client.get("/api/progress/summary?subject=polity")
    plan_response = client.get("/api/plan/today?subject=polity")
    coach_response = client.get("/api/coach/summary?subject=polity")

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200

    summary_body = summary_response.json()
    plan_body = plan_response.json()
    coach_body = coach_response.json()

    assert summary_body["recent_quizzes"] == []
    assert "string" not in summary_body["recent_weak_areas"]
    assert all(item["topic"] != "string" for item in summary_body["revision_recommendations"])
    assert all(item["topic"] != "string" for item in summary_body["priority_topics"])
    assert all(item["topic"] != "string" for item in summary_body["ranked_weak_topics"])
    assert summary_body["recommended_next_topic"] != "string"
    assert plan_body["focus_topic"] != "string"
    assert coach_body["study_today"] != "string"










def test_progress_summary_api_exposes_mastery_overview_and_topic_signals(client: TestClient) -> None:
    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity", "quiz_mode": "practice"},
    )
    assert generate_response.status_code == 200
    quiz = generate_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={"quiz_id": quiz["quiz_id"], "answers": get_mixed_answers(client, quiz, {0, 2}), "subject": "polity"},
    )
    assert submit_response.status_code == 200

    summary_response = client.get("/api/progress/summary?subject=polity")
    assert summary_response.status_code == 200
    body = summary_response.json()

    assert "mastery_overview" in body
    assert body["mastery_overview"]["overall_mastery_score"] >= 0
    assert body["mastery_overview"]["overall_confidence_score"] >= 0
    assert body["mastery_overview"]["overall_stability_score"] >= 0
    assert "study_profile" in body
    assert body["study_profile"]["profile_title"]
    assert body["study_profile"]["profile_summary"]
    assert body["study_profile"]["readiness_status"] in {"building", "steady", "ready", "revision_first"}
    assert body["study_profile"]["trend_direction"] in {"improving", "stable", "declining"}
    assert body["study_profile"]["revision_pressure"] in {"light", "building", "heavy"}

    item = next(item for item in body["topic_accuracy"] if item["topic"] == "Fundamental Rights")
    assert "study_count" in item
    assert "mastery_score" in item
    assert "confidence_score" in item
    assert "stability_score" in item
    assert item["strength_classification"] in {"fragile", "developing", "stable", "strong"}
    assert item["long_term_trend"] in {"improving", "stable", "declining"}
    assert item["revision_readiness"] in {"not_ready", "building", "ready", "needs_refresh"}


def test_progress_summary_api_exposes_topic_strength_classification(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=5)
    create_attempt_record(client, topic="Preamble", score=4)
    create_attempt_record(client, topic="Parliament", score=3)
    create_attempt_record(client, topic="Federalism", score=1)

    summary_response = client.get("/api/progress/summary?subject=polity")
    assert summary_response.status_code == 200
    body = summary_response.json()

    topic_strengths = {item["topic"]: item["topic_strength"] for item in body["topic_accuracy"]}
    assert topic_strengths["Preamble"] == "strong"
    assert topic_strengths["Parliament"] == "medium"
    assert topic_strengths["Federalism"] == "weak"
    assert "Preamble" in body["strong_topics"]
    assert "Parliament" in body["medium_topics"]
    assert "Federalism" in body["weak_topics"]


def test_progress_summary_api_exposes_revision_signal_and_retention_risk(client: TestClient) -> None:
    create_attempt_record(client, topic="Preamble", score=5)
    create_attempt_record(client, topic="Preamble", score=5)
    create_attempt_record(client, topic="Federalism", score=1)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        db.query(QuizAttempt).filter(QuizAttempt.topic == "Preamble").update({QuizAttempt.created_at: datetime.now(UTC) - timedelta(days=8)})
        db.query(QuizAttempt).filter(QuizAttempt.topic == "Federalism").update({QuizAttempt.created_at: datetime.now(UTC) - timedelta(days=2)})
        db.query(TopicStudy).filter(TopicStudy.topic == "Preamble").update({TopicStudy.last_interaction_at: datetime.now(UTC) - timedelta(days=8)})
        db.query(TopicStudy).filter(TopicStudy.topic == "Federalism").update({TopicStudy.last_interaction_at: datetime.now(UTC) - timedelta(days=2)})
        db.commit()
    finally:
        db.close()

    summary_response = client.get("/api/progress/summary?subject=polity")
    assert summary_response.status_code == 200
    body = summary_response.json()

    topic_items = {item["topic"]: item for item in body["topic_accuracy"]}
    assert topic_items["Preamble"]["revision_signal"] in {"due_now", "at_risk"}
    assert topic_items["Preamble"]["retention_risk"] in {"moderate", "high"}
    assert topic_items["Federalism"]["retention_risk"] == "high"
    assert "at_risk_topics" in body
    assert "due_now_topics" in body



def test_performance_trends_api_exposes_subject_health_signals(client: TestClient) -> None:
    create_attempt_record(client, topic="Parliament", score=5)
    create_attempt_record(client, topic="Parliament", score=3)
    create_attempt_record(client, topic="Federalism", score=1)

    response = client.get("/api/performance/trends?subject=polity")
    assert response.status_code == 200
    body = response.json()

    assert body["trend_stability"] in {"thin_history", "emerging", "established"}
    assert body["revision_pressure"] in {"light", "building", "heavy"}
    assert isinstance(body["accuracy_delta"], (int, float))
    assert isinstance(body["improving_topic_count"], int)
    assert isinstance(body["declining_topic_count"], int)
    assert isinstance(body["at_risk_topic_count"], int)
    assert isinstance(body["due_now_topic_count"], int)
    assert isinstance(body["topics"], list)
    if body["topics"]:
        first_topic = body["topics"][0]
        assert first_topic["trend_stability"] in {"thin_history", "emerging", "established"}
        assert isinstance(first_topic["accuracy_delta"], (int, float))
        assert first_topic["topic_strength"] in {"strong", "medium", "weak"}
        assert first_topic["revision_signal"] in {"stable", "due_soon", "due_now", "at_risk"}
        assert first_topic["retention_risk"] in {"low", "moderate", "high"}


def test_version9_recovery_signals_stay_aligned_across_quiz_tutor_and_guidance(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")

    summary_response = client.get("/api/progress/summary?subject=polity")
    plan_response = client.get("/api/plan/today?subject=polity")
    coach_response = client.get("/api/coach/summary?subject=polity")
    tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism", "subject": "polity"},
    )
    quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Federalism", "question_count": 5, "subject": "polity", "quiz_mode": "revision"},
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert tutor_response.status_code == 200
    assert quiz_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    tutor = tutor_response.json()
    quiz = quiz_response.json()

    assert summary["subject"] == "polity"
    assert summary["recommended_next_topic"] == "Federalism"
    assert summary["recommended_mode"] == "revise"
    assert summary["recommended_difficulty_band"] == "easy"
    assert summary["recommended_adaptive_state"] == "recovery"
    assert summary["recommended_explanation_depth"] == "foundational"

    assert plan["subject"] == "polity"
    assert plan["focus_topic"] == "Federalism"
    assert plan["recommended_mode"] == "revise"
    assert plan["recommended_difficulty_band"] == "easy"
    assert plan["recommended_adaptive_state"] == "recovery"
    assert plan["recommended_explanation_depth"] == "foundational"

    assert coach["subject"] == "polity"
    assert coach["study_today"] == "Federalism"
    assert coach["recommended_mode"] == "revise"
    assert coach["recommended_difficulty_band"] == "easy"
    assert coach["recommended_adaptive_state"] == "recovery"
    assert coach["recommended_explanation_depth"] == "foundational"

    assert tutor["subject"] == "polity"
    assert tutor["topic"] == "Federalism"
    assert tutor["explanation_depth"] == "foundational"
    assert "foundational explanation" in tutor["explanation_depth_reason"].lower()

    assert quiz["subject"] == "polity"
    assert quiz["topic"] == "Federalism"
    assert quiz["quiz_mode"] == "revision"
    assert quiz["difficulty"] == "easy"
    assert quiz["adaptive_state"] == "recovery"
    assert all("correct_answer" not in question for question in quiz["questions"])
    assert all("explanation" not in question for question in quiz["questions"])



def test_version9_adaptive_tutor_and_quiz_stay_subject_scoped(client: TestClient) -> None:
    for _ in range(3):
        create_attempt_record(client, topic="Fundamental Rights", score=5, subject="polity")
        create_attempt_record(client, topic="Preamble", score=5, subject="polity")

    create_attempt_record(client, topic="Revolt of 1857", score=1, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=1, subject="history")

    polity_summary_response = client.get("/api/progress/summary?subject=polity")
    history_summary_response = client.get("/api/progress/summary?subject=history")
    polity_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Fundamental Rights", "subject": "polity"},
    )
    history_tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Revolt of 1857", "subject": "history"},
    )
    polity_quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Fundamental Rights", "question_count": 5, "subject": "polity", "quiz_mode": "test"},
    )
    history_quiz_response = client.post(
        "/api/test/generate",
        json={"topic": "Revolt of 1857", "question_count": 5, "subject": "history", "quiz_mode": "test"},
    )

    assert polity_summary_response.status_code == 200
    assert history_summary_response.status_code == 200
    assert polity_tutor_response.status_code == 200
    assert history_tutor_response.status_code == 200
    assert polity_quiz_response.status_code == 200
    assert history_quiz_response.status_code == 200

    polity_summary = polity_summary_response.json()
    history_summary = history_summary_response.json()
    polity_tutor = polity_tutor_response.json()
    history_tutor = history_tutor_response.json()
    polity_quiz = polity_quiz_response.json()
    history_quiz = history_quiz_response.json()

    assert polity_summary["subject"] == "polity"
    assert polity_summary["subject_adaptive_state"] in {"steady", "challenge"}
    assert history_summary["subject"] == "history"
    assert history_summary["subject_adaptive_state"] == "recovery"

    assert polity_tutor["subject"] == "polity"
    assert polity_tutor["topic"] == "Fundamental Rights"
    assert polity_tutor["explanation_depth"] == "advanced"

    assert history_tutor["subject"] == "history"
    assert history_tutor["topic"] == "Revolt of 1857"
    assert history_tutor["explanation_depth"] == "foundational"

    assert polity_quiz["subject"] == "polity"
    assert polity_quiz["topic"] == "Fundamental Rights"
    assert polity_quiz["adaptive_state"] in {"steady", "challenge"}
    assert polity_quiz["difficulty"] in {"medium", "hard"}

    assert history_quiz["subject"] == "history"
    assert history_quiz["topic"] == "Revolt of 1857"
    assert history_quiz["adaptive_state"] == "recovery"
    assert history_quiz["difficulty"] == "easy"





def test_version10_doubt_flow_stays_aligned_with_recovery_guidance(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")

    question = "Can you explain federalism step by step and show how it differs from a unitary system?"
    summary_response = client.get("/api/progress/summary?subject=polity")
    plan_response = client.get("/api/plan/today?subject=polity")
    coach_response = client.get("/api/coach/summary?subject=polity")
    tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism", "subject": "polity"},
    )
    doubt_response = client.post(
        "/api/tutor/doubt",
        json={"topic": "Federalism", "question": question, "subject": "polity"},
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()

    assert summary["recommended_next_topic"] == "Federalism"
    assert summary["recommended_adaptive_state"] == "recovery"
    assert summary["recommended_explanation_depth"] == "foundational"

    assert plan["focus_topic"] == "Federalism"
    assert plan["recommended_adaptive_state"] == "recovery"
    assert plan["recommended_explanation_depth"] == "foundational"

    assert coach["study_today"] == "Federalism"
    assert coach["recommended_adaptive_state"] == "recovery"
    assert coach["recommended_explanation_depth"] == "foundational"

    assert tutor["topic"] == "Federalism"
    assert tutor["explanation_depth"] == "foundational"
    assert tutor["teaching_mode"] == "step_by_step"

    assert doubt["subject"] == "polity"
    assert doubt["selected_topic"] == "Federalism"
    assert doubt["resolved_topic"] == "Federalism"
    assert doubt["user_doubt"] == question
    assert doubt["context_status"] == "knowledge_base_context"
    assert doubt["explanation_depth"] == "foundational"
    assert doubt["teaching_support"] == "supportive"
    assert doubt["teaching_mode"] == "step_by_step"


def test_version10_doubt_flow_stays_subject_scoped_under_mixed_states(client: TestClient) -> None:
    for _ in range(3):
        create_attempt_record(client, topic="Fundamental Rights", score=5, subject="polity")
        create_attempt_record(client, topic="Preamble", score=5, subject="polity")

    create_attempt_record(client, topic="Revolt of 1857", score=1, subject="history")
    create_attempt_record(client, topic="Indian National Congress", score=1, subject="history")

    polity_doubt_response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Fundamental Rights",
            "question": "How would UPSC test Fundamental Rights in an exam question?",
            "subject": "polity",
        },
    )
    history_doubt_response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Revolt of 1857",
            "question": "Can you explain the Revolt of 1857 more simply?",
            "subject": "history",
        },
    )

    assert polity_doubt_response.status_code == 200
    assert history_doubt_response.status_code == 200

    polity_doubt = polity_doubt_response.json()
    history_doubt = history_doubt_response.json()

    assert polity_doubt["subject"] == "polity"
    assert polity_doubt["resolved_topic"] == "Fundamental Rights"
    assert polity_doubt["explanation_depth"] == "advanced"
    assert polity_doubt["teaching_support"] == "stretch"
    assert polity_doubt["teaching_mode"] == "exam_focused"

    assert history_doubt["subject"] == "history"
    assert history_doubt["resolved_topic"] == "Revolt of 1857"
    assert history_doubt["explanation_depth"] == "foundational"
    assert history_doubt["teaching_support"] == "supportive"
    assert history_doubt["teaching_mode"] == "step_by_step"


def test_version11_repair_focused_revision_keeps_tutor_supportive_after_recent_wrong_answers(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=4, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")

    summary_response = client.get("/api/progress/summary?subject=polity")
    tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism", "subject": "polity"},
    )
    doubt_response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Federalism",
            "question": "Can you explain federalism step by step and fix the confusion from my recent mistakes?",
            "subject": "polity",
        },
    )

    assert summary_response.status_code == 200
    assert tutor_response.status_code == 200
    assert doubt_response.status_code == 200

    summary = summary_response.json()
    tutor = tutor_response.json()
    doubt = doubt_response.json()
    federalism_revision = next(item for item in summary["revision_recommendations"] if item["topic"] == "Federalism")

    assert federalism_revision["wrong_answer_signal"] == "repeated_errors"
    assert federalism_revision["revision_intensity"] == "intensive"
    assert federalism_revision["reinforcement_state"] in {"reinforce_now", "overdue_reinforcement"}

    assert tutor["topic"] == "Federalism"
    assert tutor["explanation_depth"] == "foundational"
    assert tutor["teaching_support"] == "supportive"
    assert tutor["teaching_mode"] == "step_by_step"
    assert "repair-focused" in tutor["explanation_depth_reason"].lower()
    assert "repair-focused" in tutor["teaching_mode_reason"].lower()

    assert doubt["resolved_topic"] == "Federalism"
    assert doubt["explanation_depth"] == "foundational"
    assert doubt["teaching_support"] == "supportive"
    assert doubt["teaching_mode"] == "step_by_step"
    assert "repair-focused" in doubt["explanation_depth_reason"].lower()
    assert "repair-focused" in doubt["teaching_mode_reason"].lower()



def test_version11_short_revision_stays_aligned_with_repair_focused_guidance(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=4, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Preamble", score=5, subject="polity")
    create_attempt_record(client, topic="Preamble", score=5, subject="polity")

    summary_response = client.get("/api/progress/summary?subject=polity")
    plan_response = client.get("/api/plan/today?subject=polity")
    coach_response = client.get("/api/coach/summary?subject=polity")
    quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Preamble",
            "question_count": 5,
            "subject": "polity",
            "quiz_mode": "revision",
            "revision_session_mode": "short_revision",
        },
    )
    tutor_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Federalism", "subject": "polity"},
    )

    assert summary_response.status_code == 200
    assert plan_response.status_code == 200
    assert coach_response.status_code == 200
    assert quiz_response.status_code == 200
    assert tutor_response.status_code == 200

    summary = summary_response.json()
    plan = plan_response.json()
    coach = coach_response.json()
    quiz = quiz_response.json()
    tutor = tutor_response.json()

    federalism_topic = next(item for item in summary["topic_accuracy"] if item["topic"] == "Federalism")
    federalism_revision = next(item for item in summary["revision_recommendations"] if item["topic"] == "Federalism")

    assert federalism_topic["wrong_answer_signal"] == "repeated_errors"
    assert federalism_revision["revision_intensity"] == "intensive"
    assert federalism_revision["reinforcement_state"] in {"reinforce_now", "overdue_reinforcement"}
    assert "repair-focused" in federalism_revision["reason"].lower()

    assert summary["recommended_next_topic"] == "Federalism"
    assert summary["recommended_mode"] == "revise"
    assert summary["recommended_adaptive_state"] == "recovery"
    assert summary["recommended_explanation_depth"] == "foundational"

    assert plan["focus_topic"] == "Federalism"
    assert plan["recommended_mode"] == "revise"
    assert plan["recommended_adaptive_state"] == "recovery"
    assert plan["recommended_explanation_depth"] == "foundational"

    assert coach["study_today"] == "Federalism"
    assert coach["recommended_mode"] == "revise"
    assert coach["recommended_adaptive_state"] == "recovery"
    assert coach["recommended_explanation_depth"] == "foundational"
    assert coach["revise_now"] == "Federalism"
    assert "repair-focused" in coach["revise_reason"].lower()

    assert quiz["subject"] == "polity"
    assert quiz["topic"] == "Federalism"
    assert quiz["quiz_mode"] == "revision"
    assert quiz["revision_session_mode"] == "short_revision"
    assert quiz["adaptive_state"] == "recovery"
    assert quiz["difficulty"] == "easy"
    assert quiz["revision_targets"]
    assert quiz["revision_targets"][0] == "Federalism"
    assert "short revision session" in quiz["revision_session_note"].lower()
    assert all("correct_answer" not in question for question in quiz["questions"])
    assert all("explanation" not in question for question in quiz["questions"])

    assert tutor["topic"] == "Federalism"
    assert tutor["explanation_depth"] == "foundational"
    assert tutor["teaching_support"] == "supportive"
    assert tutor["teaching_mode"] == "step_by_step"
    assert tutor["lesson_mode"] == "revision_lesson"
    assert tutor["lesson_outline_state"] == "revision_reinforcement"
    assert tutor["structured_teaching_content"]["lesson_mode"] == "revision_lesson"
    assert "recommendation engine" in tutor["lesson_mode_reason"].lower()
    assert "repair-focused" in tutor["explanation_depth_reason"].lower()



def test_version11_short_revision_stays_subject_scoped_under_mixed_revision_pressure(client: TestClient) -> None:
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Federalism", score=1, subject="polity")
    create_attempt_record(client, topic="Revolt of 1857", score=1, subject="history")
    create_attempt_record(client, topic="Revolt of 1857", score=1, subject="history")

    polity_summary_response = client.get("/api/progress/summary?subject=polity")
    history_summary_response = client.get("/api/progress/summary?subject=history")
    polity_quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Preamble",
            "question_count": 5,
            "subject": "polity",
            "quiz_mode": "revision",
            "revision_session_mode": "short_revision",
        },
    )
    history_quiz_response = client.post(
        "/api/test/generate",
        json={
            "topic": "Indian National Congress",
            "question_count": 5,
            "subject": "history",
            "quiz_mode": "revision",
            "revision_session_mode": "short_revision",
        },
    )

    assert polity_summary_response.status_code == 200
    assert history_summary_response.status_code == 200
    assert polity_quiz_response.status_code == 200
    assert history_quiz_response.status_code == 200

    polity_summary = polity_summary_response.json()
    history_summary = history_summary_response.json()
    polity_quiz = polity_quiz_response.json()
    history_quiz = history_quiz_response.json()

    assert polity_summary["subject"] == "polity"
    assert history_summary["subject"] == "history"
    assert polity_summary["recent_error_topics"] == ["Federalism"]
    assert history_summary["recent_error_topics"] == ["Revolt of 1857"]

    assert polity_quiz["subject"] == "polity"
    assert polity_quiz["topic"] == "Federalism"
    assert polity_quiz["revision_session_mode"] == "short_revision"
    assert "Revolt of 1857" not in polity_quiz["revision_targets"]

    assert history_quiz["subject"] == "history"
    assert history_quiz["topic"] == "Revolt of 1857"
    assert history_quiz["revision_session_mode"] == "short_revision"
    assert "Federalism" not in history_quiz["revision_targets"]


@pytest.mark.parametrize(
        ("lesson_mode", "reason_token", "expected_outline_state"),
        [
            ("video_lecture", "video lecture", None),
            ("revision_video", "revision video", "revision_reinforcement"),
            ("crash_course_video", "crash-course video", None),
        ],
)
def test_phase23_video_lesson_modes_emit_media_ready_scripts(
    client: TestClient,
    lesson_mode: str,
    reason_token: str,
    expected_outline_state: str | None,
) -> None:
    authenticate_premium_test_user(
        client,
        email=f"phase23-{lesson_mode.replace('_', '-')}@example.com",
    )

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exam"] == "upsc"
    assert body["subject"] == "polity"
    assert body["lesson_mode"] == lesson_mode
    assert body["lesson_script_type"] == lesson_mode
    if expected_outline_state is not None:
        assert body["lesson_outline_state"] == expected_outline_state
    else:
        assert body["lesson_outline_state"] in {"foundational_recovery", "steady_learning", "exam_consolidation"}
    assert reason_token in body["lesson_mode_reason"].lower()
    assert body["structured_teaching_content"]["lesson_mode"] == lesson_mode
    assert body["lecture_structure"]["lesson_mode"] == lesson_mode
    assert body["lecture_structure"]["topic"] == body["topic"]
    assert body["lecture_structure"]["intro"]["hook"]
    assert body["lecture_structure"]["intro"]["learner_goal"]
    assert len(body["lecture_structure"]["body"]) >= 4
    assert all(section["narration"] for section in body["lecture_structure"]["body"])
    assert all(section["emphasis_cue"] for section in body["lecture_structure"]["body"])
    assert all(section["duration_hint"] for section in body["lecture_structure"]["body"])
    assert all(section["visual_or_activity_cue"] for section in body["lecture_structure"]["body"])
    assert all(section["visual_cue_suggestion"]["slide_title_suggestion"] for section in body["lecture_structure"]["body"])
    assert all(section["visual_cue_suggestion"]["key_bullet_suggestions"] for section in body["lecture_structure"]["body"])
    assert body["lecture_structure"]["recap"]["key_takeaways"]
    assert body["lecture_structure"]["recap"]["final_memory_hook"]
    assert body["lecture_structure"]["recap"]["next_step_prompt"]
    assert len(body["narration_segments"]) == len(body["lecture_structure"]["body"])
    assert all(segment["narration_block"] for segment in body["narration_segments"])
    assert all(segment["emphasis_cue"] for segment in body["narration_segments"])
    assert all(segment["duration_hint"] for segment in body["narration_segments"])
    assert all(segment["visual_cue_suggestion"]["slide_title_suggestion"] for segment in body["narration_segments"])
    assert body["visual_cue_suggestions"]
    assert all(cue["topic"] == body["topic"] for cue in body["visual_cue_suggestions"])
    assert all(cue["exam"] == "upsc" for cue in body["visual_cue_suggestions"])
    assert all(cue["key_bullet_suggestions"] for cue in body["visual_cue_suggestions"])
    assert "Instructional Arc" in body["export_ready_lesson"]
    assert "Narration Segments" in body["export_ready_lesson"]
    assert "Visual Cue Suggestions" in body["export_ready_lesson"]
    assert "Media Ready Content Structure" in body["export_ready_lesson"]
    media_ready = body["media_ready_content"]
    assert media_ready["format_version"] == "phase23_media_ready_v1"
    assert media_ready["subject"] == "polity"
    assert media_ready["exam"] == "upsc"
    assert media_ready["topic"] == body["topic"]
    assert media_ready["lesson_mode"] == lesson_mode
    assert media_ready["content_kind"] == "video_media_script"
    assert len(media_ready["lecture_sections"]) == len(body["lecture_structure"]["body"])
    assert len(media_ready["scenes"]) == len(body["video_lesson_script"]["scenes"]) if body["video_lesson_script"] else True
    assert len(media_ready["narration_segments"]) == len(body["narration_segments"])
    assert media_ready["visual_cue_suggestions"]
    assert media_ready["recap_block"]["key_takeaways"]
    assert media_ready["recap_block"]["remember_points"]
    assert media_ready["remember_points"]
    assert media_ready["export_notes"]
    if lesson_mode == "revision_video":
        assert "corrective" in body["lecture_structure"]["intro"]["tone"]
    if lesson_mode == "crash_course_video":
        assert body["lesson_outline_state"] in {"exam_consolidation", "foundational_recovery"}
        if body["lesson_outline_state"] == "exam_consolidation":
            assert "exam-facing" in body["lecture_structure"]["intro"]["tone"]
        else:
            assert "supportive" in body["lecture_structure"]["intro"]["tone"]

    video_script = body["video_lesson_script"]
    assert video_script["video_mode"] == lesson_mode
    assert video_script["topic"] == body["topic"]
    assert video_script["subject"] == "polity"
    assert video_script["exam"] == "upsc"
    assert video_script["mode_focus"]
    assert video_script["mode_specialization_note"]
    assert video_script["quick_recall_prompts"]
    assert video_script["must_remember_points"]
    assert video_script["intro_hook"]
    assert len(video_script["scenes"]) >= 4
    assert all(scene["narration"] for scene in video_script["scenes"])
    assert all(scene["emphasis_cue"] for scene in video_script["scenes"])
    assert all(scene["duration_hint"] for scene in video_script["scenes"])
    assert all(scene["visual_cue"] for scene in video_script["scenes"])
    assert all(scene["visual_cue_suggestion"]["slide_title_suggestion"] for scene in video_script["scenes"])
    assert all(scene["visual_cue_suggestion"]["emphasis_highlight_note"] for scene in video_script["scenes"])
    assert len(body["visual_cue_suggestions"]) == len(video_script["scenes"])
    assert video_script["recap"]
    assert body["export_ready_video_script"]
    assert "Key visual bullets" in body["export_ready_video_script"]
    assert "Mode focus:" in body["export_ready_video_script"]

    if lesson_mode == "video_lecture":
        assert "Balanced video lecture" in video_script["mode_focus"]
        assert "Instructional build" not in video_script["mode_focus"]
        assert body["revision_lesson_content"] is None
        assert body["crash_course_content"] is None
    if lesson_mode == "revision_video":
        assert "Revision repair video" in video_script["mode_focus"]
        assert video_script["key_corrections"]
        assert body["revision_lesson_content"] is not None
        assert "recall" in " ".join(video_script["quick_recall_prompts"]).lower()
        assert any("Revision pass" in scene["narration"] or "Quick recall" in scene["narration"] or "Correction pass" in scene["narration"] for scene in video_script["scenes"])
        assert "repair" in body["revision_lesson_content"]["weak_due_topic_reminder"].lower() or "reinforcement" in body["revision_lesson_content"]["weak_due_topic_reminder"].lower()
    if lesson_mode == "crash_course_video":
        assert "Crash-course video" in video_script["mode_focus"]
        assert video_script["exam_angle_focus"]
        assert body["crash_course_content"] is not None
        assert "high-yield" in " ".join(video_script["must_remember_points"] + [video_script["mode_focus"]]).lower()
        assert all("High-yield compression" in scene["narration"] for scene in video_script["scenes"])
        assert "exam" in body["crash_course_content"]["concise_topic_framing"].lower() or "exam" in body["crash_course_content"]["likely_asked_angle"].lower()


def test_phase23_crash_course_video_stays_supportive_for_recovery_topic(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase23-crash-recovery@example.com")
    user_id = auth["user"]["id"]
    create_attempt_record(client, topic="Directive Principles", score=1, total_questions=5, user_id=user_id)
    create_attempt_record(client, topic="Directive Principles", score=2, total_questions=5, user_id=user_id)

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Directive Principles", "subject": "polity", "exam": "upsc", "lesson_mode": "crash_course_video"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lesson_mode"] == "crash_course_video"
    assert body["lesson_outline_state"] == "revision_reinforcement"
    assert body["explanation_depth"] == "foundational"
    assert body["teaching_support"] == "supportive"
    assert body["video_lesson_script"]["video_mode"] == "crash_course_video"
    assert "Crash-course video" in body["video_lesson_script"]["mode_focus"]
    assert "teaching_support=supportive" in body["video_lesson_script"]["mode_specialization_note"]
    assert body["lecture_structure"]["intro"]["tone"] == "compact, corrective, and reassuring"
    assert body["media_ready_content"]["lesson_outline_state"] == "revision_reinforcement"
    assert any("tutor-loop lesson state" in note for note in body["media_ready_content"]["export_notes"])
    assert any("recall repair" in scene["emphasis_cue"].lower() for scene in body["video_lesson_script"]["scenes"])


@pytest.mark.parametrize("lesson_mode", ["lecture_outline", "mini_lesson", "revision_lesson", "crash_course"])
def test_phase23_existing_lesson_modes_keep_instructional_arc_without_video_script(
    client: TestClient,
    lesson_mode: str,
) -> None:
    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lesson_mode"] == lesson_mode
    assert body["video_lesson_script"] is None
    assert body["export_ready_video_script"] == ""
    assert body["lecture_structure"]["lesson_mode"] == lesson_mode
    assert body["lecture_structure"]["intro"]["hook"]
    assert body["lecture_structure"]["body"]
    assert body["narration_segments"]
    assert len(body["narration_segments"]) == len(body["lecture_structure"]["body"])
    assert body["visual_cue_suggestions"]
    assert all(cue["slide_title_suggestion"] for cue in body["visual_cue_suggestions"])
    assert all(cue["key_bullet_suggestions"] for cue in body["visual_cue_suggestions"])
    assert body["media_ready_content"]["content_kind"] == "lesson_media_structure"
    assert body["media_ready_content"]["lesson_mode"] == lesson_mode
    assert len(body["media_ready_content"]["lecture_sections"]) == len(body["lecture_structure"]["body"])
    assert len(body["media_ready_content"]["scenes"]) == len(body["narration_segments"])
    assert body["media_ready_content"]["recap_block"]["final_memory_hook"]
    assert body["media_ready_content"]["remember_points"]
    assert "Media Ready Content Structure" in body["export_ready_lesson"]
    assert body["lecture_structure"]["recap"]["key_takeaways"]


@pytest.mark.parametrize(
    "export_format",
    ["json_export", "markdown_export", "text_export", "slide_outline_export", "audio_script_export"],
)
def test_phase24_lesson_export_route_returns_downloadable_assets(client: TestClient, export_format: str) -> None:
    authenticate_premium_test_user(
        client,
        email=f"phase24-export-{export_format.replace('_', '-')}@example.com",
    )

    expected_extensions = {
        "json_export": ".json",
        "markdown_export": ".md",
        "text_export": ".txt",
        "slide_outline_export": ".slides.md",
        "audio_script_export": ".audio-script.json",
    }
    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "export_format": export_format,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-adhyantra-export-format"] == export_format
    assert response.headers["x-adhyantra-export-version"] == "phase24_lesson_export_v1"
    assert response.headers["x-adhyantra-export-generated-at"]
    assert "attachment" in response.headers["content-disposition"]
    filename = response.headers["x-adhyantra-export-filename"]
    assert filename.startswith("adhyantra-upsc-polity-preamble-video-lecture-")
    assert filename.endswith(expected_extensions[export_format])
    assert re.match(r"^adhyantra-upsc-polity-preamble-video-lecture-\d{8}t\d{6}z\.", filename)
    assert f'filename="{filename}"' in response.headers["content-disposition"]

    if export_format == "json_export":
        body = response.json()
        assert body["metadata"]["export_version"] == "phase24_lesson_export_v1"
        assert body["metadata"]["export_target"] == "json_export"
        assert body["metadata"]["requested_format"] == "json_export"
        assert body["metadata"]["product"] == "Adhyantra"
        assert body["metadata"]["filename"] == filename
        assert body["metadata"]["filename_base"].startswith("adhyantra-upsc-polity-preamble-video-lecture-")
        assert re.match(r"^\d{8}t\d{6}z$", body["metadata"]["filename_timestamp"])
        assert body["metadata"]["rendering_status"] == "structured_export_only"
        assert body["metadata"]["topic"] == body["lesson"]["topic"]
        assert body["content_context"]["topic"] == "Preamble"
        assert body["content_context"]["subject"] == "polity"
        assert body["content_context"]["exam"] == "upsc"
        assert body["lesson_state"]["lesson_mode"] == "video_lecture"
        assert body["lesson_state"]["teaching_mode"]
        assert body["tutor_loop_context"]["mode_alignment"]
        assert "video_lecture" in body["tutor_loop_context"]["mode_alignment"]
        assert "upsc" in body["tutor_loop_context"]["exam_alignment"]
        assert body["tutor_loop_context"]["adaptive_alignment"]
        assert body["tutor_loop_context"]["accountability_alignment"]
        assert body["tutor_loop_context"]["motivation_alignment"]
        assert "does not contain rendered audio, slides, or video" in body["tutor_loop_context"]["honesty_alignment"]
        assert body["tutor_loop_context"]["lesson_mode_reason"]
        assert body["media_ready"]["format_version"] == "phase23_media_ready_v1"
        assert body["media_ready"]["content_kind"] == "video_media_script"
        assert body["media_ready"]["scenes"]
        assert body["media_ready"]["lecture_sections"]
        assert body["media_ready"]["narration_segments"]
        assert body["media_ready"]["visual_cue_suggestions"]
        assert body["media_ready"]["remember_points"]
        assert body["media_ready"]["video_lesson_script"]["video_mode"] == "video_lecture"
        assert body["lesson"]["media_ready_content"]["format_version"] == "phase23_media_ready_v1"
        assert body["lesson"]["video_lesson_script"]["video_mode"] == "video_lecture"
    elif export_format == "audio_script_export":
        body = response.json()
        assert body["metadata"]["export_target"] == "audio_script_export"
        assert body["metadata"]["rendering_status"] == "audio_script_ready_package_only"
        assert body["script_notes"]
        assert body["segments"]
        assert all(segment["narration_text"] for segment in body["segments"])
        assert all(segment["pause_after"] for segment in body["segments"])
        assert all(segment["transition_cue"] for segment in body["segments"])
        assert body["segments"][0]["transition_cue"].startswith("Open with")
        assert "visual_reference" in body["segments"][0]
        assert any("Tutor-loop alignment" in note for note in body["script_notes"])
        assert body["voice_guidance"]["lesson_mode"] == "video_lecture"
        assert body["voice_guidance"]["adaptive_shape"]
        assert body["rendering_outputs"]["rendered_audio_available"] is False
        assert body["rendering_outputs"]["audio_url"] is None
    else:
        text = response.text
        assert "Adhyantra" in text
        assert "Preamble" in text
        assert "does not contain rendered audio, slides, or video" in text
        if export_format == "slide_outline_export":
            assert "Slide Outline" in text
            assert "## Deck Metadata" in text
            assert "## Section Group: Teaching Flow" in text
            assert "## Section Group: Recap" in text
            assert "Bullet suggestions" in text
            assert "Visual cue reference" in text
            assert "Speaker notes" in text
            assert "Tutor-loop alignment" in text
        if export_format == "markdown_export":
            assert text.startswith("# ")
            assert "## Teaching Body" in text
            assert "## Instructional Arc" in text
            assert "## Tutor Loop Alignment" in text
            assert "## Scene And Narration Blocks" in text
            assert "## Remember Points" in text
            assert "- Content source:" in text
        if export_format == "text_export":
            assert not text.startswith("# ")
            assert "Adhyantra lesson export" in text
            assert "Tutor Loop Alignment" in text
            assert "Instructional Arc" in text
            assert "Teaching Body" in text
            assert "Scene And Narration Blocks" in text
            assert "Remember Points" in text


@pytest.mark.parametrize(
    ("lesson_mode", "expected_alignment"),
    [
        ("revision_video", "Revision/reinforcement alignment"),
        ("crash_course_video", "Exam-compression alignment"),
    ],
)
def test_phase24_video_variant_exports_keep_tutor_loop_alignment(
    client: TestClient,
    lesson_mode: str,
    expected_alignment: str,
) -> None:
    authenticate_premium_test_user(
        client,
        email=f"phase24-video-export-{lesson_mode.replace('_', '-')}@example.com",
    )

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": lesson_mode,
            "export_format": "json_export",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lesson_state"]["lesson_mode"] == lesson_mode
    assert lesson_mode in body["tutor_loop_context"]["mode_alignment"]
    assert expected_alignment in body["tutor_loop_context"]["revision_alignment"]
    assert "upsc" in body["tutor_loop_context"]["exam_alignment"]
    assert body["media_ready"]["video_lesson_script"]["video_mode"] == lesson_mode


@pytest.mark.parametrize(
    ("legacy_format", "canonical_format"),
    [
        ("json", "json_export"),
        ("markdown", "markdown_export"),
        ("text", "text_export"),
        ("slide_outline", "slide_outline_export"),
        ("tts_package", "audio_script_export"),
    ],
)
def test_phase24_lesson_export_route_accepts_legacy_format_aliases(
    client: TestClient,
    legacy_format: str,
    canonical_format: str,
) -> None:
    authenticate_premium_test_user(
        client,
        email=f"phase24-alias-{legacy_format.replace('_', '-')}@example.com",
    )

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "export_format": legacy_format,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-adhyantra-export-format"] == canonical_format

    if canonical_format in {"json_export", "audio_script_export"}:
        body = response.json()
        assert body["metadata"]["export_target"] == canonical_format
        assert body["metadata"]["requested_format"] == legacy_format
        assert body["metadata"]["filename"] == response.headers["x-adhyantra-export-filename"]

    if legacy_format == "tts_package":
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["x-adhyantra-export-filename"].endswith(".audio-script.json")

        download_response = client.post(
            "/api/tutor/export/lesson/download",
            json={
                "topic": "Preamble",
                "subject": "polity",
                "exam": "upsc",
                "lesson_mode": "video_lecture",
                "export_format": legacy_format,
            },
        )
        assert download_response.status_code == 200
        assert download_response.headers["x-adhyantra-export-format"] == canonical_format
        assert download_response.headers["content-type"].startswith("application/json")
        assert download_response.json()["metadata"]["requested_format"] == legacy_format


def test_legacy_tts_package_alias_uses_canonical_premium_entitlement(client: TestClient) -> None:
    authenticate_test_user(client, email="phase24-free-tts-package@example.com")

    response = client.post(
        "/api/tutor/export/lesson/download",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": "tts_package",
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "lesson_exports"
    assert detail["required_plan"] == "premium"


def test_phase24_lesson_export_download_route_uses_shared_contract(client: TestClient) -> None:
    authenticate_premium_test_user(client, email="phase24-download@example.com")

    response = client.post(
        "/api/tutor/export/lesson/download",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "export_format": "markdown_export",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-adhyantra-export-format"] == "markdown_export"
    assert response.headers["x-adhyantra-export-version"] == "phase24_lesson_export_v1"
    filename = response.headers["x-adhyantra-export-filename"]
    assert filename.startswith("adhyantra-upsc-polity-preamble-video-lecture-")
    assert filename.endswith(".md")
    assert f'filename="{filename}"' in response.headers["content-disposition"]
    assert "## Teaching Body" in response.text


@pytest.mark.parametrize("lesson_mode", ["lecture_outline", "mini_lesson", "revision_lesson", "crash_course"])
def test_phase25_free_user_keeps_standard_tutor_access(client: TestClient, lesson_mode: str) -> None:
    authenticate_test_user(client, email=f"phase25-free-standard-{lesson_mode.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 200
    assert response.json()["lesson_mode"] == lesson_mode


@pytest.mark.parametrize("lesson_mode", ["video_lecture", "revision_video", "crash_course_video"])
def test_phase25_free_user_cannot_use_premium_video_lesson_mode(client: TestClient, lesson_mode: str) -> None:
    authenticate_test_user(client, email=f"phase25-free-{lesson_mode.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "premium_lesson_modes"
    assert detail["required_plan"] == "premium"
    assert detail["upgrade_required"] is True
    assert detail["sign_in_required"] is False


@pytest.mark.parametrize("lesson_mode", ["video_lecture", "revision_video", "crash_course_video"])
def test_phase25_anonymous_user_gets_sign_in_required_for_premium_video_lesson_mode(
    client: TestClient,
    lesson_mode: str,
) -> None:
    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["feature_key"] == "premium_lesson_modes"
    assert detail["sign_in_required"] is True
    assert detail["upgrade_required"] is False


@pytest.mark.parametrize("account_kind", ["anonymous", "free"])
@pytest.mark.parametrize(
    ("endpoint", "payload", "expected_feature"),
    [
        (
            "/api/tutor/explain",
            {"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": "video_lecture"},
            "premium_lesson_modes",
        ),
        (
            "/api/tutor/export/lesson",
            {
                "topic": "Preamble",
                "subject": "polity",
                "exam": "upsc",
                "lesson_mode": "revision_video",
                "export_format": "markdown_export",
            },
            "premium_lesson_modes",
        ),
        (
            "/api/tutor/export/lesson/download",
            {
                "topic": "Preamble",
                "subject": "polity",
                "exam": "upsc",
                "lesson_mode": "crash_course_video",
                "export_format": "text_export",
            },
            "premium_lesson_modes",
        ),
        (
            "/api/tutor/export/lesson",
            {
                "topic": "Preamble",
                "subject": "polity",
                "exam": "upsc",
                "lesson_mode": "mini_lesson",
                "export_format": "json_export",
            },
            "lesson_exports",
        ),
        (
            "/api/tutor/render/audio",
            {"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": "video_lecture"},
            "premium_lesson_modes",
        ),
        (
            "/api/tutor/render/video",
            {
                "topic": "Preamble",
                "subject": "polity",
                "exam": "upsc",
                "lesson_mode": "video_lecture",
                "render_type": "slide_video",
            },
            "premium_lesson_modes",
        ),
    ],
)
def test_premium_tutor_access_is_rejected_before_generation_export_or_job_creation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    account_kind: str,
    endpoint: str,
    payload: dict[str, str],
    expected_feature: str,
) -> None:
    from backend.routes import tutor_routes

    if account_kind == "free":
        authenticate_test_user(
            client,
            email=f"security-free-{endpoint.strip('/').replace('/', '-')}-{expected_feature}@example.com",
        )

    def fail_expensive_work(*args, **kwargs):
        raise AssertionError("Rejected premium access reached expensive tutor work.")

    monkeypatch.setattr(tutor_routes, "explain_topic", fail_expensive_work)
    monkeypatch.setattr(tutor_routes, "build_lesson_export_asset", fail_expensive_work)
    monkeypatch.setattr(tutor_routes, "create_media_render_job", fail_expensive_work)

    response = client.post(endpoint, json=payload)

    assert response.status_code == (401 if account_kind == "anonymous" else 403)
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        assert detail["feature_key"] == expected_feature
        assert detail["sign_in_required"] is (account_kind == "anonymous")
        assert detail["upgrade_required"] is (account_kind == "free")
    else:
        assert account_kind == "anonymous"
        assert detail == "Sign in is required for rendered media."

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        assert db.query(MediaRenderJob).count() == 0
        assert db.query(UsageConsumptionRecord).count() == 0
        assert db.query(TopicStudy).count() == 0
        assert db.query(AnalyticsEvent).filter(
            AnalyticsEvent.event_name.in_({"tutor.explained", "lesson.exported"})
        ).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("lesson_mode", ["video_lecture", "revision_video", "crash_course_video"])
def test_phase25_premium_user_can_use_premium_video_lesson_mode(client: TestClient, lesson_mode: str) -> None:
    authenticate_premium_test_user(client, email=f"phase25-premium-{lesson_mode.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": lesson_mode},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lesson_mode"] == lesson_mode
    assert body["video_lesson_script"]["video_mode"] == lesson_mode


@pytest.mark.parametrize("export_format", ["markdown_export", "text_export"])
def test_phase25_free_user_can_download_standard_lesson_exports(client: TestClient, export_format: str) -> None:
    authenticate_test_user(client, email=f"phase25-free-standard-export-{export_format.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": export_format,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-adhyantra-export-format"] == export_format
    assert "Preamble" in response.text


@pytest.mark.parametrize("lesson_mode", ["video_lecture", "revision_video", "crash_course_video"])
@pytest.mark.parametrize("export_format", ["markdown_export", "text_export"])
def test_phase25_free_user_cannot_export_premium_lesson_mode_with_standard_export(
    client: TestClient,
    lesson_mode: str,
    export_format: str,
) -> None:
    authenticate_test_user(
        client,
        email=(
            "phase25-free-premium-mode-standard-export-"
            f"{lesson_mode.replace('_', '-')}-{export_format.replace('_', '-')}@example.com"
        ),
    )

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": lesson_mode,
            "export_format": export_format,
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "premium_lesson_modes"
    assert detail["required_plan"] == "premium"
    assert detail["upgrade_required"] is True


@pytest.mark.parametrize("export_format", ["json_export", "slide_outline_export", "audio_script_export"])
def test_phase25_free_user_cannot_download_advanced_lesson_export(client: TestClient, export_format: str) -> None:
    authenticate_test_user(client, email=f"phase25-free-advanced-export-{export_format.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": export_format,
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "lesson_exports"
    assert detail["required_plan"] == "premium"
    assert detail["upgrade_required"] is True


@pytest.mark.parametrize("export_format", ["json_export", "slide_outline_export", "audio_script_export"])
def test_phase25_premium_user_can_download_advanced_lesson_export(client: TestClient, export_format: str) -> None:
    authenticate_premium_test_user(client, email=f"phase25-premium-export-{export_format.replace('_', '-')}@example.com")

    response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": export_format,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-adhyantra-export-format"] == export_format
    if export_format == "slide_outline_export":
        assert "Slide Outline" in response.text
    else:
        assert response.json()["metadata"]["export_target"] == export_format


def test_phase27_learning_flows_record_analytics_events(client: TestClient) -> None:
    auth = authenticate_test_user(client, email="phase27-events@example.com", display_name="Phase 27 Events")
    user_id = auth["user"]["id"]

    explain_response = client.post(
        "/api/tutor/explain",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "lesson_mode": "mini_lesson"},
    )
    assert explain_response.status_code == 200
    explain_body = explain_response.json()

    doubt_response = client.post(
        "/api/tutor/doubt",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "question": "Why is the Preamble important in constitutional interpretation?",
        },
    )
    assert doubt_response.status_code == 200

    generate_response = client.post(
        "/api/test/generate",
        json={"topic": "Preamble", "subject": "polity", "exam": "upsc", "question_count": 5},
    )
    assert generate_response.status_code == 200
    generated_quiz = generate_response.json()

    submit_response = client.post(
        "/api/test/submit",
        json={
            "quiz_id": generated_quiz["quiz_id"],
            "subject": "polity",
            "exam": "upsc",
            "answers": get_correct_answers(client, generated_quiz),
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()

    export_response = client.post(
        "/api/tutor/export/lesson",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
            "export_format": "markdown_export",
        },
    )
    assert export_response.status_code == 200

    events = get_analytics_events(client, user_id=user_id, exam="upsc")
    event_names = [event.event_name for event in events]
    assert {"tutor.explained", "doubt.answered", "quiz.generated", "quiz.submitted", "lesson.exported"}.issubset(set(event_names))

    event_lookup = {event.event_name: event for event in events}
    explain_event = event_lookup["tutor.explained"]
    assert explain_event.feature_area == "tutor"
    assert explain_event.lesson_mode == "mini_lesson"
    assert explain_event.topic == explain_body["topic"]
    assert explain_event.content_corpus_id == explain_body["content_corpus_id"]
    assert explain_event.content_source_scope == explain_body["content_source_scope"]

    generated_event = event_lookup["quiz.generated"]
    generated_metadata = deserialize_analytics_event_metadata(generated_event)
    assert generated_event.feature_area == "quiz"
    assert generated_event.quiz_mode == generated_quiz["quiz_mode"]
    assert generated_event.question_count == len(generated_quiz["questions"])
    assert generated_event.content_source_scope == generated_quiz["content_source_scope"]
    assert generated_metadata["covered_topic_count"] >= 1

    submitted_event = event_lookup["quiz.submitted"]
    assert submitted_event.score == submit_body["score"]
    assert submitted_event.accuracy == submit_body["accuracy"]
    assert submitted_event.quiz_mode == submit_body["quiz_mode"]
    assert submitted_event.content_corpus_id == generated_quiz["content_corpus_id"]
    assert submitted_event.content_source_scope == generated_quiz["content_source_scope"]

    export_event = event_lookup["lesson.exported"]
    export_metadata = deserialize_analytics_event_metadata(export_event)
    assert export_event.feature_area == "lesson_export"
    assert export_event.export_format == "markdown_export"
    assert export_event.lesson_mode == "mini_lesson"
    assert export_metadata["filename"].endswith(".md")

    doubt_event = event_lookup["doubt.answered"]
    doubt_metadata = deserialize_analytics_event_metadata(doubt_event)
    assert doubt_event.feature_area == "doubt"
    assert doubt_event.topic == "Preamble"
    assert doubt_event.content_corpus_id == explain_body["content_corpus_id"]
    assert doubt_event.content_source_scope == explain_body["content_source_scope"]
    assert doubt_metadata["question_length"] > 10


def test_phase27_analytics_foundation_snapshot_reuses_history_and_respects_scope(client: TestClient) -> None:
    auth = authenticate_test_user(client, email="phase27-metrics@example.com", display_name="Phase 27 Metrics")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        mark_topic_studied(db, topic="Preamble", subject="polity", exam="upsc", user_id=user_id)
        create_attempt_record(client, topic="Preamble", score=4, total_questions=5, subject="polity", exam="upsc", user_id=user_id)

        second_user = UserAccount(
            email="phase27-other@example.com",
            display_name="Other User",
            auth_status="verified",
            email_verified_at=datetime.now(UTC),
        )
        db.add(second_user)
        db.commit()
        db.refresh(second_user)
        mark_topic_studied(db, topic="Preamble", subject="polity", exam="upsc", user_id=second_user.id)
        create_attempt_record(client, topic="Preamble", score=1, total_questions=5, subject="polity", exam="upsc", user_id=second_user.id)

        record_analytics_event(
            db,
            event_name="lesson.exported",
            feature_area="lesson_export",
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            content_corpus_id="upsc-shared-core",
            content_source_scope="exam_primary",
            lesson_mode="mini_lesson",
            export_format="markdown_export",
            metadata={"filename": "adhyantra-upsc-polity-preamble-mini-lesson.md"},
        )
        record_analytics_event(
            db,
            event_name="tutor.explained",
            feature_area="tutor",
            user_id=user_id,
            exam="banking",
            subject="regulatory_basics",
            topic="Banking Basics",
            lesson_mode="mini_lesson",
            metadata={"note": "Should stay outside UPSC-scoped metrics."},
        )
        record_analytics_event(
            db,
            event_name="lesson.exported",
            feature_area="lesson_export",
            user_id=second_user.id,
            exam="upsc",
            subject="polity",
            topic="Preamble",
            content_corpus_id="upsc-shared-core",
            content_source_scope="exam_primary",
            lesson_mode="mini_lesson",
            export_format="markdown_export",
            metadata={"filename": "other-user-export.md"},
        )
        db.add(
            TopicStudy(
                user_id=user_id,
                exam="upsc",
                subject="polity",
                chapter="General",
                topic="Old Topic",
                study_count=7,
                last_interaction_at=datetime.now(UTC) - timedelta(days=90),
            )
        )
        db.add(
            TopicProgress(
                user_id=user_id,
                exam="upsc",
                subject="polity",
                chapter="General",
                topic="Old Topic",
                attempts_count=5,
                correct_answers=1,
                total_answers=5,
                accuracy=20.0,
                difficulty_band="easy",
                weak_topic=True,
                last_attempt_at=datetime.now(UTC) - timedelta(days=90),
            )
        )
        db.commit()

        snapshot = build_analytics_foundation_snapshot(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            since_days=30,
        )
    finally:
        db.close()

    learner_metrics = snapshot["learner_activity_metrics"]
    quiz_metrics = snapshot["quiz_revision_metrics"]
    lesson_metrics = snapshot["lesson_export_usage_metrics"]
    content_metrics = snapshot["content_consumption_metrics"]

    assert snapshot["version"] == "phase27_analytics_v1"
    assert snapshot["scope"]["user_id"] == user_id
    assert snapshot["scope"]["exam"] == "upsc"
    assert snapshot["scope"]["subject"] == "polity"

    assert learner_metrics["study_topic_count"] == 1
    assert learner_metrics["study_interaction_count"] == 2
    assert learner_metrics["quiz_attempt_count"] == 1
    assert learner_metrics["topics_touched"] == 1
    assert learner_metrics["active_days"] >= 1

    assert quiz_metrics["quiz_attempt_count"] == 1
    assert quiz_metrics["average_accuracy"] == 80.0
    assert quiz_metrics["latest_accuracy"] == 80.0
    assert quiz_metrics["tracked_topic_count"] == 1

    assert lesson_metrics["lesson_export_count"] == 1
    assert lesson_metrics["lesson_count_by_mode"] == {"mini_lesson": 1}
    assert lesson_metrics["export_count_by_format"] == {"markdown_export": 1}

    assert content_metrics["content_event_count"] == 1
    assert content_metrics["corpora_touched"] == 1
    assert content_metrics["content_topic_count"] == 1
    assert content_metrics["content_source_scope_counts"] == {"exam_primary": 1}


def test_phase28_media_render_job_lifecycle_tracks_owner_context_and_outputs(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase28-render-owner@example.com", display_name="Phase 28 Render Owner")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            source_content_corpus_id="upsc-shared-core",
            source_content_scope="exam_primary",
            requested_scene_count=4,
            requested_segment_count=4,
            request_metadata={"voice_key": "calm_narrator", "requested_by": "phase28_test"},
            status_note="Queued for narration rendering.",
        )

        assert db.query(MediaRenderJob).count() == 1
        assert job.user_id == user_id
        assert job.lifecycle_state == "queued"
        assert job.render_type == "audio"
        assert job.lesson_mode == "video_lecture"
        assert job.source_export_format == "audio_script_export"
        assert job.source_content_corpus_id == "upsc-shared-core"
        assert job.requested_scene_count == 4
        assert job.requested_segment_count == 4

        running = mark_media_render_job_running(db, job=job, status_note="Narration rendering in progress.")
        assert running.lifecycle_state == "running"
        assert running.started_at is not None
        assert running.completed_at is None
        assert running.status_note == "Narration rendering in progress."

        succeeded = mark_media_render_job_succeeded(
            db,
            job=running,
            output_metadata={"duration_seconds": 92, "scene_asset_count": 4},
            output_asset_filename="adhyantra-upsc-polity-preamble-video-lecture.mp3",
            output_asset_path="media-renders/2026/05/adhyantra-upsc-polity-preamble-video-lecture.mp3",
            output_content_type="audio/mpeg",
            output_file_size_bytes=481920,
            status_note="Narration render is ready.",
        )
        serialized = serialize_media_render_job(succeeded)

        assert succeeded.lifecycle_state == "succeeded"
        assert succeeded.completed_at is not None
        assert succeeded.output_asset_filename.endswith(".mp3")
        assert succeeded.output_content_type == "audio/mpeg"
        assert serialized["asset_ready"] is True
        assert serialized["output"]["metadata"]["duration_seconds"] == 92
        assert serialized["source_content_scope"] == "exam_primary"
        assert serialized["request_metadata"]["voice_key"] == "calm_narrator"
    finally:
        db.close()


def test_phase28_media_render_job_scoping_and_failed_terminal_state_are_enforced(client: TestClient) -> None:
    first_auth = authenticate_test_user(client, email="phase28-render-first@example.com", display_name="Phase 28 First")
    second_auth = authenticate_test_user(client, email="phase28-render-second@example.com", display_name="Phase 28 Second")
    first_user_id = first_auth["user"]["id"]
    second_user_id = second_auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        first_job = create_media_render_job(
            db,
            user_id=first_user_id,
            exam="upsc",
            subject="history",
            content_subject="history",
            chapter="Modern India",
            topic="Swadeshi Movement",
            lesson_mode="revision_video",
            source_export_format="audio_script_export",
            render_type="narrated_video",
            requested_scene_count=3,
            requested_segment_count=3,
        )
        second_job = create_media_render_job(
            db,
            user_id=second_user_id,
            exam="banking",
            subject="regulatory_basics",
            content_subject="polity",
            chapter="General",
            topic="Parliament",
            lesson_mode="mini_lesson",
            source_export_format="json_export",
            render_type="slide_video",
            requested_scene_count=2,
            requested_segment_count=2,
        )

        failed = mark_media_render_job_failed(
            db,
            job=first_job,
            failure_code="tts_provider_unavailable",
            failure_message="Narration provider could not accept the request.",
            status_note="Generation failed. Try again later.",
        )
        assert failed.lifecycle_state == "failed"
        assert failed.completed_at is not None
        assert failed.failure_code == "tts_provider_unavailable"
        assert failed.failure_message == "Narration provider could not accept the request."

        scoped_first_jobs = list_media_render_jobs_for_user(db, user_id=first_user_id, exam="upsc", subject="history")
        assert [job.id for job in scoped_first_jobs] == [first_job.id]

        assert get_media_render_job_for_user(db, job_id=first_job.id, user_id=first_user_id) is not None
        assert get_media_render_job_for_user(db, job_id=first_job.id, user_id=second_user_id) is None
        assert get_media_render_job_for_user(db, job_id=second_job.id, user_id=first_user_id) is None

        with pytest.raises(ValueError, match="Cannot transition final render job state"):
            mark_media_render_job_running(db, job=failed, status_note="This should not restart automatically.")
    finally:
        db.close()


def test_phase32_media_render_job_retry_and_claim_lifecycle_is_background_ready(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-render-retry@example.com", display_name="Phase 32 Retry")
    user_id = auth["user"]["id"]
    anchor = datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=3,
            requested_segment_count=3,
            max_attempts=2,
            status_note="Queued for worker dispatch.",
        )

        claimed_once = claim_media_render_job_for_worker(
            db,
            job=job,
            worker_id="worker-a",
            lease_seconds=120,
            status_note="Worker A claimed the job.",
            occurred_at=anchor,
        )
        assert claimed_once.lifecycle_state == "running"
        assert claimed_once.attempt_count == 1
        assert normalize_test_datetime(claimed_once.last_attempted_at) == anchor
        assert claimed_once.claimed_by == "worker-a"
        assert normalize_test_datetime(claimed_once.claim_expires_at) == anchor + timedelta(seconds=120)

        retryable_failed = mark_media_render_job_retryable_failed(
            db,
            job=claimed_once,
            failure_code="transient_provider_timeout",
            failure_message="Temporary upstream timeout.",
            retry_after_at=anchor + timedelta(minutes=5),
            status_note="Waiting to retry after a temporary issue.",
            occurred_at=anchor + timedelta(minutes=1),
        )
        serialized_retryable = serialize_media_render_job(retryable_failed)

        assert retryable_failed.lifecycle_state == "retryable_failed"
        assert retryable_failed.completed_at is None
        assert retryable_failed.failure_code == "transient_provider_timeout"
        assert retryable_failed.claimed_by is None
        assert retryable_failed.claim_expires_at is None
        assert normalize_test_datetime(retryable_failed.retry_after_at) == anchor + timedelta(minutes=5)
        assert serialized_retryable["lifecycle_state"] == "queued"
        assert serialized_retryable["failure_code"] is None
        assert serialized_retryable["failure_message"] is None

        claimable_before_retry = list_claimable_media_render_jobs(db, now=anchor + timedelta(minutes=2))
        assert claimable_before_retry == []

        claimable_after_retry = list_claimable_media_render_jobs(db, now=anchor + timedelta(minutes=6))
        assert [item.id for item in claimable_after_retry] == [job.id]

        claimed_twice = claim_media_render_job_for_worker(
            db,
            job=retryable_failed,
            worker_id="worker-b",
            lease_seconds=90,
            status_note="Worker B reclaimed the job.",
            occurred_at=anchor + timedelta(minutes=6),
        )
        assert claimed_twice.lifecycle_state == "running"
        assert claimed_twice.attempt_count == 2
        assert claimed_twice.claimed_by == "worker-b"
        assert normalize_test_datetime(claimed_twice.claim_expires_at) == anchor + timedelta(minutes=6, seconds=90)

        exhausted_failure = mark_media_render_job_retryable_failed(
            db,
            job=claimed_twice,
            failure_code="transient_provider_timeout",
            failure_message="Temporary upstream timeout.",
            retry_after_at=anchor + timedelta(minutes=8),
            status_note="Retries exhausted.",
            occurred_at=anchor + timedelta(minutes=7),
        )
        serialized_exhausted = serialize_media_render_job(exhausted_failure)

        assert exhausted_failure.lifecycle_state == "failed"
        assert normalize_test_datetime(exhausted_failure.completed_at) == anchor + timedelta(minutes=7)
        assert exhausted_failure.failure_code == "transient_provider_timeout"
        assert exhausted_failure.claimed_by is None
        assert exhausted_failure.retry_after_at is None
        assert serialized_exhausted["lifecycle_state"] == "failed"
        assert serialized_exhausted["failure_code"] == "transient_provider_timeout"
        assert serialized_exhausted["failure_message"] == "Media generation could not complete. Please try again."
    finally:
        db.close()


def test_phase32_dispatchable_render_jobs_require_hidden_worker_payload(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-dispatch-payload@example.com", display_name="Phase 32 Dispatch Payload")
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        manual_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=2,
            requested_segment_count=2,
        )
        dispatchable_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=2,
            requested_segment_count=2,
            dispatch_payload={
                "dispatch_version": "phase32_test_dispatch",
                "dispatch_kind": "audio",
                "action_name": "media_render.audio_create",
                "audio_script_payload": {
                    "metadata": {
                        "subject": "polity",
                        "exam": "upsc",
                        "topic": "Directive Principles",
                        "honesty_note": "test",
                    },
                    "voice_guidance": {},
                    "script_notes": [],
                    "segments": [],
                    "rendering_outputs": {},
                },
            },
        )

        claimable_jobs = list_claimable_media_render_jobs(db, now=datetime.now(UTC))
        assert {job.id for job in claimable_jobs} == {manual_job.id, dispatchable_job.id}

        dispatchable_jobs = list_dispatchable_media_render_jobs(db, now=datetime.now(UTC))
        assert [job.id for job in dispatchable_jobs] == [dispatchable_job.id]
        assert get_media_render_job_dispatch_payload(manual_job) == {}
        assert get_media_render_job_dispatch_payload(dispatchable_job)["dispatch_kind"] == "audio"
    finally:
        db.close()


def test_phase33_external_worker_mode_processes_queued_audio_job_without_embedded_dispatcher(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase33-external-worker@example.com",
        display_name="Phase 33 External Worker",
    )
    user_id = auth["user"]["id"]

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            del url, headers
            payload = dict(json or {})
            return FakeResponse(f"PHASE33-EXTERNAL-WORKER::{payload.get('input', '')}".encode("utf-8"))

    from backend.routes import tutor_routes
    from backend.services import tts_service

    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "phase33-external-worker-render-output"),
        media_render_worker_mode="external",
        media_render_worker_poll_seconds=0.05,
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tutor_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    stop_media_render_dispatcher(client.app)
    assert client.app.state.media_render_dispatcher is None

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["lifecycle_state"] == "queued"

    processed_jobs = run_media_render_worker_forever(
        client.app.state.testing_session_factory,
        settings=settings,
        worker_id="phase33-external-worker",
        max_jobs=1,
        poll_interval_seconds=0.05,
    )
    assert processed_jobs == 1

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/audio/{job_body['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["lifecycle_state"] == "succeeded"
    assert status_body["output"]["download_path"] == f"/api/tutor/render/audio/{job_body['id']}/download"

    render_records = wait_for_usage_consumption_count(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
        expected_count=1,
    )
    assert len(render_records) == 1
    assert render_records[0].media_render_job_id == job_body["id"]


def test_phase33_durable_queue_handoff_survives_missing_embedded_dispatcher(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase33-durable-handoff@example.com",
        display_name="Phase 33 Durable Handoff",
    )
    user_id = auth["user"]["id"]

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            del url, headers
            payload = dict(json or {})
            return FakeResponse(f"PHASE33-DURABLE-HANDOFF::{payload.get('input', '')}".encode("utf-8"))

    from backend.routes import tutor_routes
    from backend.services import tts_service

    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "phase33-durable-handoff-render-output"),
        media_render_worker_mode="embedded",
        media_render_worker_poll_seconds=0.05,
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tutor_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    stop_media_render_dispatcher(client.app)
    assert client.app.state.media_render_dispatcher is None

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Directive Principles",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["lifecycle_state"] == "queued"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        queued_job = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_body["id"]).first()
        assert queued_job is not None
        assert normalize_test_datetime(queued_job.queued_at) is not None
    finally:
        db.close()

    processed_job = run_media_render_worker_once(
        client.app.state.testing_session_factory,
        settings=settings,
        worker_id="phase33-durable-handoff-worker",
        poll_interval_seconds=0.05,
    )
    assert processed_job is True

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    render_records = wait_for_usage_consumption_count(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
        expected_count=1,
    )
    assert len(render_records) == 1
    assert render_records[0].media_render_job_id == job_body["id"]


def test_phase32_video_dispatch_payload_preserves_scene_package_mode(client: TestClient) -> None:
    dispatch_payload = build_video_render_dispatch_payload(
        action_name="media_render.video_create",
        quota_snapshots={},
        lesson={
            "exam": "upsc",
            "subject": "polity",
            "topic": "Preamble",
            "lesson_mode": "video_lecture",
        },
        render_type="narrated_video",
    )

    assert dispatch_payload["dispatch_kind"] == "video"
    assert dispatch_payload["render_type"] == "narrated_video"
    assert dispatch_payload["render_style"] == "scene_slide_package"
    assert dispatch_payload["narrated_audio_requested"] is True
    assert dispatch_payload["lesson_payload"]["topic"] == "Preamble"


def test_phase32_audio_render_worker_retries_transient_failure_before_succeeding(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-audio-retry-success@example.com", display_name="Phase 32 Audio Retry Success")
    user_id = auth["user"]["id"]

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        call_count = 0

        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            del url, headers
            FakeClient.call_count += 1
            if FakeClient.call_count == 1:
                raise tts_service.httpx.ReadTimeout("temporary upstream timeout")
            payload = dict(json or {})
            return FakeResponse(f"PHASE32-AUDIO-RETRY::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service

    monkeypatch.setattr(
        tts_service,
        "get_settings",
        lambda: Settings(
            tts_provider="openai",
            tts_openai_api_key="test-openai-tts-key",
            tts_openai_model="gpt-4o-mini-tts",
            tts_openai_voice="alloy",
            tts_output_format="mp3",
            media_render_output_dir=str(tmp_path / "phase32-audio-retry-success"),
        ),
    )
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["lifecycle_state"] == "queued"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/audio/{job_body['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["lifecycle_state"] == "succeeded"

    render_records = wait_for_usage_consumption_count(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
        expected_count=1,
    )
    assert len(render_records) == 1
    assert render_records[0].media_render_job_id == job_body["id"]

    assert wait_for_media_render_event_names(client, user_id=user_id, exam="upsc", expected_event_names=[
        "lesson.audio_rendered",
    ]) == [
        "lesson.audio_rendered",
    ]


def test_phase32_audio_render_worker_exhausts_transient_failures_cleanly(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-audio-retry-fail@example.com", display_name="Phase 32 Audio Retry Fail")
    user_id = auth["user"]["id"]

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None):
            del url, headers, json
            raise tts_service.httpx.ReadTimeout("temporary upstream timeout")

    from backend.services import tts_service

    monkeypatch.setattr(
        tts_service,
        "get_settings",
        lambda: Settings(
            tts_provider="openai",
            tts_openai_api_key="test-openai-tts-key",
            tts_openai_model="gpt-4o-mini-tts",
            tts_openai_voice="alloy",
            tts_output_format="mp3",
            media_render_output_dir=str(tmp_path / "phase32-audio-retry-fail"),
        ),
    )
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Directive Principles",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["lifecycle_state"] == "queued"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "failed"
    assert terminal_job.attempt_count == 3
    assert terminal_job.status_note == "Audio generation could not complete after a few tries. Please try again."

    render_records = get_usage_consumption_records(client, user_id=user_id, limit_key="media_render_creations")
    assert render_records == []

    assert wait_for_media_render_event_names(client, user_id=user_id, exam="upsc", expected_event_names=[
        "lesson.audio_render_failed",
    ]) == [
        "lesson.audio_render_failed",
    ]

    status_response = client.get(f"/api/tutor/render/audio/{job_body['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["failure_message"] == "Audio generation could not complete after a few tries. Please try again."

    download_response = client.get(f"/api/tutor/render/audio/{job_body['id']}/download")
    assert download_response.status_code == 409


def test_phase32_video_render_worker_retries_transient_narration_failure_before_succeeding(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-video-retry-success@example.com", display_name="Phase 32 Video Retry Success")
    user_id = auth["user"]["id"]

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        call_count = 0

        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            del url, headers
            FakeClient.call_count += 1
            if FakeClient.call_count == 1:
                raise tts_service.httpx.ReadTimeout("temporary upstream timeout")
            payload = dict(json or {})
            return FakeResponse(f"PHASE32-VIDEO-RETRY::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "phase32-video-retry-success"),
    )
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["lifecycle_state"] == "queued"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"], timeout_seconds=8.0)
    assert terminal_job.lifecycle_state == "succeeded"

    render_records = wait_for_usage_consumption_count(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
        expected_count=1,
    )
    assert len(render_records) == 1
    assert render_records[0].render_type == "narrated_video"

    assert wait_for_media_render_event_names(client, user_id=user_id, exam="upsc", expected_event_names=[
        "lesson.video_rendered",
    ]) == [
        "lesson.video_rendered",
    ]


def test_phase32_media_render_job_abandonment_requeue_and_cancel_are_safe(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase32-render-abandon@example.com", display_name="Phase 32 Abandon")
    user_id = auth["user"]["id"]
    anchor = datetime(2026, 5, 10, 11, 0, 0, tzinfo=UTC)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="history",
            content_subject="history",
            chapter="Modern India",
            topic="Swadeshi Movement",
            lesson_mode="revision_video",
            source_export_format="audio_script_export",
            render_type="narrated_video",
            requested_scene_count=4,
            requested_segment_count=4,
            max_attempts=4,
            status_note="Queued for background execution.",
        )

        running = claim_media_render_job_for_worker(
            db,
            job=job,
            worker_id="worker-stale",
            lease_seconds=60,
            status_note="Worker stale claimed the job.",
            occurred_at=anchor,
        )
        assert running.lifecycle_state == "running"

        abandoned_jobs = mark_stale_media_render_jobs_abandoned(
            db,
            now=anchor + timedelta(minutes=10),
        )
        assert [item.id for item in abandoned_jobs] == [job.id]

        abandoned = get_media_render_job_for_user(db, job_id=job.id, user_id=user_id)
        assert abandoned is not None
        serialized_abandoned = serialize_media_render_job(abandoned)

        assert abandoned.lifecycle_state == "abandoned"
        assert abandoned.claimed_by is None
        assert abandoned.claim_expires_at is None
        retry_after_at = normalize_test_datetime(abandoned.retry_after_at)
        assert retry_after_at is not None
        assert retry_after_at > anchor + timedelta(minutes=10)
        assert abandoned.failure_code == "worker_claim_expired"
        assert serialized_abandoned["lifecycle_state"] == "queued"
        assert serialized_abandoned["failure_code"] is None
        assert serialized_abandoned["failure_message"] is None

        requeued = requeue_media_render_job(
            db,
            job=abandoned,
            status_note="Queued again after stale worker recovery.",
            occurred_at=anchor + timedelta(minutes=11),
        )
        assert requeued.lifecycle_state == "queued"
        assert requeued.retry_after_at is None
        assert requeued.failure_code is None
        assert requeued.failure_message is None

        canceled = cancel_media_render_job(
            db,
            job=requeued,
            status_note="Media generation was canceled safely.",
            occurred_at=anchor + timedelta(minutes=12),
        )
        serialized_canceled = serialize_media_render_job(canceled)

        assert canceled.lifecycle_state == "canceled"
        assert normalize_test_datetime(canceled.completed_at) == anchor + timedelta(minutes=12)
        assert normalize_test_datetime(canceled.canceled_at) == anchor + timedelta(minutes=12)
        assert canceled.failure_code == "job_canceled"
        assert serialized_canceled["lifecycle_state"] == "failed"
        assert serialized_canceled["failure_code"] == "job_canceled"

        with pytest.raises(ValueError, match="Cannot transition final render job state"):
            mark_media_render_job_running(db, job=canceled, status_note="This should not restart automatically.")
    finally:
        db.close()


def test_phase33_stale_running_job_exhaustion_settles_to_terminal_failure(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase33-stale-exhaustion@example.com", display_name="Phase 33 Stale Exhaustion")
    user_id = auth["user"]["id"]
    anchor = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=2,
            requested_segment_count=2,
            max_attempts=1,
            status_note="Queued for background execution.",
        )

        running = claim_media_render_job_for_worker(
            db,
            job=job,
            worker_id="worker-timeout",
            lease_seconds=30,
            status_note="Worker timeout claimed the job.",
            occurred_at=anchor,
        )
        assert running.lifecycle_state == "running"
        assert running.attempt_count == 1

        recovered_jobs = mark_stale_media_render_jobs_abandoned(
            db,
            now=anchor + timedelta(minutes=3),
        )
        assert [item.id for item in recovered_jobs] == [job.id]

        exhausted = get_media_render_job_for_user(db, job_id=job.id, user_id=user_id)
        assert exhausted is not None
        serialized_exhausted = serialize_media_render_job(exhausted)

        assert exhausted.lifecycle_state == "failed"
        assert exhausted.failure_code == "worker_claim_expired"
        assert exhausted.retry_after_at is None
        assert exhausted.claimed_by is None
        assert exhausted.claim_expires_at is None
        assert serialized_exhausted["lifecycle_state"] == "failed"
        assert serialized_exhausted["failure_message"] == "Media generation could not complete after repeated interruptions. Please try again."
    finally:
        db.close()


def test_phase33_exhausted_retryable_jobs_are_finalized_by_worker_recovery_sweep(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase33-exhausted-retryable@example.com", display_name="Phase 33 Exhausted Retryable")
    user_id = auth["user"]["id"]
    anchor = datetime(2026, 5, 10, 13, 0, 0, tzinfo=UTC)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="history",
            content_subject="history",
            chapter="Modern India",
            topic="Non-Cooperation Movement",
            lesson_mode="revision_video",
            source_export_format="audio_script_export",
            render_type="narrated_video",
            requested_scene_count=3,
            requested_segment_count=3,
            max_attempts=2,
            status_note="Queued for background execution.",
        )

        claimed = claim_media_render_job_for_worker(
            db,
            job=job,
            worker_id="worker-a",
            lease_seconds=60,
            occurred_at=anchor,
        )
        retryable = mark_media_render_job_retryable_failed(
            db,
            job=claimed,
            failure_code="scene_render_retryable",
            failure_message="Temporary narration timeout.",
            retry_after_at=anchor + timedelta(minutes=1),
            status_note="Scene rendering hit a temporary issue. Trying again soon.",
            occurred_at=anchor + timedelta(seconds=10),
        )
        claimed_again = claim_media_render_job_for_worker(
            db,
            job=retryable,
            worker_id="worker-b",
            lease_seconds=60,
            occurred_at=anchor + timedelta(minutes=2),
        )
        claimed_again.lifecycle_state = "abandoned"
        claimed_again.claimed_by = None
        claimed_again.claim_expires_at = None
        claimed_again.retry_after_at = anchor + timedelta(minutes=3)
        claimed_again.failure_code = "worker_claim_expired"
        claimed_again.failure_message = "Render execution did not complete before the worker claim expired."
        claimed_again.status_note = "Media generation was interrupted and will retry soon."
        db.add(claimed_again)
        db.commit()
        db.refresh(claimed_again)

        repaired = mark_exhausted_retryable_media_render_jobs_failed(db, now=anchor + timedelta(minutes=4))
        assert [item.id for item in repaired] == [job.id]

        repaired_job = get_media_render_job_for_user(db, job_id=job.id, user_id=user_id)
        assert repaired_job is not None
        serialized_repaired = serialize_media_render_job(repaired_job)

        assert repaired_job.lifecycle_state == "failed"
        assert repaired_job.failure_code == "worker_claim_expired"
        assert repaired_job.retry_after_at is None
        assert serialized_repaired["lifecycle_state"] == "failed"
        assert serialized_repaired["failure_message"] == "Media generation could not complete after a few tries. Please try again."
    finally:
        db.close()


def test_phase34_stale_queued_jobs_are_recovered_for_restart_window(client: TestClient) -> None:
    auth = authenticate_premium_test_user(client, email="phase34-stale-queued@example.com", display_name="Phase 34 Stale Queued")
    user_id = auth["user"]["id"]
    anchor = datetime(2026, 5, 10, 14, 0, 0, tzinfo=UTC)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=2,
            requested_segment_count=2,
            max_attempts=3,
            dispatch_payload={
                "dispatch_kind": "audio",
                "render_type": "audio",
                "audio_script_payload": {},
            },
            status_note="Queued for audio generation.",
        )
        job.queued_at = anchor - timedelta(minutes=20)
        job.created_at = anchor - timedelta(minutes=20)
        job.updated_at = anchor - timedelta(minutes=20)
        db.add(job)
        db.commit()
        db.refresh(job)

        recovered_jobs = recover_stale_queued_media_render_jobs(
            db,
            now=anchor,
            stale_after_seconds=300,
        )
        assert [item.id for item in recovered_jobs] == [job.id]

        recovered_job = get_media_render_job_for_user(db, job_id=job.id, user_id=user_id)
        assert recovered_job is not None
        serialized_recovered = serialize_media_render_job(recovered_job)

        assert recovered_job.lifecycle_state == "retryable_failed"
        assert recovered_job.attempt_count == 0
        assert recovered_job.failure_code == "queue_start_delayed"
        assert recovered_job.retry_after_at is not None
        assert normalize_test_datetime(recovered_job.queued_at) == anchor
        assert recovered_job.status_note == "Media generation is taking longer than usual. Trying again soon."
        assert serialized_recovered["lifecycle_state"] == "queued"
        assert serialized_recovered["failure_code"] is None
        assert serialized_recovered["failure_message"] is None
    finally:
        db.close()


def test_phase34_worker_defers_claimable_jobs_when_storage_is_temporarily_unavailable(
    client: TestClient,
    tmp_path: Path,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase34-storage-deferral@example.com", display_name="Phase 34 Storage Deferral")
    user_id = auth["user"]["id"]
    blocked_storage_root = tmp_path / "blocked-render-output"
    blocked_storage_root.write_text("not-a-directory", encoding="utf-8")
    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(blocked_storage_root),
    )
    audio_script = build_audio_script_export_payload(
        {
            "exam": "upsc",
            "subject": "polity",
            "content_subject": "polity",
            "topic": "Preamble",
            "chapter": "General",
            "lesson_mode": "video_lecture",
            "media_ready_content": {
                "title": "Preamble",
                "narration_segments": [
                    {
                        "segment_number": 1,
                        "scene_title": "Opening frame",
                        "narration_text": "The preamble gives the constitutional promise before the detailed articles begin.",
                        "duration_hint": "short",
                        "source_section": "intro",
                    }
                ],
            },
        }
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=1,
            requested_segment_count=1,
            dispatch_payload=build_audio_render_dispatch_payload(
                action_name="media_render.audio_create",
                quota_snapshots={},
                audio_script=audio_script,
            ),
            status_note="Queued for audio generation.",
        )
        job_id = job.id
    finally:
        db.close()

    processed = run_media_render_worker_once(
        session_factory,
        settings=settings,
        worker_id="worker-storage-deferral",
    )
    assert processed is True

    db = session_factory()
    try:
        deferred_job = get_media_render_job_for_user(db, job_id=job_id, user_id=user_id)
        assert deferred_job is not None
        serialized_deferred = serialize_media_render_job(deferred_job)

        assert deferred_job.lifecycle_state == "retryable_failed"
        assert deferred_job.attempt_count == 0
        assert deferred_job.failure_code == "media_storage_temporarily_unavailable"
        assert deferred_job.retry_after_at is not None
        assert deferred_job.status_note == "Media generation is delayed right now. Trying again soon."
        assert serialized_deferred["lifecycle_state"] == "queued"
        assert serialized_deferred["failure_code"] is None
        assert serialized_deferred["failure_message"] is None
    finally:
        db.close()


def test_media_worker_executes_slide_render_from_completely_missing_storage_root(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import video_render_service

    authenticate_premium_test_user(
        client,
        email="clean-checkout-media@example.com",
        display_name="Clean Checkout Media",
    )
    storage_root = tmp_path / "clean-source" / "generated_media" / "renders"
    settings = Settings(
        tts_provider="disabled",
        media_render_worker_mode="embedded",
        media_render_output_dir=str(storage_root),
    )
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)
    assert storage_root.exists() is False

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    processed = run_media_render_worker_once(
        client.app.state.testing_session_factory,
        settings=settings,
        worker_id="clean-checkout-worker",
    )

    assert processed is True
    assert storage_root.is_dir()
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_id).first()
        assert job is not None
        assert job.lifecycle_state == "succeeded"
        assert job.output_content_type == "application/zip"
        output_metadata = json.loads(job.output_metadata_json)
        assert output_metadata["render_style"] == "scene_slide_package"
        assert output_metadata["cinematic_video"] is False
        archive_path = resolve_media_render_asset_path(job, settings=settings)
        assert archive_path is not None, {
            "stored_path": job.output_asset_path,
            "storage_root": storage_root.as_posix(),
            "written_files": [path.as_posix() for path in storage_root.rglob("*") if path.is_file()],
        }
        assert archive_path.is_file()
        assert archive_path.suffix == ".zip"
        assert archive_path.resolve().is_relative_to(storage_root.resolve())
    finally:
        db.close()


def test_phase28_openai_tts_render_job_writes_segment_audio_bundle_and_succeeds(client: TestClient, tmp_path: Path) -> None:
    auth = authenticate_premium_test_user(client, email="phase28-tts-owner@example.com", display_name="Phase 28 TTS Owner")
    user_id = auth["user"]["id"]
    audio_script = build_audio_script_export_payload(
        {
            "exam": "upsc",
            "subject": "polity",
            "content_subject": "polity",
            "topic": "Preamble",
            "chapter": "General",
            "lesson_mode": "video_lecture",
            "lesson_outline_state": "steady_learning",
            "teaching_pacing": "balanced",
            "teaching_support": "supportive",
            "media_ready_content": {
                "title": "Preamble",
                "narration_segments": [
                    {
                        "segment_number": 1,
                        "scene_title": "Opening frame",
                        "narration_text": "The preamble sets the constitutional promise before the detailed articles begin.",
                        "duration_hint": "short",
                        "source_section": "intro",
                    },
                    {
                        "segment_number": 2,
                        "scene_title": "Core idea",
                        "narration_text": "Its language helps us see justice, liberty, equality, and fraternity as the guiding frame of the Constitution.",
                        "duration_hint": "medium",
                        "source_section": "body",
                    },
                ],
                "visual_cue_suggestions": [],
            },
            "video_lesson_script": {"visual_style_note": "Warm explanatory classroom narration."},
        }
    )
    captured_calls: list[dict[str, Any]] = []
    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "render-output"),
    )

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout_seconds: float):
            self.timeout_seconds = timeout_seconds

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            captured_calls.append(
                {
                    "url": url,
                    "headers": headers or {},
                    "json": dict(json or {}),
                    "timeout_seconds": self.timeout_seconds,
                }
            )
            payload = json or {}
            return FakeResponse(f"AUDIO::{payload.get('input', '')}".encode("utf-8"))

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            source_content_corpus_id="upsc-shared-core",
            source_content_scope="exam_primary",
            requested_scene_count=2,
            requested_segment_count=2,
        )
        rendered_job = render_audio_job_from_audio_script(
            db,
            job=job,
            audio_script=audio_script,
            settings=settings,
            http_client_factory=lambda timeout_seconds: FakeClient(timeout_seconds),
        )

        assert rendered_job.lifecycle_state == "succeeded"
        assert rendered_job.status_note == "Audio is ready to download."
        assert rendered_job.output_asset_filename.endswith(".zip")
        assert rendered_job.output_content_type == "application/zip"
        assert rendered_job.output_file_size_bytes is not None and rendered_job.output_file_size_bytes > 0
        output_metadata = json.loads(rendered_job.output_metadata_json)
        assert output_metadata["segment_audio_bundle"] is True
        assert output_metadata["segment_count"] == 2
        assert output_metadata["provider_runtime"]["provider"] == "openai"
        assert output_metadata["provider_runtime"]["voice"] == "alloy"
        assert output_metadata["manifest_path"] == "manifest.json"
        assert not Path(rendered_job.output_asset_path or "").is_absolute()

        archive_path = resolve_media_render_asset_path(rendered_job, settings=settings)
        assert archive_path is not None
        assert archive_path.exists()
        with zipfile.ZipFile(archive_path) as archive:
            names = sorted(archive.namelist())
            assert "manifest.json" in names
            assert any(name.endswith(".mp3") for name in names)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["provider_runtime"]["provider"] == "openai"
        assert len(manifest["segments"]) == 2
        assert all(segment["audio_asset_filename"].endswith(".mp3") for segment in manifest["segments"])
        assert all(segment["audio_asset_path"] == segment["audio_asset_filename"] for segment in manifest["segments"])

        assert len(captured_calls) == 2
        assert all(call["url"].endswith("/audio/speech") for call in captured_calls)
        assert all(call["json"]["model"] == "gpt-4o-mini-tts" for call in captured_calls)
        assert all(call["json"]["voice"] == "alloy" for call in captured_calls)
        assert all(call["json"]["response_format"] == "mp3" for call in captured_calls)
    finally:
        db.close()


def test_phase28_tts_render_failure_marks_job_failed_and_preserves_audio_script_export(client: TestClient, tmp_path: Path) -> None:
    auth = authenticate_premium_test_user(client, email="phase28-tts-failure@example.com", display_name="Phase 28 TTS Failure")
    user_id = auth["user"]["id"]
    audio_script = build_audio_script_export_payload(
        {
            "exam": "upsc",
            "subject": "polity",
            "content_subject": "polity",
            "topic": "Directive Principles",
            "chapter": "General",
            "lesson_mode": "revision_video",
            "lesson_outline_state": "revision_heavy",
            "media_ready_content": {
                "title": "Directive Principles",
                "narration_segments": [
                    {
                        "segment_number": 1,
                        "scene_title": "Recall frame",
                        "narration_text": "Recall the Directive Principles as the constitutional direction for governance rather than enforceable rights.",
                        "duration_hint": "short",
                        "source_section": "recap",
                    }
                ],
            },
        }
    )

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="revision_video",
            source_export_format="audio_script_export",
            render_type="audio",
            requested_scene_count=1,
            requested_segment_count=1,
        )
        rendered_job = render_audio_job_from_audio_script(
            db,
            job=job,
            audio_script=audio_script,
            settings=Settings(
                tts_provider="disabled",
                media_render_output_dir=str(tmp_path / "render-output"),
            ),
        )

        assert rendered_job.lifecycle_state == "failed"
        assert rendered_job.failure_code == "tts_provider_unavailable"
        assert rendered_job.output_asset_path is None
        assert rendered_job.output_asset_filename is None
        assert audio_script.metadata.rendering_status == "audio_script_ready_package_only"
        assert audio_script.rendering_outputs["rendered_audio_available"] is False
        assert audio_script.rendering_outputs["audio_url"] is None
    finally:
        db.close()


def test_phase28_audio_render_workflow_route_creates_job_returns_status_and_download(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate_premium_test_user(client, email="phase28-route-premium@example.com", display_name="Phase 28 Route Premium")

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            payload = dict(json or {})
            return FakeResponse(f"ROUTE-AUDIO::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service

    monkeypatch.setattr(
        tts_service,
        "get_settings",
        lambda: Settings(
            tts_provider="openai",
            tts_openai_api_key="test-openai-tts-key",
            tts_openai_model="gpt-4o-mini-tts",
            tts_openai_voice="alloy",
            tts_output_format="mp3",
            media_render_output_dir=str(tmp_path / "render-output"),
        ),
    )
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["render_type"] == "audio"
    assert job_body["lifecycle_state"] == "queued"
    assert job_body["requested_segment_count"] >= 1
    assert job_body["output"]["asset_filename"] is None
    assert job_body["output"]["download_path"] is None

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/audio/{job_body['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["id"] == job_body["id"]
    assert status_body["lifecycle_state"] == "succeeded"
    assert status_body["output"]["asset_filename"].endswith(".zip")
    assert status_body["output"]["download_path"] == f"/api/tutor/render/audio/{job_body['id']}/download"

    download_response = client.get(status_body["output"]["download_path"])
    assert download_response.status_code == 200
    assert download_response.headers["cache-control"] == "private, no-store, max-age=0"
    assert download_response.headers["x-content-type-options"] == "nosniff"
    assert download_response.headers["x-adhyantra-render-job"] == str(job_body["id"])
    assert "attachment; filename=" in download_response.headers["content-disposition"]

    list_jobs_response = client.get("/api/tutor/render/jobs")
    assert list_jobs_response.status_code == 200
    listed_jobs = list_jobs_response.json()
    assert [item["id"] for item in listed_jobs] == [job_body["id"]]
    assert listed_jobs[0]["output"]["download_path"] == status_body["output"]["download_path"]

    list_assets_response = client.get("/api/tutor/render/assets?render_type=audio")
    assert list_assets_response.status_code == 200
    listed_assets = list_assets_response.json()
    assert [item["id"] for item in listed_assets] == [job_body["id"]]

    with zipfile.ZipFile(BytesIO(download_response.content)) as archive:
        archive_names = sorted(archive.namelist())
        assert "manifest.json" in archive_names
        assert any(name.endswith(".mp3") for name in archive_names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["lesson_context"]["topic"] == "Preamble"
    assert manifest["provider_runtime"]["provider"] == "openai"
    assert manifest["segments"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        stored_job = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_body["id"]).first()
        assert stored_job is not None
        assert stored_job.last_downloaded_at is not None
    finally:
        db.close()


def test_phase28_audio_render_route_fails_safely_and_download_stays_blocked(client: TestClient) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase28-route-failure@example.com",
        display_name="Phase 28 Route Failure",
    )
    user_id = auth["user"]["id"]

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Directive Principles",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["render_type"] == "audio"
    assert job_body["lifecycle_state"] == "queued"
    assert job_body["output"]["download_path"] is None

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "failed"
    assert terminal_job.failure_code == "tts_provider_unavailable"

    status_response = client.get(f"/api/tutor/render/audio/{job_body['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["lifecycle_state"] == "failed"
    assert status_response.json()["failure_code"] == "tts_provider_unavailable"
    assert status_response.json()["failure_message"] == "Audio generation is unavailable right now."

    list_jobs_response = client.get("/api/tutor/render/jobs?render_type=audio")
    assert list_jobs_response.status_code == 200
    listed_jobs = list_jobs_response.json()
    assert [item["id"] for item in listed_jobs] == [job_body["id"]]
    assert listed_jobs[0]["asset_ready"] is False

    list_assets_response = client.get("/api/tutor/render/assets")
    assert list_assets_response.status_code == 200
    assert list_assets_response.json() == []

    download_response = client.get(f"/api/tutor/render/audio/{job_body['id']}/download")
    assert download_response.status_code == 409
    assert download_response.json()["detail"] == "This audio could not be prepared. Generate it again if you still need it."

    media_usage_records = get_usage_consumption_records(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
    )
    assert media_usage_records == []

    assert wait_for_media_render_event_names(
        client,
        user_id=user_id,
        exam="upsc",
        expected_event_names=[
            "lesson.audio_render_failed",
            "lesson.audio_render_download_unavailable",
        ],
    ) == [
        "lesson.audio_render_failed",
        "lesson.audio_render_download_unavailable",
    ]


def test_phase34_media_render_asset_resolver_supports_legacy_project_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services import media_storage_service

    temp_project_root = (tmp_path / "legacy-project-root").resolve()
    legacy_output_root = temp_project_root / "backend" / "media_render_output"
    legacy_output_root.mkdir(parents=True, exist_ok=True)
    archive_path = legacy_output_root / "tests" / "legacy-audio.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"LEGACY-AUDIO")

    monkeypatch.setattr(media_storage_service, "PROJECT_ROOT", temp_project_root)
    monkeypatch.setattr(media_storage_service, "LEGACY_MEDIA_RENDER_OUTPUT_DIR", legacy_output_root)

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "active-render-output"),
    )
    job = MediaRenderJob(
        render_type="audio",
        lifecycle_state="succeeded",
        output_asset_path="backend/media_render_output/tests/legacy-audio.zip",
    )

    resolved = resolve_media_render_asset_path(job, settings=settings)

    assert resolved == archive_path.resolve()


def test_phase33_expired_render_artifact_is_hidden_and_download_blocked(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase33-expired-artifact@example.com",
        display_name="Phase 33 Expired Artifact",
    )
    user_id = auth["user"]["id"]

    from backend.services import tts_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "artifact-retention-output"),
        media_render_artifact_retention_hours=24,
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)

    output_directory = settings.effective_media_render_output_dir / "expired-audio-job"
    output_directory.mkdir(parents=True, exist_ok=True)
    asset_path = output_directory / "expired-audio.zip"
    asset_path.write_bytes(b"expired-audio")

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=job,
            output_metadata={"format": "zip"},
            output_asset_filename="expired-audio.zip",
            output_asset_path=str(asset_path),
            output_content_type="application/zip",
            output_file_size_bytes=asset_path.stat().st_size,
            artifact_retention_expires_at=datetime.now(UTC) - timedelta(minutes=5),
            status_note="Audio is ready to download.",
        )
        job_id = job.id
    finally:
        db.close()

    status_response = client.get(f"/api/tutor/render/audio/{job_id}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["lifecycle_state"] == "failed"
    assert status_body["asset_ready"] is False
    assert status_body["failure_code"] == "artifact_expired"
    assert status_body["failure_message"] == "This media is no longer available to download. Generate it again if you still need it."
    assert status_body["output"]["download_path"] is None

    assets_response = client.get("/api/tutor/render/assets?render_type=audio")
    assert assets_response.status_code == 200
    assert assets_response.json() == []

    download_response = client.get(f"/api/tutor/render/audio/{job_id}/download")
    assert download_response.status_code == 410
    assert download_response.json()["detail"] == "This audio is no longer available to download. Generate it again if you still need it."


def test_phase33_missing_render_artifact_is_marked_deleted_and_download_returns_gone(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase33-missing-artifact@example.com",
        display_name="Phase 33 Missing Artifact",
    )
    user_id = auth["user"]["id"]

    from backend.services import tts_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "missing-artifact-output"),
        media_render_artifact_retention_hours=24,
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)

    missing_output_directory = settings.effective_media_render_output_dir / "missing-audio-job"
    missing_asset_path = missing_output_directory / "missing-audio.zip"

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=job,
            output_metadata={"format": "zip"},
            output_asset_filename="missing-audio.zip",
            output_asset_path=str(missing_asset_path),
            output_content_type="application/zip",
            output_file_size_bytes=128,
            artifact_retention_expires_at=datetime.now(UTC) + timedelta(hours=4),
            status_note="Audio is ready to download.",
        )
        job_id = job.id
    finally:
        db.close()

    download_response = client.get(f"/api/tutor/render/audio/{job_id}/download")
    assert download_response.status_code == 410
    assert download_response.json()["detail"] == "This audio is no longer available to download. Generate it again if you still need it."

    status_response = client.get(f"/api/tutor/render/audio/{job_id}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["lifecycle_state"] == "failed"
    assert status_body["failure_code"] == "artifact_expired"
    assert status_body["output"]["download_path"] is None

    db = session_factory()
    try:
        refreshed = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_id).first()
        assert refreshed is not None
        assert refreshed.artifact_deleted_at is not None
        assert refreshed.artifact_cleanup_error == "artifact_file_missing"
    finally:
        db.close()

    assert wait_for_media_render_event_names(
        client,
        user_id=user_id,
        exam="upsc",
        expected_event_names=["lesson.audio_render_download_unavailable"],
    ) == ["lesson.audio_render_download_unavailable"]


def test_phase33_expired_render_artifacts_are_cleaned_from_output_storage(
    client: TestClient,
    tmp_path: Path,
) -> None:
    session_factory = client.app.state.testing_session_factory
    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "cleanup-output"),
        media_render_artifact_retention_hours=24,
    )
    output_directory = settings.effective_media_render_output_dir / "job-1-cleanup"
    output_directory.mkdir(parents=True, exist_ok=True)
    asset_path = output_directory / "lesson-audio.zip"
    asset_path.write_bytes(b"cleanup-me")
    (output_directory / "manifest.json").write_text("{}", encoding="utf-8")

    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=None,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=job,
            output_metadata={"format": "zip"},
            output_asset_filename="lesson-audio.zip",
            output_asset_path=str(asset_path),
            output_content_type="application/zip",
            output_file_size_bytes=asset_path.stat().st_size,
            artifact_retention_expires_at=datetime.now(UTC) - timedelta(hours=1),
            status_note="Audio is ready to download.",
        )
        job_id = job.id

        cleaned_jobs = cleanup_expired_media_render_artifacts(
            db,
            settings=settings,
            now=datetime.now(UTC),
        )
        assert [item.id for item in cleaned_jobs] == [job_id]

        refreshed = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_id).first()
        assert refreshed is not None
        assert refreshed.artifact_deleted_at is not None
        assert refreshed.artifact_cleanup_attempted_at is not None
        assert refreshed.artifact_cleanup_retry_after_at is None
        assert refreshed.artifact_cleanup_failure_count == 0
        assert refreshed.artifact_cleanup_error is None
    finally:
        db.close()

    assert not output_directory.exists()


def test_phase33_artifact_cleanup_failures_back_off_safely(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = client.app.state.testing_session_factory
    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "cleanup-failure-output"),
        media_render_artifact_retention_hours=24,
    )
    output_directory = settings.effective_media_render_output_dir / "job-2-cleanup"
    output_directory.mkdir(parents=True, exist_ok=True)
    asset_path = output_directory / "lesson-audio.zip"
    asset_path.write_bytes(b"cleanup-failure")

    db = session_factory()
    try:
        job = create_media_render_job(
            db,
            user_id=None,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="General",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=job,
            output_metadata={"format": "zip"},
            output_asset_filename="lesson-audio.zip",
            output_asset_path=str(asset_path),
            output_content_type="application/zip",
            output_file_size_bytes=asset_path.stat().st_size,
            artifact_retention_expires_at=datetime.now(UTC) - timedelta(hours=1),
            status_note="Audio is ready to download.",
        )
        job_id = job.id

        from backend.services import media_render_service

        def fail_cleanup(*args: Any, **kwargs: Any) -> None:
            raise OSError("cleanup target is locked")

        monkeypatch.setattr(media_render_service.shutil, "rmtree", fail_cleanup)

        cleaned_jobs = cleanup_expired_media_render_artifacts(
            db,
            settings=settings,
            now=datetime.now(UTC),
        )
        assert cleaned_jobs == []

        refreshed = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_id).first()
        assert refreshed is not None
        assert refreshed.artifact_deleted_at is None
        assert refreshed.artifact_cleanup_attempted_at is not None
        assert refreshed.artifact_cleanup_retry_after_at is not None
        assert refreshed.artifact_cleanup_retry_after_at > refreshed.artifact_cleanup_attempted_at
        assert refreshed.artifact_cleanup_failure_count == 1
        assert refreshed.artifact_cleanup_error == "cleanup target is locked"
    finally:
        db.close()


def test_phase28_audio_render_status_and_download_are_owner_scoped(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate_premium_test_user(client, email="phase28-route-owner-a@example.com", display_name="Phase 28 Owner A")

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            payload = dict(json or {})
            return FakeResponse(f"SCOPED-AUDIO::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service

    monkeypatch.setattr(
        tts_service,
        "get_settings",
        lambda: Settings(
            tts_provider="openai",
            tts_openai_api_key="test-openai-tts-key",
            tts_openai_model="gpt-4o-mini-tts",
            tts_openai_voice="alloy",
            tts_output_format="mp3",
            media_render_output_dir=str(tmp_path / "render-output"),
        ),
    )
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    authenticate_premium_test_user(client, email="phase28-route-owner-b@example.com", display_name="Phase 28 Owner B")

    status_response = client.get(f"/api/tutor/render/audio/{job_id}")
    assert status_response.status_code == 404

    download_response = client.get(f"/api/tutor/render/audio/{job_id}/download")
    assert download_response.status_code == 404

    list_jobs_response = client.get("/api/tutor/render/jobs")
    assert list_jobs_response.status_code == 200
    assert list_jobs_response.json() == []

    list_assets_response = client.get("/api/tutor/render/assets")
    assert list_assets_response.status_code == 200
    assert list_assets_response.json() == []


def test_phase28_free_user_cannot_create_audio_render_job(client: TestClient) -> None:
    authenticate_test_user(client, email="phase28-free-render@example.com", display_name="Phase 28 Free Render")

    response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "mini_lesson",
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "lesson_exports"
    assert detail["required_plan"] == "premium"


def test_phase29_failed_narrated_video_render_does_not_consume_media_quota_and_tracks_failure(
    client: TestClient,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase29-video-render-failure@example.com",
        display_name="Phase 29 Video Render Failure",
    )
    user_id = auth["user"]["id"]

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Directive Principles",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["render_type"] == "narrated_video"
    assert job_body["lifecycle_state"] == "queued"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "failed"

    media_usage_records = get_usage_consumption_records(
        client,
        user_id=user_id,
        limit_key="media_render_creations",
    )
    assert media_usage_records == []

    assert wait_for_media_render_event_names(
        client,
        user_id=user_id,
        exam="upsc",
        expected_event_names=[
        "lesson.video_render_failed",
        ],
    ) == [
        "lesson.video_render_failed",
    ]


def test_phase28_video_render_workflow_route_creates_narrated_scene_package(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate_premium_test_user(client, email="phase28-video-premium@example.com", display_name="Phase 28 Video Premium")

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            payload = dict(json or {})
            return FakeResponse(f"VIDEO-AUDIO::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "video-render-output"),
    )
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["render_type"] == "narrated_video"
    assert job_body["lifecycle_state"] == "queued"
    assert job_body["status_note"] == "Queued for narrated scene rendering."

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/video/{job_body['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["render_type"] == "narrated_video"
    assert status_body["lifecycle_state"] == "succeeded"
    assert status_body["output"]["asset_filename"].endswith(".zip")
    assert status_body["output"]["download_path"] == f"/api/tutor/render/video/{job_body['id']}/download"
    assert status_body["output"]["metadata"]["render_style"] == "scene_slide_package"
    assert status_body["output"]["metadata"]["cinematic_video"] is False
    assert status_body["output"]["metadata"]["narrated_audio_included"] is True

    list_assets_response = client.get("/api/tutor/render/assets?render_type=narrated_video")
    assert list_assets_response.status_code == 200
    listed_assets = list_assets_response.json()
    assert [item["id"] for item in listed_assets] == [job_body["id"]]

    download_response = client.get(status_body["output"]["download_path"])
    assert download_response.status_code == 200
    with zipfile.ZipFile(BytesIO(download_response.content)) as archive:
        names = sorted(archive.namelist())
        assert "index.html" in names
        assert "manifest.json" in names
        assert any(name.endswith(".svg") for name in names)
        assert any(name.endswith(".mp3") for name in names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["render_type"] == "narrated_video"
    assert manifest["render_style"] == "scene_slide_package"
    assert manifest["cinematic_video"] is False
    assert manifest["narrated_audio_included"] is True
    assert manifest["scene_assets"]
    assert all(item["scene_asset_path"] == item["scene_asset_filename"] for item in manifest["scene_assets"])
    assert all((item["audio_asset_path"] is None) or (item["audio_asset_path"] == item["audio_asset_filename"]) for item in manifest["scene_assets"])
    assert status_body["output"]["metadata"]["entrypoint_path"] == "index.html"
    assert status_body["output"]["metadata"]["manifest_path"] == "manifest.json"


def test_phase28_slide_video_render_route_succeeds_without_tts(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate_premium_test_user(client, email="phase28-slide-video@example.com", display_name="Phase 28 Slide Video")

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "slide-video-output"),
    )
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Directive Principles",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["render_type"] == "slide_video"
    assert job_body["lifecycle_state"] == "queued"
    assert job_body["status_note"] == "Queued for scene rendering."

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "succeeded"

    status_response = client.get(f"/api/tutor/render/video/{job_body['id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["output"]["metadata"]["narrated_audio_included"] is False

    download_response = client.get(status_body["output"]["download_path"])
    assert download_response.status_code == 200
    with zipfile.ZipFile(BytesIO(download_response.content)) as archive:
        names = sorted(archive.namelist())
        assert "index.html" in names
        assert "manifest.json" in names
        assert any(name.endswith(".svg") for name in names)
        assert not any(name.endswith(".mp3") for name in names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["render_type"] == "slide_video"
    assert manifest["narrated_audio_included"] is False
    assert manifest["cinematic_video"] is False
    assert all(item["scene_asset_path"] == item["scene_asset_filename"] for item in manifest["scene_assets"])


def test_phase28_video_render_status_and_download_are_owner_scoped(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authenticate_premium_test_user(client, email="phase28-video-owner-a@example.com", display_name="Phase 28 Video Owner A")

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float | None = None, **_: Any):
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict[str, Any] | None = None) -> FakeResponse:
            payload = dict(json or {})
            return FakeResponse(f"SCOPED-VIDEO::{payload.get('input', '')}".encode("utf-8"))

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="openai",
        tts_openai_api_key="test-openai-tts-key",
        tts_openai_model="gpt-4o-mini-tts",
        tts_openai_voice="alloy",
        tts_output_format="mp3",
        media_render_output_dir=str(tmp_path / "video-owner-output"),
    )
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(tts_service.httpx, "Client", FakeClient)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    authenticate_premium_test_user(client, email="phase28-video-owner-b@example.com", display_name="Phase 28 Video Owner B")

    status_response = client.get(f"/api/tutor/render/video/{job_id}")
    assert status_response.status_code == 404

    download_response = client.get(f"/api/tutor/render/video/{job_id}/download")
    assert download_response.status_code == 404

    list_jobs_response = client.get("/api/tutor/render/jobs?render_type=narrated_video")
    assert list_jobs_response.status_code == 200
    assert list_jobs_response.json() == []


def test_phase28_free_user_cannot_create_video_render_job(client: TestClient) -> None:
    authenticate_test_user(client, email="phase28-free-video@example.com", display_name="Phase 28 Free Video")

    response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "narrated_video",
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["feature_key"] == "premium_lesson_modes"
    assert detail["required_plan"] == "premium"


def test_phase28_export_and_render_routes_do_not_mutate_topic_study_history(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(client, email="phase28-history-safe@example.com", display_name="Phase 28 History Safe")
    user_id = auth["user"]["id"]

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "history-safe-render-output"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        before_count = db.query(TopicStudy).filter(TopicStudy.user_id == user_id).count()
    finally:
        db.close()

    export_response = client.post(
        "/api/tutor/export/lesson/download",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "export_format": "markdown_export",
        },
    )
    assert export_response.status_code == 200

    audio_render_response = client.post(
        "/api/tutor/render/audio",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
        },
    )
    assert audio_render_response.status_code == 200
    assert audio_render_response.json()["lifecycle_state"] == "queued"
    assert wait_for_media_render_job_terminal_state(client, job_id=audio_render_response.json()["id"]).lifecycle_state == "failed"

    video_render_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert video_render_response.status_code == 200
    assert video_render_response.json()["lifecycle_state"] == "queued"
    assert wait_for_media_render_job_terminal_state(client, job_id=video_render_response.json()["id"]).lifecycle_state == "succeeded"

    db = session_factory()
    try:
        after_count = db.query(TopicStudy).filter(TopicStudy.user_id == user_id).count()
    finally:
        db.close()

    assert before_count == after_count == 0


def test_phase28_render_jobs_and_analytics_keep_published_admin_content_identity(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase28-content-identity@example.com",
        display_name="Phase 28 Content Identity",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        content_item = ContentItem(
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Admin Curated",
            topic="Preamble",
            slug="phase-28-render-preamble-admin-topic-note",
            title="Phase 28 Render Preamble Admin Topic Note",
            content_type="topic_note",
            lifecycle_state="published",
            body_markdown="# Preamble\n\nPublished admin-reviewed content used to align render attribution.",
            summary="Published admin content item used for render attribution checks.",
            metadata_json='{"source_scope": "published_admin_content"}',
            source_corpus_id="admin_published_content",
            published_at=datetime.now(UTC),
        )
        db.add(content_item)
        db.commit()
        db.refresh(content_item)
        content_item_id = content_item.id
    finally:
        db.close()

    from backend.services import tts_service, video_render_service

    settings = Settings(
        tts_provider="disabled",
        media_render_output_dir=str(tmp_path / "content-identity-render-output"),
    )
    monkeypatch.setattr(tts_service, "get_settings", lambda: settings)
    monkeypatch.setattr(video_render_service, "get_settings", lambda: settings)

    create_response = client.post(
        "/api/tutor/render/video",
        json={
            "topic": "Preamble",
            "subject": "polity",
            "exam": "upsc",
            "lesson_mode": "video_lecture",
            "render_type": "slide_video",
        },
    )
    assert create_response.status_code == 200
    job_body = create_response.json()
    assert job_body["source_content_item_id"] == content_item_id
    assert job_body["source_content_scope"] == "published_admin_content"
    assert job_body["source_content_corpus_id"] == "admin_published_content"

    terminal_job = wait_for_media_render_job_terminal_state(client, job_id=job_body["id"])
    assert terminal_job.lifecycle_state == "succeeded"

    list_assets_response = client.get("/api/tutor/render/assets?render_type=slide_video")
    assert list_assets_response.status_code == 200
    listed_assets = list_assets_response.json()
    assert [item["id"] for item in listed_assets] == [job_body["id"]]
    assert listed_assets[0]["source_content_item_id"] == content_item_id

    download_response = client.get(f"/api/tutor/render/video/{job_body['id']}")
    assert download_response.status_code == 200
    download_path = download_response.json()["output"]["download_path"]
    assert download_path == f"/api/tutor/render/video/{job_body['id']}/download"

    download_response = client.get(download_path)
    assert download_response.status_code == 200

    db = session_factory()
    try:
        stored_job = db.query(MediaRenderJob).filter(MediaRenderJob.id == job_body["id"]).first()
        assert stored_job is not None
        assert stored_job.source_content_item_id == content_item_id

        render_events = (
            db.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == user_id,
                AnalyticsEvent.feature_area == "media_render",
                AnalyticsEvent.topic == "Preamble",
            )
            .order_by(AnalyticsEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert [event.event_name for event in render_events] == [
        "lesson.video_rendered",
        "lesson.video_render_downloaded",
    ]
    assert all(event.content_item_id == content_item_id for event in render_events)
    assert all(event.content_source_scope == "published_admin_content" for event in render_events)


def test_phase28_render_list_routes_can_filter_by_topic(client: TestClient) -> None:
    auth = authenticate_premium_test_user(
        client,
        email="phase28-topic-filter@example.com",
        display_name="Phase 28 Topic Filter",
    )
    user_id = auth["user"]["id"]

    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        preamble_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Admin Curated",
            topic="Preamble",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="audio",
            status_note="Queued for audio generation.",
        )
        mark_media_render_job_succeeded(
            db,
            job=preamble_job,
            output_metadata={"format": "zip"},
            output_asset_filename="preamble-audio.zip",
            output_asset_path="backend/media_render_output/tests/preamble-audio.zip",
            output_content_type="application/zip",
            output_file_size_bytes=1024,
            status_note="Audio is ready to download.",
        )

        directive_job = create_media_render_job(
            db,
            user_id=user_id,
            exam="upsc",
            subject="polity",
            content_subject="polity",
            chapter="Admin Curated",
            topic="Directive Principles",
            lesson_mode="video_lecture",
            source_export_format="audio_script_export",
            render_type="narrated_video",
            status_note="Queued for scene rendering.",
        )
        mark_media_render_job_succeeded(
            db,
            job=directive_job,
            output_metadata={"format": "zip"},
            output_asset_filename="directive-video.zip",
            output_asset_path="backend/media_render_output/tests/directive-video.zip",
            output_content_type="application/zip",
            output_file_size_bytes=2048,
            status_note="Scene package is ready.",
        )
    finally:
        db.close()

    jobs_response = client.get("/api/tutor/render/jobs?exam=upsc&subject=polity&topic=Preamble")
    assert jobs_response.status_code == 200
    jobs_body = jobs_response.json()
    assert [item["topic"] for item in jobs_body] == ["Preamble"]

    assets_response = client.get("/api/tutor/render/assets?exam=upsc&subject=polity&topic=Directive%20Principles")
    assert assets_response.status_code == 200
    assets_body = assets_response.json()
    assert [item["topic"] for item in assets_body] == ["Directive Principles"]
    assert assets_body[0]["render_type"] == "narrated_video"


def test_phase28_render_list_routes_require_auth(client: TestClient) -> None:
    jobs_response = client.get("/api/tutor/render/jobs")
    assert jobs_response.status_code == 401

    assets_response = client.get("/api/tutor/render/assets")
    assert assets_response.status_code == 401
