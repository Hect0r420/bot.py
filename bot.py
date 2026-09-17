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
    update_user_info, get_user_info, get_connection,
    add_coupon, get_coupon, use_coupon, get_all_coupons, delete_coupon,
    add_to_cart, get_cart, clear_cart, remove_from_cart,
    create_birthday_coupon, get_user_orders, cancel_order, update_order_status,
    get_all_users
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
# ۲۲. تابع دریافت پاسخ از AI (با مدیریت خطا)
# ۲۲. تابع دریافت پاسخ از AI (با دیباگ)
# ۲۲. تابع دریافت پاسخ از AI (Groq + Gemini Fallback)
# ==========================================
from groq import Groq

# کلید Groq از محیط خونده میشه
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# لیست مدل‌ها به ترتیب اولویت
AI_MODELS = [
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    {"provider": "gemini", "model": "gemini-2.0-flash"},
    {"provider": "gemini", "model": "gemini-2.0-flash-lite"},
    {"provider": "gemini", "model": "gemini-1.5-flash"},
    {"provider": "gemini", "model": "gemini-3.6-flash"},  # 🟢 آخرین راه‌حل
]


async def get_ai_response_async(user_message: str) -> str:
    """گرفتن پاسخ از AI با سیستم Fallback (Groq → Gemini)"""
    last_error = None

    # ۱. گرفتن لیست محصولات از دیتابیس
    try:
        conn = await get_connection()
        try:
            products = await conn.fetch(
                "SELECT name, price, stock, category FROM products WHERE stock > 0 ORDER BY product_id"
            )
        finally:
            await conn.close()

        if products:
            products_text = "\n\n📦 **لیست محصولات موجود:**\n"
            for p in products:
                products_text += f"- {p['name']} | قیمت: {p['price']:,} تومان | موجودی: {p['stock']} عدد\n"
        else:
            products_text = "\n\n⚠️ هیچ محصولی موجود نیست.\n"

        full_message = f"{user_message}\n{products_text}"

    except Exception as e:
        print(f"❌ خطا در دریافت محصولات: {e}")
        full_message = user_message

    # ۲. امتحان کردن مدل‌ها به ترتیب
    loop = asyncio.get_running_loop()

    for model_info in AI_MODELS:
        provider = model_info["provider"]
        model_name = model_info["model"]

        try:
            print(f"🔍 تلاش با {provider} - {model_name}")

            if provider == "groq":
                if not groq_client:
                    print("⚠️ Groq API Key تنظیم نشده، رد میشه.")
                    continue

                response = await loop.run_in_executor(
                    None, lambda: groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": SYSTEM_INSTRUCTION},
                            {"role": "user", "content": full_message},
                        ],
                        temperature=0.7,
                        max_tokens=1024,
                    )
                )
                print(f"✅ پاسخ از Groq ({model_name}) دریافت شد.")
                return response.choices[0].message.content

            elif provider == "gemini":
                response = await loop.run_in_executor(
                    None, lambda: ai_client.models.generate_content(
                        model=model_name,
                        contents=full_message,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION
                        ),
                    )
                )
                print(f"✅ پاسخ از Gemini ({model_name}) دریافت شد.")
                return response.text

        except Exception as e:
            error_str = str(e)
            print(f"❌ {provider} ({model_name}) خطا داد: {error_str}")
            last_error = error_str
            continue  # برو سراغ مدل بعدی

    # ۳. اگه همه‌ی مدل‌ها خطا دادن
    print(f"❌ همه‌ی مدل‌ها خطا دادن. آخرین خطا: {last_error}")
    return (
        "🙏 **متاسفانه در حال حاضر ظرفیت پاسخگویی هوش مصنوعی تکمیل شده است.**\n\n"
        "⏳ لطفاً چند دقیقه دیگه دوباره تلاش کنید.\n\n"
        f"📞 یا با پشتیبانی تماس بگیرید: `{SUPPORT_PHONE}`"
    )


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
            InlineKeyboardButton(text="📋 سفارشات من", callback_data="my_orders_btn"),
            InlineKeyboardButton(text="📞 تماس با ما", callback_data="contact_us"),
        ],
        [
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
        f"📱 شماره تماس: `{SUPPORT_PHONE}`\n\n"
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
# ۵. (مشاهده محصولات دکمه‌ی سبد)
# ۵. مشاهده همه محصولات (بدون دسته‌بندی)
# ==========================================
@dp.callback_query(F.data == "products")
async def handle_products(callback: types.CallbackQuery):
    conn = await get_connection()
    try:
        categories = await conn.fetch(
            """SELECT DISTINCT category FROM products 
               WHERE stock > 0 AND category IS NOT NULL AND category != ''
               ORDER BY category"""
        )
    finally:
        await conn.close()

    if not categories:
        await callback.message.answer(
            "🛒 **محصولات هکتور آنلاین شاپ**\n\n"
            "😔 در حال حاضر هیچ محصولی موجود نیست.\n\n"
            "📞 برای اطلاع از موجودی، با پشتیبانی تماس بگیرید."
        )
        await callback.answer()
        return

    buttons = []
    for row in categories:
        cat = row['category']
        buttons.append([InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"cat_{cat}")])

    buttons.append([InlineKeyboardButton(text="🛍️ مشاهده همه محصولات", callback_data="all_products")])
    buttons.append([InlineKeyboardButton(text="🛒 مشاهده سبد خرید", callback_data="view_cart")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(
        "📂 **دسته‌بندی محصولات**\n\n"
        "لطفاً یکی از دسته‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    await callback.answer()
# ==========================================
# ۵.۱. مشاهده همه محصولات (با عکس)
# ==========================================
@dp.callback_query(F.data == "all_products")
async def handle_all_products(callback: types.CallbackQuery):
    conn = await get_connection()
    try:
        products = await conn.fetch("SELECT * FROM products WHERE stock > 0 ORDER BY product_id")
    finally:
        await conn.close()

    if not products:
        await callback.message.answer("😔 در حال حاضر هیچ محصولی موجود نیست.")
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
                [InlineKeyboardButton(text="➕ افزودن به سبد", callback_data=f"addcart_{p['product_id']}")]
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

    await callback.message.answer(
        "🛒 برای دیدن سبد خریدت، روی دکمه‌ی زیر بزن:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 مشاهده سبد خرید", callback_data="view_cart")]
            ]
        )
    )

    await callback.answer()
# ==========================================
# ۱۸. مدیریت سبد خرید
# ==========================================

# شروع افزودن به سبد
@dp.callback_query(F.data.startswith("addcart_"))
async def handle_add_to_cart(callback: types.CallbackQuery):
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

    # ذخیره در pending_orders برای گرفتن تعداد
    await save_pending_order(callback.from_user.id, product_id)

    await callback.message.answer(
        f"🛒 **افزودن به سبد: {product['name']}**\n\n"
        f"💰 قیمت واحد: {product['price']:,} تومان\n"
        f"📦 موجودی: {product['stock']} عدد\n\n"
        f"لطفاً **تعداد** مورد نظرت رو بنویس و بفرست (فقط عدد):",
        parse_mode="Markdown"
    )
    await callback.answer()


# هندلر تعداد برای سبد (جدا از سفارش معمولی)
@dp.message(F.text.regexp(r"^\d+$"))
async def handle_cart_quantity(message: types.Message):
    user_id = message.from_user.id
    pending = await get_pending_order(user_id)
    if not pending:
        return

    # چک کن که کاربر توی حالت "افزودن به سبد" هست یا "ثبت سفارش"
    # اینجا فرض می‌کنیم هر کاربری که pending داره، داره به سبد اضافه می‌کنه
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

    # اضافه کردن به سبد
    await add_to_cart(user_id, pending['product_id'], quantity)
    await delete_pending_order(user_id)

    await message.answer(
        f"✅ **{product['name']}** به سبد خریدت اضافه شد!\n\n"
        f"🔢 تعداد: {quantity}\n\n"
        f"🛒 برای دیدن سبد و ثبت نهایی، روی دکمه‌ی زیر بزن:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 مشاهده سبد خرید", callback_data="view_cart")],
                [InlineKeyboardButton(text="🛍️ ادامه خرید", callback_data="products")],
            ]
        )
    )


# مشاهده سبد خرید
@dp.callback_query(F.data == "view_cart")
async def handle_view_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cart = await get_cart(user_id)

    if not cart:
        await callback.message.answer(
            "🛒 سبد خریدت خالیه!\n\n"
            "برای خرید، روی دکمه‌ی «🛒 مشاهده محصولات» بزن.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 مشاهده محصولات", callback_data="products")]
                ]
            )
        )
        await callback.answer()
        return

    text = "🛒 **سبد خرید شما**\n\n"
    total = 0
    for item in cart:
        item_total = item['price'] * item['quantity']
        total += item_total
        text += (
            f"🔹 **{item['name']}**\n"
            f"🔢 تعداد: {item['quantity']}\n"
            f"💰 قیمت: {item_total:,} تومان\n"
            f"─────────────\n"
        )

    text += f"\n💵 **مبلغ کل: {total:,} تومان**"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ ثبت نهایی سفارش", callback_data="checkout")],
            [InlineKeyboardButton(text="🛍️ ادامه خرید", callback_data="products")],
            [InlineKeyboardButton(text="🗑️ خالی کردن سبد", callback_data="clear_cart")],
        ]
    )

    await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


# خالی کردن سبد
@dp.callback_query(F.data == "clear_cart")
async def handle_clear_cart(callback: types.CallbackQuery):
    await clear_cart(callback.from_user.id)
    await callback.message.answer("🗑️ سبد خریدت خالی شد!")
    await callback.answer()


# ثبت نهایی سفارش (checkout)
@dp.callback_query(F.data == "checkout")
async def handle_checkout(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cart = await get_cart(user_id)

    if not cart:
        await callback.message.answer("🛒 سبد خریدت خالیه!")
        await callback.answer()
        return

    # محاسبه‌ی مبلغ کل
    total = sum(item['price'] * item['quantity'] for item in cart)

    await callback.message.answer(
        f"🛒 **سبد خرید شما آماده‌ی ثبت نهاییه!**\n\n"
        f"💰 مبلغ کل: {total:,} تومان\n\n"
        f"🎟️ **کد تخفیف داری؟**\n\n"
        f"اگه داری، کد رو بنویس و بفرست (مثلاً: `WELCOME10`).\n"
        f"اگه نداری، بنویس: **ندارم**",
        parse_mode="Markdown"
    )
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


# ==========================================
# ۶. دریافت تعداد سفارش و پرسیدن کد تخفیف
# ==========================================
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

    # ذخیره‌ی تعداد توی دیتابیس (برای مرحله‌ی بعد)
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE pending_orders SET quantity = $1 WHERE user_id = $2",
            quantity, user_id
        )
    finally:
        await conn.close()

    await message.answer(
        f"✅ تعداد ثبت شد: **{quantity}** عدد\n\n"
        f"🎟️ **کد تخفیف داری؟**\n\n"
        f"اگه داری، کد رو بنویس و بفرست (مثلاً: `WELCOME10`).\n"
        f"اگه نداری، بنویس: **ندارم**",
        parse_mode="Markdown"
    )

# ==========================================
# ۱۷. دریافت کد تخفیف (بعد از تعداد)
# ==========================================
@dp.message(F.text.func(lambda t: t.strip().upper().startswith("BDAY") or t.strip() == "ندارم"))
async def handle_coupon_input(message: types.Message):
    user_id = message.from_user.id

    # فقط اگه کاربر سفارش نیمه‌کاره داره
    pending = await get_pending_order(user_id)
    if not pending or not pending['quantity']:
        return

    text = message.text.strip()
    coupon_code = None
    discount_percent = 0

    # اگه کاربر نوشت "ندارم"
    if text == "ندارم":
        discount_percent = 0
    else:
        # چک کردن کد تخفیف
        coupon = await get_coupon(text.upper())
        if not coupon:
            await message.answer(
                "❌ کد تخفیف نامعتبره!\n\n"
                "اگه کد دیگه‌ای داری، دوباره بفرست. یا بنویس **ندارم** تا سفارشت بدون تخفیف ثبت بشه.",
                parse_mode="Markdown"
            )
            return

        # چک کردن محدودیت استفاده
        if coupon['max_uses'] > 0 and coupon['used_count'] >= coupon['max_uses']:
            await message.answer(
                "❌ این کد تخفیف به حد مجاز استفاده رسیده!\n\n"
                "بنویس **ندارم** تا سفارشت بدون تخفیف ثبت بشه.",
                parse_mode="Markdown"
            )
            return

        coupon_code = coupon['code']
        discount_percent = coupon['discount_percent']

    # گرفتن اطلاعات محصول و تعداد
    conn = await get_connection()
    try:
        product = await conn.fetchrow(
            "SELECT * FROM products WHERE product_id = $1", pending['product_id']
        )
    finally:
        await conn.close()

    if not product:
        await message.answer("❌ محصول مورد نظر پیدا نشد.")
        return

    quantity = pending['quantity']
    total_price = product['price'] * quantity

    # محاسبه‌ی تخفیف
    discount_amount = int(total_price * discount_percent / 100)
    final_price = total_price - discount_amount

    # ساخت کد سفارش
    order_code = "ORD-" + "".join(random.choices(string.digits, k=5))

    # ثبت سفارش در دیتابیس
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO orders (order_code, user_id, product_id, quantity, total_price, status)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            order_code, user_id, product['product_id'], quantity, final_price, "در انتظار پرداخت"
        )
        await conn.execute(
            "UPDATE products SET stock = stock - $1 WHERE product_id = $2",
            quantity, product['product_id']
        )

        # اگه کد تخفیف استفاده شد، تعداد استفادش رو زیاد کن
        if coupon_code:
            await conn.execute(
                "UPDATE coupons SET used_count = used_count + 1 WHERE code = $1",
                coupon_code
            )
    finally:
        await conn.close()

    # پاک کردن سفارش نیمه‌کاره
    await delete_pending_order(user_id)

    # ساخت متن رسید
    if discount_percent > 0:
        discount_text = (
            f"\n🎟️ کد تخفیف: `{coupon_code}`\n"
            f"💸 تخفیف: {discount_percent}% ({discount_amount:,} تومان)\n"
            f"💰 **مبلغ قابل پرداخت: {final_price:,} تومان**\n"
        )
    else:
        discount_text = f"\n💰 **مبلغ قابل پرداخت: {final_price:,} تومان**\n"

    await message.answer(
        f"✅ **سفارش شما ثبت شد!**\n\n"
        f"🆔 کد سفارش: `{order_code}`\n"
        f"📦 محصول: {product['name']}\n"
        f"🔢 تعداد: {quantity}\n"
        f"💵 مبلغ اصلی: {total_price:,} تومان\n"
        f"{discount_text}\n"
        f"💳 **برای تکمیل سفارش، مبلغ {final_price:,} تومان رو به شماره کارت زیر واریز کن:**\n\n"
        f"`{CARD_NUMBER}`\n\n"
        f"📸 بعد از پرداخت، **عکس رسید** رو همین‌جا بفرست.\n\n"
        f"⏳ وضعیت: **در انتظار پرداخت**",
        parse_mode="Markdown"
    )

    # پرسیدن شماره تماس (اگه قبلاً نداده)
    user_info = await get_user_info(user_id)
    if user_info and not user_info['phone_number']:
        await message.answer(
            "📞 **لطفاً شماره تماس خودت رو وارد کن:**\n\n"
            "(مثال: `09123456789`)"
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
    "👑 **پنل گرافیکی:**\n"
    "• `/admin_panel` → باز کردن پنل مدیریت با دکمه‌های شیشه‌ای\n\n"
    "📦 **مدیریت محصولات:**\n"
    "• `/add_product` → افزودن محصول جدید\n"
    "• `/stock [کد محصول]` → مشاهده اطلاعات یک محصول\n"
    "• `/add_stock [کد محصول] [تعداد]` → افزایش موجودی محصول\n"
    "• `/out_of_stock [نام یا کد]` → صفر کردن موجودی محصول\n"
    "• `/delete_product [کد محصول]` → حذف کامل محصول\n\n"
    "🛒 **مدیریت سفارشات:**\n"
    "• `/orders` → مشاهده‌ی ۲۰ سفارش آخر\n"
    "• `/manage_order [کد سفارش]` → مدیریت کامل وضعیت سفارش\n"
    "• `/confirm_order [کد سفارش]` → تایید سریع پرداخت\n\n"
    "👥 **مدیریت کاربران:**\n"
    "• `/users` → مشاهده‌ی لیست کاربران\n\n"
    "🎟️ **مدیریت کدهای تخفیف:**\n"
    "• `/add_coupon [کد] [درصد] [حداکثر استفاده]` → افزودن کد تخفیف\n"
    "• `/coupons` → مشاهده‌ی لیست کدهای تخفیف\n"
    "• `/delete_coupon [کد]` → حذف کد تخفیف\n\n"
    "📢 **ارسال پیام همگانی:**\n"
    "• `/broadcast` → ارسال پیام به همه‌ی کاربران\n\n"
    "🎂 **تخفیف تولد:**\n"
    "• (به صورت خودکار هر روز ساعت ۹ صبح اجرا میشه)\n\n"
    "📂 **دسته‌بندی محصولات:**\n"
    "• (مشتری‌ها می‌تونن از دکمه‌ی «📂 دسته‌بندی محصولات» استفاده کنن)\n\n"
    "🔍 **جستجوی محصول:**\n"
    "• (مشتری‌ها با نوشتن «جستجو [اسم محصول]» می‌تونن محصول مورد نظرشون رو پیدا کنن)\n\n"
    "📋 **سفارشات مشتری:**\n"
    "• `/my_orders` → مشتری‌ها می‌تونن سفارشات فعالشون رو ببینن و لغو کنن\n\n"
    "📊 **آمار:**\n"
    "• `/stats` → مشاهده‌ی آمار کلی ربات\n\n"
    "💡 **نکته:** برای دیدن جزئیات هر دستور، فقط خود دستور رو بدون آرگومان بفرست تا راهنماش بیاد."
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
# ۱۵. گزارش فروش روزانه (اتوماتیک)
# ==========================================
async def send_daily_report():
    """ارسال گزارش فروش روزانه به ادمین"""
    try:
        conn = await get_connection()
        try:
            # بازه‌ی امروز (از ساعت ۰۰:۰۰ امروز)
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            # تعداد و مجموع فروش امروز
            orders_today = await conn.fetch(
                """SELECT o.*, p.name as product_name, u.first_name
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.product_id
                   LEFT JOIN users u ON o.user_id = u.user_id
                   WHERE o.created_at >= $1
                   ORDER BY o.created_at DESC""",
                today_start
            )

            # کاربران جدید امروز
            new_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE joined_at >= $1",
                today_start
            )
        finally:
            await conn.close()

        if not orders_today:
            report = (
                "📊 **گزارش فروش روزانه هکتور آنلاین شاپ**\n\n"
                f"📅 تاریخ: {today_start.strftime('%Y-%m-%d')}\n\n"
                "😔 امروز هیچ سفارشی ثبت نشده.\n\n"
                f"👥 کاربران جدید: {new_users} نفر\n\n"
                "💪 فردا روز بهتری باشه!"
            )
            await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="Markdown")
            return

        # محاسبه‌ی مجموع فروش
        total_sales = sum(o['total_price'] for o in orders_today if o['status'] != "لغو شده")
        total_orders = len(orders_today)

        report = (
            "📊 **گزارش فروش روزانه هکتور آنلاین شاپ**\n\n"
            f"📅 تاریخ: {today_start.strftime('%Y-%m-%d')}\n\n"
            f"🛒 تعداد سفارشات: **{total_orders}**\n"
            f"💰 مجموع فروش: **{total_sales:,} تومان**\n"
            f"👥 کاربران جدید: **{new_users}** نفر\n\n"
            "📋 **لیست سفارشات امروز:**\n"
            "─────────────\n"
        )

        for o in orders_today:
            report += (
                f"🆔 `{o['order_code']}`\n"
                f"👤 {o['first_name'] or 'نامشخص'}\n"
                f"📦 {o['product_name'] or 'نامشخص'}\n"
                f"🔢 تعداد: {o['quantity']} | 💰 {o['total_price']:,} تومان\n"
                f"📊 {o['status']}\n"
                f"─────────────\n"
            )

        report += "\n💡 **نکته:** این گزارش هر شب ساعت ۱۲ به صورت خودکار ارسال میشه."

        # اگه متن خیلی طولانی شد، تیکه‌تیکه بفرست
        if len(report) > 4000:
            for i in range(0, len(report), 4000):
                await bot.send_message(chat_id=ADMIN_ID, text=report[i:i+4000], parse_mode="Markdown")
        else:
            await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="Markdown")

        print(f"✅ گزارش فروش روزانه ارسال شد. (تعداد سفارشات: {total_orders})")

    except Exception as e:
        print(f"❌ خطا در ارسال گزارش روزانه: {e}")

# ==========================================
# ۱۶. مدیریت کد تخفیف (ادمین)
# ==========================================
@dp.message(Command("add_coupon"))
async def cmd_add_coupon(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n"
            "**فرمت:**\n"
            "`/add_coupon کد درصد [حداکثر استفاده]`\n\n"
            "**مثال:**\n"
            "`/add_coupon WELCOME10 10`\n"
            "`/add_coupon OFF20 20 50`\n\n"
            "💡 اگه حداکثر استفاده رو ننویسی، یعنی نامحدود.",
            parse_mode="Markdown"
        )
        return

    code = parts[1].upper()
    try:
        percent = int(parts[2])
        max_uses = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        await message.answer("❌ درصد و حداکثر استفاده باید عدد باشن!")
        return

    if percent <= 0 or percent > 100:
        await message.answer("❌ درصد تخفیف باید بین ۱ تا ۱۰۰ باشه!")
        return

    await add_coupon(code, percent, max_uses)

    await message.answer(
        f"✅ **کد تخفیف با موفقیت اضافه شد!**\n\n"
        f"🎟️ کد: `{code}`\n"
        f"💰 درصد تخفیف: {percent}%\n"
        f"🔢 حداکثر استفاده: {'نامحدود' if max_uses == 0 else max_uses}\n\n"
        f"💡 این کد رو می‌تونی به مشتری‌ها بدی.",
        parse_mode="Markdown"
    )


@dp.message(Command("coupons"))
async def cmd_coupons(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    coupons = await get_all_coupons()

    if not coupons:
        await message.answer("🎟️ هیچ کد تخفیفی ثبت نشده.")
        return

    text = f"🎟️ **لیست کدهای تخفیف** (تعداد: {len(coupons)})\n\n"
    for c in coupons:
        status = "✅ فعال" if c['is_active'] else "❌ غیرفعال"
        max_uses = "نامحدود" if c['max_uses'] == 0 else c['max_uses']
        text += (
            f"🎫 کد: `{c['code']}`\n"
            f"💰 تخفیف: {c['discount_percent']}%\n"
            f"🔢 استفاده: {c['used_count']}/{max_uses}\n"
            f"📊 وضعیت: {status}\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")


@dp.message(Command("delete_coupon"))
async def cmd_delete_coupon(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n**مثال:**\n`/delete_coupon WELCOME10`",
            parse_mode="Markdown"
        )
        return

    code = parts[1].upper()
    await delete_coupon(code)

    await message.answer(
        f"✅ کد تخفیف `{code}` حذف شد.",
        parse_mode="Markdown"
    )

# ==========================================
# ۱۹. افزایش موجودی محصول (ادمین)
# ==========================================
@dp.message(Command("add_stock"))
async def cmd_add_stock(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n"
            "**فرمت:**\n"
            "`/add_stock [کد محصول] [تعداد]`\n\n"
            "**مثال:**\n"
            "`/add_stock 1 10`\n"
            "`/add_stock 3 25`",
            parse_mode="Markdown"
        )
        return

    try:
        product_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("❌ کد محصول و تعداد باید عدد باشن!")
        return

    if amount <= 0:
        await message.answer("❌ تعداد باید عددی بزرگتر از صفر باشه!")
        return

    conn = await get_connection()
    try:
        # چک کردن وجود محصول
        product = await conn.fetchrow("SELECT * FROM products WHERE product_id = $1", product_id)
        if not product:
            await message.answer(f"❌ محصولی با آیدی `{product_id}` پیدا نشد.", parse_mode="Markdown")
            return

        # افزایش موجودی
        await conn.execute(
            "UPDATE products SET stock = stock + $1 WHERE product_id = $2",
            amount, product_id
        )

        # گرفتن موجودی جدید
        new_stock = product['stock'] + amount
        print(f"✅ موجودی محصول '{product['name']}' به {new_stock} افزایش یافت.")
    finally:
        await conn.close()

    await message.answer(
        f"✅ **موجودی محصول افزایش یافت!**\n\n"
        f"🆔 کد محصول: `{product_id}`\n"
        f"📦 نام: {product['name']}\n"
        f"➕ افزایش: {amount} عدد\n"
        f"📊 موجودی قبلی: {product['stock']} عدد\n"
        f"📊 **موجودی جدید: {new_stock} عدد**",
        parse_mode="Markdown"
    )
# ==========================================
# ۲۵. مدیریت سفارش توسط ادمین
# ==========================================
@dp.message(Command("manage_order"))
async def cmd_manage_order(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ فرمت اشتباهه!\n\n"
            "**فرمت:**\n"
            "`/manage_order [کد سفارش]`\n\n"
            "**مثال:**\n"
            "`/manage_order ORD-12345`",
            parse_mode="Markdown"
        )
        return

    order_code = parts[1].upper()

    conn = await get_connection()
    try:
        order = await conn.fetchrow(
            """SELECT o.*, p.name as product_name, u.first_name, u.phone_number
               FROM orders o
               LEFT JOIN products p ON o.product_id = p.product_id
               LEFT JOIN users u ON o.user_id = u.user_id
               WHERE o.order_code = $1""",
            order_code
        )
    finally:
        await conn.close()

    if not order:
        await message.answer(f"❌ سفارشی با کد `{order_code}` پیدا نشد.", parse_mode="Markdown")
        return

    caption = (
        f"📦 **مدیریت سفارش**\n\n"
        f"🆔 کد سفارش: `{order['order_code']}`\n"
        f"👤 مشتری: {order['first_name'] or 'نامشخص'}\n"
        f"📞 تماس: `{order['phone_number'] or 'ندارد'}`\n"
        f"📦 محصول: {order['product_name'] or 'نامشخص'}\n"
        f"🔢 تعداد: {order['quantity']}\n"
        f"💰 مبلغ: {order['total_price']:,} تومان\n"
        f"📊 وضعیت فعلی: **{order['status']}**\n\n"
        f"👇 لطفاً وضعیت جدید رو انتخاب کن:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 در حال پردازش", callback_data=f"setstatus_{order_code}_در حال پردازش")],
            [InlineKeyboardButton(text="🚚 ارسال شده", callback_data=f"setstatus_{order_code}_ارسال شده")],
            [InlineKeyboardButton(text="✅ تحویل داده شده", callback_data=f"setstatus_{order_code}_تحویل داده شده")],
            [InlineKeyboardButton(text="❌ لغو سفارش", callback_data=f"setstatus_{order_code}_لغو شده")],
        ]
    )

    await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("setstatus_"))
async def handle_set_status(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ شما اجازه‌ی این کار را ندارید.", show_alert=True)
        return

    parts = callback.data.split("_", 2)
    order_code = parts[1]
    new_status = parts[2]

    conn = await get_connection()
    try:
        order = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_code = $1", order_code
        )
    finally:
        await conn.close()

    if not order:
        await callback.answer("❌ سفارش پیدا نشد.", show_alert=True)
        return

    # اگه وضعیت جدید «لغو شده» بود، موجودی رو برگردون
    if new_status == "لغو شده" and order['status'] != "لغو شده":
        await cancel_order(order_code)
    else:
        await update_order_status(order_code, new_status)

    await callback.message.answer(
        f"✅ **وضعیت سفارش تغییر یافت!**\n\n"
        f"🆔 کد سفارش: `{order_code}`\n"
        f"📊 وضعیت جدید: **{new_status}**",
        parse_mode="Markdown"
    )
    await callback.answer(f"✅ وضعیت به «{new_status}» تغییر یافت.")

# ==========================================
# ۲۶. پنل ادمین با دکمه‌های شیشه‌ای
# ==========================================
@dp.message(Command("admin_panel"))
async def cmd_admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی دسترسی به این پنل را ندارید.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 مدیریت محصولات", callback_data="admin_products"),
            ],
            [
                InlineKeyboardButton(text="🛒 مدیریت سفارشات", callback_data="admin_orders"),
            ],
            [
                InlineKeyboardButton(text="👥 مدیریت کاربران", callback_data="admin_users"),
            ],
            [
                InlineKeyboardButton(text="🎟️ مدیریت کدهای تخفیف", callback_data="admin_coupons"),
            ],
            [
                InlineKeyboardButton(text="📊 آمار ربات", callback_data="admin_stats"),
            ],
            [
                InlineKeyboardButton(text="🔄 بستن پنل", callback_data="admin_close"),
            ],
        ]
    )

    await message.answer(
        "👑 **پنل مدیریت هکتور آنلاین شاپ**\n\n"
        "خوش آمدی مدیر عزیز! 😊\n"
        "لطفاً یکی از بخش‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# ---------- زیرمنوی محصولات ----------
@dp.callback_query(F.data == "admin_products")
async def admin_products_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ افزودن محصول", callback_data="admin_add_product_help")],
            [InlineKeyboardButton(text="📋 لیست محصولات", callback_data="admin_list_products")],
            [InlineKeyboardButton(text="🔍 اطلاعات یک محصول", callback_data="admin_stock_help")],
            [InlineKeyboardButton(text="➕ افزایش موجودی", callback_data="admin_add_stock_help")],
            [InlineKeyboardButton(text="❌ حذف محصول", callback_data="admin_delete_product_help")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_back")],
        ]
    )

    await callback.message.edit_text(
        "📦 **مدیریت محصولات**\n\n"
        "لطفاً یکی از گزینه‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- راهنمای افزودن محصول ----------
@dp.callback_query(F.data == "admin_add_product_help")
async def admin_add_product_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "🛒 **افزودن محصول جدید**\n\n"
        "لطفاً اطلاعات محصول رو به این ترتیب و با **کاما (`,`)** از هم جدا کن و بفرست:\n\n"
        "`نام محصول, قیمت, موجودی, دسته‌بندی, لینک عکس`\n\n"
        "**مثال:**\n"
        "`هدفون بی‌سیم, 850000, 10, لوازم جانبی, https://example.com/image.jpg`\n\n"
        "⚠️ اگه عکس نداری، جای لینک عکس بنویس: `-`",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- لیست محصولات ----------
@dp.callback_query(F.data == "admin_list_products")
async def admin_list_products(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    conn = await get_connection()
    try:
        products = await conn.fetch("SELECT * FROM products ORDER BY product_id")
    finally:
        await conn.close()

    if not products:
        await callback.message.answer("📦 هیچ محصولی ثبت نشده.")
        await callback.answer()
        return

    text = f"📦 **لیست محصولات** (تعداد: {len(products)})\n\n"
    for p in products:
        text += (
            f"🆔 `{p['product_id']}` | **{p['name']}**\n"
            f"💰 {p['price']:,} تومان | 📦 موجودی: {p['stock']}\n"
            f"🏷️ {p['category'] or 'متفرقه'}\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await callback.message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ---------- راهنمای استعلام موجودی ----------
@dp.callback_query(F.data == "admin_stock_help")
async def admin_stock_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "🔍 **استعلام موجودی**\n\n"
        "دستور رو با کد محصول بفرست:\n\n"
        "**مثال:**\n"
        "`/stock 1`",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- راهنمای افزایش موجودی ----------
@dp.callback_query(F.data == "admin_add_stock_help")
async def admin_add_stock_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "➕ **افزایش موجودی**\n\n"
        "دستور رو با کد محصول و تعداد بفرست:\n\n"
        "**مثال:**\n"
        "`/add_stock 1 10`",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- راهنمای حذف محصول ----------
@dp.callback_query(F.data == "admin_delete_product_help")
async def admin_delete_product_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "❌ **حذف محصول**\n\n"
        "دستور رو با کد محصول بفرست:\n\n"
        "**مثال:**\n"
        "`/delete_product 1`",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- زیرمنوی سفارشات ----------
@dp.callback_query(F.data == "admin_orders")
async def admin_orders_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 آخرین سفارشات", callback_data="admin_list_orders")],
            [InlineKeyboardButton(text="🔧 مدیریت سفارش", callback_data="admin_manage_order_help")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_back")],
        ]
    )

    await callback.message.edit_text(
        "🛒 **مدیریت سفارشات**\n\n"
        "لطفاً یکی از گزینه‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- لیست سفارشات ----------
@dp.callback_query(F.data == "admin_list_orders")
async def admin_list_orders(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    conn = await get_connection()
    try:
        orders = await conn.fetch(
            """SELECT o.*, u.first_name, p.name as product_name
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.user_id
               LEFT JOIN products p ON o.product_id = p.product_id
               ORDER BY o.created_at DESC LIMIT 20"""
        )
    finally:
        await conn.close()

    if not orders:
        await callback.message.answer("📦 هیچ سفارشی ثبت نشده.")
        await callback.answer()
        return

    text = f"📦 **۲۰ سفارش آخر** (تعداد: {len(orders)})\n\n"
    for o in orders:
        text += (
            f"🆔 `{o['order_code']}`\n"
            f"👤 {o['first_name'] or 'نامشخص'}\n"
            f"📦 {o['product_name'] or 'نامشخص'}\n"
            f"💰 {o['total_price']:,} تومان | 📊 {o['status']}\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await callback.message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ---------- راهنمای مدیریت سفارش ----------
@dp.callback_query(F.data == "admin_manage_order_help")
async def admin_manage_order_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "🔧 **مدیریت سفارش**\n\n"
        "دستور رو با کد سفارش بفرست:\n\n"
        "**مثال:**\n"
        "`/manage_order ORD-12345`",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- زیرمنوی کاربران ----------
@dp.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    conn = await get_connection()
    try:
        users = await conn.fetch("SELECT * FROM users ORDER BY joined_at DESC")
    finally:
        await conn.close()

    if not users:
        await callback.message.answer("👥 هیچ کاربری ثبت نشده.")
        await callback.answer()
        return

    text = f"👥 **لیست کاربران** (تعداد: {len(users)})\n\n"
    for u in users[:20]:
        phone = u['phone_number'] or "❌"
        text += (
            f"🔹 **{u['first_name']}**\n"
            f"🆔 `{u['user_id']}`\n"
            f"📞 `{phone}`\n"
            f"─────────────\n"
        )

    if len(users) > 20:
        text += f"\n... و {len(users) - 20} کاربر دیگه."

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await callback.message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ---------- زیرمنوی کدهای تخفیف ----------
@dp.callback_query(F.data == "admin_coupons")
async def admin_coupons_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 لیست کدها", callback_data="admin_list_coupons")],
            [InlineKeyboardButton(text="➕ افزودن کد", callback_data="admin_add_coupon_help")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_back")],
        ]
    )

    await callback.message.edit_text(
        "🎟️ **مدیریت کدهای تخفیف**\n\n"
        "لطفاً یکی از گزینه‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- لیست کدهای تخفیف ----------
@dp.callback_query(F.data == "admin_list_coupons")
async def admin_list_coupons(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    coupons = await get_all_coupons()

    if not coupons:
        await callback.message.answer("🎟️ هیچ کد تخفیفی ثبت نشده.")
        await callback.answer()
        return

    text = f"🎟️ **لیست کدهای تخفیف** (تعداد: {len(coupons)})\n\n"
    for c in coupons:
        status = "✅ فعال" if c['is_active'] else "❌ غیرفعال"
        max_uses = "نامحدود" if c['max_uses'] == 0 else c['max_uses']
        text += (
            f"🎫 کد: `{c['code']}`\n"
            f"💰 تخفیف: {c['discount_percent']}%\n"
            f"🔢 استفاده: {c['used_count']}/{max_uses}\n"
            f"📊 {status}\n"
            f"─────────────\n"
        )

    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await callback.message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ---------- راهنمای افزودن کد تخفیف ----------
@dp.callback_query(F.data == "admin_add_coupon_help")
async def admin_add_coupon_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "➕ **افزودن کد تخفیف**\n\n"
        "دستور رو با فرمت زیر بفرست:\n\n"
        "`/add_coupon کد درصد [حداکثر استفاده]`\n\n"
        "**مثال:**\n"
        "`/add_coupon WELCOME10 10`",
        parse_mode="Markdown"
    )
    await callback.answer()

# ---------- راهنمای ارسال پیام همگانی ----------
@dp.callback_query(F.data == "admin_broadcast_help")
async def admin_broadcast_help(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.answer(
        "📢 **ارسال پیام همگانی**\n\n"
        "برای ارسال پیام به همه‌ی کاربران، دستور زیر رو بزن:\n\n"
        "`/broadcast`\n\n"
        "بعدش پیام مورد نظرت رو بفرست تا به همه ارسال بشه.",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- آمار ربات ----------
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    conn = await get_connection()
    try:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        product_count = await conn.fetchval("SELECT COUNT(*) FROM products")
        order_count = await conn.fetchval("SELECT COUNT(*) FROM orders")
        pending_count = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'در انتظار پرداخت'")
        total_sales = await conn.fetchval(
            "SELECT COALESCE(SUM(total_price), 0) FROM orders WHERE status != 'لغو شده'"
        )
    finally:
        await conn.close()

    await callback.message.answer(
        f"📊 **آمار کلی ربات**\n\n"
        f"👥 تعداد کاربران: `{user_count}`\n"
        f"📦 تعداد محصولات: `{product_count}`\n"
        f"🛒 تعداد سفارشات: `{order_count}`\n"
        f"⏳ سفارشات در انتظار: `{pending_count}`\n"
        f"💰 مجموع فروش: `{total_sales:,}` تومان",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- بازگشت به منوی اصلی ادمین ----------
@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 مدیریت محصولات", callback_data="admin_products")],
            [InlineKeyboardButton(text="🛒 مدیریت سفارشات", callback_data="admin_orders")],
            [InlineKeyboardButton(text="👥 مدیریت کاربران", callback_data="admin_users")],
            [InlineKeyboardButton(text="🎟️ مدیریت کدهای تخفیف", callback_data="admin_coupons")],
            [InlineKeyboardButton(text="📢 ارسال پیام همگانی", callback_data="admin_broadcast_help")],
            [InlineKeyboardButton(text="📊 آمار ربات", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔄 بستن پنل", callback_data="admin_close")],
        ]
    )

    await callback.message.edit_text(
        "👑 **پنل مدیریت هکتور آنلاین شاپ**\n\n"
        "لطفاً یکی از بخش‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------- بستن پنل ----------
@dp.callback_query(F.data == "admin_close")
async def admin_close(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await callback.message.edit_text(
        "✅ پنل مدیریت بسته شد.\n\n"
        "برای باز کردن مجدد، دستور `/admin_panel` رو بزن."
    )
    await callback.answer()

# ==========================================
# ۲۷. ارسال پیام همگانی (Broadcast)
# ==========================================
# دیکشنری برای ذخیره‌ی حالت انتظار
broadcast_waiting = {}


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ شما اجازه‌ی استفاده از این دستور را ندارید.")
        return

    broadcast_waiting[message.from_user.id] = True

    await message.answer(
        "📢 **ارسال پیام همگانی**\n\n"
        "لطفاً پیامی که می‌خوای برای همه‌ی کاربران ارسال بشه رو بنویس و بفرست.\n\n"
        "⚠️ **نکات مهم:**\n"
        "• پیام می‌تونه شامل متن، ایموجی و لینک باشه.\n"
        "• قبل از ارسال، تعداد کاربران بهت نشون داده میشه.\n"
        "• می‌تونی با زدن `/cancel_broadcast` لغو کنی.\n\n"
        "👇 پیام رو بفرست:",
        parse_mode="Markdown"
    )


@dp.message(Command("cancel_broadcast"))
async def cmd_cancel_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    if message.from_user.id in broadcast_waiting:
        del broadcast_waiting[message.from_user.id]

    await message.answer("❌ ارسال پیام همگانی لغو شد.")


@dp.message(F.text)
async def handle_broadcast_message(message: types.Message):
    # فقط اگه ادمین توی حالت انتظار باشه
    if message.from_user.id != ADMIN_ID or message.from_user.id not in broadcast_waiting:
        return

    # پاک کردن حالت انتظار
    del broadcast_waiting[message.from_user.id]

    broadcast_text = message.text

    # گرفتن لیست کاربران
    users = await get_all_users()

    if not users:
        await message.answer("❌ هیچ کاربری ثبت نشده.")
        return

    # پیام تایید
    await message.answer(
        f"📢 **شروع ارسال پیام همگانی...**\n\n"
        f"👥 تعداد کاربران: **{len(users)}**\n"
        f"📝 متن پیام:\n\n{broadcast_text}\n\n"
        f"⏳ در حال ارسال...",
        parse_mode="Markdown"
    )

    # ارسال پیام به همه
    success = 0
    failed = 0

    for user in users:
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text=broadcast_text,
                parse_mode="Markdown"
            )
            success += 1
            # تاخیر کوچیک برای جلوگیری از Rate Limit
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"❌ خطا در ارسال به {user['user_id']}: {e}")
            failed += 1

    # گزارش نهایی
    await message.answer(
        f"✅ **ارسال پیام همگانی تموم شد!**\n\n"
        f"📤 موفق: **{success}** کاربر\n"
        f"❌ ناموفق: **{failed}** کاربر\n"
        f"👥 مجموع: **{len(users)}** کاربر",
        parse_mode="Markdown"
    )

# ==========================================
# ۲۰. تخفیف ویژه تولد
# ==========================================
async def check_birthdays():
    """چک کردن تولد مشتری‌ها و ارسال کد تخفیف"""
    try:
        from datetime import datetime
        today = datetime.now().strftime("%m-%d")  # فقط ماه و روز

        conn = await get_connection()
        try:
            # پیدا کردن کاربرانی که امروز تولدشون هست
            users = await conn.fetch(
                """SELECT * FROM users 
                   WHERE birthday IS NOT NULL 
                   AND TO_CHAR(birthday::date, 'MM-DD') = $1""",
                today
            )
        finally:
            await conn.close()

        if not users:
            print("ℹ️ امروز تولد هیچ مشتری‌ای نیست.")
            return

        print(f"🎂 امروز تولد {len(users)} مشتری است.")

        for user in users:
            try:
                # ساخت کد تخفیف اختصاصی
                birthday_code = f"BDAY{user['user_id'] % 10000}"
                await create_birthday_coupon(user['user_id'], birthday_code, 15)

                # ارسال پیام تبریک
                name = user['first_name'] or "رفیق"
                message_text = (
                    f"🎉🎂 **تولدت مبارک {name} جان!** 🎂🎉\n\n"
                    f"امروز روز خاصیه و ما نمی‌تونیم این روز رو بدون هدیه بگذرونیم! 🎁\n\n"
                    f"به مناسبت تولدت، یه **کد تخفیف ۱۵٪ اختصاصی** برات آماده کردیم:\n\n"
                    f"🎟️ کد تخفیف: `{birthday_code}`\n"
                    f"⏳ اعتبار: فقط **۲۴ ساعت** (فقط برای امروز!)\n"
                    f"💰 قابل استفاده روی همه‌ی محصولات\n\n"
                    f"پس عجله کن و از تخفیف تولدت استفاده کن! 🛍️\n\n"
                    f"از طرف تیم **هکتور آنلاین شاپ** ❤️"
                )

                await bot.send_message(
                    chat_id=user['user_id'],
                    text=message_text,
                    parse_mode="Markdown"
                )
                print(f"✅ پیام تولد برای {name} ({user['user_id']}) ارسال شد.")

            except Exception as e:
                print(f"❌ خطا در ارسال پیام تولد برای {user['user_id']}: {e}")

    except Exception as e:
        print(f"❌ خطا در چک کردن تولدها: {e}")
# ==========================================
# ۲۱. جستجوی محصول
# ==========================================
@dp.message(F.text.startswith("جستجو"))
async def handle_search(message: types.Message):
    # گرفتن متن جستجو
    search_query = message.text.replace("جستجو", "").strip()

    if not search_query:
        await message.answer(
            "🔍 **جستجوی محصول**\n\n"
            "لطفاً بعد از کلمه‌ی «جستجو»، اسم محصول رو بنویس.\n\n"
            "**مثال:**\n"
            "`جستجو تیشرت`",
            parse_mode="Markdown"
        )
        return

    conn = await get_connection()
    try:
        products = await conn.fetch(
            """SELECT * FROM products 
               WHERE stock > 0 
               AND (name ILIKE $1 OR category ILIKE $1)
               ORDER BY product_id""",
            f"%{search_query}%"
        )
    finally:
        await conn.close()

    if not products:
        await message.answer(
            f"🔍 **نتیجه‌ای برای «{search_query}» پیدا نشد!**\n\n"
            f"😔 متاسفانه محصولی با این اسم موجود نیست.\n\n"
            f"💡 می‌تونی از دکمه‌ی «🛒 مشاهده محصولات» استفاده کنی یا با پشتیبانی تماس بگیری.",
            parse_mode="Markdown"
        )
        return

    await message.answer(
        f"🔍 **نتایج جستجو برای «{search_query}»** (تعداد: {len(products)})\n\n"
        f"👇 محصولات پیدا شده:",
        parse_mode="Markdown"
    )

    for p in products:
        caption = (
            f"🔹 **{p['name']}**\n"
            f"💰 قیمت: {p['price']:,} تومان\n"
            f"📦 موجودی: {p['stock']} عدد\n"
            f"🏷️ دسته‌بندی: {p['category'] or 'متفرقه'}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن به سبد", callback_data=f"addcart_{p['product_id']}")]
            ]
        )
        if p['image_url']:
            try:
                await message.answer_photo(
                    photo=p['image_url'],
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                await message.answer(
                    caption + "\n\n⚠️ (عکس در دسترس نیست)",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")

# ==========================================
# ۲۳. دسته‌بندی محصولات
# ==========================================
@dp.callback_query(F.data == "categories")
async def handle_categories(callback: types.CallbackQuery):
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """SELECT DISTINCT category FROM products 
               WHERE stock > 0 AND category IS NOT NULL AND category != ''
               ORDER BY category"""
        )
    finally:
        await conn.close()

    if not rows:
        await callback.message.answer("😔 در حال حاضر هیچ دسته‌بندی موجود نیست.")
        await callback.answer()
        return

    buttons = []
    for row in rows:
        cat = row['category']
        buttons.append([InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"cat_{cat}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(
        "📂 **دسته‌بندی محصولات**\n\n"
        "لطفاً یکی از دسته‌های زیر رو انتخاب کن: 👇",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# ==========================================
# ۲۳. نمایش محصولات یک دسته خاص (با عکس)
# ==========================================
@dp.callback_query(F.data.startswith("cat_"))
async def handle_category_products(callback: types.CallbackQuery):
    category = callback.data.replace("cat_", "")

    conn = await get_connection()
    try:
        products = await conn.fetch(
            """SELECT * FROM products 
               WHERE stock > 0 AND category = $1
               ORDER BY product_id""",
            category
        )
    finally:
        await conn.close()

    if not products:
        await callback.message.answer(f"😔 محصولی توی دسته‌ی «{category}» موجود نیست.")
        await callback.answer()
        return

    await callback.message.answer(
        f"📂 **دسته‌بندی: {category}**\n\n"
        f"تعداد محصولات: {len(products)}\n"
        f"👇",
        parse_mode="Markdown"
    )

    for p in products:
        caption = (
            f"🔹 **{p['name']}**\n"
            f"💰 قیمت: {p['price']:,} تومان\n"
            f"📦 موجودی: {p['stock']} عدد"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن به سبد", callback_data=f"addcart_{p['product_id']}")]
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
            except:
                await callback.message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await callback.message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")

    await callback.answer()

# ==========================================
# ۲۴. لغو سفارش توسط مشتری
# ==========================================
@dp.message(Command("my_orders"))
async def cmd_my_orders(message: types.Message):
    user_id = message.from_user.id
    orders = await get_user_orders(user_id)

    if not orders:
        await message.answer(
            "📦 **سفارشات شما**\n\n"
            "😔 در حال حاضر هیچ سفارش فعالی ندارید.\n\n"
            "🛒 برای ثبت سفارش جدید، از منوی اصلی استفاده کنید."
        )
        return

    await message.answer(
        f"📦 **سفارشات فعال شما** (تعداد: {len(orders)})\n\n"
        f"👇 برای لغو هر سفارش، روی دکمه‌ی مربوطه بزن:",
        parse_mode="Markdown"
    )

    for order in orders:
        can_cancel = order['status'] in ["در انتظار پرداخت", "در حال پردازش"]

        caption = (
            f"🆔 کد سفارش: `{order['order_code']}`\n"
            f"📦 محصول: {order['product_name'] or 'نامشخص'}\n"
            f"🔢 تعداد: {order['quantity']}\n"
            f"💰 مبلغ: {order['total_price']:,} تومان\n"
            f"📊 وضعیت: **{order['status']}**"
        )

        if can_cancel:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="❌ لغو سفارش",
                        callback_data=f"cancel_{order['order_code']}"
                    )]
                ]
            )
            await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(
                caption + "\n\n⚠️ این سفارش قابل لغو نیست.",
                parse_mode="Markdown"
            )


@dp.callback_query(F.data.startswith("cancel_"))
async def handle_cancel_order(callback: types.CallbackQuery):
    order_code = callback.data.replace("cancel_", "")

    conn = await get_connection()
    try:
        order = await conn.fetchrow(
            """SELECT o.*, p.name as product_name 
               FROM orders o 
               LEFT JOIN products p ON o.product_id = p.product_id
               WHERE o.order_code = $1 AND o.user_id = $2""",
            order_code, callback.from_user.id
        )
    finally:
        await conn.close()

    if not order:
        await callback.answer("❌ سفارش پیدا نشد یا مربوط به شما نیست.", show_alert=True)
        return

    if order['status'] not in ["در انتظار پرداخت", "در حال پردازش"]:
        await callback.answer(
            f"❌ این سفارش در وضعیت «{order['status']}» قابل لغو نیست.",
            show_alert=True
        )
        return

    await cancel_order(order_code)

    await callback.message.answer(
        f"✅ **سفارش شما لغو شد!**\n\n"
        f"🆔 کد سفارش: `{order_code}`\n"
        f"📦 محصول: {order['product_name'] or 'نامشخص'}\n"
        f"🔢 تعداد: {order['quantity']}\n"
        f"💰 مبلغ: {order['total_price']:,} تومان\n\n"
        f"📦 موجودی محصول به انبار برگشت داده شد.\n\n"
        f"🛒 اگه می‌خوای سفارش جدید ثبت کنی، از منوی اصلی استفاده کن.",
        parse_mode="Markdown"
    )
    await callback.answer("✅ سفارش با موفقیت لغو شد.")


@dp.callback_query(F.data == "my_orders_btn")
async def handle_my_orders_btn(callback: types.CallbackQuery):
    await cmd_my_orders(callback.message)
    await callback.answer()

# ==========================================
# ۹. AI (آخرین هندلر - Fallback)
# ==========================================
@dp.message(F.text)
async def handle_all_messages(message: types.Message):
    print(f"🔍 DEBUG 1: پیام دریافت شد: {message.text}")
    try:
        response_text = await get_ai_response_async(message.text)
        print(f"🔍 DEBUG 2: پاسخ دریافت شد: {response_text[:50]}")
        await message.answer(response_text)
    except Exception as e:
        print(f"❌ DEBUG 3: خطا: {e}")
        await message.answer(f"❌ خطا: {e}")


# ==========================================
# ۱۰. اجرای اصلی (Webhook)
# ==========================================
async def main():
    print(">>> ربات حرفه‌ای هکتور آنلاین شاپ با موفقیت روشن شد و آماده‌ی پاسخگویی است...")

    # راه‌اندازی دیتابیس
    await init_db()
    print(">>> دیتابیس راه‌اندازی شد.")

    # راه‌اندازی زمان‌بند یادآوری پرداخت (هر ۱ ساعت)
    scheduler.add_job(check_pending_orders, 'interval', hours=1)

    # راه‌اندازی زمان‌بند گزارش فروش روزانه (هر شب ساعت ۱۲)
    scheduler.add_job(send_daily_report, 'cron', hour=0, minute=0)

# راه‌اندازی زمان‌بند تخفیف تولد (هر روز ساعت ۹ صبح)
    scheduler.add_job(check_birthdays, 'cron', hour=9, minute=0)

    scheduler.start()
    print(">>> زمان‌بند یادآوری پرداخت فعال شد.")

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