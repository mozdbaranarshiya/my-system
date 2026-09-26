# سامانه آموزش و پرورش استان اصفهان

سامانه وب فارسی و راست‌به‌چپ برای مدیریت مدرسه، ثبت نمرات، اطلاعیه‌ها و اعتراض دانش‌آموزان.

نسخه جدید سامانه با **TypeScript + Node.js + Express + Prisma + PostgreSQL** اجرا می‌شود. رابط کاربری با Nunjucks و Bootstrap RTL رندر می‌شود.

## امکانات

### مدیر مدرسه
- افزودن، ویرایش و حذف معلم و دانش‌آموز
- ساخت و ویرایش پایه، کلاس و درس
- تخصیص معلم به کلاس و درس
- تعیین نماینده کلاس
- ثبت و ویرایش نمرات تکوینی و پایانی
- قفل و بازگشایی مستقل تکوینی و پایانی
- ارسال اطلاعیه برای همه، گروه‌ها، کلاس یا یک فرد
- تغییر یا بازنشانی نام کاربری و رمز کاربران

### معلم
- مشاهده فقط کلاس/درس‌های تخصیص‌یافته
- ثبت موقت نمرات
- ثبت نهایی و قفل تکوینی یا پایانی
- مشاهده اطلاعیه‌ها
- بررسی اعتراض و اصلاح نمره در صورت تأیید

### دانش‌آموز
- مشاهده کارنامه
- مشاهده اطلاعیه‌ها
- مشاهده معلمان کلاس
- ثبت اعتراض برای نمره تکوینی یا پایانی

## منطق نمره

`نمره درس = (تکوینی + پایانی) / 2`

نمره نهایی درس جداگانه ذخیره نمی‌شود و از دو مقدار اصلی محاسبه می‌شود.

## نیازمندی‌ها

- Node.js 20.19 یا جدیدتر (Node.js 24 پیشنهاد می‌شود)
- PostgreSQL
- npm

## اتصال PostgreSQL آروان‌کلاد

فایل `.env.example` را با نام `.env` کپی کنید و اطلاعات اتصال دیتابیس را وارد کنید:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require
SESSION_SECRET=یک-مقدار-تصادفی-طولانی
ADMIN_NATIONAL_ID=1234567890
ADMIN_FULL_NAME=مدیر سامانه
HOST=127.0.0.1
PORT=5000
NODE_ENV=development
COOKIE_SECURE=0
```

نکته: در نسخه Node/Prisma از `postgresql://` استفاده می‌شود؛ پیشوند قدیمی Python یعنی `postgresql+psycopg://` معتبر نیست.

اگر رمز دیتابیس شامل نویسه‌هایی مثل `@`، `:`، `/`، `#` یا `%` است، آن را URL Encode کنید.

## نصب و اجرای اولیه

```bash
npm install
cp .env.example .env
# سپس .env را با اطلاعات واقعی تکمیل کنید

npm run db:push
npm run dev
```

در Windows PowerShell:

```powershell
npm install
Copy-Item .env.example .env
# سپس .env را ویرایش کنید

npm run db:push
npm run dev
```

سپس آدرس `http://127.0.0.1:5000` را باز کنید.

## مدیر اولیه

اگر هیچ مدیر در دیتابیس وجود نداشته باشد، هنگام اجرای برنامه حساب مدیر بر اساس این دو متغیر ساخته می‌شود:

```env
ADMIN_NATIONAL_ID=1234567890
ADMIN_FULL_NAME=مدیر سامانه
```

نام کاربری و رمز اولیه هر دو همان `ADMIN_NATIONAL_ID` هستند.

## حفظ داده‌های نسخه Python

مدل Prisma نام جدول‌ها و ستون‌های اصلی نسخه Flask را حفظ می‌کند، از جمله:

- `users`
- `grade_levels`
- `classrooms`
- `student_profiles`
- `subjects`
- `teacher_assignments`
- `scores`
- `grade_locks`
- `announcements`
- `objections`

بررسی رمزهای Werkzeug با فرمت‌های `scrypt` و `pbkdf2` نیز در نسخه TypeScript پشتیبانی شده است.

اگر دیتابیس فعلی شما دارای اطلاعات واقعی است، قبل از اجرای هر دستور تغییر schema از دیتابیس Backup بگیرید. سپس روی یک کپی یا محیط staging ابتدا `npm run db:push` را اجرا و خروجی Prisma را بررسی کنید.

## Production

در محیط عملیاتی حداقل این مقادیر را تنظیم کنید:

```env
NODE_ENV=production
COOKIE_SECURE=1
SESSION_SECRET=...
DATABASE_URL=postgresql://...?...&sslmode=require
```

برنامه پشت HTTPS اجرا شود. Sessionها داخل PostgreSQL و در جدول `user_sessions` نگهداری می‌شوند.

## دستورات

```bash
npm run dev          # اجرای توسعه
npm run build        # تولید Prisma Client و کامپایل TypeScript
npm start            # اجرای خروجی build
npm test             # تست‌های Vitest
npm run db:push      # همگام‌سازی schema با PostgreSQL
npm run db:studio    # Prisma Studio
```

## ساختار پروژه

- `src/app.ts` — مسیرها و منطق برنامه
- `src/security.ts` — Hash/Verify رمز عبور
- `src/domain.ts` — اعتبارسنجی‌ها و منطق مشترک
- `src/prisma.ts` — اتصال Prisma
- `src/server.ts` — اجرای HTTP server
- `prisma/schema.prisma` — مدل دیتابیس
- `school_system/templates/` — قالب‌های فارسی RTL (Nunjucks)
- `school_system/static/` — CSS
- `tests/` — تست‌های TypeScript
