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
from database import init_db, add_user, get_all_products, create_order, get_order_status

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
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            return "🙏 متاسفانه در حال حاضر ظرفیت پاسخگویی هوش مصنوعی تکمیل شده است. لطفاً چند دقیقه دیگه دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
        return f"خطا در پردازش هوش مصنوعی: {e}"


# ==========================================
# ۳. هندلرها و دستورات تلگرام
# ==========================================


@dp.message(Command("start"))
async def cmd_start(message: types.Message):

# ثبت کاربر در دیتابیس
await add_user(
    user_id=message.from_user.id,
    username=message.from_user.username or "ندارد",
    first_name=message.from_user.first_name or "کاربر"
)
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

@dp.callback_query(F.data == "contact_us")
async def handle_contact_us(callback: types.CallbackQuery):
    my_phone_number = "09017674604"
    
    contact_text = (
        "📞 **ارتباط با مدیریت هکتور آنلاین شاپ:**\n\n"
        "شما می‌توانید برای پیگیری سفارشات با شماره زیر در ارتباط باشید:\n"
        f"📱 شماره تماس: `{my_phone_number}`\n\n"
        "ساعات پاسخگویی: همه روزه از ساعت ۱۰ صبح تا ۱۰ شب\n\n"
        "💬 همچنین می‌توانید از طریق دکمه‌ی «گفتگو با هوش مصنوعی» سوالات خود را بپرسید."
    )
    await callback.message.answer(contact_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "faq")
async def handle_faq(callback: types.CallbackQuery):
    # ساخت دکمه‌های شیشه‌ای برای سوالات
    faq_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 ارسال چقدر طول می‌کشه؟", callback_data="faq_shipping"),
            ],
            [
                InlineKeyboardButton(text="💳 روش‌های پرداخت چیه؟", callback_data="faq_payment"),
            ],
            [
                InlineKeyboardButton(text="🔄 امکان مرجوعی هست؟", callback_data="faq_return"),
            ],
            [
                InlineKeyboardButton(text="🕐 ساعات کاری شما چیه؟", callback_data="faq_hours"),
            ],
            [
                InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_start"),
            ],
        ]
    )

    await callback.message.answer(
        "❓ **سوالات متداول**\n\n"
        "لطفاً یکی از سوالات زیر رو انتخاب کن تا جوابش رو ببینی: 👇",
        reply_markup=faq_keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "faq_shipping")
async def faq_shipping(callback: types.CallbackQuery):
    await callback.message.answer(
        "📦 **ارسال چقدر طول می‌کشه؟**\n\n"
        "سفارشات شما معمولاً بین ۲ تا ۵ روز کاری به دستتون می‌رسه. "
        "ارسال به تهران معمولاً ۱ روزه و به شهرستان‌ها ۲ تا ۵ روز کاری زمان می‌بره.\n\n"
        "🚚 ارسال برای سفارشات بالای ۲ میلیون تومان **رایگان** است."
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_payment")
async def faq_payment(callback: types.CallbackQuery):
    await callback.message.answer(
        "💳 **روش‌های پرداخت**\n\n"
        "شما می‌توانید از روش‌های زیر پرداخت کنید:\n"
        "• کارت به کارت\n"
        "• پرداخت آنلاین (درگاه بانکی)\n"
        "• پرداخت در محل (فقط تهران)\n\n"
        "پس از ثبت سفارش، لینک پرداخت براتون ارسال میشه."
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_return")
async def faq_return(callback: types.CallbackQuery):
    await callback.message.answer(
        "🔄 **امکان مرجوعی**\n\n"
        "بله! شما تا ۷ روز پس از دریافت کالا، در صورت عدم رضایت یا وجود ایراد، "
        "می‌توانید کالا را مرجوع کنید.\n\n"
        "⚠️ شرط مرجوعی: کالا باید در بسته‌بندی اصلی و استفاده‌نشده باشد."
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_hours")
async def faq_hours(callback: types.CallbackQuery):
    await callback.message.answer(
        "🕐 **ساعات کاری ما**\n\n"
        "ما همه روزه از ساعت **۱۰ صبح تا ۱۰ شب** پاسخگوی شما هستیم.\n\n"
        "در خارج از این ساعات، می‌تونید از دکمه‌ی «گفتگو با هوش مصنوعی» استفاده کنید. "
        "هکتور ۲۴ ساعته در خدمت شماست! 😊"
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    # ساخت مجدد دکمه‌های منوی اصلی
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

    await callback.message.answer(
        "به منوی اصلی برگشتیم! 👋\n"
        "لطفاً یکی از گزینه‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "products")
async def handle_products(callback: types.CallbackQuery):
    products_text = (
        "🛒 **محصولات هکتور آنلاین شاپ**\n\n"
        "🔄 **در حال به‌روزرسانی...**\n\n"
        "محصولات ما به‌زودی با قیمت‌های جدید و تخفیف‌های ویژه در این بخش قرار می‌گیرن.\n\n"
        "📞 برای اطلاع از موجودی و قیمت محصولات، لطفاً با پشتیبانی تماس بگیرید یا از دکمه‌ی «💬 گفتگو با هوش مصنوعی» استفاده کنید.\n\n"
        "🙏 از صبر و شکیبایی شما سپاسگزاریم."
    )
    await callback.message.answer(products_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "track_order")
async def handle_track_order(callback: types.CallbackQuery):
    await callback.message.answer(
        "📦 **پیگیری سفارش**\n\n"
        "برای پیگیری سفارش خود، لطفاً **کد سفارش** خود را ارسال کنید.\n\n"
        "مثال: `ORD-12345`\n\n"
        "📞 یا برای پیگیری سریع‌تر با شماره پشتیبانی تماس بگیرید:\n"
        "`09017674604`"
    )
    await callback.answer()

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    # گرفتن تعداد کاربران از دیتابیس
    from database import get_connection
    
    conn = await get_connection()
    try:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        product_count = await conn.fetchval("SELECT COUNT(*) FROM products")
        order_count = await conn.fetchval("SELECT COUNT(*) FROM orders")
    finally:
        await conn.close()
    
    await message.answer(
        f"📊 **آمار دیتابیس هکتور:**\n\n"
        f"👥 تعداد کاربران: `{user_count}`\n"
        f"🛒 تعداد محصولات: `{product_count}`\n"
        f"📦 تعداد سفارشات: `{order_count}`",
        parse_mode="Markdown"
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
    print(">>> ربات حرفه‌ای هکتور آنلاین شاپ با موفقیت روشن شد و آماده‌ی پاسخگویی است...")

    # راه‌اندازی دیتابیس
    await init_db()
    print(">>> دیتابیس راه‌اندازی شد.")

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
  