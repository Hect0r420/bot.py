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
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday TEXT")

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
        await conn.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT")

        # جدول سفارشات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id SERIAL PRIMARY KEY,
                order_code TEXT UNIQUE NOT NULL,
                user_id BIGINT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price BIGINT NOT NULL,
                status TEXT DEFAULT 'در انتظار پرداخت',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute(
            "ALTER TABLE orders ALTER COLUMN product_id DROP NOT NULL"
        )


# محصولات داخل هر سفارش چندمحصولی
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
               item_id SERIAL PRIMARY KEY,
               order_id INTEGER NOT NULL,
               product_id INTEGER NOT NULL,
               product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
               unit_price BIGINT NOT NULL,
               total_price BIGINT NOT NULL,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_order_items_order_id
    ON order_items (order_id)
""")


        # جدول سفارشات نیمه‌کاره
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_orders (
                user_id BIGINT PRIMARY KEY,
                product_id INTEGER NOT NULL,
                quantity INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
         # جدول وضعیت Checkout سبد خرید
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_checkouts (
                user_id BIGINT PRIMARY KEY,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")



        # جدول کدهای تخفیف
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                coupon_id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                discount_percent INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # جدول سبد خرید
        await conn.execute("""
    CREATE TABLE IF NOT EXISTS cart_items (
        cart_id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# اضافه کردن ستون user_id به جدول coupons (برای کدهای اختصاصی)
        await conn.execute("ALTER TABLE coupons         ADD COLUMN IF NOT EXISTS user_id BIGINT")
        await conn.execute("ALTER TABLE coupons  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP")

        print("✅ جدول‌ها و ستون‌ها با موفقیت ساخته/به‌روزرسانی شدن.")
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


async def add_product(name: str, price: int, stock: int, category: str, image_url: str = None):
    """اضافه کردن محصول جدید (فقط توسط ادمین)"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO products (name, price, stock, category, image_url)
               VALUES ($1, $2, $3, $4, $5)""",
            name, price, stock, category, image_url
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

async def save_pending_order(user_id: int, product_id: int, quantity: int = None):
    """ذخیره‌ی سفارش نیمه‌کاره (با تعداد اختیاری)"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO pending_orders (user_id, product_id, quantity, updated_at)
               VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
               ON CONFLICT (user_id) 
               DO UPDATE SET product_id = $2, quantity = $3, updated_at = CURRENT_TIMESTAMP""",
            user_id, product_id, quantity
        )
        print(f"✅ سفارش نیمه‌کاره برای کاربر {user_id} ذخیره شد. (تعداد: {quantity})")
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
async def add_coupon(code: str, discount_percent: int, max_uses: int = 0):
    """اضافه کردن کد تخفیف جدید"""
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO coupons (code, discount_percent, max_uses)
               VALUES ($1, $2, $3)""",
            code.upper(), discount_percent, max_uses
        )
        print(f"✅ کد تخفیف '{code}' اضافه شد.")
    except Exception as e:
        print(f"❌ خطا در اضافه کردن کد تخفیف: {e}")
    finally:
        await conn.close()


async def get_coupon(code: str, user_id: int = None):
    """گرفتن اطلاعات کد تخفیف (با چک کردن کاربر و انقضا)"""
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM coupons WHERE code = $1 AND is_active = TRUE",
            code.upper()
        )
        if not row:
            return None

        # چک کردن انقضا
        if row['expires_at']:
            from datetime import datetime
            if datetime.now() > row['expires_at']:
                return None

        # چک کردن اینکه کد مخصوص کاربر دیگه‌ای نباشه
        if row['user_id'] and user_id and row['user_id'] != user_id:
            return None

        return row
    finally:
        await conn.close()


async def use_coupon(code: str):
    """استفاده از کد تخفیف (افزایش تعداد استفاده)"""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE coupons SET used_count = used_count + 1 WHERE code = $1",
            code.upper()
        )
    finally:
        await conn.close()


async def get_all_coupons():
    """گرفتن همه‌ی کدهای تخفیف"""
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT * FROM coupons ORDER BY coupon_id DESC")
        return rows
    finally:
        await conn.close()


async def delete_coupon(code: str):
    """حذف کد تخفیف"""
    conn = await get_connection()
    try:
        await conn.execute("DELETE FROM coupons WHERE code = $1", code.upper())
    finally:
        await conn.close()

async def add_to_cart(user_id: int, product_id: int, quantity: int):
    """اضافه کردن محصول به سبد خرید"""
    conn = await get_connection()
    try:
        existing = await conn.fetchrow(
            "SELECT * FROM cart_items WHERE user_id = $1 AND product_id = $2",
            user_id, product_id
        )
        if existing:
            await conn.execute(
                "UPDATE cart_items SET quantity = quantity + $1 WHERE user_id = $2 AND product_id = $3",
                quantity, user_id, product_id
            )
        else:
            await conn.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES ($1, $2, $3)",
                user_id, product_id, quantity
            )
    finally:
        await conn.close()


async def get_cart(user_id: int):
    """گرفتن محتویات سبد خرید"""
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """SELECT c.*, p.name, p.price 
               FROM cart_items c
               LEFT JOIN products p ON c.product_id = p.product_id
               WHERE c.user_id = $1
               ORDER BY c.added_at""",
            user_id
        )
        return rows
    finally:
        await conn.close()


async def clear_cart(user_id: int):
    """پاک کردن سبد خرید"""
    conn = await get_connection()
    try:
        await conn.execute("DELETE FROM cart_items WHERE user_id = $1", user_id)
    finally:
        await conn.close()


async def remove_from_cart(user_id: int, product_id: int):
    """حذف یک محصول از سبد خرید"""
    conn = await get_connection()
    try:
        await conn.execute(
            "DELETE FROM cart_items WHERE user_id = $1 AND product_id = $2",
            user_id, product_id
        )
    finally:
        await conn.close()

async def create_birthday_coupon(user_id: int, code: str, discount_percent: int):
    """ساخت کد تخفیف اختصاصی تولد (معتبر برای ۲۴ ساعت)"""
    from datetime import datetime, timedelta
    expires_at = datetime.now() + timedelta(hours=24)

    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO coupons (code, discount_percent, max_uses, user_id, expires_at)
               VALUES ($1, $2, 1, $3, $4)""",
            code.upper(), discount_percent, user_id, expires_at
        )
        print(f"✅ کد تخفیف تولد '{code}' برای کاربر {user_id} ساخته شد.")
    except Exception as e:
        print(f"❌ خطا در ساخت کد تخفیف تولد: {e}")
    finally:
        await conn.close()

async def update_order_status(order_code: str, new_status: str):
    """تغییر وضعیت سفارش توسط ادمین"""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE orders SET status = $1 WHERE order_code = $2",
            new_status, order_code
        )
        print(f"✅ وضعیت سفارش {order_code} به '{new_status}' تغییر یافت.")
    finally:
        await conn.close()

async def get_user_orders(user_id: int):
    """گرفتن سفارشات یک کاربر (فقط سفارشات فعال)"""
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """SELECT o.*, p.name as product_name
               FROM orders o
               LEFT JOIN products p ON o.product_id = p.product_id
               WHERE o.user_id = $1 
               AND o.status NOT IN ('تحویل داده شده', 'لغو شده')
               ORDER BY o.created_at DESC""",
            user_id
        )
        return rows
    finally:
        await conn.close()


async def cancel_order(order_code: str):
    """لغو سفارش و برگرداندن موجودی محصول"""
    conn = await get_connection()
    try:
        order = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_code = $1", order_code
        )
        if not order:
            return None

        await conn.execute(
            "UPDATE orders SET status = 'لغو شده' WHERE order_code = $1",
            order_code
        )

        await conn.execute(
            "UPDATE products SET stock = stock + $1 WHERE product_id = $2",
            order['quantity'], order['product_id']
        )

        print(f"✅ سفارش {order_code} لغو شد و موجودی برگشت.")
        return order
    finally:
        await conn.close()


async def update_order_status(order_code: str, new_status: str):
    """تغییر وضعیت سفارش توسط ادمین"""
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE orders SET status = $1 WHERE order_code = $2",
            new_status, order_code
        )
        print(f"✅ وضعیت سفارش {order_code} به '{new_status}' تغییر یافت.")
    finally:
        await conn.close()

async def get_all_users():
    """گرفتن لیست همه‌ی کاربران"""
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT user_id, first_name FROM users ORDER BY user_id")
        return rows
    finally:
        await conn.close()

async def save_pending_checkout(user_id: int):
    """ذخیره وضعیت انتظار کد تخفیف برای سبد خرید"""
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO pending_checkouts (user_id, updated_at)
            VALUES ($1, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            user_id
        )
    finally:
        await conn.close()


async def get_pending_checkout(user_id: int):
    """بررسی اینکه کاربر در مرحله Checkout هست یا نه"""
    conn = await get_connection()
    try:
        return await conn.fetchrow(
            """
            SELECT *
            FROM pending_checkouts
            WHERE user_id = $1
            """,
            user_id
        )
    finally:
        await conn.close()


async def delete_pending_checkout(user_id: int):
    """پاک کردن وضعیت Checkout بعد از ثبت سفارش"""
    conn = await get_connection()
    try:
        await conn.execute(
            "DELETE FROM pending_checkouts WHERE user_id = $1",
            user_id
        )
    finally:
        await conn.close()
