import os
import asyncpg
import ssl

DATABASE_URL = os.getenv("DATABASE_URL")
print(f"DEBUG: DATABASE_URL = {DATABASE_URL}")

# ساخت یک SSL context برای اتصال امن به Neon
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


async def get_connection():
    """گرفتن یک اتصال به دیتابیس PostgreSQL"""
    return await asyncpg.connect(DATABASE_URL, ssl=ssl_context)


async def init_db():
    """ساخت جدول‌های دیتابیس در اولین اجرا"""
    conn = await get_connection()
    try:
        # جدول کاربران
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول محصولات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price BIGINT NOT NULL,
                stock INTEGER DEFAULT 0,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول سفارشات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id SERIAL PRIMARY KEY,
                order_code TEXT UNIQUE NOT NULL,
                user_id BIGINT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price BIGINT NOT NULL,
                status TEXT DEFAULT 'در حال پردازش',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    finally:
        await conn.close()

async def add_user(user_id: int, username: str, first_name: str):
    """اضافه کردن کاربر جدید (اگه نباشه)"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO users (user_id, username, first_name)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id, username, first_name
        )
        print(f"✅ کاربر {user_id} با موفقیت ثبت شد.")
    except Exception as e:
        print(f"❌ خطا در ثبت کاربر: {e}")
    finally:
        await conn.close()


async def add_product(name: str, price: int, stock: int, category: str):
    """اضافه کردن محصول جدید (فقط توسط ادمین)"""
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO products (name, price, stock, category) VALUES ($1, $2, $3, $4)",
            name, price, stock, category
        )
        print(f"✅ محصول '{name}' با موفقیت اضافه شد.")
    except Exception as e:
        print(f"❌ خطا در اضافه کردن محصول: {e}")
    finally:
        await conn.close()


async def get_all_products():
    """گرفتن همه‌ی محصولات موجود"""
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT * FROM products WHERE stock > 0")
        return rows
    finally:
        await conn.close()


async def create_order(order_code: str, user_id: int, product_id: int, quantity: int, total_price: int):
    """ثبت سفارش جدید"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO orders (order_code, user_id, product_id, quantity, total_price)
               VALUES ($1, $2, $3, $4, $5)""",
            order_code, user_id, product_id, quantity, total_price
        )
    finally:
        await conn.close()


async def get_order_status(order_code: str):
    """گرفتن وضعیت سفارش با کد سفارش"""
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM orders WHERE order_code = $1", order_code)
        return row
    finally:
        await conn.close()

async def save_pending_order(user_id: int, product_id: int):
    """ذخیره‌ی سفارش نیمه‌کاره (کاربر محصول رو انتخاب کرده ولی تعداد رو نداده)"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO pending_orders (user_id, product_id, updated_at)
               VALUES ($1, $2, CURRENT_TIMESTAMP)
               ON CONFLICT (user_id) 
               DO UPDATE SET product_id = $2, updated_at = CURRENT_TIMESTAMP""",
            user_id, product_id
        )
        print(f"✅ سفارش نیمه‌کاره برای کاربر {user_id} ذخیره شد.")
    finally:
        await conn.close()


async def get_pending_order(user_id: int):
    """گرفتن سفارش نیمه‌کاره‌ی کاربر"""
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM pending_orders WHERE user_id = $1", user_id
        )
        return row
    finally:
        await conn.close()


async def delete_pending_order(user_id: int):
    """پاک کردن سفارش نیمه‌کاره بعد از ثبت نهایی"""
    conn = await get_connection()
    try:
        await conn.execute("DELETE FROM pending_orders WHERE user_id = $1", user_id)
    finally:
        await conn.close()


async def update_user_info(user_id: int, phone_number: str = None, birthday: str = None):
    """به‌روزرسانی اطلاعات کاربر (شماره تماس و تاریخ تولد)"""
    conn = await get_connection()
    try:
        if phone_number:
            await conn.execute(
                "UPDATE users SET phone_number = $1 WHERE user_id = $2",
                phone_number, user_id
            )
        if birthday:
            await conn.execute(
                "UPDATE users SET birthday = $1 WHERE user_id = $2",
                birthday, user_id
            )
        print(f"✅ اطلاعات کاربر {user_id} به‌روزرسانی شد.")
    finally:
        await conn.close()


async def get_user_info(user_id: int):
    """گرفتن اطلاعات کاربر"""
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return row
    finally:
        await conn.close()