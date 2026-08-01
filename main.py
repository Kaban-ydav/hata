import asyncio
import logging
from bot_ui import dp, bot, init_db
from parsers_loop import start_parser_loop

async def main():
    init_db()
    # Запускаем фоновый парсер (он будет работать параллельно с ботом)
    asyncio.create_task(start_parser_loop())
    logging.info("🚀 Бот и парсер запущены")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())