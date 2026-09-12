import os
import staypresent

# ایجاد یک پورت HTTP برای Render
staypresent.web.json({"status": "running"})

# اجرای فایل اصلی ربات که تغییر نکرده است
staypresent.run(
    "bot.py",
    port=int(os.getenv("PORT", 8080))
)