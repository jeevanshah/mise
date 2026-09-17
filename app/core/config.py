from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration, loaded from environment variables / .env.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://mise:mise_dev_pw@localhost:5432/mise_dev"
    environment: str = "development"

    # Default business-day boundary applied to a new Venue if none is given.
    # A venue open past midnight (e.g. dinner service ending 1am) still counts
    # its business_date as the day service started, up until this hour.
    default_business_day_boundary_hour: int = 4

    # --- Auth (Epic 1 step 4) ---
    # HS256 signing secret for access tokens. The default is fine for local
    # dev/tests only — it is intentionally obviously-insecure so a deploy that
    # forgets to override it fails loudly instead of silently shipping a
    # guessable secret (see Settings.model_post_init below).
    jwt_secret: str = "dev-insecure-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12  # a full shift, roughly
    magic_link_expire_minutes: int = 15

    def model_post_init(self, __context: object) -> None:
        if self.environment == "production" and self.jwt_secret == "dev-insecure-secret-change-in-production":
            raise RuntimeError(
                "JWT_SECRET must be set to a real secret when ENVIRONMENT=production "
                "— refusing to start with the default development value."
            )


settings = Settings()
