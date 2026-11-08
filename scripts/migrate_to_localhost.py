"""将旧实例快照复制到空的 localhost:3306/agenttest，核对后切换本地配置。

目标连接从 ATL_TARGET_DATABASE_URL 读取；日志及证据不包含密码或业务行。
已有目标表时拒绝覆盖，旧库始终保留。执行前停止平台写入。
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from app.core.config import Settings
from app.db.session import make_engine
from app.models.entities import Base

ROOT = Path(__file__).resolve().parents[1]


def digest(rows):
    """按完整行排序后计算摘要，排除数据库返回顺序的影响。"""
    serialized = sorted(json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str) for row in rows)
    return hashlib.sha256('\n'.join(serialized).encode()).hexdigest()


def main():
    target_string = os.environ.pop('ATL_TARGET_DATABASE_URL')
    target_url = make_url(target_string)
    assert target_url.host == 'localhost' and target_url.port == 3306 and target_url.database == 'agenttest'
    old_settings = Settings()
    source_string = old_settings.database_url.get_secret_value()
    source_url = make_url(source_string)
    assert (source_url.port, source_url.database) == (3307, 'agenttestlab'), 'Unexpected source; no changes made'
    source = make_engine(source_string)
    admin = make_engine(target_url._replace(database=None).render_as_string(hide_password=False))
    with admin.begin() as connection:
        connection.execute(text('CREATE DATABASE IF NOT EXISTS `agenttest` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    admin.dispose()
    target = make_engine(target_string)
    assert not inspect(target).get_table_names(), 'Target already contains tables; refusing to overwrite'
    with source.connect() as connection:
        active = connection.scalar(text("SELECT COUNT(*) FROM test_tasks WHERE status IN ('pending','running','paused','queued')"))
        assert active == 0, 'Stop active tasks before migration'
    # Alembic uses Settings; override only for this migration, before changing .env.
    os.environ['DATABASE_URL'] = target_string
    command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
    results = []
    with source.connect().execution_options(isolation_level='REPEATABLE READ') as old:
        with old.begin(), target.begin() as new:
            for table in Base.metadata.sorted_tables:
                rows = old.execute(select(table)).mappings().all()
                for start in range(0, len(rows), 500):
                    new.execute(table.insert(), [dict(row) for row in rows[start:start + 500]])
                copied = new.execute(select(table)).mappings().all()
                assert len(copied) == len(rows) and digest(copied) == digest(rows), table.name
                results.append({'table': table.name, 'rows': len(rows), 'content_match': True})
            assert new.scalar(text('SELECT version_num FROM alembic_version')) == '0007_delivery'
    env_path = ROOT / '.env'
    current = env_path.read_text(encoding='utf-8-sig')
    assert len(re.findall(r'^DATABASE_URL\s*=', current, re.M)) == 1
    backup = ROOT / '.local' / ('env-before-3306-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.backup')
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(current, encoding='utf-8')
    updated = re.sub(r'^DATABASE_URL\s*=.*$', lambda _: 'DATABASE_URL=' + target_string, current, flags=re.M)
    env_path.write_text(updated, encoding='utf-8')
    report = {'status': 'passed', 'date': '2026-11-06', 'source': '127.0.0.1:3307/agenttestlab',
              'target': 'localhost:3306/agenttest', 'old_database_preserved': True,
              'business_tables': len(results), 'tables': results, 'configuration_switched': True,
              'encryption_and_jwt_keys': 'preserved', 'schema_revision': '0007_delivery'}
    (ROOT / 'docs/evidence/localhost-migration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'tables'}, ensure_ascii=False))
    source.dispose()
    target.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Migration stopped ({type(exc).__name__}). No source data deleted. Check destination state before retrying; configuration switches only after successful verification.', file=sys.stderr)
        sys.exit(1)
