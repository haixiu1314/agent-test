"""统一启动的数据库检查与升级；不把含凭据的连接串输出到终端。"""
import sys
import subprocess
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import Settings
from app.db.session import make_engine

try:
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        connection = engine.connect()
    except SQLAlchemyError:
        if url.host not in ('localhost', '127.0.0.1') or url.port != 3307:
            raise
        print('Starting the legacy project MySQL instance on 3307...', flush=True)
        subprocess.run(['powershell.exe', '-NoProfile', '-File', str(Settings.model_config['env_file'].parent / 'scripts/start-mysql.ps1')], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        connection = engine.connect()
    with connection:
        name = connection.scalar(text('SELECT DATABASE()'))
    engine.dispose()
    print(f'Database: {url.host}:{url.port or 3306}/{name}', flush=True)
except (SQLAlchemyError, ValueError, subprocess.SubprocessError):
    print('Database unavailable. Check MySQL service and DATABASE_URL in local .env; import the Navicat SQL if the database does not exist.', file=sys.stderr)
    sys.exit(1)

from alembic.config import Config
from alembic import command
config = Config(str(Settings.model_config['env_file'].parent / 'backend/alembic.ini'))
try:
    command.upgrade(config, 'head')
except Exception:
    print('Database migration failed. Check the local database structure; credentials are not displayed.', file=sys.stderr)
    sys.exit(1)
