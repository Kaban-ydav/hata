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
# 🗄️ БАЗА ДАННЫХ И ХРАНЕНИЕ ОБЪЯВЛЕНИЙ
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
    if 'property_type' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN property_type TEXT DEFAULT 'any'")

    # Таблица для сохранения найденных объявлений
    c.execute('''
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            address TEXT,
            price INTEGER,
            display_price TEXT,
            url TEXT UNIQUE,
            is_whole_property INTEGER,
            room_type TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_listing_to_db(title, address, price, display_price, url, is_whole_property, room_type):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO listings (title, address, price, display_price, url, is_whole_property, room_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (title, address, price, display_price, url, 1 if is_whole_property else 0, room_type))
    conn.commit()
    conn.close()

def get_recent_listings_for_user(user_id, limit=5):
    filters = get_user_filters(user_id)
    if not filters:
        return []
    
    max_price = filters["max_price"]
    locations = filters["locations"]
    user_type = filters["property_type"]

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT title, address, price, display_price, url, is_whole_property, room_type FROM listings ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()

    matching = []
    for row in rows:
        title, address, price, display_price, url, is_whole_property, room_type = row
        
        # 1. Цена
        if price and price > max_price:
            continue
        # 2. Локация
        addr_lower = address.lower()
        if not any(loc in addr_lower for loc in locations):
            continue
        # 3. Тип жилья
        if user_type == "room" and is_whole_property:
            continue
        if user_type == "house" and not is_whole_property:
            continue

        matching.append({
            "title": title,
            "address": address,
            "display_price": display_price,
            "url": url,
            "is_whole_property": is_whole_property,
            "room_type": room_type
        })
        if len(matching) >= limit:
            break

    return matching

def add_or_update_user(user_id, max_price=None, locations=None, property_type=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute("SELECT max_price, locations, property_type FROM subscribers WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    curr_price = row[0] if row else 550
    curr_locs = json.loads(row[1]) if row and row[1] else ["waterford", "wexford"]
    curr_type = row[2] if row else "any"

    new_price = max_price if max_price is not None else curr_price
    new_locs = locations if locations is not None else curr_locs
    new_type = property_type if property_type is not None else curr_type
    
    loc_json = json.dumps(new_locs)
    
    c.execute('''
        INSERT INTO subscribers (user_id, max_price, locations, property_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            max_price = excluded.max_price,
            locations = excluded.locations,
            property_type = excluded.property_type
    ''', (user_id, new_price, loc_json, new_type))
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
    c.execute("SELECT max_price, locations, property_type FROM subscribers WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"max_price": row[0], "locations": json.loads(row[1]), "property_type": row[2]}
    return None

def get_all_subscribers():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT user_id, max_price, locations, property_type FROM subscribers")
    rows = c.fetchall()
    conn.close()
    subscribers = []
    for row in rows:
        subscribers.append({
            "user_id": row[0],
            "max_price": row[1] if row[1] is not None else 550,
            "locations": json.loads(row[2]) if row[2] else ["waterford", "wexford"],
            "property_type": row[3] if row[3] else "any"
        })
    return subscribers

async def broadcast_message(text, price, address_text, is_whole_property=False):
    users = get_all_subscribers()
    address_lower = address_text.lower()

    for user in users:
        if price is not None and price > user["max_price"]:
            continue

        user_locs = user["locations"]
        if not any(loc in address_lower for loc in user_locs):
            continue
            
        user_type = user["property_type"]
        if user_type == "room" and is_whole_property:
            continue
        if user_type == "house" and not is_whole_property:
            continue

        try:
            await bot.send_message(chat_id=user["user_id"], text=text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"[!] Не удалось отправить юзеру {user['user_id']}: {e}")

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
        [KeyboardButton(text="📋 Просмотреть варианты")],
        [KeyboardButton(text="🎯 Подписаться"), KeyboardButton(text="🛑 Отписаться")],
        [KeyboardButton(text="💰 Бюджет"), KeyboardButton(text="📍 Локация")],
        [KeyboardButton(text="🏠 Тип жилья"), KeyboardButton(text="⚙️ Мои фильтры")]
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

property_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛏️ Только комната (Share)")],
        [KeyboardButton(text="🏡 Целиком (Дом/Квартира)")],
        [KeyboardButton(text="🔄 Искать всё")],
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
        "Настрой фильтры (бюджет, локацию, тип жилья), затем нажми «🎯 Подписаться» или посмотри готовые варианты.",
        reply_markup=main_menu
    )

@dp.message(F.text == "📋 Просмотреть варианты")
async def show_listings_on_demand(message: types.Message):
    items = get_recent_listings_for_user(message.from_user.id, limit=5)
    
    if not items:
        await message.answer("😔 По твоим фильтрам пока нет сохраненных вариантов. Попробуй увеличить бюджет или изменить тип жилья/локацию!")
        return

    await message.answer(f"🔍 *Вот 5 последних подходящих вариантов:*", parse_mode="Markdown")
    for item in items:
        prop_badge = "🏡 ЦЕЛОЕ ЖИЛЬЕ" if item["is_whole_property"] else "🛏️ КОМНАТА"
        msg = (
            f"📌 *Тип:* {prop_badge}\n"
            f"🏠 *Адрес:* {item['address']}\n"
            f"🛏️ *Спальни:* {item['room_type']}\n"
            f"💰 *Цена:* {item['display_price']}\n\n"
            f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({item['url']})"
        )
        await message.answer(msg, parse_mode="Markdown")
        await asyncio.sleep(0.1)

@dp.message(F.text == "/test")
async def force_test_broadcast(message: types.Message):
    await message.answer("⏳ Запускаю тестовую рассылку по базе...")
    test_message = (
        f"🚨 *ТЕСТОВАЯ КОМНАТА!*\n\n"
        f"🏠 Адрес: Test Street, Waterford\n"
        f"💰 Цена: €450/мес\n\n"
        f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ](https://www.daft.ie)"
    )
    save_listing_to_db("Тест", "Test Street, Waterford", 450, "€450/мес", "https://www.daft.ie/test", False, "1 Bed")
    await broadcast_message(text=test_message, price=450, address_text="waterford", is_whole_property=False)
    await message.answer("✅ Тестовая рассылка завершена!")

@dp.message(F.text == "🎯 Подписаться")
async def subscribe_user(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    if not filters:
        add_or_update_user(message.from_user.id)
    await message.answer("✅ Ты подписан! Как только появится новый вариант по твоим фильтрам – я пришлю.")

@dp.message(F.text == "🛑 Отписаться")
async def unsubscribe_user(message: types.Message):
    remove_user(message.from_user.id)
    await message.answer("❌ Ты отписался.", reply_markup=main_menu)

@dp.message(F.text == "💰 Бюджет")
async def show_budget(message: types.Message):
    await message.answer("Выбери максимальную цену в месяц или введи свою:", reply_markup=budget_keyboard)

@dp.message(F.text.in_(["300 €", "400 €", "550 €", "700 €", "1000 €"]))
async def set_budget_preset(message: types.Message):
    p_val = int(message.text.replace(" €", ""))
    add_or_update_user(message.from_user.id, max_price=p_val)
    await message.answer(f"✅ Бюджет установлен: {p_val} €/мес", reply_markup=main_menu)

@dp.message(F.text == "✏️ Свой бюджет")
async def custom_budget(message: types.Message, state: FSMContext):
    await message.answer("Введи максимальную цену в евро (от 100 до 5000):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(FilterStates.waiting_for_custom_price)

@dp.message(FilterStates.waiting_for_custom_price)
async def process_custom_budget(message: types.Message, state: FSMContext):
    try:
        p_val = int(message.text.strip())
        if 100 <= p_val <= 5000:
            add_or_update_user(message.from_user.id, max_price=p_val)
            await message.answer(f"✅ Бюджет установлен: {p_val} €/мес", reply_markup=main_menu)
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
    add_or_update_user(message.from_user.id, locations=[loc])
    await message.answer(f"✅ Локация установлена: {message.text}", reply_markup=main_menu)

@dp.message(F.text == "🏠 Тип жилья")
async def show_property_type(message: types.Message):
    await message.answer("Что именно ты ищешь?", reply_markup=property_keyboard)

@dp.message(F.text.in_(["🛏️ Только комната (Share)", "🏡 Целиком (Дом/Квартира)", "🔄 Искать всё"]))
async def set_property_type(message: types.Message):
    prop_map = {
        "🛏️ Только комната (Share)": "room",
        "🏡 Целиком (Дом/Квартира)": "house",
        "🔄 Искать всё": "any"
    }
    selected_type = prop_map[message.text]
    add_or_update_user(message.from_user.id, property_type=selected_type)
    await message.answer(f"✅ Тип жилья установлен: {message.text}", reply_markup=main_menu)

@dp.message(F.text == "🔙 Назад")
async def go_back(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu)

@dp.message(F.text == "⚙️ Мои фильтры")
async def show_filters(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    if not filters:
        await message.answer("Ты ещё не подписан. Нажми «Подписаться».")
        return
        
    type_map = {"room": "Только комната", "house": "Целое жилье", "any": "Любое"}
    prop_str = type_map.get(filters['property_type'], "Любое")
    
    text = (f"💰 Бюджет: {filters['max_price']} €/мес\n"
            f"📍 Локация: {', '.join(filters['locations']).title()}\n"
            f"🏠 Тип: {prop_str}")
    await message.answer(text, reply_markup=main_menu)

@dp.message()
async def unknown(message: types.Message):
    await message.answer("Используй кнопки меню.", reply_markup=main_menu)

# ==========================================
# 🕵️‍♂️ ПАРСЕРЫ САЙТОВ (Daft.ie + Rent.ie)
# ==========================================
async def parse_daft(page, seen_urls):
    urls_daft = {
        "Waterford (Комнаты)": "https://www.daft.ie/sharing/waterford-city?maxPrice=3000",
        "Wexford (Комнаты)": "https://www.daft.ie/sharing/wexford-county?maxPrice=3000",
        "Waterford (Целиком)": "https://www.daft.ie/property-for-rent/waterford-city?maxPrice=4000",
        "Wexford (Целиком)": "https://www.daft.ie/property-for-rent/wexford-county?maxPrice=4000"
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
                print(f"[-] На Daft ({location}) сейчас пусто.")
                continue

            print(f"[+] Найдено на Daft: {len(listings)}. Фильтруем...")
            for item in listings:
                listing_data = item.get("listing")
                if not listing_data:
                    continue
                
                price_text = listing_data.get("price", "").lower()
                address = listing_data.get("title", "Адрес не указан")
                seo_path = listing_data.get("seoFriendlyPath", "")
                room_type = listing_data.get("numBedrooms", "Не указано")
                
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

                # Автоопределитель комнат
                address_lower = address.lower()
                if "room" in address_lower or "share" in address_lower or "sharing" in address_lower or monthly_price < 650:
                    is_whole_property_flag = False
                else:
                    is_whole_property_flag = "Целиком" in location

                # Сохраняем объявление в базу всегда, чтобы юзер мог его посмотреть по кнопке
                save_listing_to_db("Daft", address, monthly_price, display_price, full_url, is_whole_property_flag, room_type)

                if full_url not in seen_urls:
                    prop_badge = "🏡 ЦЕЛОЕ ЖИЛЬЕ" if is_whole_property_flag else "🛏️ КОМНАТА"
                    print(f"🏠 [Daft] {prop_badge} | {address} | {display_price}")
                    
                    message = (
                        f"🚨 *Найдено на Daft.ie!*\n\n"
                        f"📌 *Тип:* {prop_badge}\n"
                        f"🏠 *Адрес:* {address}\n"
                        f"🛏️ *Спальни:* {room_type}\n"
                        f"💰 *Цена:* {display_price}\n\n"
                        f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({full_url})"
                    )
                    await broadcast_message(message, price=monthly_price, address_text=address, is_whole_property=is_whole_property_flag)
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
            display_price = f"€{raw_price}/неделя (~€{monthly_price}/мес)" if is_weekly else f"€{monthly_price}/мес"

            save_listing_to_db("Rent.ie", address, monthly_price, display_price, full_url, False, "Комната")

            if full_url not in seen_urls:
                print(f"🏠 [Rent.ie] {address} | {display_price}")
                
                message = (
                    f"🚨 *Новая комната на Rent.ie!*\n\n"
                    f"🏠 Адрес: {address}\n"
                    f"💰 Цена: {display_price}\n\n"
                    f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({full_url})"
                )
                await broadcast_message(message, price=monthly_price, address_text=address, is_whole_property=False)
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
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-infobars"],
                    viewport={"width": 1280, "height": 720},
                    locale="en-IE",
                    timezone_id="Europe/Dublin"
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
    print("🚀 Бот с кнопкой просмотра вариантов запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())