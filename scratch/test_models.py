import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

models_to_test = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest"
]

for model_name in models_to_test:
    try:
        m = genai.GenerativeModel(model_name)
        res = m.generate_content('Say hello')
        print(f"Model {model_name} SUCCESS: {res.text.strip()[:60]}")
    except Exception as e:
        print(f"Model {model_name} ERROR: {e}")
