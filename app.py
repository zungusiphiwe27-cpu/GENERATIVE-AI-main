"""
AI Content Generator - Flask App
Text & Code: Groq (llama-3.1-8b-instant)
Images: Pollinations.ai (free, no key needed)
Optimised for Render.com free tier
"""

import os
import json
import time
import urllib.parse
import requests
from flask import Flask, render_template, request, jsonify, Response
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ─── Groq Client ──────────────────────────────────────────────────────────────
# API key loaded from .env locally or Render Environment tab in production
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

if not GROQ_API_KEY:
    print("⚠️  WARNING: GROQ_API_KEY not set. Add it to .env or Render Environment tab.")
    client = None
else:
    client = Groq(api_key=GROQ_API_KEY)

MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
# ──────────────────────────────────────────────────────────────────────────────

PROMPTS_FILE = "prompts/library.json"


def load_prompt_library():
    if os.path.exists(PROMPTS_FILE):
        with open(PROMPTS_FILE) as f:
            return json.load(f)
    return []


def save_prompt_library(prompts):
    os.makedirs("prompts", exist_ok=True)
    with open(PROMPTS_FILE, "w") as f:
        json.dump(prompts, f, indent=2)


def generate_text(system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 800) -> str:
    if not client:
        raise Exception("GROQ_API_KEY is not set. Add it to Render's Environment tab.")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Health check (required by Render) ──
@app.route("/health")
def health():
    return jsonify({
        "status":    "ok",
        "model":     MODEL,
        "api_ready": bool(GROQ_API_KEY),
    }), 200


# ── Text ──
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    system_prompt = data.get("system_prompt", "You are a helpful assistant.")
    user_prompt   = data.get("user_prompt", "")
    temperature   = float(data.get("temperature", 0.7))
    max_tokens    = int(data.get("max_tokens", 800))

    if not user_prompt.strip():
        return jsonify({"error": "user_prompt is required"}), 400

    try:
        result = generate_text(system_prompt, user_prompt, temperature, max_tokens)
        return jsonify({"content": result})
    except Exception as e:
        err = str(e)
        if "api_key" in err.lower() or "authentication" in err.lower():
            return jsonify({"error": "Invalid Groq API key. Check GROQ_API_KEY in Render Environment tab."}), 401
        if "rate_limit" in err.lower() or "429" in err:
            return jsonify({"error": "Rate limit reached. Please wait a moment and try again."}), 429
        return jsonify({"error": err}), 500


# ── Code ──
@app.route("/api/generate/code", methods=["POST"])
def api_generate_code():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    language    = data.get("language", "Python")
    user_prompt = data.get("user_prompt", "")
    temperature = float(data.get("temperature", 0.3))
    max_tokens  = int(data.get("max_tokens", 1500))

    if not user_prompt.strip():
        return jsonify({"error": "user_prompt is required"}), 400

    system_prompt = (
        f"You are an expert {language} developer. "
        f"Return ONLY raw {language} code with no markdown fences, no preamble, no explanation. "
        "Add clear inline comments. Write clean, idiomatic, production-ready code."
    )

    try:
        result = generate_text(system_prompt, user_prompt, temperature, max_tokens)
        result = result.strip()
        if result.startswith("```"):
            lines  = result.split("\n")
            result = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return jsonify({"content": result, "language": language})
    except Exception as e:
        err = str(e)
        if "api_key" in err.lower() or "authentication" in err.lower():
            return jsonify({"error": "Invalid Groq API key. Check GROQ_API_KEY in Render Environment tab."}), 401
        if "rate_limit" in err.lower() or "429" in err:
            return jsonify({"error": "Rate limit reached. Please wait a moment and try again."}), 429
        return jsonify({"error": err}), 500


# ── Image (Pollinations.ai proxied server-side) ──
@app.route("/api/generate/image", methods=["POST"])
def api_generate_image():
    data   = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    prompt = data.get("prompt", "").strip()
    width  = int(data.get("width",  1024))
    height = int(data.get("height", 1024))
    model  = data.get("model", "flux")

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    encoded_prompt = urllib.parse.quote(prompt)
    seed           = int(time.time())

    image_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&model={model}&seed={seed}&nologo=true"
    )

    try:
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()

        content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        return Response(
            img_resp.content,
            status=200,
            mimetype=content_type,
            headers={
                "Content-Length": str(len(img_resp.content)),
                "Cache-Control":  "no-store",
            }
        )

    except requests.exceptions.Timeout:
        return jsonify({"error": "Image generation timed out — try a simpler prompt"}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"Image service error: {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Prompt Library ──
@app.route("/api/prompts", methods=["GET"])
def get_prompts():
    return jsonify(load_prompt_library())


@app.route("/api/prompts", methods=["POST"])
def save_prompt():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    prompts = load_prompt_library()
    new_prompt = {
        "id":            int(time.time() * 1000),
        "name":          data.get("name", "Untitled"),
        "system_prompt": data.get("system_prompt", ""),
        "user_prompt":   data.get("user_prompt", ""),
        "category":      data.get("category", "General"),
        "type":          data.get("type", "text"),
    }
    prompts.append(new_prompt)
    save_prompt_library(prompts)
    return jsonify(new_prompt), 201


@app.route("/api/prompts/<int:prompt_id>", methods=["DELETE"])
def delete_prompt(prompt_id):
    prompts = [p for p in load_prompt_library() if p["id"] != prompt_id]
    save_prompt_library(prompts)
    return jsonify({"deleted": prompt_id})


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 10000))
    debug = os.environ.get("FLASK_ENV") == "development"

    print("=" * 50)
    print("  🤖  AI Content Generator")
    print("=" * 50)
    print(f"  URL      → http://localhost:{port}")
    print(f"  Model    → {MODEL}")
    print(f"  API Key  → {'✅ Set' if GROQ_API_KEY else '❌ NOT SET'}")
    print("=" * 50)

    app.run(host="0.0.0.0", port=port, debug=debug)
