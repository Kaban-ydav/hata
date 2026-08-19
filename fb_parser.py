
import asyncio
import os
import json
import requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from groq import Groq
import random

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"
TELEGRAM_CHAT_ID = "5012390225" # Пока шлет тебе, потом поменяешь на ID VIP-канала
GROQ_API_KEY = "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"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(CURRENT_DIR, "fb_cookies.json")
FB_DB_FILE = os.path.join(CURRENT_DIR, "seen_fb_posts.txt")
GROUPS_FILE = os.path.join(CURRENT_DIR, "fb_groups_list.txt")

MAX_MONTHLY_PRICE = 4000 # Лимит для всей страны

SEEKER_KEYWORDS = ["looking for", "looking a", "looking single", "in need of", "searching for", "wanted", "need accommodation", "phd student"]
OFFER_KEYWORDS = ["available", "to rent", "to share", "room available", "flat available", "house available", "landlord", "ensuite"]
GARBAGE_KEYWORDS = ["samsung", "iphone", "gb", "cleaning", "nail", "spa", "car", "selling"]

groq_client = Groq(api_key=GROQ_API_KEY)

def quick_python_filter(text):
    text_lower = text.lower()
    if any(g in text_lower for g in GARBAGE_KEYWORDS): return False, "Мусор"
    if any(sk in text_lower for sk in SEEKER_KEYWORDS): return False, "Ищут жилье"
    if not any(ok in text_lower for ok in OFFER_KEYWORDS): return False, "Нет слов о сдаче"
    return True, "OK"

def is_post_fresh(post_text):
    if any(old_year in post_text for old_year in ["2021", "2022", "2023", "2024", "2025"]): return False
    return True

def analyze_post_with_groq(post_text):
    prompt = f"""
    You are an expert real estate analyzer for Ireland rental posts.
    Analyze the following Facebook post and extract info into a valid JSON object ONLY.
    
    Target Locations allowed: ANYWHERE IN IRELAND (Dublin, Cork, Galway, Limerick, Waterford, etc.).
    Max Budget per month: {MAX_MONTHLY_PRICE} EUR.

    JSON Schema to return:
    {{
        "is_offering": true/false, // TRUE ONLY if someone is RENTING OUT a room/flat.
        "is_scam_or_spam": true/false,
        "location": "extracted location name or 'Ireland'",
        "price_monthly": number_or_null, // Total MONTHLY price in EUR
        "summary": "Short 1-sentence summary of the offer"
    }}

    POST TEXT:
    \"\"\"{post_text}\"\"\"
    """
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"   [!] Ошибка Groq AI: {e}")
        return None

def load_groups():
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            return list(set([line.strip() for line in f if line.strip() and "facebook.com/groups/" in line]))
    return []

def load_seen_posts():
    if os.path.exists(FB_DB_FILE):
        with open(FB_DB_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_new_post(post_id):
    with open(FB_DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")
    try:
        with open(FB_DB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 1000:
            with open(FB_DB_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-1000:])
    except: pass

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

async def run_fb_parser():
    groups = load_groups()
    if not groups or not os.path.exists(COOKIES_FILE):
        print("🔴 Нет групп или fb_cookies.json!")
        return

    seen_posts = load_seen_posts()
    print("🚀 FB-парсер (ВСЯ ИРЛАНДИЯ) запущен!")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 720}, locale="en-US", timezone_id="Europe/Dublin"
            )

            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                await context.add_cookies(json.load(f))

            page = await context.new_page()
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            while True:
                groups = load_groups()
                print(f"\n🚀 СТАРТ ПРОВЕРКИ ({len(groups)} ГРУПП | ВСЯ ИРЛАНДИЯ)")

                for idx, group_url in enumerate(groups, 1):
                    print(f"[{idx}/{len(groups)}] Проверяем: {group_url}")
                    try:
                        await page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)
                        
                        for _ in range(2):
                            await page.evaluate("window.scrollBy(0, 800)")
                            await page.wait_for_timeout(1000)

                        html = await page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        posts = soup.find_all("div", attrs={"role": "article"})

                        for post in posts[:4]:
                            raw_text = post.get_text(separator=" ").strip()
                            if len(raw_text) < 30: continue

                            post_id = str(hash(raw_text[:120]))
                            if post_id in seen_posts: continue

                            is_promising, reason = quick_python_filter(raw_text)
                            if not is_promising:
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            if not is_post_fresh(raw_text):
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            print(f"   ⚡ Отправляем в AI...")
                            ai_res = analyze_post_with_groq(raw_text)
                            if not ai_res: continue

                            is_offering = ai_res.get("is_offering", False)
                            is_scam = ai_res.get("is_scam_or_spam", False)
                            price = ai_res.get("price_monthly")

                            if not is_offering or is_scam:
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            if price and price > MAX_MONTHLY_PRICE:
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            post_link = group_url
                            for a in post.find_all("a", href=True):
                                if "/posts/" in a["href"] or "/permalink/" in a["href"]:
                                    post_link = a["href"].split("?")[0]
                                    if not post_link.startswith("http"): post_link = "https://www.facebook.com" + post_link
                                    break

                            price_display = f"€{int(price)}/мес" if price else "Не указана"
                            loc_display = ai_res.get("location", "Ирландия")

                            print(f"   🔥 НАЙДЕНО! {loc_display} - {price_display}")

                            message = (
                                f"🤖 *НОВОЕ ЖИЛЬЕ (FACEBOOK)*\n\n"
                                f"📍 *Локация:* {loc_display}\n"
                                f"💰 *Цена:* {price_display}\n"
                                f"📝 *Суть:* {ai_res.get('summary', 'Сдается жилье')}\n\n"
                                f"🔗 [ОТКРЫТЬ В FACEBOOK]({post_link})"
                            )
                            send_telegram(message)
                            save_new_post(post_id)
                            seen_posts.add(post_id)

                    except Exception as e:
                        pass
                    await asyncio.sleep(random.randint(5, 12))

                sleep_time = random.randint(1800, 2700)
                print(f"[😴] Спим {sleep_time // 60} минут...")
                await asyncio.sleep(sleep_time)

    except Exception as e:
        print(f"[!] Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(run_fb_parser())
