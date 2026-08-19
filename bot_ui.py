import asyncio
import os
import re
import random
import sqlite3
import logging
import json
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from curl_cffi import requests
import time
from playwright.async_api import async_playwright

# === НАСТРОЙКИ ОСНОВНОГО БОТА ===
TOKEN = "8758634330:AAEtOTqGStH5QH5jWowfAk70k127-oDy6Lw"

# 🚨 НАСТРОЙКИ АДМИН-БОТА (Система оповещений)
ALERT_BOT_TOKEN = "8745669235:AAH-DHGzNBXHck56eD8Ua-kKSrxwKq7cQCg"  # 👈 Вставь токен от BotFather
ADMIN_CHAT_ID = 5012390225                   # 👈 Вставь твой личный Telegram ID

# 🌐 НАСТРОЙКИ КУПЛЕННОГО ПРОКСИ (DataImpulse)
PROXY_SERVER = "http://gw.dataimpulse.com:823"
PROXY_USER = "45055cabf064c15bcefe__s.daft"
PROXY_PASS = "40bd628d323f6a4c"

# Форматированный URL прокси для requests / curl_cffi
PROXY_URL_FORMATTED = f"http://{PROXY_USER}:{PROXY_PASS}@gw.dataimpulse.com:823"

def send_system_alert(message_text):
    """Отправляет сбойные логи через отдельного Админ-бота прямо тебе в ЛС"""
    try:
        url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "text": f"🚨 *[HATA ALERT SYSTEM]*\n\n{message_text}",
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[!] Не удалось отправить системный аларм: {e}")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(CURRENT_DIR, "seen_daft_urls.txt")

# === 🌍 ГЕОГРАФИЯ ИРЛАНДИИ (26 ГРАФСТВ РЕСПУБЛИКИ) ===
IRELAND_REGIONS = {
    # Leinster (Ленстер)
    "Dublin": {"province": "Leinster", "cities": ["Dublin City", "Swords", "Tallaght", "Lucan", "Blackrock"]},
    "Kildare": {"province": "Leinster", "cities": ["Naas", "Maynooth", "Newbridge", "Celbridge"]},
    "Wicklow": {"province": "Leinster", "cities": ["Bray", "Greystones", "Arklow"]},
    "Wexford": {"province": "Leinster", "cities": ["Wexford Town", "New Ross", "Enniscorthy", "Gorey"]},
    "Kilkenny": {"province": "Leinster", "cities": ["Kilkenny City"]},
    "Carlow": {"province": "Leinster", "cities": ["Carlow Town"]},
    "Laois": {"province": "Leinster", "cities": ["Portlaoise"]},
    "Longford": {"province": "Leinster", "cities": ["Longford Town"]},
    "Louth": {"province": "Leinster", "cities": ["Dundalk", "Drogheda"]},
    "Meath": {"province": "Leinster", "cities": ["Navan", "Ashbourne"]},
    "Offaly": {"province": "Leinster", "cities": ["Tullamore"]},
    "Westmeath": {"province": "Leinster", "cities": ["Athlone", "Mullingar"]},

    # Munster (Манстер)
    "Cork": {"province": "Munster", "cities": ["Cork City", "Kinsale", "Cobh", "Bandon"]},
    "Waterford": {"province": "Munster", "cities": ["Waterford City", "Tramore", "Dungarvan"]},
    "Limerick": {"province": "Munster", "cities": ["Limerick City", "Castletroy"]},
    "Kerry": {"province": "Munster", "cities": ["Tralee", "Killarney", "Dingle"]},
    "Clare": {"province": "Munster", "cities": ["Ennis", "Shannon", "Lahinch"]},
    "Tipperary": {"province": "Munster", "cities": ["Clonmel", "Nenagh"]},

    # Connacht (Коннахт)
    "Galway": {"province": "Connacht", "cities": ["Galway City", "Tuam", "Oranmore"]},
    "Mayo": {"province": "Connacht", "cities": ["Castlebar", "Westport"]},
    "Roscommon": {"province": "Connacht", "cities": ["Roscommon Town"]},
    "Sligo": {"province": "Connacht", "cities": ["Sligo Town"]},
    "Leitrim": {"province": "Connacht", "cities": ["Carrick-on-Shannon"]},

    # Ulster (Ольстер - Республика)
    "Cavan": {"province": "Ulster", "cities": ["Cavan Town"]},
    "Donegal": {"province": "Ulster", "cities": ["Letterkenny"]},
    "Monaghan": {"province": "Ulster", "cities": ["Monaghan Town"]}
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# 🗄️ БАЗА ДАННЫХ И ХРАНЕНИЕ
# ==========================================
async def auto_clean_old_listings():
    while True:
        print("🧹 [Чистка БД] Начинаем проверку сохраненных объявлений...")
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
                        print(f"🗑️ Удалено ID {listing_id}: {url}")
                except Exception:
                    pass
                await asyncio.sleep(1)

            print(f"✅ [Чистка БД] Готово! Удалено: {deleted_count}")
        except Exception as e:
            print(f"[!] Ошибка очистки: {e}")

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
    
    c.execute('''
        INSERT INTO subscribers (user_id, max_price, locations, property_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            max_price = excluded.max_price,
            locations = excluded.locations,
            property_type = excluded.property_type
    ''', (user_id, new_price, json.dumps(new_locs), new_type))
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
    return [{"user_id": r[0], "max_price": r[1] or 550, "locations": json.loads(r[2]) if r[2] else ["waterford", "wexford"], "property_type": r[3] or "any"} for r in rows]

def get_recent_listings_for_user(user_id, offset=0, limit=5):
    filters = get_user_filters(user_id)
    if not filters: return [], False
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT title, address, price, display_price, url, is_whole_property, room_type FROM listings ORDER BY id DESC LIMIT 1000")
    rows = c.fetchall()
    conn.close()

    matching = []
    for title, address, price, display_price, url, is_whole, room_type in rows:
        if price and price > filters["max_price"]: continue
        if filters["locations"] and not any(loc.lower() in address.lower() for loc in filters["locations"]): continue
        if filters["property_type"] == "room" and is_whole: continue
        if filters["property_type"] == "house" and not is_whole: continue

        matching.append({
            "title": title, "address": address, "display_price": display_price,
            "url": url, "is_whole_property": is_whole, "room_type": room_type
        })
    return matching[offset : offset + limit], len(matching) > (offset + limit)

def add_location_to_user(user_id, new_loc):
    filters = get_user_filters(user_id)
    if not filters:
        add_or_update_user(user_id, locations=[new_loc.lower()])
        return
    locs = filters["locations"]
    if new_loc.lower() not in locs:
        locs.append(new_loc.lower())
        add_or_update_user(user_id, locations=locs)

def clear_user_locations(user_id):
    add_or_update_user(user_id, locations=[])

async def broadcast_message(text, price, address_text, is_whole_property=False):
    users = get_all_subscribers()
    for user in users:
        if price is not None and price > user["max_price"]: continue
        if not any(loc in address_text.lower() for loc in user["locations"]): continue
        if user["property_type"] == "room" and is_whole_property: continue
        if user["property_type"] == "house" and not is_whole_property: continue
        try:
            await bot.send_message(chat_id=user["user_id"], text=text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

def load_seen_urls():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_new_url(url):
    with open(DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{url}\n")

# ==========================================
# 🧠 FSM И КЛАВИАТУРЫ (Telegram UI)
# ==========================================
class FilterStates(StatesGroup):
    waiting_for_custom_price = State()

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Просмотреть варианты")],
        [KeyboardButton(text="🎯 Подписаться"), KeyboardButton(text="🛑 Отписаться")],
        [KeyboardButton(text="💰 Бюджет"), KeyboardButton(text="📍 Локация")],
        [KeyboardButton(text="🏠 Тип жилья"), KeyboardButton(text="⚙️ Мои фильтры")]
    ], resize_keyboard=True
)

budget_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="300 €"), KeyboardButton(text="400 €"), KeyboardButton(text="550 €")],
        [KeyboardButton(text="700 €"), KeyboardButton(text="1000 €"), KeyboardButton(text="✏️ Свой бюджет")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True
)

property_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛏️ Только комната (Share)")],
        [KeyboardButton(text="🏡 Целиком (Дом/Квартира)")],
        [KeyboardButton(text="🔄 Искать всё")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True
)

def get_regions_kb():
    kb, row = [], []
    for region in IRELAND_REGIONS.keys():
        row.append(InlineKeyboardButton(text=region, callback_data=f"region_{region}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_locs")])
    kb.append([InlineKeyboardButton(text="✅ Готово", callback_data="done_locs")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_cities_kb(region):
    kb = [[InlineKeyboardButton(text=f"🏡 Всё графство {region}", callback_data=f"addloc_{region}")]]
    row = []
    for city in IRELAND_REGIONS[region]["cities"]:
        row.append(InlineKeyboardButton(text=city, callback_data=f"addloc_{city}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 Назад к областям", callback_data="back_to_regions")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_or_update_user(message.from_user.id)
    await message.answer("Привет! 👋 Настрой фильтры и нажми «🎯 Подписаться».", reply_markup=main_menu)

async def send_listings_page(chat_id, user_id, offset=0):
    items, has_more = get_recent_listings_for_user(user_id, offset=offset, limit=5)
    if not items and offset == 0:
        await bot.send_message(chat_id, "😔 Пока нет вариантов по фильтрам.")
        return
    if not items:
        await bot.send_message(chat_id, "🏁 Это все варианты!")
        return

    await bot.send_message(chat_id, f"🔍 *Варианты ({offset + 1}–{offset + len(items)}):*", parse_mode="Markdown")
    for item in items:
        prop_badge = "🏡 ЦЕЛОЕ ЖИЛЬЕ" if item["is_whole_property"] else "🛏️ КОМНАТА"
        room_info = f"\n🛏️ *Спальни:* {item['room_type']}" if item.get('room_type') else ""
        msg = f"📌 *Тип:* {prop_badge}\n🏠 *Адрес:* {item['address']}{room_info}\n💰 *Цена:* {item['display_price']}\n\n🔗 [ОТКРЫТЬ]({item['url']})"
        await bot.send_message(chat_id, msg, parse_mode="Markdown")
        await asyncio.sleep(0.1)

    if has_more:
        await bot.send_message(chat_id, "Дальше?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Еще 5", callback_data=f"more_listings_{offset + 5}")]]))

@dp.message(F.text == "📋 Просмотреть варианты")
async def show_listings_on_demand(message: types.Message):
    await send_listings_page(message.chat.id, message.from_user.id, 0)

@dp.message(F.text == "🎯 Подписаться")
async def subscribe_user(message: types.Message):
    if not get_user_filters(message.from_user.id): add_or_update_user(message.from_user.id)
    await message.answer("✅ Подписан!", reply_markup=main_menu)

@dp.message(F.text == "🛑 Отписаться")
async def unsubscribe_user(message: types.Message):
    remove_user(message.from_user.id)
    await message.answer("❌ Отписан.", reply_markup=main_menu)

@dp.message(F.text == "💰 Бюджет")
async def show_budget(message: types.Message):
    await message.answer("Выбери цену:", reply_markup=budget_keyboard)

@dp.message(F.text.in_(["300 €", "400 €", "550 €", "700 €", "1000 €"]))
async def set_budget_preset(message: types.Message):
    p_val = int(message.text.replace(" €", ""))
    add_or_update_user(message.from_user.id, max_price=p_val)
    await message.answer(f"✅ Бюджет: {p_val} €/мес", reply_markup=main_menu)

@dp.message(F.text == "✏️ Свой бюджет")
async def custom_budget(message: types.Message, state: FSMContext):
    await message.answer("Введи цену в евро:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(FilterStates.waiting_for_custom_price)

@dp.message(FilterStates.waiting_for_custom_price)
async def process_custom_budget(message: types.Message, state: FSMContext):
    try:
        p_val = int(message.text.strip())
        add_or_update_user(message.from_user.id, max_price=p_val)
        await message.answer(f"✅ Бюджет: {p_val} €/мес", reply_markup=main_menu)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи целое число.")

@dp.message(F.text == "📍 Локация")
async def show_location(message: types.Message):
    filters = get_user_filters(message.from_user.id)
    current_locs = ", ".join(filters['locations']).title() if filters and filters['locations'] else "пока не выбраны"
    await message.answer(f"📍 *Локации:* {current_locs}\nВыбери область:", reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("region_"))
async def select_region(call: types.CallbackQuery):
    region = call.data.split("_")[1]
    await call.message.edit_text(f"🌍 *{region}*", reply_markup=get_cities_kb(region), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("addloc_"))
async def add_loc(call: types.CallbackQuery):
    loc = call.data.split("_")[1]
    add_location_to_user(call.from_user.id, loc)
    filters = get_user_filters(call.from_user.id)
    await call.answer(f"✅ Добавлено: {loc}")
    await call.message.edit_text(f"📍 *Локации:* {', '.join(filters['locations']).title()}", reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_regions")
async def back_to_regions(call: types.CallbackQuery):
    filters = get_user_filters(call.from_user.id)
    await call.message.edit_text(f"📍 *Локации:* {', '.join(filters['locations']).title() if filters else 'нет'}", reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "clear_locs")
async def clear_locs(call: types.CallbackQuery):
    clear_user_locations(call.from_user.id)
    await call.answer("🗑 Очищено!")
    await call.message.edit_text("📍 *Локации:* очищены", reply_markup=get_regions_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "done_locs")
async def done_locs(call: types.CallbackQuery):
    await call.message.delete()
    await call.message.answer("✅ Локации сохранены!", reply_markup=main_menu)

@dp.callback_query(F.data.startswith("more_listings_"))
async def load_more_listings(call: types.CallbackQuery):
    await call.message.delete()
    await send_listings_page(call.message.chat.id, call.from_user.id, int(call.data.split("_")[2]))

@dp.message(F.text == "🏠 Тип жилья")
async def show_property_type(message: types.Message):
    await message.answer("Что ищешь?", reply_markup=property_keyboard)

@dp.message(F.text.in_(["🛏️ Только комната (Share)", "🏡 Целиком (Дом/Квартира)", "🔄 Искать всё"]))
async def set_property_type(message: types.Message):
    prop_map = {"🛏️ Только комната (Share)": "room", "🏡 Целиком (Дом/Квартира)": "house", "🔄 Искать всё": "any"}
    add_or_update_user(message.from_user.id, property_type=prop_map[message.text])
    await message.answer(f"✅ Тип: {message.text}", reply_markup=main_menu)

@dp.message(F.text == "🔙 Назад")
async def go_back(message: types.Message):
    await message.answer("Меню:", reply_markup=main_menu)

@dp.message(F.text == "⚙️ Мои фильтры")
async def show_filters(message: types.Message):
    f = get_user_filters(message.from_user.id)
    if not f: return await message.answer("Нажми «Подписаться».")
    await message.answer(f"💰 Бюджет: {f['max_price']} €/мес\n📍 Локации: {', '.join(f['locations']).title()}\n🏠 Тип: {f['property_type']}", reply_markup=main_menu)

# ==========================================
# 🕵️‍♂️ ПАРСЕРЫ
# ==========================================
def parse_price(text):
    """Вытаскивает цену из текста и переводит недели в месяцы"""
    match = re.search(r'€\s*([\d,]+)', text)
    if match:
        val = int(match.group(1).replace(',', ''))
        if "week" in text or "pw" in text or "w/k" in text:
            return int(val * 4.33)
        return val
    return 0

async def parse_myhome(seen_urls):
    print("[*] Проверяем MyHome.ie (НАПРЯМУЮ с Azure, ВСЕ ГРАФСТВА)...")
    
    # 1. Автоматически генерируем ссылки для всех графств из твоего словаря!
    target_urls = ["https://www.myhome.ie/rentals/ireland/property-to-rent"] # Общая лента
    for county in IRELAND_REGIONS.keys():
        county_url = f"https://www.myhome.ie/rentals/{county.lower()}/property-to-rent"
        target_urls.append(county_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    # Идем по всем 27 ссылкам (Общая + 26 графств)
    for url in target_urls:
        try:
            # 2. Делаем запрос НАПРЯМУЮ без proxies=proxies (ЭКОНОМИМ ТРАФИК!)
            res = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
            
            if res.status_code != 200:
                print(f"[!] MyHome вернул код {res.status_code} для {url}")
                continue

            soup = BeautifulSoup(res.text, 'html.parser')
            cards = soup.find_all(['div', 'article'], class_=re.compile(r'PropertyCard|PropertySearchResult'))

            for card in cards:
                a_tag = card.find('a', href=True)
                if not a_tag: continue
                
                link = a_tag['href']
                if not link.startswith("http"):
                    link = "https://www.myhome.ie" + link
                
                link = link.split('?')[0]

                if link in seen_urls:
                    continue

                card_text = card.get_text(separator=" ").strip()
                card_text_lower = card_text.lower()
                
                price = parse_price(card_text_lower)
                
                location = "ireland"
                for county_name in IRELAND_REGIONS.keys():
                    if county_name.lower() in link.lower() or county_name.lower() in card_text_lower:
                        location = county_name.lower()
                        break

                is_whole = False if "room-to-share" in link or "share" in card_text_lower else True

                save_listing_to_db("MyHome", location.title(), price, f"€{price}/мес", link, is_whole, "Комната" if not is_whole else "")
                save_new_url(link)
                seen_urls.add(link)

                print(f"  🔥 НАХОДКА MYHOME: {link} (€{price}, {location})")
                
                msg = f"🚨 *Новое на MyHome.ie!*\n📌 *Тип:* {'🏡 ЦЕЛОЕ ЖИЛЬЕ' if is_whole else '🛏️ КОМНАТА'}\n🏠 *Локация:* {location.title()}\n💰 *Цена:* €{price}/мес\n🔗 [ОТКРЫТЬ]({link})"
                await broadcast_message(msg, price, location, is_whole)

        except Exception as e:
            print(f"[!] Ошибка при парсинге MyHome ({url}): {e}")

        # Небольшая пауза между графствами, чтобы MyHome нас не забанил за спам
        await asyncio.sleep(1)

async def parse_daft(seen_urls):
    print("[*] Проверяем Daft.ie (через Playwright + DataImpulse)...")
    
    target_urls = [
        ("https://www.daft.ie/property-for-rent/ireland", True),
        ("https://www.daft.ie/sharing/ireland", False)
    ]

    try:
        async with async_playwright() as p:
            # 👈 ПОДСТАВЛЕНЫ ТВОИ КУПЛЕННЫЕ ПРОКСИ
            browser = await p.chromium.launch(
                headless=True,
                proxy={
                    "server": PROXY_SERVER,
                    "username": PROXY_USER,
                    "password": PROXY_PASS
                }
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-IE",
                timezone_id="Europe/Dublin"
            )
            page = await context.new_page()

            for url, is_whole in target_urls:
                try:
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=90000
                    )
                    await asyncio.sleep(random.uniform(3, 5))
                    await page.wait_for_timeout(3000)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    script_tag = soup.find("script", id="__NEXT_DATA__")
                    
                    if not script_tag or not script_tag.string:
                        continue

                    data = json.loads(script_tag.string)
                    page_props = data.get('props', {}).get('pageProps', {})
                    listings = page_props.get('listings') or page_props.get('searchResult', {}).get('listings') or []

                    print(f"[+] Из Daft вытащено {len(listings)} объявлений!")

                    for item in listings:
                        l_data = item.get("listing", {}) if isinstance(item, dict) else {}
                        seo_path = l_data.get("seoFriendlyPath", "")
                        price_text = l_data.get("price", "").lower()
                        
                        if not seo_path or not price_text: continue
                        
                        full_url = "https://www.daft.ie" + seo_path
                        m_price = parse_price(price_text)
                        d_price = f"€{m_price}/мес"
                        title = l_data.get("title", "Ireland")

                        save_listing_to_db("Daft", title, m_price, d_price, full_url, is_whole, str(l_data.get("numBedrooms", "")))

                        if full_url not in seen_urls:
                            msg = f"🚨 *Найдено на Daft!*\n📌 *Тип:* {'🏡 ЦЕЛОЕ ЖИЛЬЕ' if is_whole else '🛏️ КОМНАТА'}\n🏠 *Адрес:* {title}\n💰 *Цена:* {d_price}\n🔗 [ОТКРЫТЬ]({full_url})"
                            await broadcast_message(msg, m_price, title, is_whole)
                            save_new_url(full_url)
                            seen_urls.add(full_url)

                except Exception as e_inner:
                    print(f"[!] Ошибка загрузки страницы Daft: {e_inner}")

            await browser.close()
    except Exception as e:
        print(f"[!] Ошибка Playwright: {e}")

async def parse_rent(seen_urls):
    print("[*] Проверяем Rent.ie (НАПРЯМУЮ с Azure, ВСЕ ГРАФСТВА)...")
    
    # 1. Генерируем ссылки: Общая Ирландия + все 26 графств
    target_urls = ["https://www.rent.ie/houses-to-let/renting_ireland/"]
    for county in IRELAND_REGIONS.keys():
        county_url = f"https://www.rent.ie/houses-to-let/renting_{county.lower()}/"
        target_urls.append(county_url)

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

        # Проходимся циклом по всем ссылкам
        for url in target_urls:
            def fetch_rent():
                # 2. ЗАПРОС НАПРЯМУЮ (БЕЗ ПРОКСИ)
                return requests.get(url, headers=headers, timeout=30)

            try:
                res = await asyncio.to_thread(fetch_rent)
                if res.status_code != 200:
                    print(f"[!] Rent.ie вернул код {res.status_code} для {url}")
                    continue
                
                soup = BeautifulSoup(res.text, "html.parser")
                cards = soup.find_all("div", class_=lambda c: c and "search-result" in c)
                
                if not cards: 
                    continue # Если карточек нет, просто идем к следующему графству
                    
                for card in cards:
                    a_tag = card.find("a", href=True)
                    if not a_tag: continue
                    link = ("https://www.rent.ie" + a_tag["href"]) if not a_tag["href"].startswith("http") else a_tag["href"]
                    
                    if link in seen_urls: continue

                    p_match = re.search(r'€\s*(\d+)', card.get_text())
                    if not p_match: continue
                    raw_p = int(p_match.group(1))
                    is_w = any(w in card.get_text().lower() for w in ["week", "pw", "w/k"])
                    m_price = int(raw_p * 4.33) if is_w else raw_p
                    d_price = f"€{raw_p}/нед (~€{m_price}/мес)" if is_w else f"€{raw_p}/мес"
                    address = a_tag.get_text(strip=True) or "Ireland"

                    # Определяем графство для базы
                    location = "ireland"
                    card_text_lower = card.get_text().lower()
                    for county_name in IRELAND_REGIONS.keys():
                        if county_name.lower() in link.lower() or county_name.lower() in card_text_lower:
                            location = county_name.lower()
                            break

                    # Определяем тип жилья
                    is_whole = False if "share" in card_text_lower or "room" in link.lower() else True

                    save_listing_to_db("Rent.ie", address, m_price, d_price, link, is_whole, "Комната" if not is_whole else "")
                    
                    seen_urls.add(link)
                    save_new_url(link)
                    
                    print(f"  🔥 НАХОДКА RENT.IE: {link} (€{m_price}, {location})")

                    msg = f"🚨 *Новое на Rent.ie!*\n📌 *Тип:* {'🏡 ЦЕЛОЕ ЖИЛЬЕ' if is_whole else '🛏️ КОМНАТА'}\n🏠 *Адрес:* {address}\n💰 *Цена:* {d_price}\n🔗 [ОТКРЫТЬ]({link})"
                    
                    # Передаем location в фильтр, чтобы он 100% правильно срабатывал у пользователей
                    await broadcast_message(msg, m_price, f"{address} {location}", is_whole)

            except Exception as e_inner:
                print(f"[!] Ошибка Rent.ie при обработке {url}: {e_inner}")

            # 3. Делаем микро-паузу 1 секунду между графствами, чтобы сайт не выдал бан за частые запросы
            await asyncio.sleep(1)

    except Exception as e:
        print(f"[!] Глобальная ошибка Rent.ie: {e}")