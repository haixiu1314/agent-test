"""报告、回归及系统参数；安全风险与轨迹表已在 0005 发布。"""

from alembic import op
import sqlalchemy as sa

revision = "0007_delivery"
down_revision = "0006_rag"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "reports",
        *base_columns(),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("test_tasks.id"), nullable=False
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_reports_task_id", "reports", ["task_id"])
    op.create_table(
        "regression_records",
        *base_columns(),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column(
            "baseline_id", sa.String(36), sa.ForeignKey("test_tasks.id"), nullable=False
        ),
        sa.Column(
            "candidate_id",
            sa.String(36),
            sa.ForeignKey("test_tasks.id"),
            nullable=False,
        ),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_regression_records_project_id", "regression_records", ["project_id"]
    )
    op.create_table(
        "system_parameters",
        *base_columns(),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("system_parameters")
    op.drop_table("regression_records")
    op.drop_table("reports")
