"""测试集/用例及真实模型生成记录。"""
from alembic import op
import sqlalchemy as sa

revision='0002_cases_models'
down_revision='0001_foundation'
branch_labels=None
depends_on=None


def common():
    return [sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False)]


def upgrade():
    op.create_table('test_suites',*common(),sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),sa.Column('description',sa.Text(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False))
    op.create_index('ix_test_suites_project_id','test_suites',['project_id'])
    op.create_table('test_suite_versions',*common(),sa.Column('suite_id',sa.String(36),sa.ForeignKey('test_suites.id'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),sa.UniqueConstraint('suite_id','revision'))
    op.create_index('ix_test_suite_versions_suite_id','test_suite_versions',['suite_id'])
    op.create_table('model_configs',*common(),sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),sa.Column('purpose',sa.String(30),nullable=False),sa.Column('config',sa.JSON(),nullable=False),sa.Column('secret',sa.Text(),nullable=False))
    op.create_table('generation_runs',*common(),sa.Column('owner_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),sa.Column('model_config_id',sa.String(36),sa.ForeignKey('model_configs.id',ondelete='SET NULL'),nullable=True),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('request_data',sa.JSON(),nullable=False),sa.Column('model_snapshot',sa.JSON(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=True),sa.Column('raw_response',sa.Text(),nullable=True),sa.Column('usage',sa.JSON(),nullable=False),
        sa.Column('error_code',sa.String(80),nullable=True),sa.Column('saved_indexes',sa.JSON(),nullable=False))
    op.create_index('ix_generation_runs_owner_id','generation_runs',['owner_id'])
    op.create_index('ix_generation_runs_project_id','generation_runs',['project_id'])
    op.create_table('test_cases',*common(),sa.Column('suite_id',sa.String(36),sa.ForeignKey('test_suites.id'),nullable=False),
        sa.Column('name',sa.String(160),nullable=False),sa.Column('test_type',sa.String(30),nullable=False),sa.Column('scenario',sa.Text(),nullable=False),
        sa.Column('preconditions',sa.Text(),nullable=False),sa.Column('user_input',sa.Text(),nullable=False),sa.Column('history',sa.JSON(),nullable=False),
        sa.Column('expected_behavior',sa.Text(),nullable=False),sa.Column('expected_result',sa.Text(),nullable=False),sa.Column('rules',sa.JSON(),nullable=False),
        sa.Column('priority',sa.String(5),nullable=False),sa.Column('tags',sa.JSON(),nullable=False),sa.Column('source',sa.String(10),nullable=False),
        sa.Column('generation_run_id',sa.String(36),sa.ForeignKey('generation_runs.id'),nullable=True),sa.Column('revision',sa.Integer(),nullable=False))
    op.create_index('ix_test_cases_suite_id','test_cases',['suite_id'])
    op.create_index('ix_test_cases_test_type','test_cases',['test_type'])
    op.create_table('demo_runs',*common(),sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('owner_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('model_snapshot',sa.JSON(),nullable=False),sa.Column('payload',sa.Text(),nullable=False))
    op.create_index('ix_demo_runs_project_id','demo_runs',['project_id'])


def downgrade():
    for name in ['demo_runs','test_cases','generation_runs','model_configs','test_suite_versions','test_suites']:
        op.drop_table(name)
