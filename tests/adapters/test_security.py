"""Argon2id 密码哈希和 JWT 访问令牌适配器测试。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from src.adapters.security import JwtAccessTokenProvider, PwdlibPasswordHasher
from src.application import InvalidAccessToken
from src.config import JWT_ALGORITHM
from src.domain import UserId

TEST_SECRET_KEY = "test-secret-key-" + ("x" * 64)


@pytest.mark.asyncio
async def test_password_hasher_uses_salted_argon2id_and_verifies() -> None:
    """相同明文应产生不同 Argon2id 哈希且都能验证。"""
    passwordHasher = PwdlibPasswordHasher()

    firstHash = await passwordHasher.hashPassword("correct horse battery staple")
    secondHash = await passwordHasher.hashPassword("correct horse battery staple")

    assert firstHash.value.startswith("$argon2id$")
    assert firstHash.value != secondHash.value
    assert "correct horse battery staple" not in firstHash.value
    assert await passwordHasher.verifyPassword(
        "correct horse battery staple",
        firstHash,
    )
    assert not await passwordHasher.verifyPassword("wrong-password", firstHash)
    assert not await passwordHasher.verifyPassword("unknown-user-password", None)


def test_access_token_contains_only_required_claims_and_fixed_algorithm() -> None:
    """JWT 载荷只包含身份和时间声明，算法固定为 HS256。"""
    provider = JwtAccessTokenProvider(secretKey=TEST_SECRET_KEY, expireMinutes=15)
    userId = UserId(str(uuid4()))

    accessToken = provider.createAccessToken(userId)
    header = jwt.get_unverified_header(accessToken.value)
    payload = jwt.decode(
        accessToken.value,
        TEST_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
    )

    assert header["alg"] == JWT_ALGORITHM
    assert set(payload) == {"sub", "iat", "exp"}
    assert payload["sub"] == str(userId)
    assert provider.getUserId(accessToken.value) == userId


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_access_token_rejects_non_whitelisted_algorithm(algorithm: str) -> None:
    """即使签名密钥相同，也必须拒绝非白名单算法。"""
    provider = JwtAccessTokenProvider(secretKey=TEST_SECRET_KEY, expireMinutes=15)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        TEST_SECRET_KEY,
        algorithm=algorithm,
    )

    with pytest.raises(InvalidAccessToken):
        provider.getUserId(token)


def test_access_token_rejects_invalid_signature_and_expiration() -> None:
    """伪造签名和过期令牌都不能建立身份。"""
    provider = JwtAccessTokenProvider(secretKey=TEST_SECRET_KEY, expireMinutes=15)
    now = datetime.now(timezone.utc)
    forgedToken = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        "different-secret-key-with-32-bytes",
        algorithm=JWT_ALGORITHM,
    )
    expiredToken = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=5),
        },
        TEST_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidAccessToken):
        provider.getUserId(forgedToken)
    with pytest.raises(InvalidAccessToken):
        provider.getUserId(expiredToken)


def test_access_token_requires_valid_uuid_subject() -> None:
    """缺少 sub 或 sub 不是服务端用户 UUID 时必须拒绝。"""
    provider = JwtAccessTokenProvider(secretKey=TEST_SECRET_KEY, expireMinutes=15)
    now = datetime.now(timezone.utc)

    for payload in (
        {"iat": now, "exp": now + timedelta(minutes=15)},
        {"sub": "alice", "iat": now, "exp": now + timedelta(minutes=15)},
    ):
        token = jwt.encode(
            payload,
            TEST_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(InvalidAccessToken):
            provider.getUserId(token)
