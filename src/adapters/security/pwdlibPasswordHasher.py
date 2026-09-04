"""使用 pwdlib 推荐 Argon2id 配置实现密码哈希端口。"""

from anyio import to_thread
from pwdlib import PasswordHash as PwdlibHash
from pwdlib.exceptions import PwdlibError

from src.application.authPorts import PasswordHasher
from src.domain import PasswordHash

# 固定假哈希不是凭证，只用于让不存在用户也执行一次 Argon2 验证。
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$wagCPXjifgvUFBzq4hqe3w$"
    "CYaIb8sB+wtD+Vu/P4uod1+Qof8h+1g7bbDlBID48Rc"
)


class PwdlibPasswordHasher(PasswordHasher):
    """在线程中执行内存密集型 Argon2id 哈希，避免阻塞事件循环。"""

    def __init__(self) -> None:
        """使用 pwdlib 当前推荐的密码哈希配置。"""
        self._passwordHash = PwdlibHash.recommended()

    async def hashPassword(self, plainPassword: str) -> PasswordHash:
        """使用库生成的随机盐计算 Argon2id 哈希。"""
        hashedValue = await to_thread.run_sync(self._passwordHash.hash, plainPassword)
        return PasswordHash(hashedValue)

    async def verifyPassword(
        self,
        plainPassword: str,
        passwordHash: PasswordHash | None,
    ) -> bool:
        """验证真实或固定假哈希，不暴露用户名是否存在。"""
        storedValue = (
            passwordHash.value if passwordHash is not None else DUMMY_PASSWORD_HASH
        )
        try:
            return await to_thread.run_sync(
                self._passwordHash.verify,
                plainPassword,
                storedValue,
            )
        except PwdlibError:
            return False
