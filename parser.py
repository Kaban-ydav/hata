import asyncio
import os
import re
import random
import sqlite3
import logging
import json
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# === НАСТРОЙКИ ===
TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "daft_real_chrome_profile")
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DB_FILE = os.path.join(CURRENT_DIR, "seen_daft_urls.txt")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# 🗄️ БАЗА ДАННЫХ И МИГРАЦИЯ
# ==========================================
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    c.execute("PRAGMA table_info(subscribers)")
    columns = [col[1] for col in c.fetchall()]
    if 'max_price' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN max_price INTEGER DEFAULT 550")
    if 'locations' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN locations TEXT DEFAULT '[\"waterford\", \"wexford\"]'")
    conn.commit()
    conn.close()

def add_or_update_user(user_id, max_price=None, locations=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    if max_price is None:
        max_price = 550
    if locations is None:
        locations = ["waterford", "wexford"]
    loc_json = json.dumps(locations)
    c.execute('''
        INSERT INTO subscribers (user_id, max_price, locations)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            max_price = excluded.max_price,
            locations = excluded.locations
    ''', (user_id, max_price, loc_json))
    conn.commit()
    conn.close()

def remove_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_filters(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT max_price, locations FROM subscribers WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"max_price": row[0], "locations": json.loads(row[1])}
    return None

def get_all_subscribers():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT user_id, max_price, locations FROM subscribers")
    rows = c.fetchall()
    conn.close()
    subscribers = []
    for row in rows:
        subscribers.append({
            "user_id": row[0],
            "max_price": row[1] if row[1] is not None else 550,
            "locations": json.loads(row[2]) if row[2] else ["waterford", "wexford"]
        })
    return subscribers

async def broadcast_message(text, price, address_text):
    """Рассылка пользователям на основе их фильтров"""
    users = get_all_subscribers()
    address_lower = address_text.lower()

    for user in users:
        # 1. Проверяем цену
        if price is not None and price > user["max_price"]:
            continue

        # 2. Проверяем локацию
        user_locs = user["locations"]
        if not any(loc in address_lower for loc in user_locs):
            continue

        try:
            await bot.send_message(chat_id=user["user_id"], text=text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"[!] Ошибка отправки пользователю {user['user_id']}: {e}")

# ==========================================
# 🛠️ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def load_seen_urls():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_new_url(url):
    with open(DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{url}\n")

# ==========================================
# 🧠 FSM И КЛАВИАТУРЫ
# ==========================================
class FilterStates(StatesGroup):
    waiting_for_custom_price = State()

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎯 Подписаться")],
        [KeyboardButton(text="💰 Бюджет"), KeyboardButton(text="📍 Локация")],
        [KeyboardButton(text="⚙️ Мои фильтры"), KeyboardButton(text="🛑 Отписаться")]
    ],
    resize_keyboard=True
)

budget_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="300 €"), KeyboardButton(text="400 €"), KeyboardButton(text="550 €")],
        [KeyboardButton(text="700 €"), KeyboardButton(text="1000 €"), KeyboardButton(text="✏️ Свой бюджет")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

location_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Waterford"), KeyboardButton(text="Wexford")],
        [KeyboardButton(text="Tramore"), KeyboardButton(text="New Ross")],
        [KeyboardButton(text="Dungarvan"), KeyboardButton(text="Kilmacthomas")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

# ==========================================
# 🤖 ОБРАБОТЧИКИ ТЕЛЕГРАМ
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_or_update_user(message.from_user.id)
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n"
        "Настрой бюджет и локацию, затем подпишись.",
        reply_markup=main_menu
    )

@dp.message(F.text == "🎯 Подписаться")
async def subscribe_user(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    if not filters:
        add_or_update_user(message.from_user.id)
    await message.answer("✅ Ты подписан! Как только появится вариант по твоим фильтрам – я пришлю.")

@dp.message(F.text == "🛑 Отписаться")
async def unsubscribe_user(message: types.Message):
    remove_user(message.from_user.id)
    await message.answer("❌ Ты отписался.", reply_markup=main_menu)

@dp.message(F.text == "💰 Бюджет")
async def show_budget(message: types.Message):
    await message.answer("Выбери максимальную цену в месяц или введи свою:", reply_markup=budget_keyboard)

@dp.message(F.text.in_(["300 €", "400 €", "550 €", "700 €", "1000 €"]))
async def set_budget_preset(message: types.Message):
    price_val = int(message.text.replace(" €", ""))
    filters = get_user_filters(message.from_user.id)
    locs = filters["locations"] if filters else ["waterford", "wexford"]
    add_or_update_user(message.from_user.id, max_price=price_val, locations=locs)
    await message.answer(f"✅ Бюджет установлен: {price_val} €/мес", reply_markup=main_menu)

@dp.message(F.text == "✏️ Свой бюджет")
async def custom_budget(message: types.Message, state: FSMContext):
    await message.answer("Введи максимальную цену в евро (от 100 до 5000):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(FilterStates.waiting_for_custom_price)

@dp.message(FilterStates.waiting_for_custom_price)
async def process_custom_budget(message: types.Message, state: FSMContext):
    try:
        price_val = int(message.text.strip())
        if 100 <= price_val <= 5000:
            filters = get_user_filters(message.from_user.id)
            locs = filters["locations"] if filters else ["waterford", "wexford"]
            add_or_update_user(message.from_user.id, max_price=price_val, locations=locs)
            await message.answer(f"✅ Бюджет установлен: {price_val} €/мес", reply_markup=main_menu)
            await state.clear()
        else:
            await message.answer("❌ Цена должна быть от 100 до 5000. Попробуй снова.")
    except ValueError:
        await message.answer("❌ Введи целое число. Попробуй снова.")

@dp.message(F.text == "📍 Локация")
async def show_location(message: types.Message):
    await message.answer("Выбери город или район:", reply_markup=location_keyboard)

@dp.message(F.text.in_(["Waterford", "Wexford", "Tramore", "New Ross", "Dungarvan", "Kilmacthomas"]))
async def set_location(message: types.Message):
    loc = message.text.lower()
    filters = get_user_filters(message.from_user.id)
    price_val = filters["max_price"] if filters else 550
    add_or_update_user(message.from_user.id, max_price=price_val, locations=[loc])
    await message.answer(f"✅ Локация установлена: {message.text}", reply_markup=main_menu)

@dp.message(F.text == "🔙 Назад")
async def go_back(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu)

@dp.message(F.text == "⚙️ Мои фильтры")
async def show_filters(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    if not filters:
        await message.answer("Ты ещё не подписан. Нажми «Подписаться».")
        return
    text = (f"💰 Бюджет: {filters['max_price']} €/мес\n"
            f"📍 Локация: {', '.join(filters['locations'])}")
    await message.answer(text, reply_markup=main_menu)

@dp.message()
async def unknown(message: types.Message):
    await message.answer("Используй кнопки меню.", reply_markup=main_menu)

# ==========================================
# 🕵️‍♂️ ПАРСЕРЫ САЙТОВ (Daft.ie + Rent.ie)
# ==========================================
async def parse_daft(page, seen_urls):
    urls_daft = {
        "Waterford": "https://www.daft.ie/sharing/waterford-city?maxPrice=3000",
        "Wexford": "https://www.daft.ie/sharing/wexford-county?maxPrice=3000"
    }
    try:
        for location, url in urls_daft.items():
            print(f"[*] Проверяем Daft.ie ({location})...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(random.randint(3000, 5000))
            
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            
            next_data_script = soup.find("script", id="__NEXT_DATA__")
            if not next_data_script:
                print(f"[-] Данные на Daft ({location}) не найдены.")
                continue
            
            try:
                data = json.loads(next_data_script.string)
                listings = data["props"]["pageProps"]["listings"]
            except Exception:
                continue

            if not listings:
                print(f"[-] На Daft ({location}) сейчас нет комнат.")
                continue

            print(f"[+] Найдено на Daft: {len(listings)}. Фильтруем...")
            for item in listings:
                listing_data = item.get("listing")
                if not listing_data:
                    continue
                
                price_text = listing_data.get("price", "").lower()
                address = listing_data.get("title", "Адрес не указан")
                seo_path = listing_data.get("seoFriendlyPath", "")
                room_type = listing_data.get("numBedrooms", "Комната")
                
                if not seo_path or not price_text:
                    continue
                    
                full_url = "https://www.daft.ie" + seo_path
                
                try:
                    price_digits = int(''.join(filter(str.isdigit, price_text)))
                except ValueError:
                    continue
                
                if "week" in price_text:
                    monthly_price = int(price_digits * 4.33)
                    display_price = f"{price_text} (~€{monthly_price}/мес)"
                else:
                    monthly_price = price_digits
                    display_price = price_text

                if full_url not in seen_urls:
                    print(f"🏠 [Daft] {address} | {display_price}")
                    
                    message = (
                        f"🚨 *Найдена комната на Daft.ie!*\n\n"
                        f"🏠 Адрес: {address}\n"
                        f"🛏️ Тип: {room_type}\n"
                        f"💰 Цена: {display_price}\n\n"
                        f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({full_url})"
                    )
                    await broadcast_message(message, price=monthly_price, address_text=address)
                    save_new_url(full_url)
                    seen_urls.add(full_url)
            
    except Exception as e:
        print(f"[!] Ошибка Daft: {e}")

async def parse_rent(page, seen_urls):
    url_rent = "https://www.rent.ie/rooms-to-rent/renting_waterford/"
    print("[*] Проверяем Rent.ie...")
    try:
        await page.goto(url_rent, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(random.randint(3000, 5000))
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        search_results = soup.find_all("div", class_=lambda c: c and "search-result" in c)
        
        if not search_results:
            print("[-] На Rent.ie пока нет карточек.")
            return

        print(f"[+] Найдено на Rent.ie: {len(search_results)}. Фильтруем...")
        for card in search_results:
            link_tag = card.find("a", href=True)
            if not link_tag or "/rooms-to-rent/" not in link_tag["href"]:
                continue
                
            full_url = link_tag["href"]
            if not full_url.startswith("http"):
                full_url = "https://www.rent.ie" + full_url
                
            card_text = card.get_text()
            price_match = re.search(r'€\s*(\d+)', card_text)
            if not price_match:
                continue
                
            raw_price = int(price_match.group(1))
            is_weekly = any(w in card_text.lower() for w in ["week", "pw", "w/k"])
            monthly_price = int(raw_price * 4.33) if is_weekly else raw_price
            address = link_tag.get_text(strip=True) or "Waterford"
            
            if full_url not in seen_urls:
                display_price = f"€{raw_price}/неделя (~€{monthly_price}/мес)" if is_weekly else f"€{monthly_price}/мес"
                print(f"🏠 [Rent.ie] {address} | {display_price}")
                
                message = (
                    f"🚨 *Новая комната на Rent.ie!*\n\n"
                    f"🏠 Адрес: {address}\n"
                    f"💰 Цена: {display_price}\n\n"
                    f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({full_url})"
                )
                await broadcast_message(message, price=monthly_price, address_text=address)
                save_new_url(full_url)
                seen_urls.add(full_url)

    except Exception as e:
        print(f"[!] Ошибка Rent.ie: {e}")

async def sites_parser_loop():
    print("🚀 Фоновый парсер сайтов (Daft + Rent) запущен!")
    seen_urls = load_seen_urls()

    while True:
        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    executable_path=CHROME_PATH,
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars"]
                )
                page = context.pages[0] if context.pages else await context.new_page()

                while True:
                    await parse_daft(page, seen_urls)
                    await parse_rent(page, seen_urls)
                    
                    sleep_time = random.randint(240, 360) 
                    print(f"\n[*] Все сайты проверены. Спим {sleep_time // 60} минут...")
                    print("="*60)
                    await asyncio.sleep(sleep_time)

        except Exception as e:
            print(f"[⚠️] Ошибка парсера сайтов ({e}). Перезапуск через 10 секунд...")
            await asyncio.sleep(10)

# ==========================================
# 🚀 ЗАПУСК СИСТЕМЫ
# ==========================================
async def main():
    init_db()
    asyncio.create_task(sites_parser_loop())
    print("🚀 Бот для сайтов Daft + Rent с фильтрами запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())