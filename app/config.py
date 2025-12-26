import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present.
load_dotenv()
from pydantic import BaseModel


class Settings(BaseModel):
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./resort.db")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
