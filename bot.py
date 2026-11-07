def generate_script(prompt):
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY topilmadi!")
        
    # Hozirgi ishlaydigan model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
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
