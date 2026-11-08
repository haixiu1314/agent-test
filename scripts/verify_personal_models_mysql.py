"""只读核对浏览器验收账号的模型密文；不输出密钥或业务内容。"""
import json
from pathlib import Path
from sqlalchemy import select, text
from app.core.config import Settings
from app.core.security import SecretVault
from app.db.session import make_engine, make_sessions
from app.models.entities import ModelConfig, User

settings = Settings()
engine = make_engine(settings.database_url.get_secret_value())
vault = SecretVault(settings.encryption_key.get_secret_value())
with make_sessions(engine)() as db:
    rows = db.scalars(select(ModelConfig).join(User, ModelConfig.created_by == User.id).where(User.username.startswith('personal_ui_', autoescape=True))).all()
    assert rows, 'Run personal-models.spec.ts against this database first'
    assert all('browser-protocol-key' not in row.secret for row in rows)
    assert all(vault.decrypt(row.secret).get('api_key') == 'browser-protocol-key' for row in rows)
    assert all(row.created_by for row in rows)
    result = {'status': 'passed', 'database': db.scalar(text('SELECT DATABASE()')), 'browser_model_rows_checked': len(rows), 'at_rest_encryption': 'verified', 'ownership_persisted': True, 'provider': 'local HTTP protocol fixture, NOT real AI'}
engine.dispose()
output = Path(__file__).resolve().parents[1] / 'docs/evidence/personal-models-mysql.json'
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
