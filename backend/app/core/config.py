from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRETS = {
    "",
    "change-me-in-production",
    "change-me-to-a-long-random-string",
    "your-secret-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "House Renovation API"
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    db_user: str = "your_db_username"
    db_password: str = "your_db_password"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "renovation"
    database_url: str = ""

    upload_dir: str = "uploads"
    cors_origins: str = "http://localhost:3000"

    # Seed admin only when both are set (never hard-code a production password)
    admin_email: str = ""
    admin_password: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "gemini-2.5-flash-image"
    enable_gemini_hq: bool = False
    # Slow (upload + Gemini round-trip); off by default for fast uploads
    enable_gemini_quality_notes: bool = False

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    # Free Workers AI — lightning works on most free accounts; runwayml img2img is often 403-blocked
    cloudflare_image_model: str = "@cf/bytedance/stable-diffusion-xl-lightning"

    # Optional Hugging Face image-to-image (uses HF_TOKEN free monthly credits)
    enable_hf_img2img: bool = False
    hf_img2img_model: str = "black-forest-labs/FLUX.1-Kontext-dev"

    # Optional fal.ai ControlNet (cloud GPU — no local GPU required)
    fal_key: str = ""
    enable_fal_controlnet: bool = True
    fal_controlnet_model: str = "fal-ai/fast-sdxl-controlnet-canny"
    fal_controlnet_scale: float = 0.65
    fal_controlnet_steps: int = 20

    # Free redesign: Pollinations Nano Banana (no key) + Cloudflare SDXL Lightning
    enable_pollinations_nanobanana: bool = True
    pollinations_nanobanana_model: str = "nanobanana"
    pollinations_api_key: str = ""  # optional — anonymous works when edits allow it
    enable_cloudflare_redesign: bool = True

    # Optional Replicate (paid) — off by default; Pollinations/Cloudflare are primary
    replicate_api_token: str = ""
    enable_nano_banana: bool = False
    nano_banana_model: str = "google/nano-banana-2"
    nano_banana_resolution: str = "1K"  # 1K | 2K | 4K (HQ uses 2K)
    enable_replicate_img2img: bool = False
    replicate_img2img_model: str = "lucataco/sdxl"
    replicate_img2img_strength: float = 0.45
    replicate_img2img_steps: int = 28
    enable_replicate_controlnet: bool = False
    replicate_controlnet_model: str = "lucataco/sdxl-controlnet"
    replicate_controlnet_scale: float = 0.85
    replicate_controlnet_steps: int = 24
    replicate_depth_model: str = "chenxwh/depth-anything-v2"
    # Real-photo material preview when AI engines fail
    allow_local_redesign_fallback: bool = True

    # Hugging Face Inference — SegFormer CMP facade + Depth Anything V2
    hf_token: str = ""
    enable_segformer: bool = True
    segformer_model: str = "nvidia/segformer-b0-finetuned-ade-512-512"
    # Depth refine is slow; still used when facade size is unknown
    enable_depth_scale: bool = True
    depth_model: str = "depth-anything/Depth-Anything-V2-Small-hf"
    # Max long edge stored for uploads (smaller = faster detect/redesign)
    upload_max_edge: int = 1600
    # SegFormer / Grounded detect long edge (higher = better small windows)
    detect_max_edge: int = 1280
    # Call Grounded-SAM when openings below this count
    grounded_min_openings: int = 3
    grounded_box_threshold: float = 0.35
    grounded_text_threshold: float = 0.25
    replicate_seg_model: str = "schananas/grounded_sam"

    default_door_width_ft: float = 3.0
    default_door_height_ft: float = 7.0
    default_window_width_ft: float = 4.0
    default_window_height_ft: float = 4.0
    default_wastage_percent: float = 10.0

    @model_validator(mode="after")
    def _reject_weak_secret_in_production(self):
        if self.environment.lower() not in {"development", "dev", "test", "local"}:
            key = (self.secret_key or "").strip()
            if key in WEAK_SECRETS or len(key) < 32:
                raise ValueError(
                    "SECRET_KEY must be a strong random value (32+ chars) when ENVIRONMENT is not development"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.strip():
            url = self.database_url.strip()
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg2://", 1)
            elif url.startswith("postgresql://") and "+psycopg2" not in url:
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
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
