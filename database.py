import aiosqlite

DB_NAME = "hector_shop.db"


async def init_db():
    """ساخت جدول‌های دیتابیس در اولین اجرا"""
    async with aiosqlite.connect(DB_NAME) as db:
        # جدول کاربران
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول محصولات
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                stock INTEGER DEFAULT 0,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول سفارشات
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price INTEGER NOT NULL,
                status TEXT DEFAULT 'در حال پردازش',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


async def add_user(user_id: int, username: str, first_name: str):
    """اضافه کردن کاربر جدید (اگه نباشه)"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )
        await db.commit()


async def add_product(name: str, price: int, stock: int, category: str):
    """اضافه کردن محصول جدید (فقط توسط ادمین)"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO products (name, price, stock, category) VALUES (?, ?, ?, ?)",
            (name, price, stock, category)
        )
        await db.commit()


async def get_all_products():
    """گرفتن همه‌ی محصولات موجود"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products WHERE stock > 0") as cursor:
            return await cursor.fetchall()


async def create_order(order_code: str, user_id: int, product_id: int, quantity: int, total_price: int):
    """ثبت سفارش جدید"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """INSERT INTO orders (order_code, user_id, product_id, quantity, total_price)
               VALUES (?, ?, ?, ?, ?)""",
            (order_code, user_id, product_id, quantity, total_price)
        )
        await db.commit()


async def get_order_status(order_code: str):
    """گرفتن وضعیت سفارش با کد سفارش"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE order_code = ?", (order_code,)
        ) as cursor:
            return await cursor.fetchone()