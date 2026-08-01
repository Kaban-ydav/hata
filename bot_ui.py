import asyncio
import os
import re
import random
import sqlite3
import logging
import json
import sys
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from curl_cffi import requests

# === НАСТРОЙКИ ===
TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "daft_real_chrome_profile")
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DB_FILE = os.path.join(CURRENT_DIR, "seen_daft_urls.txt")

# === 🌍 ГЕОГРАФИЯ ИРЛАНДИИ ===
IRELAND_REGIONS = {
    "Waterford": ["Waterford City", "Tramore", "Dungarvan", "Kilmacthomas", "Portlaw", "Dunmore East"],
    "Wexford": ["Wexford Town", "New Ross", "Enniscorthy", "Gorey"],
    "Dublin": ["Dublin City", "Swords", "Tallaght", "Lucan", "Blackrock", "Dun Laoghaire"],
    "Cork": ["Cork City", "Kinsale", "Cobh", "Bandon", "Mallow", "Midleton"],
    "Galway": ["Galway City", "Tuam", "Loughrea", "Oranmore", "Athenry"],
    "Limerick": ["Limerick City", "Castletroy", "Newcastle West", "Adare"],
    "Kerry": ["Tralee", "Killarney", "Dingle", "Kenmare"],
    "Clare": ["Ennis", "Shannon", "Kilrush", "Lahinch"],
    "Kildare": ["Naas", "Maynooth", "Newbridge", "Celbridge", "Leixlip"],
    "Meath": ["Navan", "Ashbourne", "Trim", "Kells"],
    "Wicklow": ["Bray", "Greystones", "Arklow", "Wicklow Town"],
    "Kilkenny": ["Kilkenny City", "Callan", "Thomastown"]
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# 🗄️ БАЗА ДАННЫХ И ХРАНЕНИЕ ОБЪЯВЛЕНИЙ
# ==========================================

async def auto_clean_old_listings():
    """Раз в сутки проверяет сохраненные ссылки и удаляет сданные/удаленные варианты"""
    while True:
        print("🧹 [Чистка БД] Начинаем проверку сохраненных объявлений на актуальность...")
        try:
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT id, url FROM listings")
            rows = c.fetchall()
            conn.close()

            deleted_count = 0
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

            for listing_id, url in rows:
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    
                    is_deleted = False
                    if response.status_code == 404:
                        is_deleted = True
                    elif "no longer available" in response.text.lower() or "agreed" in response.text.lower():
                        is_deleted = True

                    if is_deleted:
                        conn = sqlite3.connect('users.db')
                        c = conn.cursor()
                        c.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
                        conn.commit()
                        conn.close()
                        deleted_count += 1
                        print(f"🗑️ Удалено неактуальное объявление ID {listing_id}: {url}")

                except Exception:
                    pass
                
                await asyncio.sleep(1)

            print(f"✅ [Чистка БД] Готово! Удалено неактуальных вариантов: {deleted_count}")

        except Exception as e:
            print(f"[!] Ошибка при очистке базы: {e}")

        await asyncio.sleep(86400)

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (user_id INTEGER PRIMARY KEY)''')
    c.execute("PRAGMA table_info(subscribers)")
    columns = [col[1] for col in c.fetchall()]
    if 'max_price' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN max_price INTEGER DEFAULT 550")
    if 'locations' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN locations TEXT DEFAULT '[\"waterford\", \"wexford\"]'")
    if 'property_type' not in columns:
        c.execute("ALTER TABLE subscribers ADD COLUMN property_type TEXT DEFAULT 'any'")

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

def get_recent_listings_for_user(user_id, offset=0, limit=5):
    filters = get_user_filters(user_id)
    if not filters:
        return [], False
    
    max_price = filters["max_price"]
    locations = filters["locations"]
    user_type = filters["property_type"]

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT title, address, price, display_price, url, is_whole_property, room_type FROM listings ORDER BY id DESC LIMIT 1000")
    rows = c.fetchall()
    conn.close()

    matching = []
    for row in rows:
        title, address, price, display_price, url, is_whole_property, room_type = row
        
        if price and price > max_price:
            continue
        
        addr_lower = address.lower()
        if locations and not any(loc.lower() in addr_lower for loc in locations):
            continue
            
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

    sliced_items = matching[offset : offset + limit]
    has_more = len(matching) > (offset + limit)
    
    return sliced_items, has_more

def add_location_to_user(user_id, new_loc):
    filters = get_user_filters(user_id)
    new_loc = new_loc.lower()
    if not filters:
        add_or_update_user(user_id, locations=[new_loc])
        return
    locs = filters["locations"]
    if new_loc not in locs:
        locs.append(new_loc)
        add_or_update_user(user_id, locations=locs)

def clear_user_locations(user_id):
    add_or_update_user(user_id, locations=[])

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

property_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛏️ Только комната (Share)")],
        [KeyboardButton(text="🏡 Целиком (Дом/Квартира)")],
        [KeyboardButton(text="🔄 Искать всё")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

def get_regions_kb():
    kb = []
    row = []
    for region in IRELAND_REGIONS.keys():
        row.append(InlineKeyboardButton(text=region, callback_data=f"region_{region}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_locs")])
    kb.append([InlineKeyboardButton(text="✅ Готово", callback_data="done_locs")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_cities_kb(region):
    kb = []
    kb.append([InlineKeyboardButton(text=f"🏡 Всё графство {region}", callback_data=f"addloc_{region}")])
    row = []
    for city in IRELAND_REGIONS[region]:
        row.append(InlineKeyboardButton(text=city, callback_data=f"addloc_{city}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 Назад к областям", callback_data="back_to_regions")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

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

async def send_listings_page(chat_id, user_id, offset=0):
    items, has_more = get_recent_listings_for_user(user_id, offset=offset, limit=5)
    
    if not items and offset == 0:
        await bot.send_message(chat_id, "😔 По твоим фильтрам пока нет вариантов. Попробуй поднять бюджет или добавить локаций!")
        return

    if not items:
        await bot.send_message(chat_id, "🏁 Это все доступные варианты по твоим фильтрам!")
        return

    await bot.send_message(chat_id, f"🔍 *Показываем варианты ({offset + 1}–{offset + len(items)}):*", parse_mode="Markdown")
    
    for item in items:
        prop_badge = "🏡 ЦЕЛОЕ ЖИЛЬЕ" if item["is_whole_property"] else "🛏️ КОМНАТА"
        room_info = f"\n🛏️ *Спальни:* {item['room_type']}" if item.get('room_type') else ""
        msg = (
            f"📌 *Тип:* {prop_badge}\n"
            f"🏠 *Адрес:* {item['address']}"
            f"{room_info}\n"
            f"💰 *Цена:* {item['display_price']}\n\n"
            f"🔗 [ОТКРЫТЬ ОБЪЯВЛЕНИЕ]({item['url']})"
        )
        await bot.send_message(chat_id, msg, parse_mode="Markdown")
        await asyncio.sleep(0.1)

    if has_more:
        next_offset = offset + 5
        more_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="➡️ Показать еще 5", callback_data=f"more_listings_{next_offset}")
            ]]
        )
        await bot.send_message(chat_id, "Хочешь посмотреть следующие варианты?", reply_markup=more_kb)

@dp.message(F.text == "📋 Просмотреть варианты")
async def show_listings_on_demand(message: types.Message):
    await send_listings_page(message.chat.id, user_id=message.from_user.id, offset=0)

@dp.message(F.text == "🎯 Подписаться")
async def subscribe_user(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    if not filters:
        add_or_update_user(message.from_user.id)
    await message.answer("✅ Ты подписан! Как только появится вариант по твоим фильтрам – я пришлю.", reply_markup=main_menu)

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
    filters = get_user_filters(message.from_user.id)
    current_locs = ", ".join(filters['locations']).title() if filters and filters['locations'] else "пока не выбраны"
    text = f"📍 *Твои локации:* {current_locs}\n\nВыбери область (можно выбрать несколько):"
    await message.answer(text, reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("region_"))
async def select_region(call: types.CallbackQuery):
    region = call.data.split("_")[1]
    await call.message.edit_text(f"🌍 *Графство {region}*\n\nВыбери конкретный город или добавь всю область целиком:", reply_markup=get_cities_kb(region), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("addloc_"))
async def add_loc(call: types.CallbackQuery):
    loc = call.data.split("_")[1]
    add_location_to_user(call.from_user.id, loc)
    filters = get_user_filters(call.from_user.id)
    current_locs = ", ".join(filters['locations']).title()
    
    await call.answer(f"✅ Добавлено: {loc}")
    text = f"📍 *Твои локации:* {current_locs}\n\nВыбери еще одну область или нажми Готово:"
    await call.message.edit_text(text, reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_regions")
async def back_to_regions(call: types.CallbackQuery):
    filters = get_user_filters(call.from_user.id)
    current_locs = ", ".join(filters['locations']).title() if filters and filters['locations'] else "пока не выбраны"
    text = f"📍 *Твои локации:* {current_locs}\n\nВыбери область:"
    await call.message.edit_text(text, reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "clear_locs")
async def clear_locs(call: types.CallbackQuery):
    clear_user_locations(call.from_user.id)
    await call.answer("🗑 Список локаций очищен!")
    await call.message.edit_text("📍 *Твои локации:* очищены\n\nВыбери область с нуля:", reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "done_locs")
async def done_locs(call: types.CallbackQuery):
    await call.message.delete()
    filters = get_user_filters(call.from_user.id)
    current_locs = ", ".join(filters['locations']).title() if filters and filters['locations'] else "не выбраны"
    await call.message.answer(f"✅ Локации успешно сохранены!\nСейчас ты ищешь в: {current_locs}", reply_markup=main_menu)

@dp.callback_query(F.data.startswith("more_listings_"))
async def load_more_listings(call: types.CallbackQuery):
    next_offset = int(call.data.split("_")[2])
    await call.message.delete()
    await send_listings_page(call.message.chat.id, user_id=call.from_user.id, offset=next_offset)
    await call.answer()

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
            f"📍 Локации: {', '.join(filters['locations']).title()}\n"
            f"🏠 Тип: {prop_str}")
    await message.answer(text, reply_markup=main_menu)

@dp.message()
async def unknown(message: types.Message):
    await message.answer("Используй кнопки меню.", reply_markup=main_menu)

# ==========================================
# 🕵️‍♂️ ПАРСЕРЫ САЙТОВ (Daft.ie API + Rent.ie Playwright)
# ==========================================

async def parse_daft(seen_urls):
    api_url = "https://gateway.daft.ie/api/v2/grouped-listings"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Brand": "daft",
        "Platform": "web"
    }

    search_configs = [
        {"name": "Wexford (Комнаты)", "section": "sharing", "county": "wexford"},
        {"name": "Wexford (Целиком)", "section": "residential-to-let", "county": "wexford"},
        {"name": "Waterford (Комнаты)", "section": "sharing", "county": "waterford"},
        {"name": "Waterford (Целиком)", "section": "residential-to-let", "county": "waterford"},
        {"name": "Galway (Комнаты)", "section": "sharing", "county": "galway"},
        {"name": "Galway (Целиком)", "section": "residential-to-let", "county": "galway"},
    ]

    for config in search_configs:
        print(f"[*] Сканируем Daft.ie API -> {config['name']}...")
        
        payload = {
            "section": config["section"],
            "filters": [
                {"name": "county", "values": [config["county"]]}
            ],
            "paging": {"from": "0", "size": "20"},
            "sort": "publishDateDesc"
        }

        try:
            def fetch_api():
                s = requests.Session()
                return s.post(api_url, json=payload, headers=headers, impersonate="chrome124", timeout=15)
            
            response = await asyncio.to_thread(fetch_api)
            
            if response.status_code != 200:
                print(f"[!] API ответил кодом {response.status_code} на {config['name']}")
                continue

            data = response.json()
            listings = data.get("listings", [])

            if not listings:
                print(f"[-] Нет данных в API для {config['name']}")
                continue

            print(f"[+] API вернул {len(listings)} объявлений для {config['name']}!")

            for item in listings:
                listing_data = item.get("listing", {})
                seo_path = listing_data.get("seoFriendlyPath", "")
                price_text = listing_data.get("price", "").lower()
                address = listing_data.get("title", "Адрес не указан")
                room_type = str(listing_data.get("numBedrooms", "Не указано"))

                if not seo_path or not price_text:
                    continue

                full_url = "https://www.daft.ie" + seo_path

                try:
                    price_digits = int(''.join(filter(str.isdigit, price_text)))
                except ValueError:
                    continue

                if "week" in price_text or "pw" in price_text:
                    monthly_price = int(price_digits * 4.33)
                    display_price = f"{price_text} (~€{monthly_price}/мес)"
                else:
                    monthly_price = price_digits
                    display_price = price_text

                is_whole_property_flag = config["section"] == "residential-to-let"

                save_listing_to_db("Daft", address, monthly_price, display_price, full_url, is_whole_property_flag, room_type)

                if full_url not in seen_urls:
                    prop_badge = "🏡 ЦЕЛОЕ ЖИЛЬЕ" if is_whole_property_flag else "🛏️ КОМНАТА"
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

            await asyncio.sleep(1)

        except Exception as e:
            print(f"[!] Ошибка API Daft: {e}")

async def parse_rent(page, seen_urls):
    url_rent = "https://www.rent.ie/rooms-to-rent/ireland/"
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
            address = link_tag.get_text(strip=True) or "Ireland"
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
            # 1. Сначала дергаем Daft напрямую через API
            await parse_daft(seen_urls)

            # 2. Затем через Playwright открываем Rent.ie
            async with async_playwright() as p:
                is_linux = sys.platform.startswith("linux")
                launch_options = {
                    "user_data_dir": PROFILE_DIR,
                    "headless": True if is_linux else False,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-infobars"
                    ],
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "viewport": {"width": 1280, "height": 720},
                    "locale": "en-IE",
                    "timezone_id": "Europe/Dublin"
                }

                if not is_linux and os.path.exists(CHROME_PATH):
                    launch_options["executable_path"] = CHROME_PATH

                context = await p.chromium.launch_persistent_context(**launch_options)
                page = context.pages[0] if context.pages else await context.new_page()

                await parse_rent(page, seen_urls)
                await context.close()

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
    asyncio.create_task(auto_clean_old_listings())
    print("🚀 Ультимативный Бот с автоочисткой базы запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())