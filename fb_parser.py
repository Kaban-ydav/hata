import asyncio
import os
import re
import random
import requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"
TELEGRAM_CHAT_ID = "5012390225"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FB_PROFILE_DIR = os.path.join(CURRENT_DIR, "fb_chrome_profile")
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FB_DB_FILE = os.path.join(CURRENT_DIR, "seen_fb_posts.txt")
GROUPS_FILE = os.path.join(CURRENT_DIR, "fb_groups_list.txt")

MAX_MONTHLY_PRICE = 550

ALLOWED_LOCATIONS = [
    "waterford", "wexford", "new ross", "tramore", 
    "dungarvan", "kilmacthomas", "duncannon", "saltmills",
    "poleberry", "ferrybank", "lacken wood", "ballybeg"
]

STOP_CITIES = [
    "dublin", "cork", "galway", "limerick", "belfast", 
    "dundalk", "drogheda", "swords", "tallaght", "bray", "greystones"
]

# Ключевые слова СДАЧИ ЖИЛЬЯ (Хотя бы одно ОБЯЗАТЕЛЬНО должно быть)
OFFER_KEYWORDS = [
    "available", "to rent", "to share", "room available", 
    "flat available", "house available", "landlord", "ensuite available"
]

# Фразы ТЕХ, КТО ИЩЕТ ЖИЛЬЕ (Если есть — ИГНОРИРУЕМ)
SEEKER_KEYWORDS = [
    "looking for", "looking a", "looking single", "in need of", 
    "searching for", "wanted", "need accommodation", "phd student"
]

# МУСОРНЫЕ СЛОВА (Товары, реклама)
GARBAGE_KEYWORDS = ["samsung", "iphone", "gb", "cleaning", "nail", "spa", "car"]

def load_groups():
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            groups = [line.strip() for line in f if line.strip() and "facebook.com/groups/" in line]
            return list(set(groups))
    return []

def load_seen_posts():
    if os.path.exists(FB_DB_FILE):
        with open(FB_DB_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_new_post(post_id):
    with open(FB_DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Ошибка Telegram: {e}")

def parse_price(text):
    matches = re.findall(r'(?:€\s*(\d+)|(\d+)\s*€|(\d+)\s*(?:eur|euro|pm|pw|per week|a week|per month))', text)
    prices = []
    for m in matches:
        val = next(item for item in m if item)
        if val:
            prices.append(int(val))
            
    if not prices:
        return None, "Цена не указана"

    raw_price = prices[0]
    is_weekly = any(w in text for w in ["week", "pw", "w/k", "нед"])
    monthly_price = int(raw_price * 4.33) if is_weekly else raw_price
    
    display_str = f"€{raw_price}/нед (~€{monthly_price}/мес)" if is_weekly else f"€{monthly_price}/мес"
    return monthly_price, display_str

async def run_fb_parser():
    groups = load_groups()
    if not groups:
        print(f"[!] Файл {GROUPS_FILE} пуст!")
        return

    seen_posts = load_seen_posts()
    
    async with async_playwright() as p:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=FB_PROFILE_DIR,
            executable_path=CHROME_PATH,
            headless=False,
            user_agent=user_agent,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            timezone_id="Europe/Dublin"
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        while True:
            groups = load_groups()
            print(f"\n==========================================")
            print(f"🚀 СТАРТ ПРОВЕРКИ ({len(groups)} ГРУПП | ИДЕТ ЖЕСТКИЙ ФИЛЬТР СДАЧИ)")
            print(f"==========================================\n")

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
                    if not posts:
                        posts = soup.find_all("div", class_=lambda c: c and ("x1yzt30a" in c or "userContentWrapper" in c))

                    for post in posts[:5]:
                        post_text = post.get_text(separator=" ").lower()
                        
                        # 1. ОТСЕКАЕМ БАРАХОЛКУ И МУСОР
                        if any(g in post_text for g in GARBAGE_KEYWORDS):
                            continue

                        # 2. ОТСЕКАЕМ ДУБЛИН И Т.Д.
                        if any(stop_city in post_text for stop_city in STOP_CITIES):
                            continue

                        # 3. ОТСЕКАЕМ ТЕХ, КТО ИЩЕТ ЖИЛЬЕ ("Looking for room...")
                        if any(seeker in post_text for seeker in SEEKER_KEYWORDS):
                            continue

                        # 4. ТРЕБУЕМ ПОДТВЕРЖДЕНИЕ СДАЧИ ("Available / to rent / to share")
                        if not any(offer in post_text for offer in OFFER_KEYWORDS):
                            continue

                        # 5. ПРОВЕРКА ЛОКАЦИИ
                        if not any(loc in post_text for loc in ALLOWED_LOCATIONS):
                            continue

                        # 6. ПРОВЕРКА ЦЕНЫ (до €550)
                        monthly_price, price_str = parse_price(post_text)
                        if monthly_price and monthly_price > MAX_MONTHLY_PRICE:
                            print(f"  [-] Пропускаем, дорого: {price_str}")
                            continue

                        # 7. ССЫЛКА НА ПОСТ
                        post_link = group_url
                        for a in post.find_all("a", href=True):
                            href = a["href"]
                            if "/posts/" in href or "/permalink/" in href:
                                post_link = href.split("?")[0]
                                if not post_link.startswith("http"):
                                    post_link = "https://www.facebook.com" + post_link
                                break
                        
                        post_id = str(hash(post_text[:120]))
                        
                        if post_id not in seen_posts:
                            print(f"  🔥 РЕАЛЬНОЕ ОБЪЯВЛЕНИЕ О СДАЧЕ! ({price_str}) -> {post_link}")
                            clean_text = " ".join(post.get_text().split())[:300] + "..."
                            
                            message = (
                                f"🚨 *СВОБОДНАЯ КОМНАТА / ХАТА!*\n\n"
                                f"📍 *Регион:* Waterford / Wexford / New Ross\n"
                                f"💰 *Цена:* {price_str}\n"
                                f"📝 *Текст:* {clean_text}\n\n"
                                f"🔗 [ОТКРЫТЬ В FACEBOOK]({post_link})"
                            )
                            send_telegram(message)
                            save_new_post(post_id)
                            seen_posts.add(post_id)

                except Exception as e:
                    print(f"  [!] Ошибка группы: {e}")

                await asyncio.sleep(random.randint(3, 5))

            print(f"\n[😴] Все группы проверены! Пауза 10 минут...")
            await asyncio.sleep(600)

if __name__ == "__main__":
    asyncio.run(run_fb_parser())