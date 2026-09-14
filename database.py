import os
import asyncpg
import ssl

DATABASE_URL = os.getenv("DATABASE_URL")

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