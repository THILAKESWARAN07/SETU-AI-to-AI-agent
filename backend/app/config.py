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

    # LLM Settings
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock")  # Options: mock, gemini, openai
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    LLM_FALLBACK_TO_MOCK: bool = os.getenv("LLM_FALLBACK_TO_MOCK", "True").lower() in ("true", "1", "yes")
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "10.0"))

    # Security Token Signing Secret (for backend signed tokens if desired)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "setu-trust-layer-secret-key-12938")
    ALGORITHM: str = "HS256"

    def __init__(self):
        # Refresh instance attributes from loaded/modified environment variables
        self.DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./setu.db")
        
        # If it's a relative SQLite database URL, resolve it to an absolute path
        # to ensure the same database is read/written regardless of current working directory
        if self.DATABASE_URL.startswith("sqlite:///."):
            project_root = Path(__file__).resolve().parent.parent.parent
            db_name = self.DATABASE_URL.split("/.")[-1].lstrip("/")
            absolute_db_path = project_root / db_name
            self.DATABASE_URL = f"sqlite:///{absolute_db_path.as_posix()}"

        self.RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_mockkeyid123")
        self.RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "mocksecret123")
        self.RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "mockwebhooksecret123")
        self.IS_PAYMENT_TEST_MODE = os.getenv("IS_PAYMENT_TEST_MODE", "True").lower() in ("true", "1", "yes")
        
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "")
        self.LLM_FALLBACK_TO_MOCK = os.getenv("LLM_FALLBACK_TO_MOCK", "True").lower() in ("true", "1", "yes")
        self.LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "10.0"))
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

