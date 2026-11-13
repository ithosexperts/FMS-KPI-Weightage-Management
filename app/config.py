from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FMS KPI Weightage Management"
    environment: str = "development"
    port: int = 8000
    public_base_url: str = "http://127.0.0.1:8000"

    # Gateway API configuration
    api_base_url: str = "https://api.hosexperts.com:85/apiv3.php"
    api_test_url: str = "https://api.hosexperts.com:85/apiv2.php"
    api_database: str = "OperationsDB"
    api_auth_token: str = "Khushbu*#*#123"
    api_timeout: float = 60.0

    # Optional direct database connection (if available)
    db_server: str = ""
    db_user: str = ""
    db_password: str = ""
    db_name: str = "OperationsDB"

    # Role-based access control (WR16)
    # 1: Super Admin, 2: Management / HR Approver
    allowed_approver_role_ids: List[int] = [1, 2]

    # Application session user defaults
    default_user_code: str = "0210"
    default_user_name: str = "Himanshu Sehgal"
    default_role_id: int = 1

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod", "live"}

    def get_api_url_for_db(self, db_name: str | None = None) -> str:
        target = (db_name or self.api_database or "").strip().lower()
        if target in ("test_operationsdb", "test", "api_1"):
            return self.api_test_url
        return self.api_base_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
