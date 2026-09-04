"""跨聚合引用使用的用户标识值对象。"""

from dataclasses import dataclass

from src.domain.exceptions import InvalidUserId


@dataclass(frozen=True, slots=True)
class UserId:
    """经过规范化的用户标识值对象。"""

    value: str

    def __post_init__(self) -> None:
        """验证并规范化用户标识。"""
        if not isinstance(self.value, str):
            raise InvalidUserId("用户标识必须是字符串")

        normalizedValue = self.value.strip()
        if not normalizedValue:
            raise InvalidUserId("用户标识不能为空")

        object.__setattr__(self, "value", normalizedValue)

    def __str__(self) -> str:
        """返回可用于外层转换的文本值。"""
        return self.value
