from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """项目配置。"""

    app_name: str = "Diet Delushan API"
    secret_key: str = "replace_with_a_random_secret_key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "diet_delushan"
    database_url_override: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "DATABASE_URL_OVERRIDE", "database_url_override"),
    )

    dashscope_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.6-plus"
    llm_temperature: float = 0.4
    llm_max_tokens: int = 1200
    llm_timeout_seconds: int = 60

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )
    create_tables_on_startup: bool = False

    upload_root_dir: str = str(BASE_DIR / "app")
    bodyreport_subdir: str = "bodyreport"
    picfile_subdir: str = "picfile"

    log_dir: str = str(BASE_DIR / "logs")
    log_file_name: str = "app.log"
    backup_root_dir: str = "/var/backups/diet-delushan"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """生成 MySQL 数据库连接地址。"""
        if self.database_url_override.strip():
            return self.database_url_override.strip()
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的跨域地址转换为列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        return BASE_DIR / path

    @property
    def upload_root_path(self) -> Path:
        return self._resolve_path(self.upload_root_dir)

    @property
    def bodyreport_dir(self) -> Path:
        return self.upload_root_path / self.bodyreport_subdir

    @property
    def picfile_dir(self) -> Path:
        return self.upload_root_path / self.picfile_subdir

    @property
    def log_path(self) -> Path:
        return self._resolve_path(self.log_dir) / self.log_file_name

    @property
    def backup_root_path(self) -> Path:
        return self._resolve_path(self.backup_root_dir)


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免重复读取环境变量。"""
    return Settings()


settings = get_settings()

