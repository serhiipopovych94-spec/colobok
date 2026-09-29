"""
Кругобот: присылаешь видео — получаешь кружок.
Можно выбрать, какую часть кадра взять: верх, центр или низ (лево/право для горизонтальных).
"""
import asyncio
import logging
import os
import subprocess
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

BOT_TOKEN = os.environ["BOT_TOKEN"]  # ключ от @BotFather, задаётся в настройках хостинга
SIZE = 640          # диаметр кружка в пикселях (максимум у Telegram)
MAX_SECONDS = 60    # кружок не может быть длиннее минуты
MAX_MB = 20         # больше бот скачать не может

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# Видео, которые ждут выбора части кадра: id сообщения с кнопками -> file_id видео
pending: dict[int, str] = {}

HELP_TEXT = (
    "Как пользоваться ⭕️\n\n"
    "1. Пришли мне видео (до 20 МБ).\n"
    "2. Выбери, какую часть кадра взять: верх, центр или низ.\n"
    "3. Получи готовый кружок!\n\n"
    "Кружок будет не длиннее 60 секунд — возьму начало видео.\n"
    "Совет: отправляй видео обычным способом (со сжатием), тогда оно почти всегда влезет в 20 МБ."
)


def make_circle(src: str, dst: str, pos: float = 0.5) -> None:
    """Вырезает квадрат из видео и готовит его под кружок.
    pos: 0 — верх/лево, 0.5 — центр, 1 — низ/право."""
    side = "min(iw,ih)"
    # выражения в кавычках, иначе ffmpeg спутает запятые внутри min() с разделителем фильтров
    crop = f"crop='{side}':'{side}':'(iw-{side})*{pos}':'(ih-{side})*{pos}'"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", src,
            "-t", str(MAX_SECONDS),
            "-vf", f"{crop},scale={SIZE}:{SIZE},setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            dst,
        ],
        check=True,
        capture_output=True,
    )


def crop_keyboard(width: int | None, height: int | None) -> InlineKeyboardMarkup:
    """Кнопки выбора части кадра. Подписи зависят от того, вертикальное видео или горизонтальное."""
    if width and height and width > height:
        labels = ("⬅️ Слева", "⏺ Центр", "Справа ➡️")
    elif width and height:
        labels = ("⬆️ Верх", "⏺ Центр", "⬇️ Низ")
    else:
        labels = ("⬆️ Верх / лево", "⏺ Центр", "⬇️ Низ / право")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=labels[0], callback_data="crop:0"),
        InlineKeyboardButton(text=labels[1], callback_data="crop:0.5"),
        InlineKeyboardButton(text=labels[2], callback_data="crop:1"),
    ]])


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Пришли мне видео (до 20 МБ), и я сделаю из него кружок ⭕️\n"
        "Ты сможешь выбрать, какую часть кадра взять."
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP_TEXT)


@dp.message(F.video | F.document | F.animation)
async def handle_video(message: Message):
    media = message.video or message.animation or message.document
    if message.document and not (message.document.mime_type or "").startswith("video"):
        await message.answer("Это не похоже на видео 🤔 Пришли видеофайл.")
        return
    if media.file_size and media.file_size > MAX_MB * 1024 * 1024:
        await message.answer(f"Видео больше {MAX_MB} МБ, такое я не могу скачать 😔 Попробуй покороче.")
        return

    width = getattr(media, "width", None)
    height = getattr(media, "height", None)

    # Квадратное видео обрезать не нужно — сразу делаем кружок
    if width and height and width == height:
        status = await message.answer("Делаю кружок… ⏳")
        await process(message.chat.id, media.file_id, 0.5, status)
        return

    ask = await message.answer(
        "Какую часть кадра взять в кружок?",
        reply_markup=crop_keyboard(width, height),
    )
    pending[ask.message_id] = media.file_id


@dp.callback_query(F.data.startswith("crop:"))
async def on_crop_choice(call: CallbackQuery):
    pos = float(call.data.split(":", 1)[1])
    file_id = pending.pop(call.message.message_id, None)
    if file_id is None:
        await call.answer("Это видео уже устарело, пришли его ещё раз 🙏", show_alert=True)
        return
    await call.answer()
    status = await call.message.edit_text("Делаю кружок… ⏳")
    await process(call.message.chat.id, file_id, pos, status)


async def process(chat_id: int, file_id: str, pos: float, status: Message):
    # Пока идёт обработка, в чате виден статус «записывает видео…»
    async with ChatActionSender.record_video_note(bot=bot, chat_id=chat_id):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in")
            dst = os.path.join(tmp, "out.mp4")
            try:
                await bot.download(file_id, destination=src)
                await asyncio.to_thread(make_circle, src, dst, pos)
                await bot.send_video_note(chat_id, FSInputFile(dst), length=SIZE)
                await status.delete()
            except Exception:
                logging.exception("Не получилось обработать видео")
                await status.edit_text("Что-то пошло не так 😕 Попробуй другое видео.")


@dp.message()
async def other(message: Message):
    await message.answer("Пришли мне видео, и я сделаю из него кружок ⭕️\nПодробнее — /help")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
