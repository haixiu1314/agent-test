"""配置只从本地环境读取；错误信息不包含配置值。"""
from pathlib import Path
from pydantic import SecretStr, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore', hide_input_in_errors=True)
    database_url: SecretStr
    jwt_secret_key: SecretStr
    encryption_key: SecretStr
    milvus_uri: str = 'http://127.0.0.1:19530'
    milvus_token: SecretStr = SecretStr('')
    cors_origins: list[str] = ['http://127.0.0.1:5173', 'http://localhost:5173']
    llm_api_key: SecretStr = SecretStr('')
    llm_base_url: str = ''
    llm_model: str = ''
    llm_timeout_seconds: float = Field(default=60, ge=1, le=120)
    embedding_model: str = ''

    @field_validator('jwt_secret_key')
    @classmethod
    def validate_jwt(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError('JWT_SECRET_KEY must contain at least 32 characters')
        return value

    @field_validator('encryption_key')
    @classmethod
    def validate_encryption(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode())
        except Exception:
            raise ValueError('ENCRYPTION_KEY must be a valid Fernet key') from None
        return value
