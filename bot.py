import os
import asyncio
import requests
import edge_tts
from moviepy import AudioFileClip, ColorClip

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def generate_script(prompt):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY topilmadi!")
        
    # Model nomini api_key bilan birga to'g'ridan-to'g'ri so'raymiz
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    print("Gemini'ga so'rov yuborilmoqda...")
    response = requests.post(url, headers=headers, json=data)
    print("Javob kodi:", response.status_code)
    print("Javob matni:", response.text)
    
    if response.status_code == 200:
        res_json = response.json()
        return res_json['candidates'][0]['content']['parts'][0]['text']
    else:
        raise Exception(f"Gemini xatoligi: {response.text}")

def create_video():
    print("Video yaratilmoqda...")
    audio_clip = AudioFileClip("output.mp3")
    duration = audio_clip.duration
    
    video_clip = ColorClip(size=(1080, 1920), color=(15, 15, 30), duration=duration)
    video_clip = video_clip.with_audio(audio_clip)
    video_clip.write_videofile("output.mp4", fps=24, codec="libx264", audio_codec="aac", logger=None)
    print("Video tayyor!")

def send_to_telegram():
    print("Telegram botga yuborilmoqda...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    
    if not os.path.exists("output.mp4"):
        raise Exception("Xatolik: 'output.mp4' fayli topilmadi!")
        
    with open("output.mp4", "rb") as video_file:
        files = {"video": video_file}
        data = {
            "chat_id": CHAT_ID, 
            "caption": "🤖 YouTube Shorts videongiz tayyor!"
        }
        response = requests.post(url, data=data, files=files, timeout=60)
        print("Telegram javobi:", response.text)
        if response.status_code != 200:
            raise Exception(f"Telegramga yuborishda xatolik: {response.text}")
        print("Muvaffaqiyatli yuborildi!")

async def main():
    print("1. Ssenariy tayyorlanmoqda...")
    prompt = "YouTube Shorts uchun 15 soniyali qiziqarli fakt yozib ber, o'zbek tilida."
    script = generate_script(prompt)
    print("\nYozilgan ssenariy:\n", script)
    
    print("\n2. Ovozga aylantirilmoqda...")
    communicate = edge_tts.Communicate(script, "uz-UZ-SardorNeural")
    await communicate.save("output.mp3")
    
    create_video()
    send_to_telegram()

if __name__ == "__main__":
    asyncio.run(main())
