"""Initial PostgreSQL model/schema baseline.

This revision is the empty-database representation of the current 15-table
SQLAlchemy metadata. An existing compatible database, including the separately
verified Supabase database, must be stamped at this revision rather than
upgraded from ``base``.

Row-level-security policy and least-privileged application roles require a
separate reviewed migration. Python-side business defaults intentionally remain
Python-side; this revision includes only defaults represented by the metadata.

Revision ID: 20260823_0001
Revises:
Create Date: 2026-08-23 21:43:43.005438
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260823_0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('runtime_process_heartbeats',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('service_name', sa.String(length=80), nullable=False),
    sa.Column('process_role', sa.String(length=30), nullable=False),
    sa.Column('runtime_instance_id', sa.String(length=120), nullable=False),
    sa.Column('environment', sa.String(length=30), nullable=False),
    sa.Column('worker_mode', sa.String(length=30), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('service_name', 'runtime_instance_id', name='uq_runtime_process_heartbeats_service_instance')
    )
    op.create_index(op.f('ix_runtime_process_heartbeats_environment'), 'runtime_process_heartbeats', ['environment'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_id'), 'runtime_process_heartbeats', ['id'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_last_heartbeat_at'), 'runtime_process_heartbeats', ['last_heartbeat_at'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_process_role'), 'runtime_process_heartbeats', ['process_role'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_runtime_instance_id'), 'runtime_process_heartbeats', ['runtime_instance_id'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_service_name'), 'runtime_process_heartbeats', ['service_name'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_status'), 'runtime_process_heartbeats', ['status'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_stopped_at'), 'runtime_process_heartbeats', ['stopped_at'], unique=False)
    op.create_index(op.f('ix_runtime_process_heartbeats_worker_mode'), 'runtime_process_heartbeats', ['worker_mode'], unique=False)
    op.create_table('user_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('auth_status', sa.String(length=30), nullable=False),
    sa.Column('primary_auth_method', sa.String(length=30), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('billing_email', sa.String(length=320), nullable=True),
    sa.Column('subscription_plan', sa.String(length=30), nullable=False),
    sa.Column('subscription_status', sa.String(length=30), nullable=False),
    sa.Column('subscription_customer_ref', sa.String(length=120), nullable=True),
    sa.Column('subscription_provider_ref', sa.String(length=160), nullable=True),
    sa.Column('subscription_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('subscription_current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('subscription_trial_ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('subscription_cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('subscription_price_id', sa.String(length=120), nullable=True),
    sa.Column('subscription_product_id', sa.String(length=120), nullable=True),
    sa.Column('feature_access_overrides_json', sa.Text(), nullable=False),
    sa.Column('account_role', sa.String(length=30), nullable=False),
    sa.Column('admin_privileges_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_accounts_account_role'), 'user_accounts', ['account_role'], unique=False)
    op.create_index(op.f('ix_user_accounts_email'), 'user_accounts', ['email'], unique=True)
    op.create_index(op.f('ix_user_accounts_id'), 'user_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_user_accounts_subscription_customer_ref'), 'user_accounts', ['subscription_customer_ref'], unique=True)
    op.create_index(op.f('ix_user_accounts_subscription_provider_ref'), 'user_accounts', ['subscription_provider_ref'], unique=False)
    op.create_table('analytics_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_name', sa.String(length=120), nullable=False),
    sa.Column('feature_area', sa.String(length=50), nullable=False),
    sa.Column('event_version', sa.String(length=50), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=True),
    sa.Column('subject', sa.String(length=100), nullable=True),
    sa.Column('content_subject', sa.String(length=100), nullable=True),
    sa.Column('chapter', sa.String(length=255), nullable=True),
    sa.Column('topic', sa.String(length=255), nullable=True),
    sa.Column('content_corpus_id', sa.String(length=120), nullable=True),
    sa.Column('content_source_scope', sa.String(length=120), nullable=True),
    sa.Column('content_fallback_used', sa.Boolean(), nullable=False),
    sa.Column('content_item_id', sa.Integer(), nullable=True),
    sa.Column('lesson_mode', sa.String(length=50), nullable=True),
    sa.Column('quiz_mode', sa.String(length=50), nullable=True),
    sa.Column('revision_session_mode', sa.String(length=50), nullable=True),
    sa.Column('export_format', sa.String(length=50), nullable=True),
    sa.Column('question_count', sa.Integer(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('accuracy', sa.Float(), nullable=True),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analytics_events_content_corpus_id'), 'analytics_events', ['content_corpus_id'], unique=False)
    op.create_index(op.f('ix_analytics_events_content_item_id'), 'analytics_events', ['content_item_id'], unique=False)
    op.create_index(op.f('ix_analytics_events_content_source_scope'), 'analytics_events', ['content_source_scope'], unique=False)
    op.create_index(op.f('ix_analytics_events_created_at'), 'analytics_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_analytics_events_event_name'), 'analytics_events', ['event_name'], unique=False)
    op.create_index(op.f('ix_analytics_events_exam'), 'analytics_events', ['exam'], unique=False)
    op.create_index(op.f('ix_analytics_events_export_format'), 'analytics_events', ['export_format'], unique=False)
    op.create_index(op.f('ix_analytics_events_feature_area'), 'analytics_events', ['feature_area'], unique=False)
    op.create_index(op.f('ix_analytics_events_id'), 'analytics_events', ['id'], unique=False)
    op.create_index(op.f('ix_analytics_events_lesson_mode'), 'analytics_events', ['lesson_mode'], unique=False)
    op.create_index(op.f('ix_analytics_events_quiz_mode'), 'analytics_events', ['quiz_mode'], unique=False)
    op.create_index(op.f('ix_analytics_events_subject'), 'analytics_events', ['subject'], unique=False)
    op.create_index(op.f('ix_analytics_events_topic'), 'analytics_events', ['topic'], unique=False)
    op.create_index(op.f('ix_analytics_events_user_id'), 'analytics_events', ['user_id'], unique=False)
    op.create_table('billing_event_receipts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_name', sa.String(length=40), nullable=False),
    sa.Column('provider_event_id', sa.String(length=160), nullable=False),
    sa.Column('event_type', sa.String(length=120), nullable=False),
    sa.Column('livemode', sa.Boolean(), nullable=False),
    sa.Column('processing_state', sa.String(length=30), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('customer_ref', sa.String(length=120), nullable=True),
    sa.Column('subscription_ref', sa.String(length=160), nullable=True),
    sa.Column('payload_json', sa.Text(), nullable=False),
    sa.Column('delivery_attempt_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_delivery_count', sa.Integer(), nullable=False),
    sa.Column('processing_attempt_count', sa.Integer(), nullable=False),
    sa.Column('event_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_lifecycle_state', sa.String(length=40), nullable=True),
    sa.Column('resolved_plan_tier', sa.String(length=30), nullable=True),
    sa.Column('resolved_subscription_status', sa.String(length=30), nullable=True),
    sa.Column('resolved_premium_quota_state', sa.String(length=30), nullable=True),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_name', 'provider_event_id', name='uq_billing_event_receipts_provider_event')
    )
    op.create_index(op.f('ix_billing_event_receipts_customer_ref'), 'billing_event_receipts', ['customer_ref'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_event_created_at'), 'billing_event_receipts', ['event_created_at'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_event_type'), 'billing_event_receipts', ['event_type'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_failed_at'), 'billing_event_receipts', ['failed_at'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_id'), 'billing_event_receipts', ['id'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_last_received_at'), 'billing_event_receipts', ['last_received_at'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_livemode'), 'billing_event_receipts', ['livemode'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_processed_at'), 'billing_event_receipts', ['processed_at'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_processing_state'), 'billing_event_receipts', ['processing_state'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_provider_event_id'), 'billing_event_receipts', ['provider_event_id'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_provider_name'), 'billing_event_receipts', ['provider_name'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_resolved_lifecycle_state'), 'billing_event_receipts', ['resolved_lifecycle_state'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_resolved_plan_tier'), 'billing_event_receipts', ['resolved_plan_tier'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_resolved_premium_quota_state'), 'billing_event_receipts', ['resolved_premium_quota_state'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_resolved_subscription_status'), 'billing_event_receipts', ['resolved_subscription_status'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_subscription_ref'), 'billing_event_receipts', ['subscription_ref'], unique=False)
    op.create_index(op.f('ix_billing_event_receipts_user_id'), 'billing_event_receipts', ['user_id'], unique=False)
    op.create_table('content_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('content_subject', sa.String(length=100), nullable=True),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('lifecycle_state', sa.String(length=30), nullable=False),
    sa.Column('body_markdown', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('source_corpus_id', sa.String(length=120), nullable=True),
    sa.Column('source_path', sa.String(length=512), nullable=True),
    sa.Column('author_user_id', sa.Integer(), nullable=True),
    sa.Column('reviewer_user_id', sa.Integer(), nullable=True),
    sa.Column('publisher_user_id', sa.Integer(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('submitted_for_review_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_user_id'], ['user_accounts.id'], ),
    sa.ForeignKeyConstraint(['publisher_user_id'], ['user_accounts.id'], ),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('exam', 'subject', 'content_type', 'slug', name='uq_content_items_exam_subject_type_slug')
    )
    op.create_index(op.f('ix_content_items_author_user_id'), 'content_items', ['author_user_id'], unique=False)
    op.create_index(op.f('ix_content_items_content_type'), 'content_items', ['content_type'], unique=False)
    op.create_index(op.f('ix_content_items_exam'), 'content_items', ['exam'], unique=False)
    op.create_index(op.f('ix_content_items_id'), 'content_items', ['id'], unique=False)
    op.create_index(op.f('ix_content_items_lifecycle_state'), 'content_items', ['lifecycle_state'], unique=False)
    op.create_index(op.f('ix_content_items_publisher_user_id'), 'content_items', ['publisher_user_id'], unique=False)
    op.create_index(op.f('ix_content_items_reviewer_user_id'), 'content_items', ['reviewer_user_id'], unique=False)
    op.create_index(op.f('ix_content_items_slug'), 'content_items', ['slug'], unique=False)
    op.create_index(op.f('ix_content_items_subject'), 'content_items', ['subject'], unique=False)
    op.create_index(op.f('ix_content_items_topic'), 'content_items', ['topic'], unique=False)
    op.create_table('email_otp_challenges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('pending_display_name', sa.String(length=120), nullable=True),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('delivery_mode', sa.String(length=30), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=False),
    sa.Column('requested_ip_address', sa.String(length=64), nullable=True),
    sa.Column('requested_user_agent', sa.String(length=512), nullable=True),
    sa.Column('attempts_count', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_otp_challenges_email'), 'email_otp_challenges', ['email'], unique=False)
    op.create_index(op.f('ix_email_otp_challenges_id'), 'email_otp_challenges', ['id'], unique=False)
    op.create_index(op.f('ix_email_otp_challenges_user_id'), 'email_otp_challenges', ['user_id'], unique=False)
    op.create_table('media_render_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('content_subject', sa.String(length=100), nullable=True),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('lesson_mode', sa.String(length=50), nullable=True),
    sa.Column('source_export_format', sa.String(length=50), nullable=True),
    sa.Column('render_type', sa.String(length=50), nullable=False),
    sa.Column('lifecycle_state', sa.String(length=30), nullable=False),
    sa.Column('source_content_corpus_id', sa.String(length=120), nullable=True),
    sa.Column('source_content_scope', sa.String(length=120), nullable=True),
    sa.Column('source_content_fallback_used', sa.Boolean(), nullable=False),
    sa.Column('source_content_item_id', sa.Integer(), nullable=True),
    sa.Column('requested_scene_count', sa.Integer(), nullable=True),
    sa.Column('requested_segment_count', sa.Integer(), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claimed_by', sa.String(length=120), nullable=True),
    sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_after_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('request_metadata_json', sa.Text(), nullable=False),
    sa.Column('dispatch_payload_json', sa.Text(), nullable=False),
    sa.Column('output_metadata_json', sa.Text(), nullable=False),
    sa.Column('output_asset_filename', sa.String(length=255), nullable=True),
    sa.Column('output_asset_path', sa.String(length=1024), nullable=True),
    sa.Column('output_content_type', sa.String(length=120), nullable=True),
    sa.Column('output_file_size_bytes', sa.Integer(), nullable=True),
    sa.Column('artifact_retention_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_downloaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('artifact_deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('artifact_cleanup_attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('artifact_cleanup_retry_after_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('artifact_cleanup_failure_count', sa.Integer(), nullable=False),
    sa.Column('artifact_cleanup_error', sa.Text(), nullable=True),
    sa.Column('status_note', sa.Text(), nullable=True),
    sa.Column('failure_code', sa.String(length=120), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_media_render_jobs_artifact_cleanup_retry_after_at'), 'media_render_jobs', ['artifact_cleanup_retry_after_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_artifact_deleted_at'), 'media_render_jobs', ['artifact_deleted_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_artifact_retention_expires_at'), 'media_render_jobs', ['artifact_retention_expires_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_claim_expires_at'), 'media_render_jobs', ['claim_expires_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_claimed_by'), 'media_render_jobs', ['claimed_by'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_exam'), 'media_render_jobs', ['exam'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_id'), 'media_render_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_lesson_mode'), 'media_render_jobs', ['lesson_mode'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_lifecycle_state'), 'media_render_jobs', ['lifecycle_state'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_queued_at'), 'media_render_jobs', ['queued_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_render_type'), 'media_render_jobs', ['render_type'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_retry_after_at'), 'media_render_jobs', ['retry_after_at'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_source_content_corpus_id'), 'media_render_jobs', ['source_content_corpus_id'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_source_content_item_id'), 'media_render_jobs', ['source_content_item_id'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_source_content_scope'), 'media_render_jobs', ['source_content_scope'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_source_export_format'), 'media_render_jobs', ['source_export_format'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_subject'), 'media_render_jobs', ['subject'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_topic'), 'media_render_jobs', ['topic'], unique=False)
    op.create_index(op.f('ix_media_render_jobs_user_id'), 'media_render_jobs', ['user_id'], unique=False)
    op.create_table('quizzes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('difficulty', sa.String(length=50), nullable=False),
    sa.Column('quiz_mode', sa.String(length=50), nullable=False),
    sa.Column('question_count', sa.Integer(), nullable=False),
    sa.Column('questions_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quizzes_exam'), 'quizzes', ['exam'], unique=False)
    op.create_index(op.f('ix_quizzes_id'), 'quizzes', ['id'], unique=False)
    op.create_index(op.f('ix_quizzes_topic'), 'quizzes', ['topic'], unique=False)
    op.create_index(op.f('ix_quizzes_user_id'), 'quizzes', ['user_id'], unique=False)
    op.create_table('topic_progress',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('attempts_count', sa.Integer(), nullable=False),
    sa.Column('correct_answers', sa.Integer(), nullable=False),
    sa.Column('total_answers', sa.Integer(), nullable=False),
    sa.Column('accuracy', sa.Float(), nullable=False),
    sa.Column('difficulty_band', sa.String(length=50), nullable=False),
    sa.Column('weak_topic', sa.Boolean(), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'exam', 'subject', 'chapter', 'topic', name='uq_topic_progress_user_exam_subject_chapter_topic')
    )
    op.create_index(op.f('ix_topic_progress_exam'), 'topic_progress', ['exam'], unique=False)
    op.create_index(op.f('ix_topic_progress_id'), 'topic_progress', ['id'], unique=False)
    op.create_index(op.f('ix_topic_progress_topic'), 'topic_progress', ['topic'], unique=False)
    op.create_index(op.f('ix_topic_progress_user_id'), 'topic_progress', ['user_id'], unique=False)
    op.create_table('topic_studies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('study_count', sa.Integer(), nullable=False),
    sa.Column('last_interaction_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'exam', 'subject', 'chapter', 'topic', name='uq_topic_studies_user_exam_subject_chapter_topic')
    )
    op.create_index(op.f('ix_topic_studies_exam'), 'topic_studies', ['exam'], unique=False)
    op.create_index(op.f('ix_topic_studies_id'), 'topic_studies', ['id'], unique=False)
    op.create_index(op.f('ix_topic_studies_topic'), 'topic_studies', ['topic'], unique=False)
    op.create_index(op.f('ix_topic_studies_user_id'), 'topic_studies', ['user_id'], unique=False)
    op.create_table('user_profiles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('avatar_url', sa.String(length=512), nullable=True),
    sa.Column('avatar_initials', sa.String(length=12), nullable=True),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('locale', sa.String(length=50), nullable=True),
    sa.Column('onboarding_state', sa.String(length=30), nullable=False),
    sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('user_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('session_token_hash', sa.String(length=128), nullable=False),
    sa.Column('auth_method', sa.String(length=30), nullable=False),
    sa.Column('session_label', sa.String(length=120), nullable=True),
    sa.Column('device_label', sa.String(length=120), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_authenticated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoke_reason', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_sessions_id'), 'user_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_user_sessions_session_token_hash'), 'user_sessions', ['session_token_hash'], unique=True)
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_table('user_settings',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('theme_preference', sa.String(length=20), nullable=False),
    sa.Column('mentor_mode', sa.String(length=20), nullable=False),
    sa.Column('preferred_exam', sa.String(length=50), nullable=False),
    sa.Column('preferred_subject', sa.String(length=100), nullable=False),
    sa.Column('current_exam', sa.String(length=50), nullable=False),
    sa.Column('current_subject', sa.String(length=100), nullable=False),
    sa.Column('timezone', sa.String(length=100), nullable=True),
    sa.Column('study_reminders_enabled', sa.Boolean(), nullable=False),
    sa.Column('marketing_emails_enabled', sa.Boolean(), nullable=False),
    sa.Column('progress_digest_frequency', sa.String(length=30), nullable=False),
    sa.Column('billing_notifications_enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('quiz_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('quiz_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('exam', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('chapter', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('difficulty', sa.String(length=50), nullable=False),
    sa.Column('quiz_mode', sa.String(length=50), nullable=False),
    sa.Column('submitted_answers_json', sa.Text(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('total_questions', sa.Integer(), nullable=False),
    sa.Column('accuracy', sa.Float(), nullable=False),
    sa.Column('incorrect_questions_json', sa.Text(), nullable=False),
    sa.Column('weak_areas_json', sa.Text(), nullable=False),
    sa.Column('topic_breakdown_json', sa.Text(), nullable=False),
    sa.Column('next_recommendation', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quiz_attempts_exam'), 'quiz_attempts', ['exam'], unique=False)
    op.create_index(op.f('ix_quiz_attempts_id'), 'quiz_attempts', ['id'], unique=False)
    op.create_index(op.f('ix_quiz_attempts_topic'), 'quiz_attempts', ['topic'], unique=False)
    op.create_index(op.f('ix_quiz_attempts_user_id'), 'quiz_attempts', ['user_id'], unique=False)
    op.create_table('usage_consumption_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('limit_key', sa.String(length=80), nullable=False),
    sa.Column('source_action', sa.String(length=120), nullable=False),
    sa.Column('units_consumed', sa.Integer(), nullable=False),
    sa.Column('plan_tier', sa.String(length=30), nullable=False),
    sa.Column('subscription_status', sa.String(length=30), nullable=False),
    sa.Column('exam', sa.String(length=50), nullable=True),
    sa.Column('subject', sa.String(length=100), nullable=True),
    sa.Column('content_subject', sa.String(length=100), nullable=True),
    sa.Column('chapter', sa.String(length=255), nullable=True),
    sa.Column('topic', sa.String(length=255), nullable=True),
    sa.Column('lesson_mode', sa.String(length=50), nullable=True),
    sa.Column('export_format', sa.String(length=50), nullable=True),
    sa.Column('render_type', sa.String(length=50), nullable=True),
    sa.Column('media_render_job_id', sa.Integer(), nullable=True),
    sa.Column('metadata_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['media_render_job_id'], ['media_render_jobs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_consumption_records_created_at'), 'usage_consumption_records', ['created_at'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_exam'), 'usage_consumption_records', ['exam'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_export_format'), 'usage_consumption_records', ['export_format'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_id'), 'usage_consumption_records', ['id'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_lesson_mode'), 'usage_consumption_records', ['lesson_mode'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_limit_key'), 'usage_consumption_records', ['limit_key'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_media_render_job_id'), 'usage_consumption_records', ['media_render_job_id'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_render_type'), 'usage_consumption_records', ['render_type'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_source_action'), 'usage_consumption_records', ['source_action'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_subject'), 'usage_consumption_records', ['subject'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_topic'), 'usage_consumption_records', ['topic'], unique=False)
    op.create_index(op.f('ix_usage_consumption_records_user_id'), 'usage_consumption_records', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usage_consumption_records_user_id'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_topic'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_subject'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_source_action'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_render_type'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_media_render_job_id'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_limit_key'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_lesson_mode'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_id'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_export_format'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_exam'), table_name='usage_consumption_records')
    op.drop_index(op.f('ix_usage_consumption_records_created_at'), table_name='usage_consumption_records')
    op.drop_table('usage_consumption_records')
    op.drop_index(op.f('ix_quiz_attempts_user_id'), table_name='quiz_attempts')
    op.drop_index(op.f('ix_quiz_attempts_topic'), table_name='quiz_attempts')
    op.drop_index(op.f('ix_quiz_attempts_id'), table_name='quiz_attempts')
    op.drop_index(op.f('ix_quiz_attempts_exam'), table_name='quiz_attempts')
    op.drop_table('quiz_attempts')
    op.drop_table('user_settings')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_session_token_hash'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_id'), table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_table('user_profiles')
    op.drop_index(op.f('ix_topic_studies_user_id'), table_name='topic_studies')
    op.drop_index(op.f('ix_topic_studies_topic'), table_name='topic_studies')
    op.drop_index(op.f('ix_topic_studies_id'), table_name='topic_studies')
    op.drop_index(op.f('ix_topic_studies_exam'), table_name='topic_studies')
    op.drop_table('topic_studies')
    op.drop_index(op.f('ix_topic_progress_user_id'), table_name='topic_progress')
    op.drop_index(op.f('ix_topic_progress_topic'), table_name='topic_progress')
    op.drop_index(op.f('ix_topic_progress_id'), table_name='topic_progress')
    op.drop_index(op.f('ix_topic_progress_exam'), table_name='topic_progress')
    op.drop_table('topic_progress')
    op.drop_index(op.f('ix_quizzes_user_id'), table_name='quizzes')
    op.drop_index(op.f('ix_quizzes_topic'), table_name='quizzes')
    op.drop_index(op.f('ix_quizzes_id'), table_name='quizzes')
    op.drop_index(op.f('ix_quizzes_exam'), table_name='quizzes')
    op.drop_table('quizzes')
    op.drop_index(op.f('ix_media_render_jobs_user_id'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_topic'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_subject'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_source_export_format'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_source_content_scope'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_source_content_item_id'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_source_content_corpus_id'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_retry_after_at'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_render_type'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_queued_at'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_lifecycle_state'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_lesson_mode'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_id'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_exam'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_claimed_by'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_claim_expires_at'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_artifact_retention_expires_at'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_artifact_deleted_at'), table_name='media_render_jobs')
    op.drop_index(op.f('ix_media_render_jobs_artifact_cleanup_retry_after_at'), table_name='media_render_jobs')
    op.drop_table('media_render_jobs')
    op.drop_index(op.f('ix_email_otp_challenges_user_id'), table_name='email_otp_challenges')
    op.drop_index(op.f('ix_email_otp_challenges_id'), table_name='email_otp_challenges')
    op.drop_index(op.f('ix_email_otp_challenges_email'), table_name='email_otp_challenges')
    op.drop_table('email_otp_challenges')
    op.drop_index(op.f('ix_content_items_topic'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_subject'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_slug'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_reviewer_user_id'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_publisher_user_id'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_lifecycle_state'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_id'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_exam'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_content_type'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_author_user_id'), table_name='content_items')
    op.drop_table('content_items')
    op.drop_index(op.f('ix_billing_event_receipts_user_id'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_subscription_ref'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_resolved_subscription_status'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_resolved_premium_quota_state'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_resolved_plan_tier'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_resolved_lifecycle_state'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_provider_name'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_provider_event_id'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_processing_state'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_processed_at'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_livemode'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_last_received_at'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_id'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_failed_at'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_event_type'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_event_created_at'), table_name='billing_event_receipts')
    op.drop_index(op.f('ix_billing_event_receipts_customer_ref'), table_name='billing_event_receipts')
    op.drop_table('billing_event_receipts')
    op.drop_index(op.f('ix_analytics_events_user_id'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_topic'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_subject'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_quiz_mode'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_lesson_mode'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_id'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_feature_area'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_export_format'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_exam'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_event_name'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_created_at'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_content_source_scope'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_content_item_id'), table_name='analytics_events')
    op.drop_index(op.f('ix_analytics_events_content_corpus_id'), table_name='analytics_events')
    op.drop_table('analytics_events')
    op.drop_index(op.f('ix_user_accounts_subscription_provider_ref'), table_name='user_accounts')
    op.drop_index(op.f('ix_user_accounts_subscription_customer_ref'), table_name='user_accounts')
    op.drop_index(op.f('ix_user_accounts_id'), table_name='user_accounts')
    op.drop_index(op.f('ix_user_accounts_email'), table_name='user_accounts')
    op.drop_index(op.f('ix_user_accounts_account_role'), table_name='user_accounts')
    op.drop_table('user_accounts')
    op.drop_index(op.f('ix_runtime_process_heartbeats_worker_mode'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_stopped_at'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_status'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_service_name'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_runtime_instance_id'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_process_role'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_last_heartbeat_at'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_id'), table_name='runtime_process_heartbeats')
    op.drop_index(op.f('ix_runtime_process_heartbeats_environment'), table_name='runtime_process_heartbeats')
    op.drop_table('runtime_process_heartbeats')
