import os
from dotenv import load_dotenv
load_dotenv()

from google import genai
gemini_key = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=gemini_key)

print("Listing Gemini models or testing recommended 3.x models...")
for m in ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"]:
    try:
        resp = client.models.generate_content(
            model=m,
            contents="Say 'gemini-ok'"
        )
        print(f"Model '{m}': SUCCESS -> {resp.text.strip()}")
    except Exception as e:
        print(f"Model '{m}': FAILED -> {e}")
