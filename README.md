# سامانه آموزش و پرورش استان اصفهان

سامانه وب فارسی و راست‌به‌چپ برای مدیریت مدرسه با سه نقش **مدیر، معلم و دانش‌آموز**. بک‌اند با Flask و SQLAlchemy نوشته شده و برای PostgreSQL مدیریت‌شده آروان‌کلاد آماده است.

## امکانات

- مدیر: افزودن/ویرایش/حذف معلم و دانش‌آموز، پایه، کلاس و درس، تخصیص معلم و درس به کلاس، ثبت دانش‌آموز در کلاس، تعیین نماینده، ثبت و قفل/بازگشایی نمره، اطلاعیه گروهی/فردی.
- معلم: ثبت موقت نمره، ثبت نهایی مستقل برای تکوینی یا پایانی، مشاهده اطلاعیه‌ها، بررسی اعتراض و در صورت تأیید تغییر اجباری نمره.
- دانش‌آموز: مشاهده کارنامه، محاسبه خودکار نمره درس با (تکوینی + پایانی) / 2، مشاهده معلم هر درس و اطلاعیه‌ها، ثبت اعتراض برای تکوینی یا پایانی.
- ورود: نام کاربری برابر کدملی است. رمز اولیه نیز همان کدملی است، ولی در پایگاه داده فقط هش رمز ذخیره می‌شود. تغییر/بازنشانی رمز فقط توسط مدیر انجام می‌شود.

## اتصال به دیتابیس PostgreSQL آروان‌کلاد

در پنل آروان‌کلاد یک دیتابیس PostgreSQL مدیریت‌شده بسازید و اطلاعات اتصال را دریافت کنید. سپس فایل .env.example را به .env کپی و مقادیر واقعی را وارد کنید:

~~~env
DATABASE_URL=postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:DB_PORT/DB_NAME?sslmode=require
SECRET_KEY=یک-رشته-تصادفی-طولانی
ADMIN_NATIONAL_ID=کدملی-مدیر-۱۰-رقمی
ADMIN_NAME=نام مدیر
HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=0
~~~

فایل .env عمداً در .gitignore قرار دارد و نباید روی GitHub commit شود.

برای ساخت SECRET_KEY:

~~~bash
python -c "import secrets; print(secrets.token_hex(32))"
~~~

## اجرای محلی

Python 3.11 یا جدیدتر پیشنهاد می‌شود.

~~~bash
git clone https://github.com/mozdbaranarshiya/my-system.git
cd my-system
python -m venv .venv
~~~

Windows PowerShell:

~~~powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# فایل .env را ویرایش کنید
flask --app app init-db
python app.py
~~~

Linux / macOS:

~~~bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# فایل .env را ویرایش کنید
flask --app app init-db
python app.py
~~~

سپس مرورگر را روی http://127.0.0.1:5000 باز کنید. در اولین ورود، نام کاربری و رمز مدیر هر دو مقدار ADMIN_NATIONAL_ID هستند.

## اجرای آزمایشی بدون آروان‌کلاد

فقط برای توسعه محلی می‌توانید به‌طور موقت SQLite را فعال کنید:

~~~env
USE_SQLITE_DEV=1
SECRET_KEY=dev-secret-change-me
ADMIN_NATIONAL_ID=0012345678
ADMIN_NAME=مدیر آزمایشی
~~~

در محیط واقعی از PostgreSQL آروان‌کلاد استفاده کنید.

## نکات امنیتی

- هرگز .env، رمز دیتابیس، SECRET_KEY یا کدملی واقعی مدیر را commit نکنید.
- HTTPS را در محیط عملیاتی فعال کنید و FLASK_ENV=production بگذارید.
- برای استقرار عمومی بهتر است reverse proxy و Gunicorn استفاده شود؛ مثلاً: gunicorn -w 3 -b 127.0.0.1:8000 app:app
- قبل از استفاده واقعی، سیاست پشتیبان‌گیری، کنترل دسترسی شبکه دیتابیس و نگهداری داده‌های هویتی مدرسه را با الزامات سازمانی تطبیق دهید.
