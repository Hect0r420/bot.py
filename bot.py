import asyncio
import logging
import os  # این کتابخانه برای خواندن اطلاعات امنیتی است
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
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
  await message.answer(
      "سلام هکتور عزیز! ربات فروشگاه «هکتور آنلاین شاپ» آماده و آنلاین است.\nچطور"
      " می‌توانم کمکتان کنم؟"
  )


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
      ">>> ربات حرفه‌ای هکتور آنلاین شاپ با موفقیت روشن شد و آماده‌ی پاسخگویی"
      " است..."
  )
  await bot.delete_webhook(drop_pending_updates=True)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
  