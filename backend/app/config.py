import os
from pathlib import Path
from dotenv import load_dotenv

# Load env file if it exists
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if not env_path.exists():
    env_path = Path.cwd() / ".env"

if env_path.exists():
    load_dotenv(env_path, override=False)
else:
    load_dotenv(override=False)

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
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "mock")
    RAZORPAY_MODE: str = os.getenv("RAZORPAY_MODE", "test")

    # LLM General Settings
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # Default global fallback provider
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_FALLBACK_TO_MOCK: bool = os.getenv("LLM_FALLBACK_TO_MOCK", "True").lower() in ("true", "1", "yes")
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # Role-Specific LLM Settings (100% Free / Free-Tier Providers)
    BUYER_LLM_PROVIDER: str = os.getenv("BUYER_LLM_PROVIDER", "gemini")
    BUYER_LLM_MODEL: str = os.getenv("BUYER_LLM_MODEL", "gemini-3.1-flash-lite")
    BUYER_LLM_FALLBACKS: str = os.getenv("BUYER_LLM_FALLBACKS", "openrouter,groq,mock")

    MERCHANT_LLM_PROVIDER: str = os.getenv("MERCHANT_LLM_PROVIDER", "groq")
    MERCHANT_LLM_MODEL: str = os.getenv("MERCHANT_LLM_MODEL", "llama-3.3-70b-versatile")
    MERCHANT_LLM_FALLBACKS: str = os.getenv("MERCHANT_LLM_FALLBACKS", "openrouter,gemini,mock")

    AUXILIARY_LLM_PROVIDER: str = os.getenv("AUXILIARY_LLM_PROVIDER", "groq")
    AUXILIARY_LLM_MODEL: str = os.getenv("AUXILIARY_LLM_MODEL", "llama-3.3-70b-versatile")
    AUXILIARY_LLM_FALLBACKS: str = os.getenv("AUXILIARY_LLM_FALLBACKS", "gemini,openrouter,mock")

    # API Keys & Models for Free Providers
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    # Security Token Signing Secret (for backend signed tokens if desired)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "setu-trust-layer-secret-key-12938")
    ALGORITHM: str = "HS256"

    def __init__(self):
        # Refresh instance attributes from loaded/modified environment variables
        self.DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./setu.db")
        
        if self.DATABASE_URL.startswith("sqlite:///."):
            project_root = Path(__file__).resolve().parent.parent.parent
            db_name = self.DATABASE_URL.split("/.")[-1].lstrip("/")
            absolute_db_path = project_root / db_name
            self.DATABASE_URL = f"sqlite:///{absolute_db_path.as_posix()}"

        self.RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_mockkeyid123")
        self.RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "mocksecret123")
        self.RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "mockwebhooksecret123")
        self.IS_PAYMENT_TEST_MODE = os.getenv("IS_PAYMENT_TEST_MODE", "True").lower() in ("true", "1", "yes")
        
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
        self.LLM_FALLBACK_TO_MOCK = os.getenv("LLM_FALLBACK_TO_MOCK", "True").lower() in ("true", "1", "yes")
        self.LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
        self.LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

        self.BUYER_LLM_PROVIDER = os.getenv("BUYER_LLM_PROVIDER", "gemini")
        self.BUYER_LLM_MODEL = os.getenv("BUYER_LLM_MODEL", "gemini-3.1-flash-lite")
        self.BUYER_LLM_FALLBACKS = os.getenv("BUYER_LLM_FALLBACKS", "openrouter,groq,mock")

        self.MERCHANT_LLM_PROVIDER = os.getenv("MERCHANT_LLM_PROVIDER", "groq")
        self.MERCHANT_LLM_MODEL = os.getenv("MERCHANT_LLM_MODEL", "llama-3.3-70b-versatile")
        self.MERCHANT_LLM_FALLBACKS = os.getenv("MERCHANT_LLM_FALLBACKS", "openrouter,gemini,mock")

        self.AUXILIARY_LLM_PROVIDER = os.getenv("AUXILIARY_LLM_PROVIDER", "groq")
        self.AUXILIARY_LLM_MODEL = os.getenv("AUXILIARY_LLM_MODEL", "llama-3.3-70b-versatile")
        self.AUXILIARY_LLM_FALLBACKS = os.getenv("AUXILIARY_LLM_FALLBACKS", "gemini,openrouter,mock")

        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
        self.GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
        self.OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        self.SECRET_KEY = os.getenv("SECRET_KEY", "setu-trust-layer-secret-key-12938")

        # Determine if valid Razorpay test credentials are present
        has_credentials = (
            self.RAZORPAY_KEY_ID and
            self.RAZORPAY_KEY_ID.startswith("rzp_test_") and
            self.RAZORPAY_KEY_ID != "rzp_test_mockkeyid123" and
            self.RAZORPAY_KEY_SECRET and
            self.RAZORPAY_KEY_SECRET != "mocksecret123"
        )
        
        # Requirement 5: PAYMENT_MODE must become "razorpay" when valid Razorpay test credentials are present.
        if has_credentials:
            self.PAYMENT_MODE = "razorpay"
        else:
            self.PAYMENT_MODE = os.getenv("PAYMENT_MODE", "mock")
            
        # Requirement 6: RAZORPAY_MODE must be "test".
        self.RAZORPAY_MODE = "test"

    @property
    def active_payment_mode(self) -> str:
        mode = self.PAYMENT_MODE.lower()
        if mode == "razorpay":
            has_credentials = (
                self.RAZORPAY_KEY_ID and
                self.RAZORPAY_KEY_ID.startswith("rzp_test_") and
                self.RAZORPAY_KEY_ID != "rzp_test_mockkeyid123" and
                self.RAZORPAY_KEY_SECRET and
                self.RAZORPAY_KEY_SECRET != "mocksecret123"
            )
            if has_credentials:
                return "razorpay"
        return "mock"

settings = Settings()

