import os
import asyncio
import logging
import tempfile
import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import subprocess

# -------------------- تنظیمات --------------------
TOKEN = "8932564239:AAHpbG9M3Jz9QVkUWskx6tTXp3TgmSZNugw"
AUDD_API_KEY = "31420984d0cfdad80356a6bfc3ce72a6" # کلید API از audd.io
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20MB سقف حجم فایل ورودی

# -------------------- توابع کمکی --------------------
async def download_telegram_file(file_id, file_unique_id, context):
    """دانلود فایل از تلگرام و بازگرداندن مسیر فایل موقت"""
    file = await context.bot.get_file(file_id)
    # ساخت نام موقت
    suffix = ".mp4" if "video" in file.file_path else ".mp3"
    temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    await file.download_to_drive(custom_path=temp_file.name)
    temp_file.close()
    return temp_file.name

def extract_audio_from_video(video_path):
    """استخراج صدا از ویدیو با ffmpeg"""
    output_path = video_path + ".mp3"
    cmd = [
        "ffmpeg", "-i", video_path,
        "-q:a", "0", "-map", "a",
        "-y", output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path

async def identify_music(audio_path):
    """ارسال فایل صوتی به AudD برای شناسایی"""
    url = "https://api.audd.io/"
    data = {
        'api_token': AUDD_API_KEY,
        'return': 'apple_music,spotify',
    }
    async with aiohttp.ClientSession() as session:
        with open(audio_path, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('file', f, filename='audio.mp3', content_type='audio/mpeg')
            form.add_field('api_token', AUDD_API_KEY)
            async with session.post(url, data=form) as resp:
                result = await resp.json()
                if result.get('status') == 'success' and result.get('result'):
                    track = result['result']
                    title = track.get('title')
                    artist = track.get('artist')
                    if title and artist:
                        return f"{artist} - {title}"
                return None

async def download_audio_from_youtube(query):
    """جستجوی یوتیوب و دانلود صدا با yt-dlp"""
    output_template = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    cmd = [
        "yt-dlp",
        f"ytsearch1:{query}",
        "-x",  # استخراج صدا
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", output_template,
        "--no-playlist",
        "--max-filesize", "50m"
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        # فایل دانلود شده (yt-dlp ممکن است پسوند mp3 را اضافه کند)
        actual_file = output_template + ".mp3" if os.path.exists(output_template + ".mp3") else output_template
        return actual_file
    else:
        logging.error(f"yt-dlp error: {stderr.decode()}")
        return None

# -------------------- Handler اصلی --------------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat_type = update.effective_chat.type

    # فقط در پی‌وی کار کند (اختیاری)
    if chat_type != "private":
        await message.reply_text("لطفاً کلیپ را در پی‌وی برای من ارسال کنید.")
        return

    # بررسی نوع فایل
    if not (message.video or message.audio or message.voice or message.document):
        await message.reply_text("لطفاً یک ویدیو یا فایل صوتی ارسال کنید.")
        return

    # دریافت file_id (ویدیو، صدا، یا voice)
    if message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
    elif message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
    elif message.voice:
        file_id = message.voice.file_id
        file_unique_id = message.voice.file_unique_id
    else:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id

    # بررسی حجم (حداکثر 20MB برای API AudD)
    file_size = (message.video or message.audio or message.voice or message.document).file_size
    if file_size > MAX_FILE_SIZE:
        await message.reply_text("حجم فایل بیش از ۲۰ مگابایت است. لطفاً کلیپ کوچک‌تری بفرستید.")
        return

    await message.reply_text("⏳ در حال پردازش...")

    try:
        # مرحله ۱: دانلود فایل از تلگرام
        input_path = await download_telegram_file(file_id, file_unique_id, context)

        # مرحله ۲: اگر ویدیو است، صدا را استخراج کن
        if message.video or message.document:
            audio_path = extract_audio_from_video(input_path)
        else:
            audio_path = input_path  # فایل صوتی یا ویس مستقیماً استفاده شود

        # مرحله ۳: شناسایی موسیقی
        song_query = await identify_music(audio_path)
        if not song_query:
            await message.reply_text("❌ نتوانستم آهنگ را شناسایی کنم.")
            return

        await message.reply_text(f"🎵 شناسایی شد: {song_query}\n🔄 در حال دانلود آهنگ کامل...")

        # مرحله ۴: دانلود از یوتیوب
        full_audio_path = await download_audio_from_youtube(song_query)
        if full_audio_path and os.path.exists(full_audio_path):
            # مرحله ۵: ارسال برای کاربر
            await context.bot.send_audio(
                chat_id=user.id,
                audio=open(full_audio_path, 'rb'),
                title=song_query.split(" - ")[-1],
                performer=song_query.split(" - ")[0],
                caption=f"🎶 {song_query}"
            )
            # پاکسازی فایل‌های موقت
            for p in [input_path, audio_path, full_audio_path]:
                try:
                    os.unlink(p)
                except:
                    pass
        else:
            await message.reply_text("⚠️ نتوانستم فایل کامل را دانلود کنم. شاید آهنگ در یوتیوب موجود نباشد.")
    except Exception as e:
        logging.exception(e)
        await message.reply_text("❗ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
        # پاکسازی فایل‌های موقت احتمالی
        for p in [input_path, audio_path, full_audio_path]:
            if 'p' in locals() and os.path.exists(p):
                os.unlink(p)

# -------------------- اجرای ربات --------------------
def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_media))
    print("✅ ربات موزیک‌یاب اجرا شد...")
    app.run_polling()

if __name__ == "__main__":
    main()