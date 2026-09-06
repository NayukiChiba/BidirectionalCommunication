"""Docker 构建与单实例部署配置静态验收测试。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_image_is_non_root_and_uses_frozen_production_dependencies() -> None:
    """镜像应从锁文件恢复依赖，并以非 root 单进程启动。"""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "uv sync --frozen --no-dev" in dockerfile
    assert "COPY pyproject.toml uv.lock" in dockerfile
    assert "USER appuser:appgroup" in dockerfile
    assert 'CMD ["uvicorn", "main:app"' in dockerfile
    assert "--reload" not in dockerfile
    assert "--workers" not in dockerfile
    assert "AUTH_SECRET_KEY=" not in dockerfile


def test_dockerignore_excludes_local_environment_secrets_and_databases() -> None:
    """构建上下文不能包含本地虚拟环境、密钥或 SQLite 数据。"""
    ignored = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {".venv/", ".env", "data/", "*.sqlite3", ".git/"} <= ignored
    assert "uv.lock" not in ignored


def test_compose_separates_migration_from_application_and_mounts_data_volume() -> None:
    """迁移应是独立服务，应用与迁移必须共享唯一 SQLite 卷。"""
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "  migrate:" in compose
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert "condition: service_completed_successfully" in compose
    assert compose.count("- chat-data:/app/data") == 2
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
