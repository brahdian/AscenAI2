"""Centralize configurations and expand schemas.

Revision ID: 0015
Revises: 0013
Create Date: 2026-04-07 21:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- agents ---
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS agent_config JSONB NOT NULL DEFAULT '{}'::jsonb")
    # Drop legacy columns if they exist
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS greeting_message")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS voice_greeting_url")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS auto_detect_language")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS supported_languages")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS voice_system_prompt")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS tools")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS knowledge_base_ids")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS llm_config")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS escalation_config")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS voice_config")

    # --- template_playbooks ---
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS flow_definition")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS tone")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS dos")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS donts")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS scenarios")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS out_of_scope_response")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS fallback_response")
    op.execute("ALTER TABLE template_playbooks DROP COLUMN IF EXISTS custom_escalation_message")

    # --- agent_playbooks ---
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS instructions")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS tone")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS dos")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS donts")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS scenarios")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS out_of_scope_response")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS fallback_response")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS custom_escalation_message")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS input_schema")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS output_schema")
    op.execute("ALTER TABLE agent_playbooks DROP COLUMN IF EXISTS tools")

    # --- agent_guardrails ---
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS blocked_keywords")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS blocked_topics")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS allowed_topics")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS profanity_filter")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS pii_redaction")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS pii_pseudonymization")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS max_response_length")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS require_disclaimer")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS blocked_message")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS off_topic_message")
    op.execute("ALTER TABLE agent_guardrails DROP COLUMN IF EXISTS content_filter_level")

    # --- sessions & messages metadata ---
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ")
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS turn_count INTEGER DEFAULT 0")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_last_activity ON sessions (last_activity_at)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS playbook_name VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS sources JSONB")
    op.execute("ALTER TABLE message_feedback ADD COLUMN IF NOT EXISTS playbook_correction JSONB")
    op.execute("ALTER TABLE message_feedback ADD COLUMN IF NOT EXISTS tool_corrections JSONB")


def downgrade() -> None:
    # --- agents ---
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS greeting_message TEXT")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_greeting_url TEXT")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS auto_detect_language BOOLEAN DEFAULT true")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS supported_languages JSONB DEFAULT '[\"en\"]'::jsonb")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_system_prompt TEXT")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS tools JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS knowledge_base_ids JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS llm_config JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS escalation_config JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_config JSONB DEFAULT '{}'::jsonb")
    
    # --- template_playbooks ---
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS flow_definition JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS tone VARCHAR(255) DEFAULT 'professional'")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS dos JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS donts JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS scenarios JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS out_of_scope_response TEXT")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS fallback_response TEXT")
    op.execute("ALTER TABLE template_playbooks ADD COLUMN IF NOT EXISTS custom_escalation_message TEXT")
    
    # --- agent_playbooks ---
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS instructions TEXT")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS tone VARCHAR(255) DEFAULT 'professional'")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS dos JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS donts JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS scenarios JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS out_of_scope_response TEXT")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS fallback_response TEXT")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS custom_escalation_message TEXT")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS input_schema JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS output_schema JSONB DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE agent_playbooks ADD COLUMN IF NOT EXISTS tools JSONB DEFAULT '[]'::jsonb")
    
    # --- agent_guardrails ---
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_keywords JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_topics JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS allowed_topics JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS profanity_filter BOOLEAN DEFAULT true")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS pii_redaction BOOLEAN DEFAULT true")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS pii_pseudonymization BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS max_response_length INTEGER DEFAULT 2000")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS require_disclaimer BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS blocked_message TEXT")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS off_topic_message TEXT")
    op.execute("ALTER TABLE agent_guardrails ADD COLUMN IF NOT EXISTS content_filter_level VARCHAR(255) DEFAULT 'medium'")
    
    # --- sessions & messages metadata ---
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS last_activity_at")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS turn_count")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS playbook_name")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS sources")
    op.execute("ALTER TABLE message_feedback DROP COLUMN IF EXISTS playbook_correction")
    op.execute("ALTER TABLE message_feedback DROP COLUMN IF EXISTS tool_corrections")
