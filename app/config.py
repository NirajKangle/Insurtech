import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache
def get_settings():
    return Settings()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    app_url: str = os.getenv("APP_URL", "http://localhost:8000")
    fitbit_client_id: str = os.getenv("FITBIT_CLIENT_ID", "")
    fitbit_client_secret: str = os.getenv("FITBIT_CLIENT_SECRET", "")
    garmin_consumer_key: str = os.getenv("GARMIN_CONSUMER_KEY", "")
    garmin_consumer_secret: str = os.getenv("GARMIN_CONSUMER_SECRET", "")
    insurer_api_key: str = os.getenv("INSURER_API_KEY", "")

    @property
    def fitbit_configured(self) -> bool:
        return bool(self.fitbit_client_id and self.fitbit_client_secret)

    @property
    def garmin_configured(self) -> bool:
        return bool(self.garmin_consumer_key and self.garmin_consumer_secret)
