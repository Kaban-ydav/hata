import asyncio
import os
import re
import json
import requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from groq import Groq
import random
# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"
TELEGRAM_CHAT_ID = "5012390225"

GROQ_API_KEY = "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"

ALERT_BOT_TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw" 
ADMIN_CHAT_ID = 5012390225

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(CURRENT_DIR, "fb_cookies.json")
FB_DB_FILE = os.path.join(CURRENT_DIR, "seen_fb_posts.txt")
GROUPS_FILE = os.path.join(CURRENT_DIR, "fb_groups_list.txt")

MAX_MONTHLY_PRICE = 550

ALLOWED_LOCATIONS = [
    "waterford", "wexford", "new ross", "tramore", 
    "dungarvan", "kilmacthomas", "duncannon", "saltmills",
    "poleberry", "ferrybank", "lacken wood", "ballybeg"
]

STOP_CITIES = ["dublin", "cork", "galway", "limerick", "belfast", "dundalk", "drogheda", "swords", "tallaght"]
SEEKER_KEYWORDS = ["looking for", "looking a", "looking single", "in need of", "searching for", "wanted", "need accommodation", "phd student"]
OFFER_KEYWORDS = ["available", "to rent", "to share", "room available", "flat available", "house available", "landlord", "ensuite"]
GARBAGE_KEYWORDS = ["samsung", "iphone", "gb", "cleaning", "nail", "spa", "car", "selling"]

groq_client = Groq(api_key=GROQ_API_KEY)

def quick_python_filter(text):
    """Быстрый бесплатный фильтр Python. Экономит лимиты Groq!"""
    text_lower = text.lower()
    
    # 1. Отсекаем мусор и барахолку
    if any(g in text_lower for g in GARBAGE_KEYWORDS): return False, "Мусор/Барахолка"
    # 2. Отсекаем стоп-города
    if any(sc in text_lower for sc in STOP_CITIES): return False, "Другой город"
    # 3. Отсекаем тех кто ищет жилье
    if any(sk in text_lower for sk in SEEKER_KEYWORDS): return False, "Ищет жилье"
    # 4. Проверяем наличие ключевиков сдачи
    if not any(ok in text_lower for ok in OFFER_KEYWORDS): return False, "Нет слов о сдаче"
    
    return True, "OK"

def is_post_fresh(post_text):
    """Проверяет свежесть поста по маркерам времени FB (например: 1h, 5h, 1d, 2d, Just now)"""
    # Если в тексте шапки поста есть индикаторы старых лет — пропускаем
    if any(old_year in post_text for old_year in ["2021", "2022", "2023", "2024", "2025"]):
        return False
    # Обычно свежие посты содержат маркировки типа "hrs", "mins", "1d", "2d", "Yesterday"
    return True

def analyze_post_with_groq(post_text):
    prompt = f"""
    You are an expert real estate analyzer for Ireland rental posts.
    Analyze the following Facebook post and extract info into a valid JSON object ONLY.
    
    Target Locations allowed: {', '.join(ALLOWED_LOCATIONS)}.
    Max Budget per month: {MAX_MONTHLY_PRICE} EUR.

    JSON Schema to return:
    {{
        "is_offering": true/false, // TRUE ONLY if someone is RENTING OUT a room/flat. FALSE if looking for or advice.
        "is_scam_or_spam": true/false,
        "location": "extracted location name or unknown",
        "price_monthly": number_or_null, // Total MONTHLY price in EUR (weekly * 4.33).
        "is_matching_location": true/false, // TRUE if location is in/near Waterford, Wexford, New Ross, Tramore etc.
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
        print(f"  [!] Ошибка Groq AI: {e}")
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
    # 1. Записываем новый пост в базу
    with open(FB_DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")
        
    # 2. АВТО-ОЧИСТКА (Самоочищающаяся память)
    # Оставляем только последние 1000 записей, остальное стираем
    try:
        with open(FB_DB_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if len(lines) > 1000:
            with open(FB_DB_FILE, "w", encoding="utf-8") as f:
                # Перезаписываем файл, оставляя только свежак
                f.writelines(lines[-1000:])
    except Exception as e:
        print(f"[!] Ошибка при очистке FB-базы: {e}")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Ошибка Telegram: {e}")

async def run_fb_parser():
    groups = load_groups()
    if not groups or not os.path.exists(COOKIES_FILE):
        print("🔴 Нет групп или файла fb_cookies.json!")
        return

    seen_posts = load_seen_posts()
    print("🚀 Экономный FB-парсер с AI подгружен!")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US", timezone_id="Europe/Dublin"
            )

            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                await context.add_cookies(json.load(f))

            page = await context.new_page()
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            while True:
                groups = load_groups()
                print(f"\n==========================================")
                print(f"🚀 СТАРТ ПРОВЕРКИ ({len(groups)} ГРУПП | УМНАЯ СБЕРЕГАТЕЛЬНАЯ ФИЛЬТРАЦИЯ)")
                print(f"==========================================\n")

                for idx, group_url in enumerate(groups, 1):
                    print(f"[{idx}/{len(groups)}] Проверяем: {group_url}")
                    try:
                        await page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)
                        
                        # Берем только САМЫЕ СВЕЖИЕ 3-5 постов с верха ленты (они отсортированы FB по хронологии)
                        for _ in range(2):
                            await page.evaluate("window.scrollBy(0, 800)")
                            await page.wait_for_timeout(1000)

                        html = await page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        posts = soup.find_all("div", attrs={"role": "article"})

                        for post in posts[:4]: # Только 4 верхних поста!
                            raw_text = post.get_text(separator=" ").strip()
                            if len(raw_text) < 30: continue

                            post_id = str(hash(raw_text[:120]))
                            if post_id in seen_posts: continue

                            # ⚡ ШАГ 1: БЕСПЛАТНАЯ ПРОВЕРКА PYTHON (Экономит Groq)
                            is_promising, reason = quick_python_filter(raw_text)
                            if not is_promising:
                                print(f"  [-] Python отсеял ({reason}) -> Пропускаем Groq")
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            # ⚡ ШАГ 2: ПРОВЕРКА СВЕЖЕСТИ (Старье пропускаем)
                            if not is_post_fresh(raw_text):
                                print(f"  [-] Старый пост (прошлые года) -> Пропускаем")
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            # 🧠 ШАГ 3: ТОЛЬКО ДЛЯ КАНДИДАТОВ — ВЫЗЫВАЕМ AI GROQ!
                            print(f"  ⚡ Пост прошёл фильтры! Отправляем в Groq AI...")
                            ai_res = analyze_post_with_groq(raw_text)
                            
                            if not ai_res: continue

                            is_offering = ai_res.get("is_offering", False)
                            is_scam = ai_res.get("is_scam_or_spam", False)
                            price = ai_res.get("price_monthly")
                            is_loc_ok = ai_res.get("is_matching_location", False)

                            if not is_offering or is_scam or not is_loc_ok:
                                print(f"  [-] AI забраковал: {'Не сдача' if not is_offering else 'Локация/Скам'}")
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            if price and price > MAX_MONTHLY_PRICE:
                                print(f"  [-] Дорого по оценке AI: €{price}/мес")
                                save_new_post(post_id)
                                seen_posts.add(post_id)
                                continue

                            # Ищем ссылку
                            post_link = group_url
                            for a in post.find_all("a", href=True):
                                if "/posts/" in a["href"] or "/permalink/" in a["href"]:
                                    post_link = a["href"].split("?")[0]
                                    if not post_link.startswith("http"):
                                        post_link = "https://www.facebook.com" + post_link
                                    break

                            price_display = f"€{int(price)}/мес" if price else "Не указана"
                            summary = ai_res.get("summary", "Сдается жилье")

                            print(f"  🔥 ИДЕАЛЬНОЕ СВЕЖЕЕ ОБЪЯВЛЕНИЕ! ({price_display}) -> {post_link}")

                            message = (
                                f"🤖 *AI НАШЁЛ ЖИЛЬЕ НА FACEBOOK!*\n\n"
                                f"📍 *Локация:* {ai_res.get('location', 'Waterford/Wexford')}\n"
                                f"💰 *Цена:* {price_display}\n"
                                f"📝 *Суть:* {summary}\n\n"
                                f"📄 *Текст:* {raw_text[:250]}...\n\n"
                                f"🔗 [ОТКРЫТЬ В FACEBOOK]({post_link})"
                            )
                            send_telegram(message)
                            save_new_post(post_id)
                            seen_posts.add(post_id)

                    except Exception as e:
                        print(f"  [!] Ошибка группы: {e}")

                    # 1. Пауза между группами от 5 до 12 секунд (имитация чтения)
                    await asyncio.sleep(random.randint(5, 12))

                # 2. Пауза между кругами от 30 до 45 минут (в секундах: от 1800 до 2700)
                sleep_time = random.randint(1800, 2700)
                print(f"\n[😴] Все группы проверены! Спим {sleep_time // 60} минут...")
                await asyncio.sleep(sleep_time)

    except Exception as e:
        print(f"[!] Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(run_fb_parser())