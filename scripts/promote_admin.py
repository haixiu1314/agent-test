"""本地管理员命令：仅提升已注册账号，不提供公开提权接口。"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.core.config import Settings
from app.db.session import make_engine, make_sessions
from app.models.entities import User

parser = argparse.ArgumentParser()
parser.add_argument('username')
args = parser.parse_args()
engine = make_engine(Settings().database_url.get_secret_value())
with make_sessions(engine)() as db:
    user = db.scalar(select(User).where(User.username == args.username.lower()))
    if user is None:
        raise SystemExit('Account not found; register it first.')
    user.role = 'admin'
    db.commit()
    print('Role updated. Keep this script and .env accessible only to the machine owner.')
engine.dispose()
