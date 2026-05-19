from __future__ import annotations

import argparse
from backend.config import ConfigValidationError
import logging
import signal
import threading
from typing import Sequence

from backend.config import get_settings
from backend.db import init_db
from backend.services.media_render_dispatch_service import run_media_render_worker_forever, run_media_render_worker_once


logger = logging.getLogger(__name__)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Adhyantra media render worker against queued media_render_jobs.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Process at most one queued job, then exit.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Process up to this many jobs before exiting.",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default="",
        help="Override the generated worker identifier for logs and job claims.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=None,
        help="Override the queue poll interval for this worker process.",
    )
    parser.add_argument(
        "--claim-lease-seconds",
        type=int,
        default=None,
        help="Override the job claim lease duration for this worker process.",
    )
    parser.add_argument(
        "--skip-db-init",
        action="store_true",
        help="Skip startup DB initialization if another process already handles it.",
    )
    return parser


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle_stop_signal(signum, _frame) -> None:
        logger.info("Media render worker received signal %s and will stop after the current poll cycle.", signum)
        stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        try:
            signal.signal(signal_value, _handle_stop_signal)
        except (ValueError, OSError):  # pragma: no cover - platform/embedding dependent
            continue


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.effective_log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        validation = settings.enforce_worker_startup_config()
    except ConfigValidationError as exc:
        for issue in exc.result.errors:
            logger.error("Worker configuration error [%s.%s]: %s", issue.category, issue.code, issue.message)
        for issue in exc.result.warnings:
            logger.warning("Worker configuration warning [%s.%s]: %s", issue.category, issue.code, issue.message)
        return 2
    for issue in validation.warnings:
        logger.warning("Worker configuration warning [%s.%s]: %s", issue.category, issue.code, issue.message)

    if not args.skip_db_init:
        init_db()

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    if args.run_once:
        processed_jobs = int(
            run_media_render_worker_once(
                settings=settings,
                worker_id=str(args.worker_id or "").strip() or None,
                poll_interval_seconds=args.poll_interval_seconds,
                claim_lease_seconds=args.claim_lease_seconds,
            )
        )
    else:
        processed_jobs = run_media_render_worker_forever(
            settings=settings,
            worker_id=str(args.worker_id or "").strip() or None,
            stop_event=stop_event,
            max_jobs=args.max_jobs,
            poll_interval_seconds=args.poll_interval_seconds,
            claim_lease_seconds=args.claim_lease_seconds,
        )
    logger.info(
        "Media render worker exited cleanly after processing %s job(s).",
        processed_jobs,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
