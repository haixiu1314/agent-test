"""首次生成密钥；不覆盖现有 .env，数据库密码由用户在本地填写。"""
from pathlib import Path
import secrets
import base64

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; left unchanged.')
else:
    template = (root / '.env.example').read_text(encoding='utf-8')
    template = template.replace('JWT_SECRET_KEY=\n', f'JWT_SECRET_KEY={secrets.token_urlsafe(48)}\n')
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    template = template.replace('ENCRYPTION_KEY=\n', f'ENCRYPTION_KEY={key}\n')
    target.write_text(template, encoding='utf-8')
    print('Created .env with random keys. Fill DATABASE_URL locally before starting backend.')
