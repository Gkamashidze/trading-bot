"""Give new audit events an unambiguous append order without rewriting history."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_log_chain_position_seq")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_position BIGINT")
    op.execute("""ALTER TABLE audit_log ALTER COLUMN chain_position
                  SET DEFAULT nextval('audit_log_chain_position_seq')""")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_audit_log_chain_position
                  ON audit_log (chain_position) WHERE chain_position IS NOT NULL""")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_log_chain_position")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS chain_position")
    op.execute("DROP SEQUENCE IF EXISTS audit_log_chain_position_seq")
