import os
import json
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
    value = os.environ.get(name)
    return value.strip() if value else None


GEMINI_API_KEY = get_env("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
CHAT_ID = get_env("CHAT_ID")
PEXELS_API_KEY = get_env("PEXELS_API_KEY")

# Model nomini kerak bo'lsa GitHub Variables / env orqali almashtirasiz
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
VOICE = os.environ.get("VOICE", "en-US-AndrewNeural")
FONT_PATH = os.environ.get(
    "FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)
HISTORY_FILE = "history.json"
W, H = 1080, 1920


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


# ---------- 1. Ssenariy ----------
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
- "hashtags": list of 3-5 hashtags

Script rules:
- The first sentence is a curiosity hook, max 12 words, no greetings.
- Short sentences. Conversational. No emojis, no markdown, no stage directions.
- The last sentence should connect back to the hook so the video loops.
- Use only facts you are highly confident are true. If unsure, pick another fact.

Do NOT repeat any of these recent titles or topics: {recent}
"""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }

    last_error = None
    for attempt in range(3):
        try:
            print(f"Gemini'ga so'rov yuborilmoqda... (urinish {attempt + 1})")
            r = requests.post(url, headers=headers, json=body, timeout=60)
            if r.status_code != 200:
                raise Exception(f"Gemini xatoligi: {r.status_code} {r.text[:300]}")
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = text.strip().removeprefix("```json").removesuffix("```").strip()
            content = json.loads(text)
            for key in ("title", "script", "keywords", "description", "hashtags"):
                if key not in content:
                    raise Exception(f"JSON'da '{key}' yo'q")
            return content
        except Exception as e:
            last_error = e
            print("Xato:", e)
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
        print(f"Pexels'dan '{kw}' qidirilmoqda...")
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": kw, "per_page": 8, "orientation": "portrait"},
            timeout=30,
        )
        if r.status_code != 200:
            print("Pexels xatoligi:", r.status_code)
            continue
        videos = r.json().get("videos", [])
        random.shuffle(videos)
        for v in videos[:2]:
            files = [
                f
                for f in v["video_files"]
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

    if not paths:
        raise Exception("Mos fon video topilmadi!")
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


# ---------- 6. Telegram (ko'rib chiqish uchun) ----------
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


async def main():
    history = load_history()

    print("1. Ssenariy tayyorlanmoqda...")
    content = generate_content(history)
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
    send_to_telegram(content)

    history.append({"title": content["title"], "script": content["script"]})
    save_history(history)


if __name__ == "__main__":
    asyncio.run(main())
