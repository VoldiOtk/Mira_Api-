from __future__ import annotations
import os


class Settings:
    def __init__(self):
        self.s3_bucket_models: str = os.getenv("S3_BUCKET_MODELS", "mira-models")
        self.s3_bucket_datasets: str = os.getenv("S3_BUCKET_DATASETS", "mira-datasets")
        self.secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./backend/saas.db")
        self.api_keys_required: bool = os.getenv("API_KEYS_REQUIRED", "false").lower() == "true"
        self.admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
        self.jwt_algorithm: str = "HS256"
        self.jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


settings = Settings()
