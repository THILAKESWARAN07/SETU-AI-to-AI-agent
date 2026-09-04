import os
import sys
sys.path.insert(0, os.path.abspath("."))
import google.generativeai as genai
from backend.app.config import settings

api_key = os.getenv("GEMINI_API_KEY", settings.GEMINI_API_KEY)
genai.configure(api_key=api_key)

print("Listing models supported for generateContent:")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"Model name: {m.name}, Display name: {m.display_name}")
