"""Plans, subscriptions, audit_logs tables + ApiKey/Client columns.

Revision ID: 002
Revises: 001
Create Date: 2026-06-21 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # plans
    # ------------------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("monthly_price", sa.Float(), nullable=True),
        sa.Column("annual_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
        sa.Column("monthly_request_limit", sa.Integer(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_api_keys", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_file_size_mb", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_models", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("allow_premium_models", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("allow_webhooks", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("allow_detailed_logs", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("allow_team_members", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("support_level", sa.String(32), nullable=False, server_default="community"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_plans_id", "plans", ["id"])
    op.create_index("ix_plans_slug", "plans", ["slug"], unique=True)

    # ------------------------------------------------------------------
    # subscriptions
    # ------------------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
        sa.UniqueConstraint("stripe_subscription_id"),
    )
    op.create_index("ix_subscriptions_id", "subscriptions", ["id"])
    op.create_index("ix_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"])

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ------------------------------------------------------------------
    # api_keys — add new columns
    # ------------------------------------------------------------------
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(
            sa.Column("name", sa.String(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("environment", sa.String(32), nullable=False, server_default="production")
        )
        batch_op.add_column(
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
        )

    # ------------------------------------------------------------------
    # clients — add organization column
    # ------------------------------------------------------------------
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column("organization", sa.String(255), nullable=True)
        )

    # ------------------------------------------------------------------
    # Seed default plans
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO plans (
            name, slug, description, monthly_price, annual_price, currency,
            monthly_request_limit, rate_limit_per_minute, max_api_keys,
            max_file_size_mb, max_models, allow_premium_models, allow_webhooks,
            allow_detailed_logs, allow_team_members, support_level, is_active, features
        ) VALUES
        (
            'Free', 'free', 'Plan gratuit pour démarrer',
            0, 0, 'EUR',
            100, 10, 2,
            5, 1, 0, 0,
            0, 0, 'community', 1,
            '["100 requêtes/mois", "Support communautaire", "2 clés API max"]'
        ),
        (
            'Starter', 'starter', 'Plan idéal pour les petits projets',
            29, 290, 'EUR',
            1000, 30, 5,
            10, 3, 0, 0,
            0, 0, 'email', 1,
            '["1 000 requêtes/mois", "Support email", "5 clés API max"]'
        ),
        (
            'Pro', 'pro', 'Pour les projets à forte charge',
            99, 990, 'EUR',
            10000, 60, 20,
            50, 10, 1, 1,
            1, 0, 'priority', 1,
            '["10 000 requêtes/mois", "Support prioritaire", "Webhooks", "Logs détaillés", "20 clés API max"]'
        ),
        (
            'Enterprise', 'enterprise', 'Solution sur mesure pour les entreprises',
            NULL, NULL, 'EUR',
            100000, 200, 100,
            200, 50, 1, 1,
            1, 1, 'dedicated', 1,
            '["100 000+ requêtes", "SLA dédié", "Support 24/7", "Membres d équipe", "100 clés API max"]'
        )
    """)


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("organization")

    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("environment")
        batch_op.drop_column("name")

    op.drop_table("audit_logs")
    op.drop_table("subscriptions")
    op.drop_table("plans")
