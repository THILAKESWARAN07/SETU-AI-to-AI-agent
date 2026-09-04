import os
import sys
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

models_to_test = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
    "gemini-3.1-flash-lite",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]

for model_name in models_to_test:
    print(f"Testing {model_name}...", flush=True)
    try:
        m = genai.GenerativeModel(model_name)
        res = m.generate_content("Say OK", request_options={"timeout": 15})
        print(f"SUCCESS -> {model_name}: {res.text.strip()[:60]}", flush=True)
    except Exception as e:
        err = str(e)
        if "ResourceExhausted" in err:
            print(f"QUOTA EXHAUSTED -> {model_name}", flush=True)
        elif "NotFound" in err:
            print(f"NOT FOUND -> {model_name}", flush=True)
        elif "Deadline" in err or "timeout" in err.lower():
            print(f"TIMEOUT -> {model_name}", flush=True)
        else:
            print(f"ERROR -> {model_name}: {err[:120]}", flush=True)
