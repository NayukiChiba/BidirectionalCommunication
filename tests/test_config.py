"""认证环境配置测试。"""

import pytest
from pydantic import ValidationError

from src.config import AuthSettings, RuntimeSettings


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


def test_runtime_settings_read_limits_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单实例安全限制应由统一环境配置读取。"""
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "4096")
    monkeypatch.setenv("WS_INPUT_RATE_LIMIT_COUNT", "5")
    monkeypatch.setenv("WS_INPUT_RATE_LIMIT_WINDOW_SECONDS", "2.5")
    monkeypatch.setenv("WS_MAX_CONNECTIONS", "20")
    monkeypatch.setenv("READINESS_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    settings = RuntimeSettings(_env_file=None)

    assert settings.maxWebSocketMessageBytes == 4096
    assert settings.inputRateLimitCount == 5
    assert settings.inputRateLimitWindowSeconds == 2.5
    assert settings.maxWebSocketConnections == 20
    assert settings.readinessTimeoutSeconds == 0.5
    assert settings.logLevel == "WARNING"


@pytest.mark.parametrize(
    ("fieldName", "value"),
    [
        ("maxWebSocketMessageBytes", 100),
        ("inputRateLimitCount", 0),
        ("inputRateLimitWindowSeconds", 0),
        ("maxWebSocketConnections", 0),
        ("readinessTimeoutSeconds", 0),
        ("logLevel", "TRACE"),
    ],
)
def test_runtime_settings_reject_invalid_security_limits(
    fieldName: str,
    value: object,
) -> None:
    """危险或不受支持的运行配置应在启动前快速失败。"""
    with pytest.raises(ValidationError):
        RuntimeSettings(**{fieldName: value}, _env_file=None)
