"""在本项目私有实例的临时数据库中验证升降级；不删除业务库。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

root=Path(__file__).resolve().parents[1]
admin=json.loads((root/'.local/mysql-admin.json').read_text(encoding='utf-8'))
engine=create_engine(URL.create('mysql+pymysql',username=admin['username'],password=admin['password'],host=admin['host'],port=admin['port']))
name='atl_migration_'+uuid4().hex
with engine.begin() as conn:
    conn.execute(text(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4'))
url=URL.create('mysql+pymysql',username=admin['username'],password=admin['password'],host=admin['host'],port=admin['port'],database=name)
environment={**os.environ,'DATABASE_URL':url.render_as_string(hide_password=False),
             'PYTHONPATH':str(root/'runtime-packages')+os.pathsep+str(root/'backend')}
try:
    for operation in [('upgrade','head'),('downgrade','base'),('upgrade','head')]:
        result=subprocess.run([sys.executable,'-m','alembic',*operation],cwd=root/'backend',env=environment,capture_output=True,text=True,timeout=60)
        if result.returncode:
            raise RuntimeError('Migration failed; inspect migration code (raw output withheld to protect configuration).')
    probe=create_engine(url)
    with probe.connect() as conn:
        tables=conn.execute(text('SHOW TABLES')).scalars().all()
        assert set(tables)=={'users','projects','agents','agent_versions','operation_logs','alembic_version',
                            'test_suites','test_suite_versions','test_cases','model_configs','generation_runs','demo_runs',
                            'test_tasks','test_results','evaluation_details','trace_events','security_findings',
                            'knowledge_bases','rag_documents','rag_chunks','rag_issues','rag_evaluations','rag_datasets','reports','regression_records','system_parameters'}
    probe.dispose()
    print(json.dumps({'status':'passed','checks':['upgrade','downgrade','reupgrade','table_schema']}))
finally:
    with engine.begin() as conn:
        conn.execute(text(f'DROP DATABASE `{name}`'))
    engine.dispose()

