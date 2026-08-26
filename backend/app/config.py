import os
from pathlib import Path
from dotenv import load_dotenv

# Load env file if it exists
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

class Settings:
    PROJECT_NAME: str = "SETU — AI Commerce Trust Layer"
    VERSION: str = "1.0.0"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./setu.db")
    
    # Razorpay (Test Mode keys)
    # Default to mock values if not provided, allowing execution out-of-the-box
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_mockkeyid123")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "mocksecret123")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "mockwebhooksecret123")
    IS_PAYMENT_TEST_MODE: bool = os.getenv("IS_PAYMENT_TEST_MODE", "True").lower() in ("true", "1", "yes")

    # LLM Settings
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock")  # Options: mock, gemini, openai
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    LLM_FALLBACK_TO_MOCK: bool = os.getenv("LLM_FALLBACK_TO_MOCK", "True").lower() in ("true", "1", "yes")

    # Security Token Signing Secret (for backend signed tokens if desired)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "setu-trust-layer-secret-key-12938")
    ALGORITHM: str = "HS256"

settings = Settings()
