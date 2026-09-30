from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "House Renovation API"
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    # Edit these in .env — DATABASE_URL is built automatically
    db_user: str = "your_db_username"
    db_password: str = "your_db_password"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "renovation"
    # Optional override. Leave empty to use DB_* fields above.
    database_url: str = ""

    upload_dir: str = "uploads"
    cors_origins: str = "http://localhost:3000"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "gemini-2.5-flash-image"
    enable_gemini_hq: bool = False

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_image_model: str = "@cf/bytedance/stable-diffusion-xl-lightning"

    default_door_width_ft: float = 3.0
    default_door_height_ft: float = 7.0
    default_window_width_ft: float = 4.0
    default_window_height_ft: float = 4.0
    default_wastage_percent: float = 10.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (
            f"postgresql+psycopg2://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
