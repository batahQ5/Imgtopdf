try:
    from telegram import __version__ as ptb_version
    print(f"✅ python-telegram-bot version: {ptb_version}")
except ImportError:
    print("❌ خطأ: لم يتم تثبيت python-telegram-bot")
    print("=> الرجاء تشغيل: pip install python-telegram-bot==20.5")
    exit(1)

from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TimedOut, RetryAfter
from PIL import Image
from fpdf import FPDF
import os
import asyncio
import logging
import time

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)
REQUIRED_CHANNEL = "@en313g"
BOT_TOKEN = "7890442746:AAFS8TCmscI0836vX6FjOBMxqL1QAGP_sak"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

user_data = {}

TEXTS = {
    "start": {"ar": "👋 أهلاً! أرسل لي الصور، ثم اضغط 'إنشاء PDF' للحصول على ملف PDF."},
    "images_received": {"ar": "📸 الصور المستلمة: {count}\n\nأرسل المزيد أو اضغط لإنشاء PDF:"},
    "pdf_created": {"ar": "✅ تم إنشاء PDF بنجاح!"},
    "cancelled": {"ar": "❌ تم إلغاء العملية."},
    "no_images": {"ar": "❌ لا توجد صور بعد. أرسل بعض الصور أولاً."},
    "error": {"ar": "❌ حدث خطأ: {error}"},
    "must_subscribe": {"ar": "❗️ يجب الاشتراك في قناتنا أولاً:\n{channel}"},
    "check_subscription": {"ar": "✅ تحقق من الاشتراك"},
    "subscribe_button": {"ar": "📢 اشترك الآن"},
    "restart_button": {"ar": "🔄 بدء جديد"},
    "what_next": {"ar": "ماذا تريد أن تفعل الآن؟"},
    "sending_pdf": {"ar": "⏳ جاري إنشاء وإرسال ملف PDF..."},
    "join_success": {"ar": "✅ تم الاشتراك بنجاح! يمكنك الآن استخدام البوت."}
}

def get_user_lang(user_id):
    return "ar"

async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        member = await context.bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL, 
            user_id=user_id
        )
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"خطأ في التحقق من الاشتراك: {e}")
        return False

async def send_subscription_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)

    keyboard = [
        [InlineKeyboardButton(
            TEXTS["subscribe_button"][lang], 
            url=f"https://t.me/{REQUIRED_CHANNEL.strip('@')}"
        )],
        [InlineKeyboardButton(
            TEXTS["check_subscription"][lang], 
            callback_data="check_subscription"
        )]
    ]

    await update.message.reply_text(
        TEXTS["must_subscribe"][lang].format(channel=REQUIRED_CHANNEL),
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

def cleanup_files(file_paths):
    for file in file_paths:
        try:
            if os.path.exists(file):
                os.remove(file)
        except Exception as e:
            logger.error(f"خطأ في حذف الملف: {file} - {e}")

def convert_images_to_pdf(image_paths, output_path):
    pdf = FPDF()
    for img_path in image_paths:
        try:
            with Image.open(img_path) as image:
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                temp_jpg = f"{img_path}_temp.jpg"
                image.save(temp_jpg, "JPEG", quality=90)

                img_w, img_h = image.size
                orientation = 'L' if img_w > img_h else 'P'
                pdf.add_page(orientation=orientation)
                page_w, page_h = (297, 210) if orientation == 'L' else (210, 297)

                ratio = min(page_w / img_w, page_h / img_h)
                new_w = img_w * ratio
                new_h = img_h * ratio

                x = (page_w - new_w) / 2
                y = (page_h - new_h) / 2

                pdf.image(temp_jpg, x, y, new_w, new_h)
                os.remove(temp_jpg)
        except Exception as e:
            logger.error(f"خطأ في معالجة الصورة: {img_path} - {e}")
    pdf.output(output_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)

    if not await check_subscription(context, user_id):
        await send_subscription_message(update, context)
        return

    user_data[user_id] = {"images": [], "task": None}
    await update.message.reply_text(TEXTS["start"][lang])

async def handle_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)

    if not await check_subscription(context, user_id):
        await send_subscription_message(update, context)
        return

    if user_id not in user_data:
        user_data[user_id] = {"images": [], "task": None}

    if user_data[user_id].get("task"):
        user_data[user_id]["task"].cancel()

    file_obj = None
    if update.message.photo:
        file_obj = update.message.photo[-1]
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file_obj = update.message.document
    else:
        return

    try:
        file = await context.bot.get_file(file_obj.file_id)
        ext = ".jpg" if update.message.photo else os.path.splitext(file_obj.file_name)[1] or ".jpg"
        file_path = os.path.join(TEMP_DIR, f"{user_id}_{int(time.time())}{ext}")
        await file.download_to_drive(file_path)
        user_data[user_id]["images"].append(file_path)

        keyboard = [
            [InlineKeyboardButton("📄 إنشاء PDF", callback_data="create_pdf")],
            [InlineKeyboardButton("🗑️ مسح الصور", callback_data="cancel")]
        ]
        await update.message.reply_text(
            TEXTS["images_received"][lang].format(count=len(user_data[user_id]["images"])),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        async def auto_clear():
            await asyncio.sleep(600)
            if user_data.get(user_id) and user_data[user_id].get("images"):
                cleanup_files(user_data[user_id]["images"])
                user_data[user_id]["images"] = []

        user_data[user_id]["task"] = asyncio.create_task(auto_clear())

    except Exception as e:
        logger.error(f"خطأ في تحميل الصورة: {e}")
        await update.message.reply_text(TEXTS["error"][lang].format(error=str(e)))

async def send_pdf_with_retry(context, chat_id, pdf_path, caption, max_retries=5):
    for attempt in range(max_retries):
        try:
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename="الصور_ملف.pdf"),
                    caption=caption
                )
            return True
        except (TimedOut, RetryAfter) as e:
            wait = getattr(e, 'retry_after', 5)
            logger.warning(f"إعادة المحاولة بعد {wait} ثانية...")
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"فشل في إرسال PDF: {e}")
            break
    return False

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    await query.answer()

    if query.data == "check_subscription":
        if await check_subscription(context, user_id):
            await query.edit_message_text(TEXTS["join_success"][lang])
            user_data[user_id] = {"images": [], "task": None}
            await context.bot.send_message(chat_id=query.message.chat_id, text=TEXTS["start"][lang])
        else:
            await query.answer("❌ لم تشترك بعد!", show_alert=True)
        return

    if not await check_subscription(context, user_id):
        await send_subscription_message(update, context)
        return

    if query.data == "create_pdf":
        if not user_data.get(user_id) or not user_data[user_id].get("images"):
            await query.edit_message_text(TEXTS["no_images"][lang])
            return

        await query.edit_message_text(TEXTS["sending_pdf"][lang])
        pdf_path = os.path.join(TEMP_DIR, f"{user_id}_{int(time.time())}.pdf")

        try:
            convert_images_to_pdf(user_data[user_id]["images"], pdf_path)
            success = await send_pdf_with_retry(
                context, 
                query.message.chat_id, 
                pdf_path, 
                TEXTS["pdf_created"][lang]
            )

            if not success:
                await context.bot.send_message(
                    query.message.chat_id, 
                    TEXTS["error"][lang].format(error="فشل إرسال الملف بعد عدة محاولات")
                )
        except Exception as e:
            logger.error(f"خطأ في إنشاء PDF: {e}")
            await context.bot.send_message(
                query.message.chat_id, 
                TEXTS["error"][lang].format(error=str(e))
            )
        finally:
            if user_data.get(user_id):
                cleanup_files(user_data[user_id]["images"] + [pdf_path])
                user_data[user_id] = {"images": [], "task": None}

        keyboard = [[InlineKeyboardButton(TEXTS["restart_button"][lang], callback_data="restart")]]
        await context.bot.send_message(
            query.message.chat_id, 
            TEXTS["what_next"][lang], 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "cancel":
        if user_data.get(user_id):
            cleanup_files(user_data[user_id].get("images", []))
            if user_data[user_id].get("task"):
                user_data[user_id]["task"].cancel()
            user_data[user_id] = {"images": [], "task": None}

        await query.edit_message_text(TEXTS["cancelled"][lang])
        await context.bot.send_message(
            chat_id=query.message.chat_id, 
            text=TEXTS["start"][lang]
        )

    elif query.data == "restart":
        if user_data.get(user_id):
            cleanup_files(user_data[user_id].get("images", []))
            if user_data[user_id].get("task"):
                user_data[user_id]["task"].cancel()
            user_data[user_id] = {"images": [], "task": None}

        await context.bot.send_message(
            chat_id=query.message.chat_id, 
            text=TEXTS["start"][lang]
        )

def main():
    print("✅ جاري تشغيل البوت...")
    print(f"قناة الاشتراك الإجباري: {REQUIRED_CHANNEL}")

    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_images))
        app.add_handler(CallbackQueryHandler(button_handler))

        print("✅ البوت يعمل الآن...")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"خطأ فادح: {e}")
        print(f"❌ فشل التشغيل: {e}")

if __name__ == "__main__":
    main()
