from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    display_name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    auth_status = Column(String(30), nullable=False, default="pending_verification")
    primary_auth_method = Column(String(30), nullable=False, default="email_otp")
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    billing_email = Column(String(320), nullable=True)
    subscription_plan = Column(String(30), nullable=False, default="free")
    subscription_status = Column(String(30), nullable=False, default="inactive")
    subscription_customer_ref = Column(String(120), nullable=True, unique=True, index=True)
    subscription_provider_ref = Column(String(160), nullable=True, index=True)
    subscription_started_at = Column(DateTime(timezone=True), nullable=True)
    subscription_current_period_end = Column(DateTime(timezone=True), nullable=True)
    subscription_trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    subscription_cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    subscription_price_id = Column(String(120), nullable=True)
    subscription_product_id = Column(String(120), nullable=True)
    feature_access_overrides_json = Column(Text, nullable=False, default="{}")
    account_role = Column(String(30), nullable=False, default="student", index=True)
    admin_privileges_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    settings = relationship("UserSetting", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    otp_challenges = relationship("EmailOtpChallenge", back_populates="user", cascade="all, delete-orphan")
    topic_studies = relationship("TopicStudy", back_populates="user")
    quizzes = relationship("Quiz", back_populates="user")
    quiz_attempts = relationship("QuizAttempt", back_populates="user")
    topic_progress_rows = relationship("TopicProgress", back_populates="user")
    analytics_events = relationship("AnalyticsEvent", back_populates="user")
    billing_event_receipts = relationship("BillingEventReceipt", back_populates="user")
    media_render_jobs = relationship("MediaRenderJob", back_populates="user")
    usage_consumption_records = relationship("UsageConsumptionRecord", back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(Integer, ForeignKey("user_accounts.id"), primary_key=True)
    avatar_url = Column(String(512), nullable=True)
    avatar_initials = Column(String(12), nullable=True)
    bio = Column(Text, nullable=True)
    locale = Column(String(50), nullable=True)
    onboarding_state = Column(String(30), nullable=False, default="new")
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserAccount", back_populates="profile")


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("user_accounts.id"), primary_key=True)
    theme_preference = Column(String(20), nullable=False, default="system")
    mentor_mode = Column(String(20), nullable=False, default="normal")
    preferred_exam = Column(String(50), nullable=False, default="upsc")
    preferred_subject = Column(String(100), nullable=False, default="polity")
    current_exam = Column(String(50), nullable=False, default="upsc")
    current_subject = Column(String(100), nullable=False, default="polity")
    timezone = Column(String(100), nullable=True)
    study_reminders_enabled = Column(Boolean, nullable=False, default=True)
    marketing_emails_enabled = Column(Boolean, nullable=False, default=False)
    progress_digest_frequency = Column(String(30), nullable=False, default="important_only")
    billing_notifications_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserAccount", back_populates="settings")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=False, index=True)
    session_token_hash = Column(String(128), nullable=False, unique=True, index=True)
    auth_method = Column(String(30), nullable=False, default="email_otp")
    session_label = Column(String(120), nullable=True)
    device_label = Column(String(120), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_authenticated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(String(120), nullable=True)

    user = relationship("UserAccount", back_populates="sessions")


class EmailOtpChallenge(Base):
    __tablename__ = "email_otp_challenges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    email = Column(String(320), nullable=False, index=True)
    pending_display_name = Column(String(120), nullable=True)
    code_hash = Column(String(128), nullable=False)
    delivery_mode = Column(String(30), nullable=False, default="console")
    purpose = Column(String(30), nullable=False, default="login")
    requested_ip_address = Column(String(64), nullable=True)
    requested_user_agent = Column(String(512), nullable=True)
    attempts_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("UserAccount", back_populates="otp_challenges")


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint(
            "exam",
            "subject",
            "content_type",
            "slug",
            name="uq_content_items_exam_subject_type_slug",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity", index=True)
    content_subject = Column(String(100), nullable=True)
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False, default="topic_note", index=True)
    lifecycle_state = Column(String(30), nullable=False, default="draft", index=True)
    body_markdown = Column(Text, nullable=False, default="")
    summary = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    source_corpus_id = Column(String(120), nullable=True)
    source_path = Column(String(512), nullable=True)
    author_user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    reviewer_user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    publisher_user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    submitted_for_review_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String(120), nullable=False, index=True)
    feature_area = Column(String(50), nullable=False, index=True)
    event_version = Column(String(50), nullable=False, default="phase27_analytics_v1")
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=True, index=True)
    subject = Column(String(100), nullable=True, index=True)
    content_subject = Column(String(100), nullable=True)
    chapter = Column(String(255), nullable=True)
    topic = Column(String(255), nullable=True, index=True)
    content_corpus_id = Column(String(120), nullable=True, index=True)
    content_source_scope = Column(String(120), nullable=True, index=True)
    content_fallback_used = Column(Boolean, nullable=False, default=False)
    content_item_id = Column(Integer, nullable=True, index=True)
    lesson_mode = Column(String(50), nullable=True, index=True)
    quiz_mode = Column(String(50), nullable=True, index=True)
    revision_session_mode = Column(String(50), nullable=True)
    export_format = Column(String(50), nullable=True, index=True)
    question_count = Column(Integer, nullable=True)
    score = Column(Integer, nullable=True)
    accuracy = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = relationship("UserAccount", back_populates="analytics_events")


class BillingEventReceipt(Base):
    __tablename__ = "billing_event_receipts"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "provider_event_id",
            name="uq_billing_event_receipts_provider_event",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_name = Column(String(40), nullable=False, index=True)
    provider_event_id = Column(String(160), nullable=False, index=True)
    event_type = Column(String(120), nullable=False, index=True)
    livemode = Column(Boolean, nullable=False, default=False, index=True)
    processing_state = Column(String(30), nullable=False, default="received", index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    customer_ref = Column(String(120), nullable=True, index=True)
    subscription_ref = Column(String(160), nullable=True, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    delivery_attempt_count = Column(Integer, nullable=False, default=0)
    duplicate_delivery_count = Column(Integer, nullable=False, default=0)
    processing_attempt_count = Column(Integer, nullable=False, default=0)
    event_created_at = Column(DateTime(timezone=True), nullable=True, index=True)
    first_received_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_received_at = Column(DateTime(timezone=True), nullable=True, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    failed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    resolved_lifecycle_state = Column(String(40), nullable=True, index=True)
    resolved_plan_tier = Column(String(30), nullable=True, index=True)
    resolved_subscription_status = Column(String(30), nullable=True, index=True)
    resolved_premium_quota_state = Column(String(30), nullable=True, index=True)
    processing_error = Column(Text, nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserAccount", back_populates="billing_event_receipts")


class RuntimeProcessHeartbeat(Base):
    __tablename__ = "runtime_process_heartbeats"
    __table_args__ = (
        UniqueConstraint(
            "service_name",
            "runtime_instance_id",
            name="uq_runtime_process_heartbeats_service_instance",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(80), nullable=False, index=True)
    process_role = Column(String(30), nullable=False, index=True)
    runtime_instance_id = Column(String(120), nullable=False, index=True)
    environment = Column(String(30), nullable=False, default="development", index=True)
    worker_mode = Column(String(30), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="starting", index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class MediaRenderJob(Base):
    __tablename__ = "media_render_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity", index=True)
    content_subject = Column(String(100), nullable=True)
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    lesson_mode = Column(String(50), nullable=True, index=True)
    source_export_format = Column(String(50), nullable=True, index=True)
    render_type = Column(String(50), nullable=False, default="audio", index=True)
    lifecycle_state = Column(String(30), nullable=False, default="queued", index=True)
    source_content_corpus_id = Column(String(120), nullable=True, index=True)
    source_content_scope = Column(String(120), nullable=True, index=True)
    source_content_fallback_used = Column(Boolean, nullable=False, default=False)
    source_content_item_id = Column(Integer, nullable=True, index=True)
    requested_scene_count = Column(Integer, nullable=True)
    requested_segment_count = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    queued_at = Column(DateTime(timezone=True), nullable=True, index=True)
    claimed_by = Column(String(120), nullable=True, index=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_after_at = Column(DateTime(timezone=True), nullable=True, index=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    request_metadata_json = Column(Text, nullable=False, default="{}")
    dispatch_payload_json = Column(Text, nullable=False, default="{}")
    output_metadata_json = Column(Text, nullable=False, default="{}")
    output_asset_filename = Column(String(255), nullable=True)
    output_asset_path = Column(String(1024), nullable=True)
    output_content_type = Column(String(120), nullable=True)
    output_file_size_bytes = Column(Integer, nullable=True)
    artifact_retention_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_downloaded_at = Column(DateTime(timezone=True), nullable=True)
    artifact_deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    artifact_cleanup_attempted_at = Column(DateTime(timezone=True), nullable=True)
    artifact_cleanup_retry_after_at = Column(DateTime(timezone=True), nullable=True, index=True)
    artifact_cleanup_failure_count = Column(Integer, nullable=False, default=0)
    artifact_cleanup_error = Column(Text, nullable=True)
    status_note = Column(Text, nullable=True)
    failure_code = Column(String(120), nullable=True)
    failure_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserAccount", back_populates="media_render_jobs")
    usage_consumption_records = relationship("UsageConsumptionRecord", back_populates="media_render_job")


class UsageConsumptionRecord(Base):
    __tablename__ = "usage_consumption_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=False, index=True)
    limit_key = Column(String(80), nullable=False, index=True)
    source_action = Column(String(120), nullable=False, index=True)
    units_consumed = Column(Integer, nullable=False, default=1)
    plan_tier = Column(String(30), nullable=False, default="free")
    subscription_status = Column(String(30), nullable=False, default="inactive")
    exam = Column(String(50), nullable=True, index=True)
    subject = Column(String(100), nullable=True, index=True)
    content_subject = Column(String(100), nullable=True)
    chapter = Column(String(255), nullable=True)
    topic = Column(String(255), nullable=True, index=True)
    lesson_mode = Column(String(50), nullable=True, index=True)
    export_format = Column(String(50), nullable=True, index=True)
    render_type = Column(String(50), nullable=True, index=True)
    media_render_job_id = Column(Integer, ForeignKey("media_render_jobs.id"), nullable=True, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = relationship("UserAccount", back_populates="usage_consumption_records")
    media_render_job = relationship("MediaRenderJob", back_populates="usage_consumption_records")


class TopicStudy(Base):
    __tablename__ = "topic_studies"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exam",
            "subject",
            "chapter",
            "topic",
            name="uq_topic_studies_user_exam_subject_chapter_topic",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity")
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    study_count = Column(Integer, nullable=False, default=0)
    last_interaction_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("UserAccount", back_populates="topic_studies")


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity")
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    difficulty = Column(String(50), nullable=False)
    quiz_mode = Column(String(50), nullable=False, default="test")
    question_count = Column(Integer, nullable=False)
    questions_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("UserAccount", back_populates="quizzes")
    attempts = relationship("QuizAttempt", back_populates="quiz")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity")
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    difficulty = Column(String(50), nullable=False)
    quiz_mode = Column(String(50), nullable=False, default="test")
    submitted_answers_json = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    accuracy = Column(Float, nullable=False)
    incorrect_questions_json = Column(Text, nullable=False)
    weak_areas_json = Column(Text, nullable=False)
    topic_breakdown_json = Column(Text, nullable=False, default="[]")
    next_recommendation = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("UserAccount", back_populates="quiz_attempts")
    quiz = relationship("Quiz", back_populates="attempts")


class TopicProgress(Base):
    __tablename__ = "topic_progress"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exam",
            "subject",
            "chapter",
            "topic",
            name="uq_topic_progress_user_exam_subject_chapter_topic",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, index=True)
    exam = Column(String(50), nullable=False, default="upsc", index=True)
    subject = Column(String(100), nullable=False, default="polity")
    chapter = Column(String(255), nullable=False, default="General")
    topic = Column(String(255), nullable=False, index=True)
    attempts_count = Column(Integer, nullable=False, default=0)
    correct_answers = Column(Integer, nullable=False, default=0)
    total_answers = Column(Integer, nullable=False, default=0)
    accuracy = Column(Float, nullable=False, default=0.0)
    difficulty_band = Column(String(50), nullable=False, default="medium")
    weak_topic = Column(Boolean, nullable=False, default=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("UserAccount", back_populates="topic_progress_rows")
