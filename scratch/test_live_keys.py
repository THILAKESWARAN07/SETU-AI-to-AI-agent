import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("CHECKING ENVIRONMENT VARIABLES AND PROVIDER ACCESSIBILITY")
print("=" * 60)

keys = ['GROQ_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'CEREBRAS_API_KEY', 'NVIDIA_NIM_API_KEY']
for k in keys:
    val = os.getenv(k, '')
    status = f"PRESENT (length: {len(val)}, starts with {val[:4]}...)" if val else "NOT SET"
    print(f"{k:22}: {status}")

print("-" * 60)

# 1. Test Groq
groq_key = os.getenv("GROQ_API_KEY", "")
if groq_key:
    print("\n--- Testing Groq ---")
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "groq/compound-mini", "llama3-8b-8192"]:
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi, reply with one word: hello"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            print(f"Model '{model}': HTTP {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            print(f"Model '{model}' error: {e}")

# 2. Test Gemini
gemini_key = os.getenv("GEMINI_API_KEY", "")
if gemini_key:
    print("\n--- Testing Gemini SDK & Models ---")
    # Test google-genai
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        for g_model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite"]:
            try:
                response = client.models.generate_content(
                    model=g_model,
                    contents="Hi, reply with one word: hello"
                )
                print(f"google-genai '{g_model}': SUCCESS -> {response.text.strip()[:60]}")
            except Exception as e:
                print(f"google-genai '{g_model}' error: {e}")
    except Exception as e:
        print(f"google-genai import error: {e}")

    # Test google-generativeai
    try:
        import google.generativeai as legacy_genai
        legacy_genai.configure(api_key=gemini_key)
        for g_model in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
            try:
                model = legacy_genai.GenerativeModel(g_model)
                res = model.generate_content("Hi, reply with one word: hello")
                print(f"google-generativeai '{g_model}': SUCCESS -> {res.text.strip()[:60]}")
            except Exception as e:
                print(f"google-generativeai '{g_model}' error: {e}")
    except Exception as e:
        print(f"google-generativeai error: {e}")

# 3. Test OpenRouter
openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
if openrouter_key:
    print("\n--- Testing OpenRouter ---")
    for or_model in ["meta-llama/llama-3.3-70b-instruct:free", "google/gemini-2.0-flash-exp:free", "mistralai/mistral-7b-instruct:free", "dots-studio/dots-3-note-preview:free"]:
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://setu.ai",
                    "X-Title": "SETU AI Gateway"
                },
                json={
                    "model": or_model,
                    "messages": [{"role": "user", "content": "Hi, reply with one word: hello"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            print(f"OpenRouter '{or_model}': HTTP {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            print(f"OpenRouter '{or_model}' error: {e}")

# 4. Test Cerebras
cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
if cerebras_key:
    print("\n--- Testing Cerebras ---")
    for c_model in ["llama3.3-70b", "llama3.1-8b"]:
        try:
            resp = httpx.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {cerebras_key}", "Content-Type": "application/json"},
                json={
                    "model": c_model,
                    "messages": [{"role": "user", "content": "Hi, reply with one word: hello"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            print(f"Cerebras '{c_model}': HTTP {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            print(f"Cerebras '{c_model}' error: {e}")
