"""
项目配置

统一管理项目根目录、数据目录和 SQLite 数据库文件路径。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "chat.sqlite3"
