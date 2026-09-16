import asyncio
import logging
import os
import random
import string
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler, setup_application
)
from google import genai
from google.genai import types as genai_types
from database import (
    init_db, add_user, get_all_products, create_order, get_order_status,
    save_pending_order, get_pending_order, delete_pending_order,
    update_user_info, get_user_info, get_connection
)

# ==========================================
# ۱. تنظیمات و اطلاعات پایه (Config)
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # 🟢 اینجا آیدی عددی تلگرام خودت رو بذار
CARD_NUMBER = "6219-8619-4669-5482"  # 🟢 شماره کارت خودت رو اینجا بذار
# شماره پشتیبانی
SUPPORT_PHONE = "09017674604"  # 🟢 شماره پشتیبانی

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

SYSTEM_INSTRUCTION = """
نام تو «هکتور» است و تو دستیار هوشمند و اختصاصی مجموعه «هکتور آنلاین شاپ» هستی.
دستورالعمل بسیار مهم: هر زمان که کاربر پیامی داد یا سوالی پرسید، باید در ابتدای پاسخ خود با صراحت بگویی:
"من برای مجموعه هکتور آنلاین شاپ ساخته شده‌ام و برای موجودی محصول و ثبت سفارش ساخته شده‌ام (و در حال به‌روزرسانی هستم)."
سپس بلافاصله بعد از این جمله، به بقیه سوال یا پیام کاربر با لحنی صمیمی و مودبانه پاسخ بده.
هدف اصلی تو کمک به مشتریان برای بررسی موجودی محصولات و ثبت سفارش است.
"""

ai_client = genai.Client(api_key=GEMINI_API_KEY)


# ==========================================
# ۲. بخش ارتباط با هوش مصنوعی (با آگاهی از محصولات)
# ==========================================
async def get_ai_response_async(user_message: str) -> str:
    try:
        conn = await get_connection()
        try:
            products = await conn.fetch(
                "SELECT name, price, stock, category FROM products WHERE stock > 0 ORDER BY product_id"
            )
        finally:
            await conn.close()

        if products:
            products_text = "\n\n📦 **لیست محصولات موجود در فروشگاه (از دیتابیس):**\n"
            for p in products:
                products_text += (
                    f"- {p['name']} | قیمت: {p['price']:,} تومان | "
                    f"موجودی: {p['stock']} عدد | دسته: {p['category'] or 'متفرقه'}\n"
                )
            products_text += "\n⚠️ این اطلاعات از دیتابیس واقعی فروشگاهه. حتماً موقع جواب دادن به مشتری، از همین اطلاعات استفاده کن.\n"
        else:
            products_text = "\n\n⚠️ در حال حاضر هیچ محصولی توی دیتابیس موجود نیست.\n"

        full_message = f"{user_message}\n{products_text}"

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: ai_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=full_message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION
                ),
            )
        )
        return response.text
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            return "🙏 متاسفانه در حال حاضر ظرفیت پاسخگویی هوش مصنوعی تکمیل شده است. لطفاً چند دقیقه دیگه دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
        return f"خطا در پردازش هوش مصنوعی: {e}"


# ==========================================
# ۳. منوی اصلی و شروع
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await add_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "ندارد",
        first_name=message.from_user.first_name or "کاربر"
    )

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


# ==========================================
# ۴. هندلرهای دکمه‌های شیشه‌ای
# ==========================================
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
    contact_text = (
        "📞 **ارتباط با مدیریت هکتور آنلاین شاپ:**\n\n"
        "شما می‌توانید برای پیگیری سفارشات با شماره زیر در ارتباط باشید:\n"
        "📱 شماره تماس: `{SUPPORT_PHONE}`\n\n"
        "ساعات پاسخگویی: همه روزه از ساعت ۱۰ صبح تا ۱۰ شب\n\n"
        "💬 همچنین می‌توانید از دکمه‌ی «گفتگو با هوش مصنوعی» سوالات خود را بپرسید."
    )
    await callback.message.answer(contact_text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "faq")
async def handle_faq(callback: types.CallbackQuery):
    faq_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 ارسال چقدر طول می‌کشه؟", callback_data="faq_shipping")],
            [InlineKeyboardButton(text="💳 روش‌های پرداخت چیه؟", callback_data="faq_payment")],
            [InlineKeyboardButton(text="🔄 امکان مرجوعی هست؟", callback_data="faq_return")],
            [InlineKeyboardButton(text="🕐 ساعات کاری شما چیه؟", callback_data="faq_hours")],
            [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_start")],
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


# ==========================================
# ۵. مشاهده محصولات (با عکس)
# ==========================================
@dp.callback_query(F.data == "products")
async def handle_products(callback: types.CallbackQuery):
    conn = await get_connection()
    try:
        products = await conn.fetch("SELECT * FROM products WHERE stock > 0 ORDER BY product_id")
    finally:
        await conn.close()

    if not products:
        await callback.message.answer(
            "🛒 **محصولات هکتور آنلاین شاپ**\n\n"
            "😔 در حال حاضر هیچ محصولی موجود نیست.\n\n"
            "📞 برای اطلاع از موجودی، با پشتیبانی تماس بگیرید."
        )
        await callback.answer()
        return

    for p in products:
        caption = (
            f"🔹 **{p['name']}**\n"
            f"💰 قیمت: {p['price']:,} تومان\n"
            f"📦 موجودی: {p['stock']} عدد\n"
            f"🏷️ دسته‌بندی: {p['category'] or 'متفرقه'}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 ثبت سفارش", callback_data=f"order_{p['product_id']}")]
            ]
        )
        if p['image_url']:
            try:
                await callback.message.answer_photo(
                    photo=p['image_url'],
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"❌ خطا در ارسال عکس {p['name']}: {e}")
                await callback.message.answer(
                    caption + "\n\n⚠️ (عکس این محصول در دسترس نیست)",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await callback.message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")

    await callback.answer()


# ==========================================
# ۶. ثبت سفارش
# ==========================================
@dp.callback_query(F.data.startswith("order_"))
async def handle_order_start(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])

    conn = await get_connection()
    try:
        product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", product_id)
    finally:
        await conn.close()

    if not product:
        await callback.message.answer("❌ محصول مورد نظر پیدا نشد.")
        await callback.answer()
        return

    await save_pending_order(callback.from_user.id, product_id)

    await callback.message.answer(
        f"🛒 **ثبت سفارش: {product['name']}**\n\n"
        f"💰 قیمت واحد: {product['price']:,} تومان\n"
        f"📦 موجودی: {product['stock']} عدد\n\n"
        f"لطفاً **تعداد** مورد نظرت رو بنویس و بفرست (فقط عدد):",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(F.text.regexp(r"^\d+$"))
async def handle_order_quantity(message: types.Message):
    user_id = message.from_user.id
    pending = await get_pending_order(user_id)
    if not pending:
        return

    conn = await get_connection()
    try:
        product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", pending['product_id'])
    finally:
        await conn.close()

    if not product:
        await message.answer("❌ محصول مورد نظر پیدا نشد.")
        await delete_pending_order(user_id)
        return

    quantity = int(message.text)

    if quantity <= 0:
        await message.answer("❌ تعداد باید عددی بزرگتر از صفر باشه.")
        return

    if quantity > product['stock']:
        await message.answer(f"❌ متاسفانه فقط {product['stock']} عدد موجوده.")
        return

    order_code = "ORD-" + "".join(random.choices(string.digits, k=5))
    total_price = product['price'] * quantity

    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO orders (order_code, user_id, product_id, quantity, total_price, status)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            order_code, user_id, product['product_id'], quantity, total_price, "در انتظار پرداخت"
        )
        await conn.execute(
            "UPDATE products SET stock = stock - $1 WHERE product_id = $2",
            quantity, product['product_id']
        )
        print(f"✅ سفارش {order_code} ثبت شد.")
    finally:
        await conn.close()

    await delete_pending_order(user_id)

    await message.answer(
        f"✅ **سفارش شما با موفقیت ثبت شد!**\n\n"
        f"🆔 کد سفارش: `{order_code}`\n"
        f"📦 محصول: {product['name']}\n"
        f"🔢 تعداد: {quantity}\n"
        f"💰 مبلغ کل: {total_price:,} تومان\n\n"
        f"💳 **برای تکمیل سفارش، مبلغ {total_price:,} تومان رو به شماره کارت زیر واریز کن:**\n\n"
        f"`{CARD_NUMBER}`\n\n"
        f"📸 بعد از پرداخت، **عکس رسید** رو همین‌جا بفرست.\n\n"
        f"⏳ وضعیت سفارش: **در انتظار پرداخت**",
        parse_mode="Markdown"
    )

    user_info = await get_user_info(user_id)
    if user_info and not user_info['phone_number']:
        await message.answer(
            "📞 **لطفا شماره خود را وارد کنین :**\n\n"
            "(مثال: `09123456789`)\n\n"
            "این اطلاعات برای هماهنگی سفارش و اطلاع‌رسانی تخفیف‌ها استفاده میشه."
        )


@dp.message(F.text.regexp(r"^09\d{9}$"))
async def handle_phone_number(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip()
    await update_user_info(user_id, phone_number=phone)
    await message.answer(
        f"✅ شماره تماس `{phone}` ذخیره شد.\n\n"
        f"🎂 حالا **تاریخ تولدت** رو وارد کن:\n\n"
        f"فرمت: `YYYY-MM-DD`\n"
        f"مثال: `1995-05-20`",
        parse_mode="Markdown"
    )


@dp.message(F.text.regexp(r"^\d{4}-\d{2}-\d{2}$"))
async def handle_birthday(message: types.Message):
    user_id = message.from_user.id
    birthday = message.text.strip()
    await update_user_info(user_id, birthday=birthday)
    await message.answer(
        f"🎉 **ممنون! اطلاعاتت کامل شد.**\n\n"
        f"🎂 تاریخ تولد: `{birthday}`\n\n"
        f"از این به بعد، توی روز تولدت تخفیف‌های ویژه‌ای برات در نظر می‌گیریم! 🎁"
    )


# ==========================================
# ۷. دستورات ادمین
# ==========================================
@dp.message(Command("add_product"))
async def cmd_add_product(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    await message.answer(
        "🛒 **افزودن محصول جدید**\n\n"
        "لطفاً اطلاعات محصول رو به این ترتیب و با **کاما (`,`)** از هم جدا کن و بفرست:\n\n"
        "`نام محصول, قیمت, موجودی, دسته‌بندی, لینک عکس`\n\n"
        "**مثال:**\n"
        "`هدفون بی‌سیم, 850000, 10, لوازم جانبی, https://example.com/image.jpg`\n\n"
        "⚠️ اگه عکس نداری، جای لینک عکس بنویس: `-`",
        parse_mode="Markdown"
    )


@dp.message(F.text.regexp(r"^.+,.+,.+,.+,.+$"))
async def handle_product_input(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = [p.strip() for p in message.text.split(",")]

    if len(parts) != 5:
        await message.answer(
            "❌ فرمت اشتباهه! لطفاً دقیقاً ۵ بخش با کاما جدا کن:\n"
            "`نام, قیمت, موجودی, دسته‌بندی, لینک عکس`",
            parse_mode="Markdown"
        )
        return

    name, price_str, stock_str, category, image_url = parts
    if image_url == "-":
        image_url = None

    try:
        price = int(price_str)
        stock = int(stock_str)
    except ValueError:
        await message.answer("❌ قیمت و موجودی باید عدد باشن!")
        return

    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO products (name, price, stock, category, image_url)
               VALUES ($1, $2, $3, $4, $5)""",
            name, price, stock, category, image_url
        )
        print(f"✅ محصول '{name}' اضافه شد.")
    except Exception as e:
        print(f"❌ خطا: {e}")
        await message.answer(f"❌ خطا در اضافه کردن محصول: {e}")
        return
    finally:
        await conn.close()

    await message.answer(
        f"✅ **محصول با موفقیت اضافه شد!**\n\n"
        f"📦 نام: {name}\n"
        f"💰 قیمت: {price:,} تومان\n"
        f"🔢 موجودی: {stock}\n"
        f"🏷️ دسته‌بندی: {category}\n"
        f"🖼️ عکس: {'داره ✅' if image_url else 'نداره ❌'}",
        parse_mode="Markdown"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
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


@dp.message(Command("confirm_order"))
async def cmd_confirm_order(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n**مثال:**\n`/confirm_order ORD-12345`",
            parse_mode="Markdown"
        )
        return

    order_code = parts[1]
    conn = await get_connection()
    try:
        order = await conn.fetchrow("SELECT * FROM orders WHERE order_code = $1", order_code)
        if not order:
            await message.answer(f"❌ سفارشی با کد `{order_code}` پیدا نشد.", parse_mode="Markdown")
            return
        await conn.execute(
            "UPDATE orders SET status = $1 WHERE order_code = $2",
            "در حال پردازش", order_code
        )
    finally:
        await conn.close()

    await message.answer(
        f"✅ **سفارش تایید شد!**\n\n"
        f"🆔 کد سفارش: `{order_code}`\n"
        f"📦 وضعیت جدید: **در حال پردازش**",
        parse_mode="Markdown"
    )


@dp.message(Command("out_of_stock"))
async def cmd_out_of_stock(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n**مثال:**\n`/out_of_stock هدفون بی‌سیم`",
            parse_mode="Markdown"
        )
        return

    query = parts[1].strip()
    conn = await get_connection()
    try:
        if query.isdigit():
            product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", int(query))
        else:
            product = await conn.fetchrow("SELECT * FROM products WHERE name ILIKE $1", f"%{query}%")

        if not product:
            await message.answer(f"❌ محصولی با `{query}` پیدا نشد.", parse_mode="Markdown")
            return

        await conn.execute("UPDATE products SET stock = 0 WHERE product_id = $1", product['product_id'])
        print(f"✅ موجودی '{product['name']}' صفر شد.")
    finally:
        await conn.close()

    await message.answer(
        f"✅ **موجودی صفر شد!**\n\n"
        f"🆔 کد: `{product['product_id']}`\n"
        f"📦 نام: {product['name']}",
        parse_mode="Markdown"
    )


@dp.message(Command("delete_product"))
async def cmd_delete_product(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer(
            "❌ فرمت اشتباهه!\n\n**مثال:**\n`/delete_product 3`",
            parse_mode="Markdown"
        )
        return

    product_id = int(parts[1].strip())
    conn = await get_connection()
    try:
        product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", product_id)
        if not product:
            await message.answer(f"❌ محصولی با آیدی `{product_id}` پیدا نشد.", parse_mode="Markdown")
            return
        await conn.execute("DELETE FROM products WHERE product_id = $1", product_id)
    finally:
        await conn.close()

    await message.answer(
        f"✅ **محصول حذف شد!**\n\n"
        f"🆔 کد: `{product_id}`\n"
        f"📦 نام: {product['name']}",
        parse_mode="Markdown"
    )


@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    conn = await get_connection()
    try:
        users = await conn.fetch("SELECT * FROM users ORDER BY joined_at DESC")
    finally:
        await conn.close()

    if not users:
        await message.answer("👥 هیچ کاربری ثبت نشده.")
        return

    text = f"👥 **لیست کاربران** (تعداد: {len(users)})\n\n"
    for u in users:
        phone = u['phone_number'] or "❌ ثبت نشده"
        birthday = u['birthday'] or "❌ ثبت نشده"
        text += (
            f"🔹 **{u['first_name']}**\n"
            f"🆔 `{u['user_id']}`\n"
            f"📞 `{phone}`\n"
            f"🎂 `{birthday}`\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")


@dp.message(Command("orders"))
async def cmd_orders(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    conn = await get_connection()
    try:
        orders = await conn.fetch(
            """SELECT o.*, u.first_name, u.phone_number, p.name as product_name
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.user_id
               LEFT JOIN products p ON o.product_id = p.product_id
               ORDER BY o.created_at DESC LIMIT 20"""
        )
    finally:
        await conn.close()

    if not orders:
        await message.answer("📦 هیچ سفارشی ثبت نشده.")
        return

    text = f"📦 **آخرین سفارشات** (تعداد: {len(orders)})\n\n"
    for o in orders:
        text += (
            f"🆔 `{o['order_code']}`\n"
            f"👤 {o['first_name'] or 'نامشخص'}\n"
            f"📞 `{o['phone_number'] or 'ندارد'}`\n"
            f"📦 {o['product_name'] or 'نامشخص'}\n"
            f"🔢 تعداد: {o['quantity']}\n"
            f"💰 {o['total_price']:,} تومان\n"
            f"📊 **{o['status']}**\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    admin_help = (
        "👑 **پنل مدیریت هکتور آنلاین شاپ**\n\n"
        "در اینجا لیست تمام دستورات مدیریتی موجود قرار دارد:\n\n"
        "📦 **مدیریت محصولات:**\n"
        "• `/add_product` → افزودن محصول جدید\n"
        "• `/stock [کد محصول]` → مشاهده اطلاعات یک محصول\n"
        "• `/out_of_stock [نام یا کد]` → صفر کردن موجودی محصول\n"
        "• `/delete_product [کد محصول]` → حذف کامل محصول\n\n"
        "🛒 **مدیریت سفارشات:**\n"
        "• `/orders` → مشاهده‌ی ۲۰ سفارش آخر\n"
        "• `/confirm_order [کد سفارش]` → تایید پرداخت سفارش\n\n"
        "👥 **مدیریت کاربران:**\n"
        "• `/users` → مشاهده‌ی لیست کاربران\n\n"
        "📊 **آمار:**\n"
        "• `/stats` → مشاهده‌ی آمار کلی ربات\n\n"
        "💡 **نکته:** برای دیدن جزئیات هر دستور، فقط خود دستور رو بدون آرگومان بفرست (مثلاً `/stock`) تا راهنماش بیاد."
    )
    await message.answer(admin_help, parse_mode="Markdown")

# ==========================================
# ۱۳. پیگیری سفارش (دریافت کد سفارش)
# ==========================================
@dp.message(F.text.regexp(r"^ORD-\d{5}$"))
async def handle_order_code(message: types.Message):
    order_code = message.text.strip()

    conn = await get_connection()
    try:
        # گرفتن اطلاعات سفارش با کد سفارش
        order = await conn.fetchrow(
            """SELECT o.*, p.name as product_name
               FROM orders o
               LEFT JOIN products p ON o.product_id = p.product_id
               WHERE o.order_code = $1""",
            order_code
        )
    finally:
        await conn.close()

    if not order:
        await message.answer(
            f"❌ سفارشی با کد `{order_code}` پیدا نشد.\n\n"
            f"لطفاً کد سفارش رو دقیقاً همون‌طور که گرفتی وارد کن.\n"
            f"📞 یا با پشتیبانی تماس بگیر: `{SUPPORT_PHONE}`",
            parse_mode="Markdown"
        )
        return

    # وضعیت سفارش رو با ایموجی مناسب نشون بده
    status_emoji = {
        "در انتظار پرداخت": "⏳",
        "در حال پردازش": "🔄",
        "ارسال شده": "🚚",
        "تحویل داده شده": "✅",
        "لغو شده": "❌"
    }.get(order['status'], "📦")

    await message.answer(
        f"📦 **وضعیت سفارش شما**\n\n"
        f"🆔 کد سفارش: `{order['order_code']}`\n"
        f"🛍️ محصول: {order['product_name'] or 'نامشخص'}\n"
        f"🔢 تعداد: {order['quantity']} عدد\n"
        f"💰 مبلغ کل: {order['total_price']:,} تومان\n"
        f"{status_emoji} وضعیت فعلی: **{order['status']}**\n\n"
        f"📅 تاریخ ثبت: {order['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
        f"💬 هر سوالی داشتی، با پشتیبانی تماس بگیر:\n"
        f"📞 `{SUPPORT_PHONE}`",
        parse_mode="Markdown"
    )

# ==========================================
# ۱۱. دستور استعلام موجودی محصول (ادمین)
# ==========================================
@dp.message(Command("stock"))
async def cmd_stock(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer(
            "❌ فرمت اشتباهه!\n\n**مثال:**\n`/stock 3`",
            parse_mode="Markdown"
        )
        return

    product_id = int(parts[1].strip())
    conn = await get_connection()
    try:
        product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", product_id)
    finally:
        await conn.close()

    if not product:
        await message.answer(f"❌ محصولی با آیدی `{product_id}` پیدا نشد.", parse_mode="Markdown")
        return

    await message.answer(
        f"📦 **اطلاعات محصول**\n\n"
        f"🆔 کد: `{product['product_id']}`\n"
        f"📛 نام: {product['name']}\n"
        f"💰 قیمت: {product['price']:,} تومان\n"
        f"📊 موجودی: {product['stock']} عدد\n"
        f"🏷️ دسته: {product['category'] or 'متفرقه'}",
        parse_mode="Markdown"
    )


# ==========================================
# ۸. پیگیری سفارش (نمایش راهنما)
# ==========================================
@dp.callback_query(F.data == "track_order")
async def handle_track_order(callback: types.CallbackQuery):
    await callback.message.answer(
        "📦 **پیگیری سفارش**\n\n"
        "برای پیگیری سفارش خود، لطفاً **کد سفارش** خود را ارسال کنید.\n\n"
        "مثال: `ORD-12345`\n\n"
        f"📞 یا برای پیگیری سریع‌تر با شماره پشتیبانی تماس بگیرید:\n"
        f"`{SUPPORT_PHONE}`",
        parse_mode="Markdown"
    )
    await callback.answer()

# ==========================================
# ۱۴. یادآوری خودکار پرداخت
# ==========================================
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta

scheduler = AsyncIOScheduler()


async def check_pending_orders():
    """چک کردن سفارشات در انتظار پرداخت و ارسال یادآوری"""
    try:
        conn = await get_connection()
        try:
            # پیدا کردن سفارشاتی که بیش از ۱ ساعت در انتظار پرداخت موندن
            one_hour_ago = datetime.now() - timedelta(hours=1)

            orders = await conn.fetch(
                """SELECT o.*, u.first_name 
                   FROM orders o
                   LEFT JOIN users u ON o.user_id = u.user_id
                   WHERE o.status = 'در انتظار پرداخت' 
                   AND o.created_at < $1""",
                one_hour_ago
            )
        finally:
            await conn.close()

        for order in orders:
            try:
                name = order['first_name'] or "رفیق"
                message_text = (
                    f"سلام {name} جان! 👋😊\n\n"
                    f"دیدم سفارشت هنوز منتظر پرداخته. گفتم یه سر بزنم ببینم اوضاع چطوره! 🌟\n\n"
                    f"🆔 کد سفارش: `{order['order_code']}`\n"
                    f"💰 مبلغ: {order['total_price']:,} تومان\n"
                    f"⏳ وضعیت: در انتظار پرداخت\n\n"
                    f"اگه سوالی داری یا مشکلی پیش اومده، من اینجام کمکت کنم! 💬\n"
                    f"فقط یادت باشه که سفارشت رزرو مونده و هر لحظه ممکنه تموم بشه. 😉\n\n"
                    f"📞 یا اگه راحت‌تری، با پشتیبانی تماس بگیر:\n"
                    f"`{SUPPORT_PHONE}`"
                )

                await bot.send_message(
                    chat_id=order['user_id'],
                    text=message_text,
                    parse_mode="Markdown"
                )
                print(f"✅ یادآوری برای سفارش {order['order_code']} ارسال شد.")

            except Exception as e:
                print(f"❌ خطا در ارسال یادآوری برای سفارش {order['order_code']}: {e}")

    except Exception as e:
        print(f"❌ خطا در چک کردن سفارشات: {e}")

# ==========================================
# ۹. AI (آخرین هندلر - Fallback)
# ==========================================
@dp.message(F.text)
async def handle_all_messages(message: types.Message):
    response_text = await get_ai_response_async(message.text)
    await message.answer(response_text)


# ==========================================
# ۱۰. اجرای اصلی (Webhook)
# ==========================================
async def main():
    print(">>> ربات حرفه‌ای هکتور آنلاین شاپ با موفقیت روشن شد و آماده‌ی پاسخگویی است...")

    await init_db()
    print(">>> دیتابیس راه‌اندازی شد.")

    # راه‌اندازی زمان‌بند یادآوری پرداخت (هر ۱ ساعت)
scheduler.add_job(check_pending_orders, 'interval', hours=1)
scheduler.start()
print(">>> زمان‌بند یادآوری پرداخت فعال شد.")

    RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
    PORT = int(os.getenv("PORT", 10000))
    WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}"

    await bot.set_webhook(url=f"{RENDER_URL}{WEBHOOK_PATH}")
    print(f">>> Webhook تنظیم شد: {RENDER_URL}{WEBHOOK_PATH}")

    app = web.Application()

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    async def health_check(request):
        return web.Response(text="Hector Bot is alive!")

    app.router.add_get("/health", health_check)

    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    print(f">>> سرور روی پورت {PORT} بالا آمد. ربات آماده است!")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())