import os
import json
import time
import random
import asyncio
import requests
import edge_tts
from moviepy import (
    AudioFileClip,
    VideoFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
)


# ---------- Sozlamalar ----------
def get_env(name):
    """Secretdagi ortiqcha qator/bo'sh joylarni olib tashlaydi.
    Kalitlarda bo'sh joy bo'lmaydi, shuning uchun eng uzun bo'lakni olamiz."""
    value = os.environ.get(name)
    if not value:
        return None
    tokens = value.split()
    return max(tokens, key=len) if tokens else None


GEMINI_API_KEY = get_env("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
CHAT_ID = get_env("CHAT_ID")
PEXELS_API_KEY = get_env("PEXELS_API_KEY")
YT_CLIENT_ID = get_env("YT_CLIENT_ID")
YT_CLIENT_SECRET = get_env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = get_env("YT_REFRESH_TOKEN")

# Bo'sh qiymat kelsa ham (GitHub Variables o'rnatilmagan bo'lsa) standartga qaytadi
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
GEMINI_MODELS = [GEMINI_MODEL] + [
    m.strip()
    for m in (
        os.environ.get("GEMINI_FALLBACK_MODELS")
        or "gemini-2.5-flash,gemini-2.5-flash-lite"
    ).split(",")
    if m.strip()
]
VOICE = os.environ.get("VOICE") or "en-US-AndrewNeural"
FONT_PATH = (
    os.environ.get("FONT_PATH")
    or "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)
YT_PRIVACY = (os.environ.get("YT_PRIVACY") or "private").strip().lower()
if YT_PRIVACY not in ("private", "unlisted", "public"):
    YT_PRIVACY = "private"

HISTORY_FILE = "history.json"
FACTS_FILE = "facts.json"
W, H = 1080, 1920
REQUIRED_KEYS = ("title", "script", "keywords", "description", "hashtags")


# ---------- Tarix (takrorlanmaslik uchun) ----------
def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-300:], f, ensure_ascii=False, indent=2)


# ---------- Ssenariy tekshiruvi ----------
def validate_content(c):
    for key in REQUIRED_KEYS:
        if key not in c:
            raise Exception(f"'{key}' yo'q")
    if not isinstance(c["keywords"], list) or not c["keywords"]:
        raise Exception("'keywords' ro'yxat bo'lishi va bo'sh bo'lmasligi kerak")
    if not isinstance(c["hashtags"], list):
        raise Exception("'hashtags' ro'yxat bo'lishi kerak")
    if not str(c["script"]).strip().endswith((".", "!", "?")):
        raise Exception("Ssenariy to'liq emas (gap yarim qolgan)")


# ---------- 1a. Tayyor ssenariylar navbati (facts.json) ----------
def next_queued_fact(history):
    """facts.json dan hali ishlatilmagan birinchi ssenariyni qaytaradi."""
    try:
        with open(FACTS_FILE, "r", encoding="utf-8") as f:
            facts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print("facts.json o'qilmadi:", e)
        return None, 0

        used = {h.get("title") for h in history}
