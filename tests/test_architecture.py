"""洋葱架构依赖方向测试。"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def imported_roots(filepath: Path) -> set[str]:
    """返回 Python 文件直接导入的顶级模块名称。"""
    syntax_tree = ast.parse(filepath.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".", maxsplit=1)[0])
    return roots


def python_files(package_name: str) -> list[Path]:
    """返回指定项目包中的全部 Python 文件。"""
    return sorted((PROJECT_ROOT / package_name).glob("*.py"))


def assert_packages_not_imported(
    package_name: str,
    forbidden_roots: set[str],
) -> None:
    """断言包内文件没有导入禁止模块。"""
    for filepath in python_files(package_name):
        imported = imported_roots(filepath)
        assert imported.isdisjoint(forbidden_roots), (
            f"{filepath.relative_to(PROJECT_ROOT)} 导入了禁止模块："
            f"{sorted(imported & forbidden_roots)}"
        )


def test_domain_does_not_depend_on_outer_layers_or_frameworks() -> None:
    """领域层只能依赖标准库和领域内部模块。"""
    assert_packages_not_imported(
        "domain",
        {
            "adapters",
            "application",
            "bootstrap",
            "entrypoints",
            "fastapi",
            "main",
            "pydantic",
            "sqlalchemy",
            "starlette",
        },
    )


def test_application_does_not_depend_on_outer_layers_or_frameworks() -> None:
    """应用层只能依赖领域层和应用内部模块。"""
    assert_packages_not_imported(
        "application",
        {
            "adapters",
            "bootstrap",
            "entrypoints",
            "fastapi",
            "main",
            "pydantic",
            "sqlalchemy",
            "starlette",
        },
    )


def test_adapters_do_not_depend_on_entrypoints_or_startup_modules() -> None:
    """技术适配器不能反向依赖请求入口和启动模块。"""
    assert_packages_not_imported(
        "adapters",
        {"bootstrap", "entrypoints", "main"},
    )


def test_entrypoints_do_not_depend_on_adapters_or_startup_modules() -> None:
    """请求入口通过注入使用能力，而不导入具体适配器。"""
    assert_packages_not_imported(
        "entrypoints",
        {"adapters", "bootstrap", "domain", "main"},
    )


def test_main_only_imports_the_composition_root() -> None:
    """唯一启动入口只能从组合根取得应用。"""
    assert imported_roots(PROJECT_ROOT / "main.py") == {"bootstrap"}


def test_concrete_dependencies_are_only_created_in_bootstrap() -> None:
    """生产代码只能在组合根中实例化具体依赖。"""
    concrete_names = {
        "ConnectionManager",
        "InMemoryMessageRepository",
        "SendMessageService",
        "WebSocketMessageNotifier",
    }
    production_files = [
        PROJECT_ROOT / "main.py",
        *python_files("domain"),
        *python_files("application"),
        *python_files("adapters"),
        *python_files("entrypoints"),
    ]

    for filepath in production_files:
        syntax_tree = ast.parse(filepath.read_text(encoding="utf-8"))
        called_names = {
            node.func.id
            for node in ast.walk(syntax_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert called_names.isdisjoint(concrete_names), (
            f"{filepath.relative_to(PROJECT_ROOT)} 创建了具体依赖："
            f"{sorted(called_names & concrete_names)}"
        )

    bootstrap_tree = ast.parse(
        (PROJECT_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    )
    bootstrap_calls = {
        node.func.id
        for node in ast.walk(bootstrap_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert concrete_names <= bootstrap_calls
