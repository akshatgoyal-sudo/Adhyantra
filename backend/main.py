from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.config import get_active_sqlite_db_path, get_settings, normalize_exam, read_demo_seed_metadata
from backend.db import SessionLocal, database_readiness_snapshot, init_db, managed_db_session
from backend.routes.account_billing_routes import router as account_billing_router
from backend.routes.admin_content_routes import router as admin_content_router
from backend.routes.admin_ops_routes import router as admin_ops_router
from backend.routes.auth_routes import router as auth_router
from backend.routes.coach_routes import router as coach_router
from backend.routes.progress_routes import router as progress_router
from backend.routes.test_routes import router as test_router
from backend.routes.topic_routes import router as topic_router
from backend.routes.tutor_routes import router as tutor_router
from backend.services.media_render_dispatch_service import start_media_render_dispatcher, stop_media_render_dispatcher
from backend.services.media_render_ops_service import build_media_render_pipeline_snapshot, build_media_render_worker_snapshot
from backend.services.media_render_service import recover_stale_queued_media_render_jobs
from backend.services.ops_logging import log_event, request_log_context, stable_hash


settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.effective_log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("adhyantra.events")


def _sanitize_request_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return uuid.uuid4().hex
    safe = "".join(character for character in candidate[:80] if character.isalnum() or character in {"-", "_", "."})
    return safe or uuid.uuid4().hex


def _safe_validation_errors(exc: RequestValidationError) -> list[dict]:
    safe_errors = []
    for error in exc.errors():
        safe_errors.append(
            {
                "loc": list(error.get("loc") or []),
                "msg": str(error.get("msg") or "Invalid value."),
                "type": str(error.get("type") or "validation_error"),
            }
        )
    return safe_errors


def _safe_http_detail(detail: object) -> str:
    if isinstance(detail, str):
        if "@" in detail:
            return "redacted"
        return detail[:200]
    return type(detail).__name__


def _utc_iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _state_value(name: str, default: object = None) -> object:
    return getattr(app.state, name, default)


def _build_demo_seed_debug_context(demo_seed_metadata: dict | None) -> dict | None:
    if not isinstance(demo_seed_metadata, dict):
        return None

    raw_accounts = demo_seed_metadata.get("accounts")
    account_keys = [
        str(item.get("key") or "").strip()
        for item in raw_accounts
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ] if isinstance(raw_accounts, list) else []
    raw_scenarios = demo_seed_metadata.get("scenarios")
    scenarios = [
        str(item or "").strip()
        for item in raw_scenarios
        if str(item or "").strip()
    ] if isinstance(raw_scenarios, list) else []
    scenario = str(demo_seed_metadata.get("scenario") or "").strip() or None
    if scenario and scenario not in scenarios:
        scenarios = [scenario, *scenarios]

    note = str(demo_seed_metadata.get("note") or "").strip() or None
    mode = str(demo_seed_metadata.get("mode") or "").strip() or None
    seeded_at = str(demo_seed_metadata.get("seeded_at") or "").strip() or None

    return {
        "visible": True,
        "mode": mode,
        "seeded_at": seeded_at,
        "scenario": scenario or (scenarios[0] if scenarios else None),
        "scenarios": scenarios,
        "account_keys": account_keys,
        "account_count": len(account_keys),
        "note": note,
    }


def _boot_snapshot() -> dict:
    return {
        "status": str(_state_value("boot_status", "not_started")),
        "started_at": _state_value("boot_started_at"),
        "completed_at": _state_value("boot_completed_at"),
        "failed_at": _state_value("boot_failed_at"),
        "failure_type": _state_value("boot_failure_type"),
    }


def _public_worker_readiness_note(worker_snapshot: dict[str, object]) -> str:
    mode = str(worker_snapshot.get("mode") or "").strip().lower()
    ready = bool(worker_snapshot.get("ready"))
    if mode == "disabled":
        return "Media worker is disabled."
    if ready:
        return "Media worker is available."
    return "Media worker is unavailable."


def _public_pipeline_degraded_reasons(pipeline_snapshot: dict[str, object]) -> list[str]:
    public_reasons: list[str] = []
    seen: set[str] = set()
    for reason in pipeline_snapshot.get("degraded_reasons") or []:
        normalized = str(reason or "").strip().lower()
        if normalized in {
            "storage_root_not_directory",
            "storage_parent_missing",
            "storage_parent_not_directory",
            "storage_unavailable",
        }:
            public_reason = "storage_unavailable"
        elif normalized == "storage_path_project_local_for_external_worker":
            public_reason = "shared_storage_recommended"
        elif normalized in {"worker_unavailable", "worker_mode_disabled"}:
            public_reason = normalized
        else:
            public_reason = normalized or "pipeline_unavailable"
        if public_reason not in seen:
            seen.add(public_reason)
            public_reasons.append(public_reason)
    return public_reasons


def _public_pipeline_readiness_note(pipeline_snapshot: dict[str, object]) -> str:
    mode = str(pipeline_snapshot.get("mode") or "").strip().lower()
    ready = bool(pipeline_snapshot.get("ready"))
    storage_ready = bool(pipeline_snapshot.get("storage_ready"))
    degraded_reasons = set(_public_pipeline_degraded_reasons(pipeline_snapshot))

    if ready:
        return "Media pipeline is available."
    if mode == "disabled":
        return "Media pipeline is disabled."
    if not storage_ready:
        return "Media pipeline storage is unavailable."
    if "worker_unavailable" in degraded_reasons:
        return "Media pipeline is waiting for worker availability."
    return "Media pipeline is not fully available."


def _public_worker_readiness_snapshot(worker_snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "mode": str(worker_snapshot.get("mode") or "").strip().lower() or "disabled",
        "ready": bool(worker_snapshot.get("ready")),
        "required_for_readiness": bool(worker_snapshot.get("required_for_readiness")),
        "note": _public_worker_readiness_note(worker_snapshot),
    }


def _public_pipeline_readiness_snapshot(pipeline_snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "mode": str(pipeline_snapshot.get("mode") or "").strip().lower() or "disabled",
        "ready": bool(pipeline_snapshot.get("ready")),
        "required_for_readiness": bool(pipeline_snapshot.get("required_for_readiness")),
        "submission_ready": bool(pipeline_snapshot.get("submission_ready")),
        "execution_ready": bool(pipeline_snapshot.get("execution_ready")),
        "storage_ready": bool(pipeline_snapshot.get("storage_ready")),
        "degraded_reasons": _public_pipeline_degraded_reasons(pipeline_snapshot),
        "note": _public_pipeline_readiness_note(pipeline_snapshot),
    }


def _public_database_type() -> str:
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    if sqlite_db_path is not None:
        return "sqlite"
    return str(settings.db_url or "").split(":", 1)[0] or "unknown"


def _safe_runtime_config_snapshot() -> dict:
    validation = settings.validate_runtime_config(process_role="api")
    return {
        "environment": settings.environment_name,
        "environment_policy": settings.environment_policy_summary(),
        "app_version": settings.app_version,
        "release": {
            "commit_configured": bool(str(settings.release_commit or "").strip()),
            "deployment_id_configured": bool(str(settings.deployment_id or "").strip()),
        },
        "config_validation": validation.to_public_dict(),
        "ai": settings.ai_runtime_summary(),
        "email": settings.email_runtime_summary(),
        "security": {
            "secure_session_cookies": settings.effective_secure_session_cookies,
            "session_cookie_samesite": settings.effective_session_cookie_samesite,
            "frontend_backend_cross_site": settings.frontend_backend_cross_site,
            "session_idle_timeout_seconds": settings.effective_session_idle_timeout_seconds,
            "cors_origin_count": len(settings.effective_cors_allowed_origins),
            "cors_method_count": len(settings.effective_cors_allowed_methods),
            "cors_header_count": len(settings.effective_cors_allowed_headers),
            "cors_methods_wildcard": "*" in settings.effective_cors_allowed_methods,
            "cors_headers_wildcard": "*" in settings.effective_cors_allowed_headers,
            "cors_max_age_seconds": settings.effective_cors_max_age_seconds,
            "trusted_host_count": len(settings.effective_trusted_hosts),
            "deployed_mode": settings.deployed_mode,
        },
        "deployment": {
            "staging": settings.staging_mode,
            "production": settings.production_mode,
            "frontend_origin_configured": bool(str(settings.frontend_origin or "").strip()),
            "backend_public_url_configured": bool(str(settings.backend_public_url or "").strip()),
            "session_cookie_domain_effective": bool(settings.effective_session_cookie_domain),
        },
    }


def _runtime_session_factory():
    return getattr(app.state, "testing_session_factory", None) or SessionLocal


def _readiness_failure_reasons(
    *,
    boot_ready: bool,
    config_ready: bool,
    db_ready: bool,
    worker_required: bool,
    worker_ready: bool,
    pipeline_required: bool,
    pipeline_ready: bool,
    pipeline_snapshot: dict,
    boot: dict,
    runtime_config: dict,
    db_readiness: dict,
) -> list[str]:
    reasons: list[str] = []
    if not boot_ready:
        reasons.append(f"boot:{boot.get('status') or 'unknown'}")
    if not config_ready:
        error_count = int(runtime_config["config_validation"].get("error_count") or 0)
        reasons.append(f"config:{error_count}_error{'s' if error_count != 1 else ''}")
    if not db_ready:
        reasons.append(f"database:{db_readiness.get('status') or 'unknown'}")
    if worker_required and not worker_ready:
        reasons.append("media_render_worker:unavailable")
    if pipeline_required and not pipeline_ready:
        if not bool(pipeline_snapshot.get("storage_ready")):
            reasons.append("media_render_pipeline:storage_unavailable")
        elif not bool(pipeline_snapshot.get("submission_ready")):
            reasons.append("media_render_pipeline:submission_unavailable")
        elif "media_render_worker:unavailable" not in reasons:
            reasons.append("media_render_pipeline:unavailable")
    return reasons


def _readiness_summary(
    *,
    ready: bool,
    boot: dict,
    runtime_config: dict,
    db_readiness: dict,
    worker_snapshot: dict,
    pipeline_snapshot: dict,
    failure_reasons: list[str],
) -> dict:
    return {
        "ready": ready,
        "failure_reasons": failure_reasons,
        "boot_status": boot.get("status"),
        "database_status": db_readiness.get("status"),
        "database_type": db_readiness.get("database_type"),
        "media_render_worker_mode": worker_snapshot.get("mode"),
        "media_render_worker_ready": worker_snapshot.get("ready"),
        "media_render_worker_required": worker_snapshot.get("required_for_readiness"),
        "media_render_pipeline_ready": pipeline_snapshot.get("ready"),
        "media_render_pipeline_required": pipeline_snapshot.get("required_for_readiness"),
        "media_render_pipeline_submission_ready": pipeline_snapshot.get("submission_ready"),
        "media_render_pipeline_storage_ready": pipeline_snapshot.get("storage_ready"),
        "config_error_count": runtime_config["config_validation"].get("error_count", 0),
        "config_warning_count": runtime_config["config_validation"].get("warning_count", 0),
        "email_delivery_mode": runtime_config["email"].get("delivery_mode"),
        "email_transport": runtime_config["email"].get("transport"),
        "deployed_mode": runtime_config["security"].get("deployed_mode"),
        "secure_session_cookies": runtime_config["security"].get("secure_session_cookies"),
    }


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    fastapi_app.state.boot_status = "starting"
    fastapi_app.state.boot_started_at = _utc_iso_now()
    fastapi_app.state.boot_completed_at = None
    fastapi_app.state.boot_failed_at = None
    fastapi_app.state.boot_failure_type = None
    ai_summary = settings.ai_runtime_summary()
    logger.info("Starting Adhyantra backend with AI provider '%s'.", ai_summary["provider"])
    log_event(
        event_logger,
        logging.INFO,
        "app.starting",
        environment=settings.environment_name,
        app_version=settings.app_version,
        deployed_mode=settings.deployed_mode,
        ai_provider=ai_summary["provider"],
        ai_provider_chain=ai_summary["provider_chain"],
        email_delivery_mode=settings.effective_email_delivery_mode,
        email_transport=settings.effective_email_transport,
        secure_session_cookies=settings.effective_secure_session_cookies,
        session_cookie_samesite=settings.effective_session_cookie_samesite,
        frontend_backend_cross_site=settings.frontend_backend_cross_site,
        session_cookie_domain_effective=bool(settings.effective_session_cookie_domain),
        cors_origin_count=len(settings.effective_cors_allowed_origins),
        trusted_host_count=len(settings.effective_trusted_hosts),
    )
    try:
        validation = settings.enforce_startup_config(process_role="api")
        for issue in validation.errors:
            logger.error("Configuration error [%s.%s]: %s", issue.category, issue.code, issue.message)
            log_event(
                event_logger,
                logging.ERROR,
                "app.config_issue",
                environment=settings.environment_name,
                severity=issue.severity,
                category=issue.category,
                issue_code=issue.code,
            )
        for issue in validation.warnings:
            logger.warning("Configuration warning [%s.%s]: %s", issue.category, issue.code, issue.message)
            log_event(
                event_logger,
                logging.WARNING,
                "app.config_issue",
                environment=settings.environment_name,
                severity=issue.severity,
                category=issue.category,
                issue_code=issue.code,
            )
        log_event(
            event_logger,
            logging.INFO,
            "app.config_validated",
            environment=settings.environment_name,
            error_count=len(validation.errors),
            warning_count=len(validation.warnings),
        )
        init_db()
        with managed_db_session(SessionLocal) as recovery_db:
            recovered_startup_jobs = recover_stale_queued_media_render_jobs(
                recovery_db,
                stale_after_seconds=max(
                    settings.effective_media_render_worker_stale_after_seconds,
                    settings.effective_media_render_claim_lease_seconds,
                ),
            )
        if recovered_startup_jobs:
            log_event(
                event_logger,
                logging.INFO,
                "media_render.queued_jobs_recovered_on_startup",
                environment=settings.environment_name,
                recovered_job_count=len(recovered_startup_jobs),
                worker_mode=settings.effective_media_render_worker_mode,
            )
        if settings.embedded_media_render_worker_enabled:
            start_media_render_dispatcher(fastapi_app, settings=settings)
        else:
            fastapi_app.state.media_render_dispatcher = None
            log_event(
                event_logger,
                logging.INFO,
                "media_render.worker_embedded_disabled",
                environment=settings.environment_name,
                worker_mode=settings.effective_media_render_worker_mode,
            )
        fastapi_app.state.boot_status = "ready"
        fastapi_app.state.boot_completed_at = _utc_iso_now()
        logger.info("Database initialized successfully.")
        log_event(
            event_logger,
            logging.INFO,
            "app.started",
            environment=settings.environment_name,
            boot_status=fastapi_app.state.boot_status,
            completed_at=fastapi_app.state.boot_completed_at,
        )
        yield
    except Exception as exc:
        fastapi_app.state.boot_status = "failed"
        fastapi_app.state.boot_failed_at = _utc_iso_now()
        fastapi_app.state.boot_failure_type = type(exc).__name__
        log_event(
            event_logger,
            logging.ERROR,
            "app.startup_failed",
            environment=settings.environment_name,
            failure_type=type(exc).__name__,
            failed_at=fastapi_app.state.boot_failed_at,
        )
        logger.exception("Adhyantra backend failed during startup.")
        raise
    finally:
        stop_media_render_dispatcher(fastapi_app)


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.state.boot_status = "not_started"
app.state.boot_started_at = None
app.state.boot_completed_at = None
app.state.boot_failed_at = None
app.state.boot_failure_type = None
app.state.media_render_dispatcher = None


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    request_id = _sanitize_request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_event(
            event_logger,
            logging.ERROR,
            "http.request_failed",
            **request_log_context(request),
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        raise

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    status_code = int(response.status_code)
    log_level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
    log_event(
        event_logger,
        log_level,
        "http.request_completed",
        **request_log_context(request),
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        duration_ms=duration_ms,
    )
    return response

trusted_hosts = list(settings.effective_trusted_hosts)
if trusted_hosts:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=trusted_hosts,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.effective_cors_allowed_origins),
    allow_credentials=True,
    allow_methods=list(settings.effective_cors_allowed_methods),
    allow_headers=list(settings.effective_cors_allowed_headers),
    expose_headers=[
        "X-Request-ID",
        "Content-Disposition",
        "X-Adhyantra-Export-Format",
        "X-Adhyantra-Export-Filename",
        "X-Adhyantra-Export-Version",
        "X-Adhyantra-Export-Generated-At",
    ],
    max_age=settings.effective_cors_max_age_seconds,
)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = _safe_validation_errors(exc)
    log_event(
        event_logger,
        logging.WARNING,
        "http.validation_error",
        **request_log_context(request),
        method=request.method,
        path=request.url.path,
        error_count=len(safe_errors),
        error_types=[error["type"] for error in safe_errors],
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed.", "errors": safe_errors},
        headers={"X-Request-ID": str(getattr(request.state, "request_id", ""))},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    log_event(
        event_logger,
        logging.ERROR if exc.status_code >= 500 else logging.WARNING,
        "http.exception",
        **request_log_context(request),
        method=request.method,
        path=request.url.path,
        status_code=exc.status_code,
        detail=_safe_http_detail(exc.detail),
    )
    headers = dict(exc.headers or {})
    headers.setdefault("X-Request-ID", str(getattr(request.state, "request_id", "")))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    log_event(
        event_logger,
        logging.WARNING,
        "http.value_error",
        **request_log_context(request),
        method=request.method,
        path=request.url.path,
        message=_safe_http_detail(str(exc)),
    )
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
        headers={"X-Request-ID": str(getattr(request.state, "request_id", ""))},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_event(
        event_logger,
        logging.ERROR,
        "http.unhandled_exception",
        **request_log_context(request),
        method=request.method,
        path=request.url.path,
        exception_type=type(exc).__name__,
        exception_hash=stable_hash(str(exc), length=10),
    )
    logger.exception("Unhandled error on %s %s request_id=%s", request.method, request.url.path, getattr(request.state, "request_id", None))
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the server. Please try again."},
        headers={"X-Request-ID": str(getattr(request.state, "request_id", ""))},
    )


@app.get("/health/live")
def liveness_check() -> dict:
    return {
        "status": "ok",
        "service": "adhyantra-api",
        "environment": settings.environment_name,
        "version": settings.app_version,
        "boot": _boot_snapshot(),
    }


def _readiness_payload() -> tuple[dict, int]:
    runtime_config = _safe_runtime_config_snapshot()
    db_readiness = database_readiness_snapshot()
    boot = _boot_snapshot()
    session_factory = _runtime_session_factory()
    with managed_db_session(session_factory) as worker_db:
        worker_snapshot = build_media_render_worker_snapshot(worker_db, app, settings=settings)
    pipeline_snapshot = build_media_render_pipeline_snapshot(
        settings=settings,
        worker_snapshot=worker_snapshot,
    )
    boot_ready = boot["status"] == "ready"
    config_ready = bool(runtime_config["config_validation"]["ok"])
    db_ready = bool(db_readiness["ok"])
    worker_required = bool(worker_snapshot.get("required_for_readiness"))
    worker_ready = bool(worker_snapshot.get("ready"))
    pipeline_required = bool(pipeline_snapshot.get("required_for_readiness"))
    pipeline_ready = bool(pipeline_snapshot.get("ready"))
    ready = bool(boot_ready and config_ready and db_ready and (pipeline_ready or not pipeline_required))
    failure_reasons = _readiness_failure_reasons(
        boot_ready=boot_ready,
        config_ready=config_ready,
        db_ready=db_ready,
        worker_required=worker_required,
        worker_ready=worker_ready,
        pipeline_required=pipeline_required,
        pipeline_ready=pipeline_ready,
        pipeline_snapshot=pipeline_snapshot,
        boot=boot,
        runtime_config=runtime_config,
        db_readiness=db_readiness,
    )
    summary = _readiness_summary(
        ready=ready,
        boot=boot,
        runtime_config=runtime_config,
        db_readiness=db_readiness,
        worker_snapshot=worker_snapshot,
        pipeline_snapshot=pipeline_snapshot,
        failure_reasons=failure_reasons,
    )
    public_worker_snapshot = _public_worker_readiness_snapshot(worker_snapshot)
    public_pipeline_snapshot = _public_pipeline_readiness_snapshot(pipeline_snapshot)

    payload = {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "service": "adhyantra-api",
        "environment": settings.environment_name,
        "version": settings.app_version,
        "checked_at": _utc_iso_now(),
        "boot": boot,
        "summary": summary,
        "checks": {
            "boot": {
                "ok": boot_ready,
                "status": boot["status"],
            },
            "database": db_readiness,
            "configuration": runtime_config["config_validation"],
            "media_render_worker": public_worker_snapshot,
            "media_render_pipeline": public_pipeline_snapshot,
        },
        "runtime": {
            "environment_policy": runtime_config["environment_policy"],
            "ai": runtime_config["ai"],
            "email": runtime_config["email"],
            "security": runtime_config["security"],
            "deployment": runtime_config["deployment"],
            "release": runtime_config["release"],
        },
    }
    return payload, 200 if ready else 503


@app.get("/health/ready")
def readiness_check() -> JSONResponse:
    payload, status_code = _readiness_payload()
    if status_code >= 500:
        summary = payload.get("summary") or {}
        log_event(
            event_logger,
            logging.WARNING,
            "ops.readiness_failed",
            environment=payload.get("environment"),
            failure_reasons=summary.get("failure_reasons"),
            boot_status=summary.get("boot_status"),
            database_status=summary.get("database_status"),
            media_render_worker_mode=summary.get("media_render_worker_mode"),
            media_render_worker_ready=summary.get("media_render_worker_ready"),
            media_render_worker_required=summary.get("media_render_worker_required"),
            config_error_count=summary.get("config_error_count"),
            config_warning_count=summary.get("config_warning_count"),
            deployed_mode=summary.get("deployed_mode"),
        )
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/ready")
def ready_alias() -> JSONResponse:
    payload, status_code = _readiness_payload()
    if status_code >= 500:
        summary = payload.get("summary") or {}
        log_event(
            event_logger,
            logging.WARNING,
            "ops.readiness_failed",
            environment=payload.get("environment"),
            failure_reasons=summary.get("failure_reasons"),
            boot_status=summary.get("boot_status"),
            database_status=summary.get("database_status"),
            media_render_worker_mode=summary.get("media_render_worker_mode"),
            media_render_worker_ready=summary.get("media_render_worker_ready"),
            media_render_worker_required=summary.get("media_render_worker_required"),
            config_error_count=summary.get("config_error_count"),
            config_warning_count=summary.get("config_warning_count"),
            deployed_mode=summary.get("deployed_mode"),
        )
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/health")
def health_check() -> dict:
    validation = settings.validate_runtime_config(process_role="api")
    boot = _boot_snapshot()
    ai_summary = settings.ai_runtime_summary()
    ai_mode = str(ai_summary.get("provider") or "mock")
    ai_note = (
        "Adhyantra is currently using its local mock fallback, not a live AI call."
        if settings.mock_mode
        else f"Adhyantra is currently configured for live AI through {ai_mode}."
    )
    sqlite_db_path = get_active_sqlite_db_path(settings.db_url)
    demo_seed_metadata = read_demo_seed_metadata(sqlite_db_path)
    if settings.deployed_mode:
        data_note = "Runtime data is configured for this environment."
        demo_seed_debug_context = None
        db_path_value = "redacted"
    else:
        data_note = (
            "Knowledge-base content is seeded from markdown. Quiz and progress history stay empty until you study or intentionally run the demo seed script."
        )
        if demo_seed_metadata is not None:
            data_note = (
                "This database currently includes intentionally seeded demo progress. Run `python scripts/reset_local_db.py` to start fresh."
            )
        demo_seed_debug_context = _build_demo_seed_debug_context(demo_seed_metadata)
        db_path_value = sqlite_db_path.as_posix() if sqlite_db_path else settings.db_url

    return {
        "status": "ok",
        "exam": normalize_exam(settings.default_exam),
        "subject": settings.default_subject,
        "environment": settings.environment_name,
        "version": settings.app_version,
        "boot": {
            "status": boot["status"],
            "completed_at": boot["completed_at"],
        },
        "readiness_endpoint": "/health/ready",
        "mock_mode": settings.mock_mode,
        "ai_mode": ai_mode,
        "ai_note": ai_note,
        "security": {
            "config_validation": validation.to_public_dict(),
            "secure_session_cookies": settings.effective_secure_session_cookies,
            "session_cookie_samesite": settings.effective_session_cookie_samesite,
            "frontend_backend_cross_site": settings.frontend_backend_cross_site,
            "session_cookie_path": settings.effective_session_cookie_path,
            "session_cookie_domain_configured": bool(str(settings.session_cookie_domain or "").strip()),
            "session_cookie_domain_effective": bool(settings.effective_session_cookie_domain),
            "session_ttl_seconds": settings.effective_session_ttl_seconds,
            "session_idle_timeout_seconds": settings.effective_session_idle_timeout_seconds,
            "cors_origin_count": len(settings.effective_cors_allowed_origins),
            "cors_method_count": len(settings.effective_cors_allowed_methods),
            "cors_header_count": len(settings.effective_cors_allowed_headers),
            "cors_methods_wildcard": "*" in settings.effective_cors_allowed_methods,
            "cors_headers_wildcard": "*" in settings.effective_cors_allowed_headers,
            "trusted_host_count": len(settings.effective_trusted_hosts),
            "otp_delivery_mode": settings.email_otp_delivery_mode,
            "dev_otp_return_enabled": settings.effective_dev_otp_return_enabled,
        },
        "database_type": _public_database_type(),
        "db_path": db_path_value,
        "demo_seeded": demo_seed_metadata is not None,
        "debug_runtime_context": demo_seed_debug_context,
        "data_note": data_note,
    }


app.include_router(tutor_router)
app.include_router(test_router)
app.include_router(progress_router)
app.include_router(topic_router)
app.include_router(coach_router)
app.include_router(auth_router)
app.include_router(account_billing_router)
app.include_router(admin_content_router)
app.include_router(admin_ops_router)
