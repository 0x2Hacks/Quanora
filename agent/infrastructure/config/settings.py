"""配置模块"""
import os
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI

load_dotenv()


class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_USER_AGENT = os.getenv("OPENAI_USER_AGENT", "codex_cli_rs/0.0.0").strip()
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    MODEL_REASONING_EFFORT = os.getenv("MODEL_REASONING_EFFORT", "").strip()
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))

    @classmethod
    def validate(cls):
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")
        return True

    @classmethod
    def get_client(cls) -> OpenAI:
        return OpenAI(
            api_key=cls.OPENAI_API_KEY,
            base_url=cls.OPENAI_API_BASE,
            default_headers=cls._default_headers(),
        )

    @classmethod
    def get_async_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=cls.OPENAI_API_KEY,
            base_url=cls.OPENAI_API_BASE,
            default_headers=cls._default_headers(),
        )

    @classmethod
    def _default_headers(cls) -> dict[str, str] | None:
        if not cls.OPENAI_USER_AGENT:
            return None
        return {"User-Agent": cls.OPENAI_USER_AGENT}
