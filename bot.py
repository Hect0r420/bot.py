import asyncio
import logging
import os  # این کتابخانه برای خواندن اطلاعات امنیتی است
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler, setup_application
)
from google import genai
from google.genai import types as genai_types

# ==========================================
# ۱. تنظیمات و اطلاعات پایه (Config)
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# شخصیت و دستورالعمل‌های هوش مصنوعی (هکتور و معرفی‌نامه دقیق)
SYSTEM_INSTRUCTION = """
نام تو «هکتور» است و تو دستیار هوشمند و اختصاصی مجموعه «هکتور آنلاین شاپ» هستی.
دستورالعمل بسیار مهم: هر زمان که کاربر پیامی داد یا سوالی پرسید، باید در ابتدای پاسخ خود با صراحت بگویی:
"من برای مجموعه هکتور آنلاین شاپ ساخته شده‌ام و برای موجودی محصول و ثبت سفارش ساخته شده‌ام (و در حال به‌روزرسانی هستم)."
سپس بلافاصله بعد از این جمله، به بقیه سوال یا پیام کاربر با لحنی صمیمی و مودبانه پاسخ بده.
هدف اصلی تو کمک به مشتریان برای بررسی موجودی محصولات و ثبت سفارش است.
"""

# ==========================================
# ۲. بخش ارتباط با هوش مصنوعی
# ==========================================
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def get_ai_response(user_message: str) -> str:
  try:
    response = ai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION
        ),
    )
    return response.text
  except Exception as e:
    return f"خطا در پردازش هوش مصنوعی: {e}"


# ==========================================
# ۳. هندلرها و دستورات تلگرام
# ==========================================


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # ساخت دکمه‌های شیشه‌ای
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛒 مشاهده محصولات", callback_data="products"),
                InlineKeyboardButton(text="📦 پیگیری سفارش", callback_data="track_order"),
            ],
            [
                InlineKeyboardButton(text="📞 تماس با ما", callback_data="contact_us"),
                InlineKeyboardButton(text="❓ سوالات متداول", callback_data="faq"),
            ],
            [
                InlineKeyboardButton(text="ℹ️ درباره ما", callback_data="about_us"),
            ],
            [
                InlineKeyboardButton(text="💬 گفتگو با هوش مصنوعی", callback_data="chat_ai"),
            ],
        ]
    )

    await message.answer(
        "سلام رفیق! 👋 خوش اومدی به «هکتور آنلاین شاپ» 🛍️\n\n"
        "من هکتور هستم، دستیار هوشمند این مجموعه. اینجا می‌تونی:\n"
        "✅ موجودی محصولات رو چک کنی\n"
        "✅ سفارش ثبت کنی\n"
        "✅ و هر سوالی داشتی ازم بپرسی\n\n"
        "لطفاً یکی از گزینه‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "chat_ai")
async def handle_chat_ai(callback: types.CallbackQuery):
    await callback.message.answer(
        "خب رفیق! 😊 من اینجام. هر سوالی درباره محصولات، موجودی یا هر چیز دیگه‌ای داری، بپرس تا کمکت کنم.\n\n"
        "فقط کافیه سوالت رو تایپ کنی و بفرستی. 👇"
    )
    await callback.answer()

@dp.callback_query(F.data == "about_us")
async def handle_about_us(callback: types.CallbackQuery):
    about_text = (
        "ℹ️ **درباره هکتور آنلاین شاپ**\n\n"
        "به «هکتور آنلاین شاپ» خوش آمدید! 🛍️\n\n"
        "ما یک مجموعه‌ی آنلاین هستیم که با هدف ارائه‌ی بهترین محصولات با کیفیت و قیمت مناسب فعالیت می‌کنیم.\n\n"
        "🎯 **هدف ما:**\n"
        "جلب رضایت شما مشتریان عزیز و ارائه‌ی تجربه‌ی خرید آسان و مطمئن.\n\n"
        "✅ **چرا ما؟**\n"
        "• محصولات اورجینال و باکیفیت\n"
        "• قیمت‌های رقابتی و منصفانه\n"
        "• پشتیبانی پاسخگو و سریع\n"
        "• ارسال سریع به سراسر کشور\n\n"
        "🙏 از اینکه ما رو انتخاب کردید صمیمانه سپاسگزاریم.\n"
        "تیم هکتور آنلاین شاپ ❤️"
    )
    await callback.message.answer(about_text, parse_mode="Markdown")
    await callback.answer()


# بخش تماس با ما
@dp.message(F.text == "تماس با ما")
async def contact_us(message: types.Message):
  my_phone_number = "09017674604"  # شماره تماس شما

  contact_text = (
      "📞 **ارتباط با مدیریت هکتور آنلاین شاپ:**\n\n"
      "شما می‌توانید برای پیگیری سفارشات با شماره زیر در ارتباط باشید:\n"
      f"📱 شماره تماس: `{my_phone_number}`\n\n"
      "ساعات پاسخگویی: همه روزه از ساعت ۱۰ صبح تا ۱۰ شب"
  )
  await message.answer(contact_text, parse_mode="Markdown")


@dp.message(F.text)
async def handle_all_messages(message: types.Message):
  loop = asyncio.get_running_loop()
  response_text = await loop.run_in_executor(
      None, get_ai_response, message.text
  )
  await message.answer(response_text)


# ==========================================
# ۴. استارت اصلی برنامه
# ==========================================
async def main():
    print(
    ">>> ربات حرفه‌ای هکتور آنلاین شاپ با موفقیت روشن شد و آماده‌ی پاسخگویی است..."
)

    RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
    PORT = int(os.getenv("PORT", 10000))
    WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}"

    # ست کردن Webhook در تلگرام
    await bot.set_webhook(url=f"{RENDER_URL}{WEBHOOK_PATH}")
    print(f">>> Webhook تنظیم شد: {RENDER_URL}{WEBHOOK_PATH}")

    # ساخت وب‌سرور aiohttp
    app = web.Application()

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # این خط برای UptimeRobot (بیدار موندن)
    async def health_check(request):
        return web.Response(text="Hector Bot is alive!")

    app.router.add_get("/health", health_check)

    setup_application(app, dp, bot=bot)

    # اجرای وب‌سرور
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    print(f">>> سرور روی پورت {PORT} بالا آمد. ربات آماده است!")
    await asyncio.Event().wait()


if __name__ == "__main__":
  asyncio.run(main())
  