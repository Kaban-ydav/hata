import os
import sys
from typing import List, Literal
from pydantic import BaseModel, Field

try:
    import pyperclip  # Для автоматического чтения из буфера обмена
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("\n❌ Не установлены библиотеки. Выполни в консоли:")
    print("pip install google-genai pydantic pyperclip\n")
    sys.exit(1)


# Схема JSON-ответа
class ScamAnalysisResult(BaseModel):
    is_scam: bool = Field(description="True, если пост с высокой вероятностью является скамом")
    risk_score: int = Field(description="Оценка риска от 0 (безопасно) до 100 (100% скам)")
    red_flags: List[str] = Field(description="Список найденных подозрительных факторов")
    summary_ru: str = Field(description="Краткое обоснование решения на русском языке")
    recommended_action: Literal["PUBLISH", "MANUAL_REVIEW", "REJECT"] = Field(
        description="PUBLISH (<30%), MANUAL_REVIEW (30-70%), REJECT (>70%)"
    )


SYSTEM_INSTRUCTION = """
Ты — эксперт по безопасности недвижимости и аренды жилья в Ирландии.
Твоя задача — анализировать объявления об аренде из Telegram-каналов и выявлять мошенников (скам).

Критерии проверки:
1. Телефоны: Ирландские мобильные номера начинаются с +353, 083, 085, 087, 089. Иностранные коды (+56, +33, +1 и т.д.) без понятного контекста — высокий риск скама.
2. Цены: Отдельная квартира в центре Дублина за €500–€900 — 100% скам (рынок €1500+). Комната в Дублине дешевле €500 — подозрительно.
3. Оплата и условия: Просьба перевести депозит/оплату ДО личного просмотра (viewing) или договора — скам. Переводы через Western Union, MoneyGram, гифт-карты, крипту, непонятные IBAN — скам.
4. Легенды: "Я за границей / в командировке / уехал, переведите деньги и я вышлю ключи".
5. Машинный перевод: Корявый или неестественный язык объявления.
6. Программа ARP: Подозрительные требования или схемы с доплатами наличными без чеков.

Верни строго JSON по заданной схеме.
"""


def main():
    api_key = "AIzaSyAaKTYLsayZbmUbiT0Q1beQNgV2KvBk52Q"

    client = genai.Client(api_key=api_key)

    print("\n" + "=" * 65)
    print("🛡️  ИНТЕРАКТИВНЫЙ ДЕТЕКТОР СКАМА В ЖИЛЬЕ (ИРЛАНДИЯ)")
    print("=" * 65)
    if HAS_PYPERCLIP:
        print("💡 [СПРАВКА]: Просто скопируй пост в Telegram (Ctrl+C) и нажми ENTER.")
    else:
        print("💡 [СПРАВКА]: Вставь пост, затем с новой строки напиши 'GO' и нажми ENTER.")
    print("📌 Для выхода напиши 'q' и нажми Enter.")
    print("=" * 65)

    while True:
        print("\n📥 Выбери действие:")
        print("1 — Проверить то, что СКОПИРОВАНО в буфер обмена (Ctrl+C)")
        print("2 — Вставить текст вручную")
        print("q — Выход")
        
        choice = input("\nВвод (по умолчанию 1) > ").strip().lower()

        if choice in ["q", "exit", "выход"]:
            print("\n👋 Работа завершена!")
            break

        post_text = ""

        if choice in ["", "1"]:
            if not HAS_PYPERCLIP:
                print("⚠️  Библиотека pyperclip не установлена. Установи через: pip install pyperclip")
                continue
            post_text = pyperclip.paste().strip()
            if not post_text:
                print("❌ В буфере обмена пусто! Скопируй пост из Telegram и попробуй снова.")
                continue
            print("\n📋 Проверяю скопированный текст:")
            print("—" * 40)
            print(post_text[:200] + ("..." if len(post_text) > 200 else ""))
            print("—" * 40)

        elif choice == "2":
            print("\n📥 Вставляй текст (любые переносы строк разрешены).")
            print("👉 Когда закончишь, набери  GO  или  END  с новой строки и нажми Enter:")
            lines = []
            while True:
                line = input()
                if line.strip().upper() in ["GO", "END", "ГО"]:
                    break
                lines.append(line)
            post_text = "\n".join(lines).strip()

        if not post_text:
            print("❌ Пустой текст.")
            continue

        print("\n⏳ Анализирую целое объявление через Gemini 2.5 Flash...")

        try:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=ScamAnalysisResult,
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Проанализируй текст объявления:\n\n{post_text}",
                config=config,
            )

            res: ScamAnalysisResult = response.parsed

            print("\n" + "—" * 50)
            if res.recommended_action == "PUBLISH":
                print("🟢 [ВЕРДИКТ]: БЕЗОПАСНО -> Публиковать в канал")
            elif res.recommended_action == "MANUAL_REVIEW":
                print("🟡 [ВЕРДИКТ]: СОМНИТЕЛЬНО -> Отправить на проверку модератору")
            else:
                print("🔴 [ВЕРДИКТ]: СКАМ / ОПАСНО -> Блокировать")

            print(f"📊 Оценка риска: {res.risk_score}%")
            print(f"💬 Вывод: {res.summary_ru}")
            
            if res.red_flags:
                print("🚩 Найденные красные флаги:")
                for flag in res.red_flags:
                    print(f"   • {flag}")
            print("—" * 50)

        except Exception as e:
            print(f"\n❌ Ошибка при обращении к API: {e}")


if __name__ == "__main__":
    main()