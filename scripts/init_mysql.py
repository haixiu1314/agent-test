"""用户授权的项目内 MySQL 独立实例，绝不改动系统 MySQL80 服务。"""
from pathlib import Path
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
DATA = LOCAL / 'mysql-data'
BIN = Path(shutil.which('mysql') or r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe').parent
PORT = 3307
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def port_open():
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(('127.0.0.1', PORT)) == 0


def main():
    LOCAL.mkdir(exist_ok=True)
    if (LOCAL / 'mysql-admin.json').exists():
        print('Instance already initialized. Use start-mysql.ps1; credentials left unchanged.')
        return
    if port_open():
        raise SystemExit('Port 3307 already in use; refusing to touch existing instance.')
    resume = '--resume-bootstrap' in sys.argv
    if DATA.exists() and not resume:
        raise SystemExit('Existing data directory detected; refusing to reinitialize. Inspect .local logs.')
    if not (ROOT / '.env').exists():
        raise SystemExit('Run init_local_config.py first.')
    DATA.mkdir(exist_ok=True)
    ini = LOCAL / 'mysql.ini'
    ini.write_text('[mysqld]\nport=3307\nbind-address=127.0.0.1\nmysqlx=0\n'
        f'datadir={DATA.as_posix()}\nlog-error={(LOCAL / "mysql-error.log").as_posix()}\n'
        'character-set-server=utf8mb4\ncollation-server=utf8mb4_0900_ai_ci\n'
        'innodb-buffer-pool-size=128M\n', encoding='utf-8')
    if not resume:
        initialize = subprocess.run([str(BIN / 'mysqld.exe'), f'--defaults-file={ini}', '--initialize-insecure'],
                                    capture_output=True, creationflags=FLAGS, timeout=120)
        if initialize.returncode:
            raise SystemExit('MySQL initialization failed. Inspect .local/mysql-error.log. No existing service was changed.')
    with (LOCAL / 'mysql-console.log').open('ab') as stream:
        process = subprocess.Popen([str(BIN / 'mysqld.exe'), f'--defaults-file={ini}'],
            stdout=stream, stderr=stream, creationflags=FLAGS)
    (LOCAL / 'mysql.pid').write_text(str(process.pid))
    for _ in range(60):
        if process.poll() is not None:
            raise SystemExit('MySQL exited. Inspect .local/mysql-error.log.')
        if port_open():
            break
        time.sleep(0.5)
    else:
        raise SystemExit('MySQL startup timed out.')
    password, admin_password = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
    # 凭证不出现在命令行或日志中；安装初期的空 root 密码仅用于这个新建隔离实例。
    sql = f"CREATE DATABASE agenttestlab CHARACTER SET utf8mb4; CREATE USER 'agenttestlab'@'127.0.0.1' IDENTIFIED BY '{password}'; GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES ON agenttestlab.* TO 'agenttestlab'@'127.0.0.1'; ALTER USER 'root'@'localhost' IDENTIFIED BY '{admin_password}';"
    result = subprocess.run([str(BIN / 'mysql.exe'), '--no-defaults', '--protocol=TCP',
        '--host=127.0.0.1', '--port=3307', '--user=root', '--skip-password'], input=sql,
        text=True, capture_output=True, creationflags=FLAGS, timeout=30)
    if result.returncode:
        raise SystemExit('Database account bootstrap failed; inspect local instance before retrying.')
    (LOCAL / 'mysql-admin.json').write_text(json.dumps({'host':'127.0.0.1','port':PORT,'username':'root',
        'password':admin_password}), encoding='utf-8')
    env = ROOT / '.env'
    lines = env.read_text(encoding='utf-8').splitlines()
    lines = [f'DATABASE_URL=mysql+pymysql://agenttestlab:{password}@127.0.0.1:3307/agenttestlab?charset=utf8mb4'
             if line.startswith('DATABASE_URL=') else line for line in lines]
    env.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Project MySQL initialized on 127.0.0.1:3307. Credentials saved locally; system MySQL80 unchanged.')


if __name__ == '__main__':
    main()
