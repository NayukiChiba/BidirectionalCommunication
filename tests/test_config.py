"""认证环境配置测试。"""

import pytest
from pydantic import ValidationError

from src.config import AuthSettings


def test_auth_settings_requires_environment_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有环境密钥时认证配置必须拒绝启动。"""
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        AuthSettings(_env_file=None)


def test_auth_settings_rejects_short_secret() -> None:
    """HS256 密钥少于 32 字节时必须拒绝。"""
    with pytest.raises(ValidationError, match="至少需要 32 字节"):
        AuthSettings(secretKey="short-secret", _env_file=None)


def test_auth_settings_hides_secret_and_validates_expiration() -> None:
    """配置展示不能暴露密钥，并限制令牌有效期。"""
    secretKey = "configuration-secret-" + ("x" * 32)
    settings = AuthSettings(
        secretKey=secretKey,
        accessTokenExpireMinutes=30,
        _env_file=None,
    )

    assert str(settings.secretKey) == "**********"
    assert secretKey not in repr(settings)
    assert settings.accessTokenExpireMinutes == 30

    with pytest.raises(ValidationError):
        AuthSettings(
            secretKey=secretKey,
            accessTokenExpireMinutes=0,
            _env_file=None,
        )
