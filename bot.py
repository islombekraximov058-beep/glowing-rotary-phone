import os
import asyncio
import requests
import edge_tts
from moviepy import AudioFileClip, VideoFileClip

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

def generate_script(prompt):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY topilmadi!")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    print("Gemini'ga so'rov yuborilmoqda...")
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 200:
        res_json = response.json()
        return res_json['candidates'][0]['content']['parts'][0]['text']
    else:
        raise Exception(f"Gemini xatoligi: {response.text}")

def download_background_video(query="technology"):
    print(f"Pexels'dan '{query' bo'yicha video qidirilmoqda...")
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=1&orientation=portrait"
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Pexels xatoligi: {response.text}")
        
    data = response.json()
    if not data.get("videos"):
        raise Exception("Mos keluvchi video topilmadi!")
        
    # Eng yaxshi sifatdagi vertikal video havolasini olish
    video_files = data["videos"][0]["video_files"]
    # HD vertikal videoni tanlashga harakat qilamiz
    hd_video = next((v for v in video_files if v.get("width") and v["width"] >= 720), video_files[0])
    video_url = hd_video["link"]
    
    print("Video yuklab olinmoqda...")
    vid_data = requests.get(video_url)
    with open("bg_video.mp4", "wb") as f:
        f.write(vid_data.content)
    print("Video fon yuklandi!")

def create_video():
    print("Video render qilinmoqda...")
    audio_clip = AudioFileClip("output.mp3")
    duration = audio_clip.duration
    
    # Pexels'dan olingan videoni yuklash
    video_clip = VideoFileClip("bg_video.mp4")
    
    # Agar video ovozdan qisqa bo'lsa, uni takrorlash yoki qisqartirish mumkin
    # Hozircha videoni audio davomiyligigacha qirqib olamiz (yoki loop qilamiz)
    if video_clip.duration > duration:
        video_clip = video_clip.subclipped(0, duration)
    
    # Videoning ovozini o'chirish (fon musiqasi/shovqini bo'lmasligi uchun) va o'zimizning TTS ovozni qo'shish
    video_clip = video_clip.with_audio(audio_clip)
    
    # Shorts formatiga moslab o'lchamini to'g'rilash (1080x1920)
    # MoviePy'da resizing/crop qilish mumkin, hozircha oddiy saqlaymiz:
    video_clip.write_videofile(
        "output.mp4", 
        fps=24, 
        codec="libx264", 
        audio_codec="aac", 
        logger=None
    )
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
            "caption": "🔥 Pexels foni asosida tayyorlangan video!"
        }
        response = requests.post(url, data=data, files=files, timeout=120)
        res_json = response.json()
        
        if not res_json.get("ok"):
            raise Exception(f"Telegram xatosi: {res_json.get('description')}")
        print("Muvaffaqiyatli yuborildi!")

async def main():
    print("1. Ssenariy tayyorlanmoqda...")
    prompt = "YouTube Shorts uchun 15 soniyali qiziqarli texnologiya факti yozib ber, o'zbek tilida. Faqat matnning o'zini yoz."
    script = generate_script(prompt)
    print("\nYozilgan ssenariy:\n", script)
    
    print("\n2. Ovozga aylantirilmoqda...")
    communicate = edge_tts.Communicate(script, "uz-UZ-SardorNeural")
    await communicate.save("output.mp3")
    
    print("\n3. Fon video qidirilmoqda...")
    download_background_video(query="technology futuristic") # Mavzuga qarab o'zgartirish mumkin
    
    create_video()
    send_to_telegram()

if __name__ == "__main__":
    asyncio.run(main())
