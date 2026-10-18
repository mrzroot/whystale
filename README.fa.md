<div dir="rtl">

# whystale

**کد رو عوض کردی ولی هنوز رفتار قدیمی؟** `whystale` پیدا می‌کنه کدوم سرور، بیلد یا وابستگی کهنه شده و باید ری‌استارت یا دوباره ساخته بشه: سروری که قبل از تغییر `.env` یا lockfile بالا اومده، پوشه‌ی `dist/` که از سورس قدیمی‌تره، `node_modules` که از lockfile عقب‌تره، یا کد تولیدشده (Prisma، GraphQL، protobuf، OpenAPI) که از اسکیماش قدیمی‌تره. دلیلش رو می‌گه و **دقیقاً همون دستوری** که باید بزنی رو چاپ می‌کنه.

[English](README.md) | فارسی

</div>

```text
$ whystale
✗ process · Next.js dev server — `next-server (v14.2.3)` (pid 41872 :3000)
    why:    started 17:02:11, but 1 file(s) it reads at startup changed afterwards (latest 3m 29s later)
    fix:    kill 41872
            cd /home/me/shop-web && npm run dev
✗ deps · node_modules installed state is older than package-lock.json
    fix:    npm ci
✗ generated · Prisma client is older than its schema
    fix:    npx prisma generate
```

<div dir="rtl">

(خروجی بالا نمونه‌ی ساده‌شده است؛ خروجی واقعیِ دموی آفلاین در [docs/demo.txt](docs/demo.txt) هست.)

## چرا؟

تغییر درست بوده ولی «کار نمی‌کنه». دلیلش معمولاً ساده‌ست: بعد از عوض شدن `.env` یا کانفیگ سرور ری‌استارت نشده، `dist/` دوباره ساخته نشده، بعد از `git pull` وابستگی‌ها نصب نشدن، یا کلاینت تولیدشده (Prisma، GraphQL، protobuf، OpenAPI) دوباره تولید نشده. فریمورک‌ها در اینکه چی رو خودشون reload کنن فرق دارن، پس آدم‌ها (و ایجنت‌های هوش مصنوعی) حدس می‌زنن و کدِ درست رو بارها «درست» می‌کنن. `whystale` این حدس رو با یک گزارشِ فقط‌خواندنی و چندزبانه جایگزین می‌کنه: **چی از چیزی که ازش ساخته شده کهنه‌تره.**

## نصب

پایتون ۳٫۹ به بالا، بدون هیچ وابستگی. لینوکس و macOS (ویندوز پشتیبانی نمی‌شه).

</div>

```sh
pipx install git+https://github.com/mrzroot/whystale     # بعد از انتشار روی PyPI: pipx install whystale
uvx --from git+https://github.com/mrzroot/whystale whystale --demo
pip install -e .                                          # از یک کلون محلی
```

<div dir="rtl">

## استفاده

</div>

```sh
whystale                  # پروژه‌ی پوشه‌ی فعلی
whystale ~/code/shop      # یک پروژه‌ی دیگر
whystale --json           # خروجی ماشینی
whystale --markdown       # گزارش آماده‌ی paste برای ایجنت
whystale --watch          # هر ۲ ثانیه دوباره بررسی و چاپ تغییرها
whystale --only deps,generated
whystale --strict         # موارد «maybe» هم کد خروج را خراب کنن
whystale --no-fail        # همیشه با کد ۰ خارج شو
whystale --demo           # سناریوی آفلاین: فایل‌های واقعی + یک سرور واقعی
```

<div dir="rtl">

**کد خروج:** `۰` یعنی چیزی کهنه نیست، `۳` یعنی چیزی کهنه است، `۲` یعنی خطای استفاده یا کانفیگ. یافته‌ها دو سطح دارن: `stale` (مدرک محکم) و `maybe` (حدسی؛ مثلاً پروسه‌ای که فریمورکش احتمالاً خودش reload می‌کنه). فقط `stale` کد خروج رو خراب می‌کنه، مگر اینکه `--strict` بدی. برای امتحان بدون پروژه: `whystale --demo`.

برای ایجنت‌ها و CI: دستور `whystale --markdown --no-fail` رو قبل از «تموم شد» بزنن، یا `whystale` رو در CI بذار تا تا وقتی چیزی کهنه‌ست با کد ۳ خارج بشه. متن آماده‌ی `AGENTS.md` در [docs/AGENTS.snippet.md](docs/AGENTS.snippet.md) هست.

## چی رو تشخیص می‌ده

- **پروسه‌ای که قبل از تغییر فایلی که موقع شروع می‌خونه، بالا اومده.** فقط پروسه‌هایی که پوشه‌ی کاری‌شون داخل پروژه‌ست و شبیه سرور/runtime هستن. فایل‌های `.env*` (نه `.env.example`)، lockfileها، کانفیگ فریمورک‌ها، `settings.py` و فایل‌های مانیفست (به‌صورت `maybe`). راه‌حل: `kill PID` و همون دستور اولیه.
- **خروجی بیلد قدیمی‌تر از سورس:** `dist`، `build`، `out`، `.next`، `.nuxt`، `.output`، `.svelte-kit` برای پروژه‌های Node و `target/` برای Rust.
- **وابستگی نصب‌شده قدیمی‌تر از lockfile:** `node_modules` در برابر `package-lock.json`، `pnpm-lock.yaml`، `yarn.lock`؛ و virtualenvهای پایتون در برابر `requirements*.txt`، `poetry.lock`، `uv.lock`، `Pipfile.lock`. علاوه بر زمان، **نسخه‌ها** هم مقایسه می‌شن (برای npm و pnpm و پایتون).
- **کد تولیدشده قدیمی‌تر از اسکیما:** Prisma، protobuf، کلاینت OpenAPI، GraphQL Code Generator (`codegen.yml`) و قوانین خودت در `.whystale.toml`.

### چطور مثبت کاذب رو کم می‌کنه

اول باید فایل از چیزی که ازش ساخته شده **بیشتر از یک مهلت (۲ ثانیه برای پروسه، ۵ ثانیه برای فایل‌ها)** جدیدتر باشه. بعدش بررسی محتوا فقط می‌تونه یک یافته رو **پاک** کنه: مقدارهای `.env` از قبل توی محیط پروسه هستن (لینوکس)؛ lockfile فقط `touch` شده ولی نسخه‌های نصب‌شده یکی هستن؛ اسکیمای Prisma با نسخه‌ی ذخیره‌شده کنار کلاینت یکیه؛ pinهای `requirements.txt` برقرارن. پروسه‌هایی که خودشون reload می‌کنن (Vite، Next.js، Nuxt، Astro، Django runserver و سرورهای `--reload`) فقط `maybe` می‌شن، با ذکر دلیل. با `whystale -v` می‌بینی چی پاک شد و چرا.

## تنظیمات

فایل اختیاری `.whystale.toml` در ریشه‌ی پروژه:

</div>

```toml
[settings]
grace_seconds = 2
fs_grace_seconds = 5

[ignore]
paths = ["legacy/**"]
processes = ["tailscaled"]

[process]
include = ["mydaemon"]

[checks]
deps = false

[[generated]]
name = "API client"
sources = ["api/spec.yaml"]
outputs = ["src/client/**"]
command = "make client"
```

<div dir="rtl">

## محدودیت‌ها (لطفاً بخون)

whystale **شاهد** گزارش می‌کنه، نه اثبات قطعی.

- همه‌چیز از زمان تغییر فایل‌ها شروع می‌شه. ویرایشگر، فرمت‌کننده، `touch` یا `git checkout` می‌تونن زمان رو بدون تغییر محتوا عوض کنن. بررسی محتوا موارد رایج رو پاک می‌کنه ولی نه همه رو. زمان شروع پروسه در لینوکس حدود یک ثانیه دقت داره.
- فقط پروسه‌هایی دیده می‌شن که پوشه‌ی کاری‌شون داخل پروژه‌ست. سرور داخل Docker یا سروری که از جای دیگه بالا اومده دیده نمی‌شه. تغییر **کد سورس** نسبت به زمان شروع پروسه در نسخه‌ی ۰٫۱ بررسی نمی‌شه.
- جدول «خودش reload می‌کنه» از مستندات ابزارها اومده و عمداً محتاطانه‌ست (`maybe`).
- بیلد: فقط Node و Rust؛ برای بقیه قانون `[[artifact]]` بنویس. `yarn.lock` فقط با زمان سنجیده می‌شه. `bun`، `composer`، `bundler` و ماژول‌های Go بررسی نمی‌شن. محیط مجازی پایتون باید داخل پروژه باشه.
- مایگریشن‌های دیتابیس فایلی (مثل SQLite) بررسی **نمی‌شن**.
- لینوکس هدف اصلیه. مسیر `ps`/`lsof` برای macOS با خروجی ضبط‌شده تست شده و روی لینوکس هم اجرا می‌شه، ولی نویسنده هنوز روی مک واقعی امتحانش نکرده. ویندوز پشتیبانی نمی‌شه.

## مقایسه با ابزارهای نزدیک

تا اکتبر ۲۰۲۶ ابزار متن‌بازِ دیگه‌ای پیدا نکردم که همین ترکیب (گزارش فقط‌خواندنیِ «چی از چیزی که ازش ساخته شده کهنه‌تره» مرتبط با پروسه‌های در حال اجرا) رو انجام بده. اگه می‌شناسی، یه issue باز کن تا لینکش کنم. نزدیک‌ترین‌ها: [`devpilot`](https://github.com/benseverndev-oss/devpilot) (ناظر سرورهای توسعه، نه تشخیص کهنگی از روی زمان فایل‌ها)؛ watcherهای فریمورک‌ها مثل [`nodemon`](https://github.com/remy/nodemon)، [Vite](https://vite.dev/) و Next.js ([بحث](https://github.com/vercel/next.js/discussions/59558)) که هرکدوم فقط فایل‌های خودشون رو دنبال می‌کنن و نمی‌گن چی reload **نشده**؛ [`needrestart`](https://github.com/liske/needrestart) (فقط سرویس‌های سیستمی با کتابخانه‌ی قدیمی)؛ و دستورهایی مثل `npm ci` و `uv sync --locked` که lockfile رو اعمال می‌کنن ولی نمی‌گن پروسه یا بیلدی عقبه.

## توسعه و مجوز

</div>

```sh
pip install -e ".[test]" && python -m pytest && python -m whystale --demo
```

<div dir="rtl">

مجوز: MIT. © ۲۰۲۶ محمدرضا زارع ([@mrzroot](https://github.com/mrzroot)). مشارکت: [CONTRIBUTING.md](CONTRIBUTING.md).

</div>
