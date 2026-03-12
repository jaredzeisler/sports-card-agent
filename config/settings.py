"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # eBay
    ebay_app_id: str = Field(default="", alias="EBAY_APP_ID")
    ebay_cert_id: str = Field(default="", alias="EBAY_CERT_ID")
    ebay_dev_id: str = Field(default="", alias="EBAY_DEV_ID")
    ebay_redirect_uri: str = Field(default="", alias="EBAY_REDIRECT_URI")
    ebay_user_token: str = Field(default="", alias="EBAY_USER_TOKEN")
    ebay_sandbox: bool = Field(default=True, alias="EBAY_SANDBOX")

    # CardLadder
    cardladder_api_key: str = Field(default="", alias="CARDLADDER_API_KEY")

    # PSA
    psa_api_key: str = Field(default="", alias="PSA_API_KEY")

    # Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Agent limits
    auto_buy_limit: float = Field(default=50.0, alias="AGENT_AUTO_BUY_LIMIT")
    max_portfolio_value: float = Field(default=500000.0, alias="AGENT_MAX_PORTFOLIO_VALUE")
    max_single_card: float = Field(default=5000.0, alias="AGENT_MAX_SINGLE_CARD")
    min_profit_margin: float = Field(default=0.15, alias="AGENT_MIN_PROFIT_MARGIN")
    scan_interval_minutes: int = Field(default=30, alias="AGENT_SCAN_INTERVAL_MINUTES")

    # Notifications — Email
    notification_email: str = Field(default="", alias="NOTIFICATION_EMAIL")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")

    # Notifications — SMS (Twilio)
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field(default="", alias="TWILIO_FROM_NUMBER")
    sms_to_number: str = Field(default="", alias="SMS_TO_NUMBER")

    # Notifications — Push (ntfy.sh, free, no account needed)
    ntfy_topic: str = Field(default="", alias="NTFY_TOPIC")

    # Database
    database_url: str = Field(default="sqlite:///sports_cards.db", alias="DATABASE_URL")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def ebay_base_url(self) -> str:
        if self.ebay_sandbox:
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    @property
    def ebay_auth_url(self) -> str:
        if self.ebay_sandbox:
            return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        return "https://api.ebay.com/identity/v1/oauth2/token"


def get_settings() -> Settings:
    return Settings()
