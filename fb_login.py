import asyncio
import json
import os
from playwright.async_api import async_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(CURRENT_DIR, "fb_cookies.json")

async def login():
    async with async_playwright() as p:
        # Запускаем обычный браузер без сложных профилей
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Europe/Dublin"
        )
        page = await context.new_page()

        print("\n" + "="*50)
        print("🌐 Переходим на Facebook...")
        print("="*50 + "\n")

        await page.goto("https://www.facebook.com/")

        print("\n" + "="*50)
        print("🔑 Залогинься в открывшемся окне!")
        print("Когда зайдёшь в аккаунт — вернись в консоль и нажми ENTER.")
        print("="*50 + "\n")

        # Пауза до нажатия Enter в консоли
        await asyncio.to_thread(input, "Нажми ENTER после успешного входа: ")

        # Сохраняем куки авторизации в файлик
        cookies = await context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Успешно! Куки сохранены в {COOKIES_FILE}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(login())