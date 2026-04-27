"""Add tenant_members table for cross-product RBAC

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-26 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tenant_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),   # NULL = pending (invite not accepted)
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False, server_default=''),
        # Product-level access
        sa.Column('can_access_agents', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('can_access_crm', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('can_access_billing', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('can_access_admin', sa.Boolean(), nullable=False, server_default='false'),
        # Permission levels per product
        sa.Column('agents_role', sa.String(50), nullable=False, server_default='viewer'),  # viewer|editor|admin
        sa.Column('crm_role', sa.String(50), nullable=False, server_default='viewer'),
        # CRM-only users have no AscenAI account - they login via magic link only
        sa.Column('is_crm_only', sa.Boolean(), nullable=False, server_default='false'),
        # Invite tracking
        sa.Column('invite_token_hash', sa.String(64), nullable=True),
        sa.Column('invite_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invited_by_user_id', sa.UUID(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending|active|revoked
        sa.Column('crm_workspace_id', sa.UUID(), nullable=True),  # for CRM-only users
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tenant_members_tenant_id', 'tenant_members', ['tenant_id'])
    op.create_index('ix_tenant_members_user_id', 'tenant_members', ['user_id'])
    op.create_index('ix_tenant_members_email', 'tenant_members', ['tenant_id', 'email'], unique=True)
    op.create_index('ix_tenant_members_status', 'tenant_members', ['status'])

    # Backfill: create a TenantMember row for every existing User
    op.execute("""
        INSERT INTO tenant_members (
            id, tenant_id, user_id, email, full_name,
            can_access_agents, can_access_crm, can_access_billing, can_access_admin,
            agents_role, crm_role, is_crm_only, status,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            u.tenant_id,
            u.id,
            u.email,
            u.full_name,
            true,  -- can_access_agents
            CASE WHEN u.role IN ('owner', 'admin') THEN true ELSE false END,  -- can_access_crm
            CASE WHEN u.role IN ('owner', 'admin') THEN true ELSE false END,  -- can_access_billing
            CASE WHEN u.role IN ('owner') THEN true ELSE false END,           -- can_access_admin
            CASE
                WHEN u.role = 'owner' THEN 'admin'
                WHEN u.role = 'admin' THEN 'admin'
                WHEN u.role = 'developer' THEN 'editor'
                ELSE 'viewer'
            END,  -- agents_role
            CASE
                WHEN u.role IN ('owner', 'admin') THEN 'admin'
                ELSE 'viewer'
            END,  -- crm_role
            false,  -- is_crm_only
            'active',
            u.created_at,
            u.updated_at
        FROM users u
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.drop_index('ix_tenant_members_status', table_name='tenant_members')
    op.drop_index('ix_tenant_members_email', table_name='tenant_members')
    op.drop_index('ix_tenant_members_user_id', table_name='tenant_members')
    op.drop_index('ix_tenant_members_tenant_id', table_name='tenant_members')
    op.drop_table('tenant_members')
