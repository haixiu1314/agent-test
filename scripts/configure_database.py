"""在用户本机终端安全输入目标密码，连接验证成功后才切换数据库。"""
import getpass
import os
from pathlib import Path
import re
import sys
from datetime import datetime
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from app.db.session import make_engine
from app.models.entities import Base

root = Path(__file__).resolve().parents[1]
try:
    username = input('MySQL user [root]: ').strip() or 'root'
    password = getpass.getpass('MySQL password (hidden, local only): ')
    url = URL.create('mysql+pymysql', username=username, password=password, host='localhost', port=3306, database='agenttest', query={'charset': 'utf8mb4'}).render_as_string(hide_password=False)
    if '--migrate' in sys.argv:
        os.environ['ATL_TARGET_DATABASE_URL'] = url
        from migrate_to_localhost import main
        main()
    else:
        engine = make_engine(url)
        with engine.connect() as connection:
            assert set(Base.metadata.tables) | {'alembic_version'} == set(inspect(connection).get_table_names()), 'Import the Navicat SQL into agenttest first'
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0007_delivery', 'Unexpected migration version'
        engine.dispose()
        env_path = root / '.env'
        current = env_path.read_text(encoding='utf-8-sig')
        assert len(re.findall(r'^DATABASE_URL\s*=', current, flags=re.M)) == 1, 'Expected one DATABASE_URL setting'
        backup = root / '.local' / ('env-before-db-config-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.backup')
        backup.parent.mkdir(exist_ok=True)
        backup.write_text(current, encoding='utf-8')
        env_path.write_text(re.sub(r'^DATABASE_URL\s*=.*$', lambda _: 'DATABASE_URL=' + url, current, flags=re.M), encoding='utf-8')
        print('Database configured: localhost:3306/agenttest. Restart npm run dev. Existing encryption/JWT keys preserved.')
except (Exception, KeyboardInterrupt) as exc:
    original = getattr(exc, 'orig', exc)
    code = original.args[0] if original.args and isinstance(original.args[0], int) else type(exc).__name__
    print(f'Database configuration stopped ({code}). No source data deleted. Check local credentials and target schema; no password is logged.', file=sys.stderr)
    sys.exit(1)
