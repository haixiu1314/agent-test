"""扩大已部署实例的加密响应容量，保留已有 0002 数据。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT
revision='0003_response_capacity'
down_revision='0002_cases_models'
branch_labels=None
depends_on=None

def upgrade():
    if op.get_bind().dialect.name=='mysql':
        op.alter_column('generation_runs','raw_response',existing_type=sa.Text(),type_=MEDIUMTEXT(),existing_nullable=True)
        op.alter_column('demo_runs','payload',existing_type=sa.Text(),type_=MEDIUMTEXT(),existing_nullable=False)

def downgrade():
    # 不收缩字段，避免回退时截断已保存证据；0002 应用能读取 MEDIUMTEXT。
    pass
