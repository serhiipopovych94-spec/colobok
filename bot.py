"""
Кругобот: присылаешь видео — получаешь кружок.
Берёт центральную квадратную часть кадра, первые 60 секунд.
"""
import asyncio
import logging
import os
import subprocess
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

BOT_TOKEN = os.environ["BOT_TOKEN"]  # ключ от @BotFather, задаётся в настройках хостинга
SIZE = 640          # диаметр кружка в пикселях (максимум у Telegram)
MAX_SECONDS = 60    # кружок не может быть длиннее минуты
MAX_MB = 20         # больше бот скачать не может

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)


def make_circle(src: str, dst: str) -> None:
    """Обрезает видео до квадрата по центру и готовит его под кружок."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", src,
            "-t", str(MAX_SECONDS),
            "-vf", f"crop='min(iw,ih)':'min(iw,ih)',scale={SIZE}:{SIZE},setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            dst,
        ],
        check=True,
        capture_output=True,
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Пришли мне видео (до 20 МБ), и я сделаю из него кружок ⭕️\n"
        "Возьму центр кадра и первые 60 секунд."
    )


@dp.message(F.video | F.document | F.animation)
async def handle_video(message: Message):
    media = message.video or message.animation or message.document
    if message.document and not (message.document.mime_type or "").startswith("video"):
        await message.answer("Это не похоже на видео 🤔 Пришли видеофайл.")
        return
    if media.file_size and media.file_size > MAX_MB * 1024 * 1024:
        await message.answer(f"Видео больше {MAX_MB} МБ, такое я не могу скачать 😔 Попробуй покороче.")
        return

    status = await message.answer("Делаю кружок… ⏳")
    # Пока идёт обработка, в чате виден статус «записывает видео…»
    async with ChatActionSender.record_video_note(bot=bot, chat_id=message.chat.id):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in")
            dst = os.path.join(tmp, "out.mp4")
            try:
                await bot.download(media, destination=src)
                await asyncio.to_thread(make_circle, src, dst)
                await message.answer_video_note(FSInputFile(dst), length=SIZE)
                await status.delete()
            except Exception:
                logging.exception("Не получилось обработать видео")
                await status.edit_text("Что-то пошло не так 😕 Попробуй другое видео.")


@dp.message()
async def other(message: Message):
    await message.answer("Пришли мне видео, и я сделаю из него кружок ⭕️")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
