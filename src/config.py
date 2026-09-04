"""
项目配置

统一管理项目根目录、数据目录和 SQLite 数据库文件路径。
"""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "chat.sqlite3"
JWT_ALGORITHM = "HS256"


class AuthSettings(BaseSettings):
    """从环境或本地 .env 文件读取认证安全配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    secretKey: SecretStr = Field(alias="AUTH_SECRET_KEY")
    accessTokenExpireMinutes: int = Field(
        default=15,
        alias="AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
        ge=1,
        le=1440,
    )

    @field_validator("secretKey")
    @classmethod
    def validateSecretKey(cls, secretKey: SecretStr) -> SecretStr:
        """HS256 密钥必须至少包含 32 字节随机数据。"""
        if len(secretKey.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("AUTH_SECRET_KEY 至少需要 32 字节")
        return secretKey
