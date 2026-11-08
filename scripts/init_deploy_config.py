"""生成项目私有 MinIO 凭证；已有文件不覆盖。"""
from pathlib import Path
import secrets
target=Path(__file__).resolve().parents[1]/'deploy'/'.env'
if target.exists():
    print('deploy/.env exists; left unchanged.')
else:
    target.write_text('MINIO_ROOT_USER=agenttestlab\nMINIO_ROOT_PASSWORD='+secrets.token_urlsafe(36)+'\n',encoding='utf-8')
    print('Created deploy/.env. Credentials not printed.')
