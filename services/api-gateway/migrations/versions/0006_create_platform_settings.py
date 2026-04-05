"""create platform settings table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-03 01:52:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json

# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create table
    op.create_table(
        'platform_settings',
        sa.Column('key', sa.String(length=100), primary_key=True),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # 2. Seed initial data
    # We use raw SQL for seeding during migration
    language_greeting_map = {
        "en": "For English, please continue.",
        "fr": "Pour le français, parlez français s'il vous plaît.",
        "zh": "对于中文请直接用中文交流。",
        "es": "Para español, por favor hable en español.",
        "de": "Für Deutsch sprechen Sie bitte Deutsch.",
        "it": "Per l'italiano, per favore parla in italiano.",
        "pt": "Para português, por favor fale em português.",
    }
    
    language_fallback_map = {
        "en": "Sorry, I didn't quite catch that. Could you say that again?",
        "fr": "Désolé, je n'ai pas bien compris. Pourriez-vous répéter?",
        "zh": "对不起，我没听清。请再说一遍。",
        "es": "Lo siento, no he entendido bien. ¿Podría repetir?",
        "de": "Entschuldigung, das habe ich nicht verstanden. Könnten Sie das bitte wiederholen?",
        "it": "Scusa, non ho capito bene. Potresti ripetere?",
        "pt": "Desculpe, não entendi bem. Você poderia repetir?",
    }

    voice_protocol_template = """\
## Multi-lingual & IVR Operational Protocol
- **INITIAL GREETING (MANDATORY)**: You MUST begin every new voice session with the following opening:
  "{opening}"
- **DYNAMIC LANGUAGE ADAPTATION**: You are globally configured to handle the following languages: {all_langs}.
- **PROTOCOL**: Upon detecting ANY of the supported languages, pivot your response language immediately to match the user without requesting procedural confirmation (e.g., avoid "Would you like to speak French?").
- **CONTEXTUAL METADATA**: Ensure the `language` field in your response metadata accurately identifies the communication language used in the current turn.
"""

    op.execute(
        sa.text("INSERT INTO platform_settings (key, value, description) VALUES (:key, CAST(:value AS JSONB), :desc)")
        .bindparams(key="language_greeting_map", value=json.dumps(language_greeting_map), desc="Mapping of language codes to audible greeting phrases")
    )
    op.execute(
        sa.text("INSERT INTO platform_settings (key, value, description) VALUES (:key, CAST(:value AS JSONB), :desc)")
        .bindparams(key="language_fallback_map", value=json.dumps(language_fallback_map), desc="Mapping of language codes to fallback phrases")
    )
    op.execute(
        sa.text("INSERT INTO platform_settings (key, value, description) VALUES (:key, CAST(:value AS JSONB), :desc)")
        .bindparams(key="voice_protocol_template", value=json.dumps({"template": voice_protocol_template}), desc="Base system prompt template for voice agents")
    )


def downgrade():
    op.drop_table('platform_settings')
