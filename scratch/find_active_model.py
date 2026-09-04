import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

candidate_models = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
    "gemini-2.5-pro",
]

for model_name in candidate_models:
    print(f"Testing {model_name}...", flush=True)
    try:
        m = genai.GenerativeModel(model_name)
        res = m.generate_content("Say OK", request_options={"timeout": 10})
        print(f"AVAILABLE -> {model_name}: {res.text.strip()[:60]}", flush=True)
    except Exception as e:
        err_str = str(e)
        if "ResourceExhausted" in err_str:
            print(f"QUOTA EXHAUSTED -> {model_name}", flush=True)
        elif "NotFound" in err_str:
            print(f"NOT FOUND -> {model_name}", flush=True)
        else:
            print(f"ERROR -> {model_name}: {err_str[:120]}", flush=True)
