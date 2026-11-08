"""阶段一基础表，显式固定结构以保证未来迁移可重放。"""
from alembic import op
import sqlalchemy as sa

revision = '0001_foundation'
down_revision = None
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    op.create_table('users', *common(), sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(200), nullable=False), sa.Column('role', sa.String(20), nullable=False))
    op.create_table('projects', *common(), sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('description', sa.Text(), nullable=False),
        sa.Column('business_type', sa.String(50), nullable=False))
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'])
    op.create_table('agents', *common(), sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False), sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False))
    op.create_index('ix_agents_project_id', 'agents', ['project_id'])
    op.create_table('agent_versions', *common(), sa.Column('agent_id', sa.String(36), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('secret', sa.Text(), nullable=False), sa.UniqueConstraint('agent_id', 'version'))
    op.create_index('ix_agent_versions_agent_id', 'agent_versions', ['agent_id'])
    op.create_table('operation_logs', *common(), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(80), nullable=False), sa.Column('resource_id', sa.String(36), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False))
    op.create_index('ix_operation_logs_user_id', 'operation_logs', ['user_id'])


def downgrade():
    for table in ['operation_logs', 'agent_versions', 'agents', 'projects', 'users']:
        op.drop_table(table)
