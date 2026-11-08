"""20,000 字符的四字节 Unicode 输入需要超过 64 KiB 的容量。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT
revision='0004_unicode_input_capacity'
down_revision='0003_response_capacity'
branch_labels=None
depends_on=None

def upgrade():
    if op.get_bind().dialect.name=='mysql':
        op.alter_column('test_cases','user_input',existing_type=sa.Text(),type_=MEDIUMTEXT(),existing_nullable=False)

def downgrade():
    # 保留容量以避免回退截断数据；0003 应用兼容该列类型。
    pass
