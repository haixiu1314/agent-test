"""密码不可逆哈希；Agent 密钥可逆加密；JWT 有明确用途和有效期。"""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
import jwt
from cryptography.fernet import Fernet


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored)
        actual = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
        return hmac.compare_digest(actual, raw[16:])
    except (ValueError, TypeError):
        return False


def issue_token(user_id: str, secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': user_id, 'iat': now, 'exp': now + timedelta(hours=2),
                       'iss': 'agenttestlab', 'aud': 'agenttestlab-api'}, secret, algorithm='HS256')


def read_token(token: str, secret: str) -> str:
    return jwt.decode(token, secret, algorithms=['HS256'], issuer='agenttestlab',
                      audience='agenttestlab-api', options={'require': ['exp', 'iat', 'sub']})['sub']


class SecretVault:
    def __init__(self, key: str):
        self.cipher = Fernet(key.encode())

    def encrypt(self, value: dict) -> str:
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value: str) -> dict:
        return json.loads(self.cipher.decrypt(value.encode()))
