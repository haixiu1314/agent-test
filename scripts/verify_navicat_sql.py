"""在独立临时数据库实际执行 Navicat SQL，并在 finally 中清理临时库。"""
import json
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from app.models.entities import Base

root = Path(__file__).resolve().parents[1]
config = json.loads((root / '.local/mysql-admin.json').read_text(encoding='utf-8-sig'))
admin_url = URL.create('mysql+pymysql', username=config['username'], password=config['password'], host=config['host'], port=config['port'])
engine = create_engine(admin_url)
temporary = 'atl_navicat_' + uuid4().hex
try:
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        connection.execute(text(f'CREATE DATABASE `{temporary}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
        connection.execute(text(f'USE `{temporary}`'))
        sql = (root / 'deploy/agenttest-Navicat-MySQL8.sql').read_text(encoding='utf-8')
        sql = '\n'.join(line for line in sql.splitlines() if not line.strip().startswith('--'))
        for statement in sql.split(';'):
            statement = statement.strip()
            if not statement or statement.startswith('CREATE DATABASE') or statement.startswith('USE '):
                continue
            connection.execute(text(statement))
        inspector = inspect(connection)
        tables = inspector.get_table_names(schema=temporary)
        assert set(tables) == set(Base.metadata.tables) | {'alembic_version'}
        for name, table in Base.metadata.tables.items():
            assert {c['name'] for c in inspector.get_columns(name, schema=temporary)} == set(table.columns.keys())
            assert len(inspector.get_foreign_keys(name, schema=temporary)) == len(table.foreign_key_constraints)
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0007_delivery'
        result = {'status': 'passed', 'tested_server': f"{config['host']}:{config['port']}", 'temporary_database_cleaned': True,
                  'schema_tables': len(tables), 'columns_and_foreign_keys': 'match current models', 'revision': '0007_delivery',
                  'target_3306': 'not executed: supplied account rejected with MySQL 1045'}
finally:
    with engine.begin() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS `{temporary}`'))
    engine.dispose()
(root / 'docs/evidence/navicat-sql-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
