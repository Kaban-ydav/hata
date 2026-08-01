import asyncio
import os
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(CURRENT_DIR, "daft_real_chrome_profile")

async def get_exact_links():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR, 
            executable_path=CHROME_PATH, 
            headless=False
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("[*] Переходим на DoneDeal...")
        await page.goto("https://www.donedeal.ie/", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # 1. Пробуем кликнуть "Accept All" на куки-баннере, если он есть
        try:
            accept_button = page.locator('button:has-text("Accept"), button:has-text("Agree"), button[id*="onetrust"]')
            if await accept_button.is_visible(timeout=3000):
                await accept_button.first.click()
                print("[+] Куки-баннер успешно закрыт!")
                await page.wait_for_timeout(1000)
        except Exception:
            print("[-] Куки-баннер не найден или уже закрыт.")

        # 2. Вводим запрос в поиск
        search_input = page.locator('input[type="search"], input[type="text"]').first
        await search_input.fill('waterford room')
        await page.keyboard.press('Enter')
        
        print("[*] Ждем загрузки результатов...")
        await page.wait_for_timeout(5000)
        
        print(f"\n[🚀 REAL URL]: {page.url}\n")
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Ищем карточки
        links = [a["href"] for a in soup.find_all("a", href=True) if any(x in a["href"] for x in ["/view/", "/for-sale/", "/rooms/"])]
        print(f"[+] Найдено прямых объявлений: {len(set(links))}")
        for l in set(links[:5]):
            print("  ->", l)

if __name__ == "__main__":
    asyncio.run(get_exact_links())