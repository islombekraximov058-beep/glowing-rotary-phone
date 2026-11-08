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
    pending = []
    for fact in facts:
        if fact.get("title") in used:
            continue
        try:
            validate_content(fact)
        except Exception as e:
            print(f"Fakt o'tkazib yuborildi ({fact.get('title')}): {e}")
            continue
        pending.append(fact)
    if not pending:
        return None, 0
    return pending[0], len(pending) - 1


# ---------- 1b. Gemini (navbat bo'sh bo'lsa zaxira) ----------
def generate_content(history):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY topilmadi!")

    recent = [h["title"] for h in history[-60:]]
    prompt = f"""You write scripts for faceless YouTube Shorts for a US audience.
Topic area: surprising, well-established facts about science, space, history,
the human body and technology.

Return ONLY a JSON object with these keys:
- "title": catchy title, max 70 characters, no clickbait lies
- "script": narration, 60-80 words, plain text only
- "keywords": list of 4 short English search terms for stock footage that
  visually match the topic (concrete things you can film, not abstract ideas)
- "description": 1-2 sentence YouTube description
- "hashtags": list of 3-5 hashtags, include #shorts

Script rules:
- The first sentence is a curiosity hook, max 12 words, no greetings.
- Short sentences. Conversational. No emojis, no markdown, no stage directions.
- The last sentence should connect back to the hook so the video loops.
- Use only facts you are highly confident are true and uncontroversial.
  Avoid disputed claims and phrases like "NASA confirms" or "scientists prove".

Do NOT repeat any of these recent titles or topics: {recent}
"""
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }

    last_error = None
    for round_no in range(3):
        for model in GEMINI_MODELS:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            )
            try:
                print(f"Gemini ({model}) so'rov... (urinish {round_no + 1})")
                r = requests.post(url, headers=headers, json=body, timeout=60)
                if r.status_code != 200:
                    raise Exception(f"{model}: {r.status_code} {r.text[:200]}")
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = text.strip().removeprefix("```json").removesuffix("```").strip()
                content = json.loads(text)
                validate_content(content)
                return content
            except Exception as e:
                last_error = e
                print("Xato:", e)
        time.sleep(15 * (round_no + 1))
    raise Exception(f"Ssenariy olinmadi: {last_error}")


# ---------- 2. Ovoz + so'z vaqtlari ----------
async def synthesize(text, mp3_path="output.mp3"):
    communicate = edge_tts.Communicate(
        text, VOICE, rate="+8%", boundary="WordBoundary"
    )
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                words.append({"text": chunk["text"], "start": start, "end": end})
    if not words:
        raise Exception("So'z vaqtlari olinmadi (edge-tts>=7.0 kerak).")
    return words


# ---------- 3. Fon videolar ----------
def fetch_backgrounds(keywords, needed_seconds):
    if not PEXELS_API_KEY:
        raise Exception("PEXELS_API_KEY topilmadi!")
    headers = {"Authorization": PEXELS_API_KEY}
    paths, total = [], 0.0
    keywords = list(keywords)
    random.shuffle(keywords)

    for kw in keywords:
        try:
            print(f"Pexels'dan '{kw}' qidirilmoqda...")
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": kw, "per_page": 8, "orientation": "portrait"},
                timeout=30,
            )
            if r.status_code != 200:
                print("Pexels xatoligi:", r.status_code, r.text[:200])
                continue
            videos = r.json().get("videos", [])
            random.shuffle(videos)
            for v in videos[:2]:
                files = [
                    f
                    for f in v.get("video_files", [])
                    if f.get("width")
                    and 720 <= f["width"] <= 1440
                    and f.get("file_type") == "video/mp4"
                ]
                if not files:
                    continue
                best = min(files, key=lambda x: abs(x["width"] - 1080))
                path = f"bg_{len(paths)}.mp4"
                data = requests.get(best["link"], timeout=90).content
                with open(path, "wb") as f:
                    f.write(data)
                paths.append(path)
                total += float(v.get("duration", 5))
                if total >= needed_seconds + 2:
                    return paths
        except Exception as e:
            print(f"Pexels so'rovi muvaffaqiyatsiz ('{kw}'): {e}")
            continue

    if not paths:
        raise Exception("Mos fon video topilmadi (Pexels kalitini tekshiring)!")
    return paths


def fit_vertical(clip):
    """Kadrni 1080x1920 ga to'ldirib, markazdan qirqadi."""
    scale = max(W / clip.w, H / clip.h)
    clip = clip.resized(scale)
    return clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)


def build_background(paths, duration):
    segments, t, i = [], 0.0, 0
    while t < duration:
        src = VideoFileClip(paths[i % len(paths)]).without_audio()
        seg = min(src.duration, random.uniform(3.0, 5.0), duration - t)
        if seg <= 0.05:
            break
        segments.append(fit_vertical(src.subclipped(0, seg)))
        t += seg
        i += 1
    return concatenate_videoclips(segments, method="compose")


# ---------- 4. Subtitr ----------
def build_subtitles(words, words_per_group=3):
    clips = []
    groups = [words[i : i + words_per_group] for i in range(0, len(words), words_per_group)]
    for idx, group in enumerate(groups):
        start = group[0]["start"]
        end = groups[idx + 1][0]["start"] if idx + 1 < len(groups) else group[-1]["end"]
        text = " ".join(w["text"] for w in group).upper()
        txt = TextClip(
            font=FONT_PATH,
            text=text,
            font_size=96,
            color="white",
            stroke_color="black",
            stroke_width=8,
            method="caption",
            size=(W - 160, 400),
            text_align="center",
        )
        clips.append(
            txt.with_position(("center", 1100))
            .with_start(start)
            .with_duration(max(end - start, 0.15))
        )
    return clips


# ---------- 5. Montaj ----------
def create_video(words, bg_paths, mp3_path="output.mp3", out_path="output.mp4"):
    print("Video render qilinmoqda...")
    audio = AudioFileClip(mp3_path)
    duration = audio.duration + 0.3

    bg = build_background(bg_paths, duration)
    subs = build_subtitles(words)
    final = CompositeVideoClip([bg] + subs, size=(W, H)).with_audio(audio)
    final = final.with_duration(duration)
    final.write_videofile(
        out_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=2,
        logger=None,
    )
    final.close()
    audio.close()
    print("Video tayyor!")


# ---------- 6. Telegram ----------
def telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text[:4000]},
            timeout=30,
        )
    except Exception as e:
        print("Telegram xabari yuborilmadi:", e)


def send_to_telegram(content, path="output.mp4"):
    if not os.path.exists(path):
        raise Exception(f"Xatolik: '{path}' fayli topilmadi!")
    caption = (
        f"{content['title']}\n\n{content['description']}\n\n"
        f"{' '.join(content['hashtags'])}"
    )[:1000]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    with open(path, "rb") as video_file:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"video": video_file},
            timeout=180,
        )
    res = r.json()
    if not res.get("ok"):
        raise Exception(f"Telegram xatosi: {res.get('description')}")
    print("Telegramga yuborildi!")


# ---------- 7. YouTube'ga yuklash (ixtiyoriy) ----------
def youtube_configured():
    return bool(YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN)


def youtube_access_token():
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise Exception(f"YouTube token xatosi: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def upload_to_youtube(content, path="output.mp4"):
    token = youtube_access_token()
    hashtags = list(content["hashtags"])
    if not any(h.lower() == "#shorts" for h in hashtags):
        hashtags.append("#Shorts")
    meta = {
        "snippet": {
            "title": content["title"][:95],
            "description": f"{content['description']}\n\n{' '.join(hashtags)}",
            "tags": [h.lstrip("#") for h in hashtags],
            "categoryId": "28",  # Science & Technology
        },
        "status": {
            "privacyStatus": YT_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    size = os.path.getsize(path)
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        data=json.dumps(meta),
        timeout=60,
    )
    if init.status_code != 200:
        raise Exception(f"YouTube boshlash xatosi: {init.status_code} {init.text[:300]}")
    upload_url = init.headers["Location"]

    with open(path, "rb") as f:
        up = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4"},
            data=f,
            timeout=900,
        )
    if up.status_code not in (200, 201):
        raise Exception(f"YouTube yuklash xatosi: {up.status_code} {up.text[:300]}")
    return up.json()["id"]


# ---------- Asosiy oqim ----------
async def main():
    history = load_history()

    print("1. Ssenariy tayyorlanmoqda...")
    content, remaining = next_queued_fact(history)
    origin = "queue"
    if content:
        print(f"Navbatdan olindi (navbatda yana {remaining} ta qoldi)")
    else:
        print("Navbat bo'sh, Gemini yozadi...")
        content = generate_content(history)
        origin = "gemini"
    print("Sarlavha:", content["title"])
    print("Ssenariy:", content["script"])

    print("2. Ovoz va so'z vaqtlari...")
    words = await synthesize(content["script"])

    print("3. Fon videolar...")
    duration = words[-1]["end"] + 0.3
    bg_paths = fetch_backgrounds(content["keywords"], duration)

    print("4. Montaj...")
    create_video(words, bg_paths)

    print("5. Telegram...")
    try:
        send_to_telegram(content)
    except Exception as e:
        print("Telegram xatosi:", e)
        if not youtube_configured():
            raise

    history.append(
        {"title": content["title"], "script": content["script"], "origin": origin}
    )
    save_history(history)

    if origin == "queue" and remaining <= 3:
        telegram_message(
            f"Eslatma: facts.json navbatida {remaining} ta ssenariy qoldi. "
            "Yangilarini qo'shing."
        )

    if youtube_configured():
        print("6. YouTube'ga yuklanmoqda...")
        try:
            video_id = upload_to_youtube(content)
            msg = f"YouTube'ga yuklandi ({YT_PRIVACY}): https://youtu.be/{video_id}"
            print(msg)
            telegram_message(msg)
        except Exception as e:
            print("YouTube xatosi:", e)
            telegram_message(f"YouTube'ga yuklashda xato: {e}")


if __name__ == "__main__":
    asyncio.run(main())
