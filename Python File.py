
import asyncio
import html
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ReplyParameters,
)

# ========== НАСТРОЙКИ ==========

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROUP_1_ID = int(os.getenv("SOURCE_GROUP_ID", "0"))
GROUP_2_ID = int(os.getenv("TARGET_GROUP_ID", "0"))
SENDER_NAME = os.getenv("NICK_NAME", "")

SKIP_HOMEWORK = {
    "физкультура",
    "основы безопасности и защиты родины",
    "в мире профессий",
    "разговоры о важном",
    "индивидуальный проект",
}

TIMER_SECONDS = 10
TIMER_STEP = 3
DELETE_DELAY = 3

BASE_DIR = Path(__file__).resolve().parent

HW_FILE = BASE_DIR / "homework.json"
SCHEDULE_FILE = BASE_DIR / "schedule.json"

COMMANDS = {
    "istoriya": "история",
    "biologiya": "биология",
    "fizika": "физика",
    "himiya": "химия",
    "russkiy": "русский язык",
    "literatura": "литература",
    "obshchestvo": "обществознание",
    "geografiya": "география",
    "algebra": "алгебра",
    "geometriya": "геометрия",
    "veroyatnost": "вероятность",
    "informatika": "информатика",
    "angliyskiy": "иностранный язык",
}

SCHEDULE_ALIASES = {
    "английский язык": "иностранный язык",
    "английский": "иностранный язык",
    "вероятность и статистика": "вероятность",
    "русский": "русский язык",
}

VARIANTS = {
    "геометрия профиль": [
        "геометрия профиль", "геометрия, профиль",
        "геометрии профиль", "геометрии профилю",
        "геометрии, профиль", "геометрии, профилю",
    ],
    "геометрия база": [
        "геометрия база", "геометрия, база",
        "геометрии база", "геометрии базе",
        "геометрии, база", "геометрии, базе",
    ],
    "алгебра профиль": [
        "алгебра профиль", "алгебра, профиль",
        "алгебре профиль", "алгебре профилю",
        "алгебре, профиль", "алгебре, профилю",
    ],
    "алгебра база": [
        "алгебра база", "алгебра, база",
        "алгебре база", "алгебре базе",
        "алгебре, база", "алгебре, базе",
    ],
    "вероятность база": [
        "вероятность база", "вероятность, база",
        "вероятности база", "вероятности, базе",
    ],
    "вероятность профиль": [
        "вероятность профиль", "вероятность, профиль",
        "вероятности профилю", "вероятности, профилю",
        "вероятность профилю", "вероятности, профилю",
    ],
    "русский язык": [
        "русский язык", "русскому языку", "русский", "русскому",
    ],
    "литература": [
        "литература", "литературе", "литра", "литре",
        "лит-ра", "лит-ре",
    ],
    "физика": ["физика", "физике"],
    "химия": ["химия", "химии"],
    "биология": ["биология", "биологии"],
    "история": ["история", "истории"],
    "иностранный язык профиль": [
        "английский язык профиль", "английский язык, профиль",
        "английский профиль", "английский, профиль",
        "английскому профиль", "английскому, профиль",
        "английскому профилю", "английскому, профилю",
        "иностранный язык профиль", "иностранный язык, профиль",
        "иностранный профиль", "иностранный, профиль",
        "иностранному профиль", "иностранному, профиль",
        "иностранному профилю", "иностранному, профилю",
    ],
    "иностранный язык база": [
        "английский язык база", "английский язык, база",
        "английский база", "английский, база",
        "английскому база", "английскому, база",
        "английскому базе", "английскому, базе",
        "иностранный язык база", "иностранный язык, база",
        "иностранный база", "иностранный, база",
        "иностранному база", "иностранному, база",
        "иностранному базе", "иностранному, базе",
    ],
    "обществознание": [
        "обществознание", "обществознанию", "общество", "обществу",
    ],
    "информатика профиль": [
        "информатика профиль", "информатика, профиль",
        "информатике профиль", "информатике, профиль",
        "информатике профилю", "информатике, профилю",
    ],
    "информатика база": [
        "информатика база", "информатика, база",
        "информатике база", "информатике, база",
        "информатике базе", "информатике, базе",
    ],
    "география": ["география", "географии"],
}

# =================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher()

# ---------- ВСПОМОГАТЕЛЬНОЕ ----------

def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def norm(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def split_level(key: str) -> tuple[str, str | None]:
    for level in ("база", "профиль"):
        if key.endswith(" " + level):
            return key[:-len(level) - 1], level
    return key, None


GROUPS: dict[str, list[str]] = {}

for _key in VARIANTS:
    GROUPS.setdefault(split_level(_key)[0], []).append(_key)

for _keys in GROUPS.values():
    _keys.sort(key=lambda k: k.endswith("профиль"))

VARIANT_TO_KEY = {
    norm(v): key
    for key, variants in VARIANTS.items()
    for v in variants
}


def display(key: str) -> str:
    if key.startswith("иностранный язык"):
        key = "английский язык" + key[len("иностранный язык"):]
    return key[:1].upper() + key[1:]


# Названия для клавиатуры /dz
SUBJECT_LABELS = {
    key: display(key)
    for key in VARIANTS
}

LABEL_TO_KEY = {
    norm(label): key
    for key, label in SUBJECT_LABELS.items()
}


# ---------- УДАЛЕНИЕ СООБЩЕНИЙ ----------

async def safe_delete(chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass


async def delete_message(message: Message):
    await safe_delete(message.chat.id, message.message_id)


# ---------- ХРАНЕНИЕ ДЗ ----------

def load_homework() -> dict:
    if not HW_FILE.exists():
        return {}

    try:
        raw = json.loads(HW_FILE.read_text(encoding="utf-8"))
        return {norm(k): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        logging.exception("Ошибка чтения homework.json")
        return {}


def save_homework(key: str, value):
    data = load_homework()
    data[key] = value

    HW_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_photo_homework(hw) -> bool:
    return isinstance(hw, dict) and hw.get("type") == "photo"


def get_text_homework(hw) -> str | None:
    if isinstance(hw, str):
        return hw

    if isinstance(hw, dict) and hw.get("type") == "text":
        return hw.get("text")

    return None


def format_hw_block(title: str, hw) -> str:
    if is_photo_homework(hw):
        body = "(Отметил ниже)"
    else:
        text = get_text_homework(hw)
        body = esc(text) if text else "не нашел:("

    return (
        f"<b>{esc(title)}:</b>\n"
        f"<blockquote>{body}</blockquote>"
    )


# ---------- ПОСЛЕДНЕЕ РАСПИСАНИЕ ----------

def save_schedule(text: str):
    SCHEDULE_FILE.write_text(
        json.dumps({"text": text}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_schedule() -> str | None:
    if not SCHEDULE_FILE.exists():
        return None

    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))

        # Поддержка как нового, так и простого строкового формата
        if isinstance(data, dict):
            return data.get("text")

        if isinstance(data, str):
            return data

    except (json.JSONDecodeError, OSError):
        logging.exception("Ошибка чтения schedule.json")

    return None


# ---------- РАСПИСАНИЕ ----------

SENDER_RE = re.compile(
    rf"^\s*{re.escape(SENDER_NAME)}\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

SCHEDULE_RE = re.compile(
    r"^\s*расписание уроков",
    re.IGNORECASE,
)

LESSON_RE = re.compile(r"^\s*\d+\s*[.)]\s*(.+?)\s*$")

LEVEL_RE = re.compile(
    r"^(.+?)[,\s]+(профиль|база)[\s/\\.,;:]*$",
    re.IGNORECASE,
)


def extract_text(raw: str) -> str | None:
    match = SENDER_RE.match(raw)

    if not match:
        return None

    return match.group(1).strip() or None


def lesson_items(name: str) -> list[tuple[str | None, str]]:
    n = norm(name)

    # Убираем лишние знаки в конце названия предмета
    n = re.sub(r"[\s/\\.,;:]+$", "", n)

    if n in SKIP_HOMEWORK:
        return []

    match = LEVEL_RE.match(n)

    base, level = (
        (match.group(1).strip(), match.group(2).lower())
        if match else (n, None)
    )

    base = SCHEDULE_ALIASES.get(base, base)

    if base in SKIP_HOMEWORK:
        return []

    keys = GROUPS.get(base)

    if not keys:
        return [(None, name)]

    if level and len(keys) > 1:
        selected_key = f"{base} {level}"

        if selected_key in keys:
            keys = [selected_key]

    return [(k, display(k)) for k in keys]



def homework_items(lines: list[str]):
    result = []
    seen = set()

    for line in lines:
        match = LESSON_RE.match(line)

        if match:
            # Обычная строка с номером урока.
            name = match.group(1)
        else:
            # Проверяем строку без номера:
            # например, «Алгебра, база».
            name = line.strip()

            n = norm(name)
            n = re.sub(r"[\s/\\.,;:]+$", "", n)

            level_match = LEVEL_RE.match(n)

            base = (
                level_match.group(1).strip()
                if level_match
                else n
            )

            base = SCHEDULE_ALIASES.get(base, base)

            # Продолжаем только если это известный предмет.
            if base not in GROUPS:
                continue

        for key, title in lesson_items(name):
            ident = key or norm(title)

            if ident not in seen:
                seen.add(ident)
                result.append((key, title))

    return result


def format_schedule(text: str) -> str:
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        return esc(text)

    # Заголовок расписания со смайликом
    result = [f"📚 <b>{esc(lines[0])}</b>"]

    # Сами уроки
    for line in lines[1:]:
        result.append(esc(line))

    # Собираем предметы для блока ДЗ
    items = homework_items(lines[1:])
    data = load_homework()

    homework_blocks = []

    for key, title in items:
        if not key:
            continue

        hw = data.get(key)
        homework_blocks.append(
            format_hw_block(title, hw)
        )

    if homework_blocks:
        result.append("")
        result.append("📝 <b>ДЗ:</b>")
        result.append("")
        result.extend(homework_blocks)

    return "\n".join(result)



async def send_schedule(chat_id: int, text: str):
    schedule_message = await bot.send_message(
        chat_id,
        format_schedule(text),
    )

    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        return schedule_message

    items = homework_items(lines[1:])
    data = load_homework()

    for key, title in items:
        if not key:
            continue

        hw = data.get(key)

        if not is_photo_homework(hw):
            continue

        source_chat_id = hw.get("source_chat_id")
        source_message_id = hw.get("source_message_id")

        kwargs = {}

        # Если фотография находится в том же чате,
        # отправляем название предмета ответом на неё.
        if (
            source_message_id
            and source_chat_id == chat_id
        ):
            kwargs["reply_parameters"] = ReplyParameters(
                message_id=source_message_id,
                allow_sending_without_reply=True,
            )

        await bot.send_message(
            chat_id=chat_id,
            text=f"<b>{esc(title)}:</b>",
            **kwargs,
        )

    return schedule_message



# ---------- ПРЕДМЕТНЫЕ КОМАНДЫ ----------

async def send_subject_command(message: Message, group: str):
    data = load_homework()
    keys = GROUPS.get(group, [])

    if not keys:
        return

    values = [(key, data.get(key)) for key in keys]

    # Если фотографий нет, сохраняем прежний формат:
    # все предметы отправляются одним сообщением.
    if not any(is_photo_homework(hw) for _, hw in values):
        text = "\n\n".join(
            format_hw_block(display(key), hw)
            for key, hw in values
        )

        await message.answer(text)
        return

    # Если есть фотографии, отправляем каждый предмет отдельно.
    for key, hw in values:
        title = display(key)

        if is_photo_homework(hw):
            source_chat_id = hw.get("source_chat_id")
            source_message_id = hw.get("source_message_id")

            kwargs = {}

            if (
                    source_message_id
                    and (
                    source_chat_id is None
                    or source_chat_id == message.chat.id
            )
            ):
                kwargs["reply_parameters"] = ReplyParameters(
                    message_id=source_message_id,
                    allow_sending_without_reply=True,
                )

            await bot.send_message(
                chat_id=message.chat.id,
                text=f"<b>{esc(title)}:</b>",
                **kwargs,
            )

        else:
            await message.answer(
                format_hw_block(title, hw)
            )


# ---------- ЗАПИСЬ ДЗ С ТАЙМЕРОМ ----------

def _variant_pattern(variant: str) -> str:
    words = (
        re.escape(w).replace("е", "[её]")
        for w in variant.split()
    )

    return r"\s+".join(words)


def remove_subject_prefix(text: str) -> str:
    pattern = (
        r"^\s*("
        + "|".join(
            _variant_pattern(v)
            for v in sorted(VARIANT_TO_KEY, key=len, reverse=True)
        )
        + r")(?:\s*:\s*|\s+)"
    )

    return re.sub(
        pattern,
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


HW_RE = re.compile(
    r"^\s*("
    + "|".join(
        _variant_pattern(v)
        for v in sorted(VARIANT_TO_KEY, key=len, reverse=True)
    )
    + r")(?:\s*:\s*|\s+)(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_homework(text: str):
    match = HW_RE.match(text)

    if not match:
        return None

    key = VARIANT_TO_KEY.get(norm(match.group(1)))
    body = match.group(2).strip()

    if not key or not body:
        return None

    return key, body


def parse_photo_homework(caption: str):
    if not caption:
        return None

    # Сначала пробуем обычный формат: «Химия: § 12»
    parsed = parse_homework(caption)

    if parsed:
        return parsed

    # Отдельно разрешаем пустое ДЗ: «Химия:»
    match = re.match(
        r"^\s*("
        + "|".join(
            _variant_pattern(v)
            for v in sorted(VARIANT_TO_KEY, key=len, reverse=True)
        )
        + r")\s*:\s*$",
        caption,
        re.IGNORECASE,
    )

    if not match:
        return None

    key = VARIANT_TO_KEY.get(norm(match.group(1)))

    if not key:
        return None

    return key, ""


def confirm_text(left: int) -> str:
    return f"Это дз? ({left} сек.)"


def cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Отказ",
                callback_data="hw_cancel",
            )
        ]]
    )


pending: set[tuple[int, int]] = set()
background_tasks: set[asyncio.Task] = set()


async def safe_edit(
    msg: Message,
    text: str,
    kb: InlineKeyboardMarkup | None = None,
):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


async def finish(msg: Message, text: str):
    await safe_edit(msg, text)

    await asyncio.sleep(DELETE_DELAY)

    await delete_message(msg)


async def run_timer(sent: Message, key_: str, homework):
    timer_key = (sent.chat.id, sent.message_id)

    left = TIMER_SECONDS

    while left > 0:
        wait = min(TIMER_STEP, left)

        await asyncio.sleep(wait)
        left -= wait

        if timer_key not in pending:
            return

        if left > 0:
            await safe_edit(
                sent,
                confirm_text(left),
                cancel_kb(),
            )

    pending.discard(timer_key)

    # Приводим обычный текст к единому формату.
    if isinstance(homework, str):
        homework = {
            "type": "text",
            "text": homework,
        }

    save_homework(key_, homework)

    await finish(sent, "Запись дз успешна ✅")


# ---------- /DZ: СОСТОЯНИЕ ВЫБОРА ----------

# (chat_id, user_id) -> информация о текущем выборе
pending_dz: dict[tuple[int, int], dict] = {}


def make_subject_keyboard() -> ReplyKeyboardMarkup:
    labels = list(SUBJECT_LABELS.values())

    keyboard = []

    # Две кнопки в строке
    for i in range(0, len(labels), 2):
        keyboard.append([
            KeyboardButton(text=labels[i]),
            *(
                [KeyboardButton(text=labels[i + 1])]
                if i + 1 < len(labels)
                else []
            ),
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
        selective=True,
        input_field_placeholder="Выбери школьный предмет",
    )


async def cancel_dz_selection(
    chat_id: int,
    user_id: int,
    selection_message: Message | None = None,
):
    state = pending_dz.pop((chat_id, user_id), None)

    if not state:
        return

    # Убираем клавиатуру
    remove_msg = await bot.send_message(
        chat_id,
        "Выбор сброшен.",
        reply_markup=ReplyKeyboardRemove(),
    )

    if selection_message:
        await delete_message(selection_message)

    await safe_delete(chat_id, state["command_message_id"])
    await safe_delete(chat_id, state["prompt_message_id"])

    await asyncio.sleep(1)

    await delete_message(remove_msg)


# ---------- /DZ ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text.regexp(r"^/dz(?:@\w+)?(?:\s|$)")
)
async def dz_command(message: Message):
    logging.info(
        "/dz получена: user=%s, chat=%s, reply=%s",
        message.from_user.id if message.from_user else None,
        message.chat.id,
        message.reply_to_message.message_id if message.reply_to_message else None,
    )

    if not message.reply_to_message:
        await delete_message(message)
        await bot.send_message(
            GROUP_2_ID,
            "Нужно ответить этой командой на сообщение с домашним заданием.",
        )
        return

    source = message.reply_to_message

    if source.photo:
        homework = {
            "type": "photo",
            "file_id": source.photo[-1].file_id,
            "caption": remove_subject_prefix(source.caption or ""),
            "source_chat_id": source.chat.id,
            "source_message_id": source.message_id,
        }

    elif source.text:
        homework = {
            "type": "text",
            "text": remove_subject_prefix(source.text),
        }

    elif source.caption:
        homework = {
            "type": "text",
            "text": remove_subject_prefix(source.caption),
        }

    else:
        await delete_message(message)
        await bot.send_message(
            GROUP_2_ID,
            "Это сообщение нельзя использовать как ДЗ.",
        )
        return

    if not message.from_user:
        await delete_message(message)
        return

    state_key = (message.chat.id, message.from_user.id)

    # Удаляем старый незавершённый выбор, если он был
    old_state = pending_dz.pop(state_key, None)

    if old_state:
        await safe_delete(
            message.chat.id,
            old_state["command_message_id"],
        )
        await safe_delete(
            message.chat.id,
            old_state["prompt_message_id"],
        )

    # ВАЖНО: клавиатура отвечает на /dz,
    # чтобы selective=True показывал её автору команды.
    prompt = await bot.send_message(
        GROUP_2_ID,
        "Выбери предмет, к которому относится ДЗ:",
        reply_markup=make_subject_keyboard(),
        reply_parameters=ReplyParameters(
            message_id=message.message_id,
            allow_sending_without_reply=True,
        ),
    )

    pending_dz[state_key] = {
        "command_message_id": message.message_id,
        "prompt_message_id": prompt.message_id,
        "homework": homework,
    }

    # Удаляем /dz только после отправки клавиатуры
    await delete_message(message)

    logging.info(
        "Открыт выбор предмета: user=%s, homework_type=%s",
        message.from_user.id,
        homework["type"],
    )


# ---------- ОБРАБОТКА ВЫБОРА ПРЕДМЕТА ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text,
    lambda m: (
        m.from_user is not None
        and (m.chat.id, m.from_user.id) in pending_dz
        and not m.text.startswith("/")
    )
)
async def dz_subject_selection(message: Message):
    if not message.from_user:
        return

    state_key = (message.chat.id, message.from_user.id)
    state = pending_dz.get(state_key)

    if not state:
        return

    selected = LABEL_TO_KEY.get(norm(message.text))

    if not selected:
        await cancel_dz_selection(
            message.chat.id,
            message.from_user.id,
            message,
        )
        return

    save_homework(selected, state["homework"])
    pending_dz.pop(state_key, None)

    confirmation = await bot.send_message(
        message.chat.id,
        "Запись дз успешна ✅",
        reply_markup=ReplyKeyboardRemove(),
    )

    await safe_delete(message.chat.id, state["command_message_id"])
    await delete_message(message)

    await safe_delete(
        message.chat.id,
        state["prompt_message_id"],
    )

    await asyncio.sleep(2)
    await delete_message(confirmation)


# ---------- /RAS ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text.regexp(r"^/ras(?:@\w+)?(?:\s|$)")
)
async def ras_command(message: Message):
    schedule = load_schedule()

    if schedule:
        await send_schedule(GROUP_2_ID, schedule)
    else:
        await bot.send_message(
            GROUP_2_ID,
            "Пока нет сохранённого расписания.",
        )

    await delete_message(message)


# ---------- /Q И /QQ ----------

# (chat_id, user_id) -> message_id сообщения «жду от тебя сообщение»
forwarding_users: dict[tuple[int, int], int] = {}



@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text.regexp(r"^/q(?:@\w+)?(?:\s|$)")
)
async def q_command(message: Message):
    user = message.from_user

    if not user:
        await delete_message(message)
        return

    state_key = (message.chat.id, user.id)

    # Если режим уже включён, не создаём второй запрос
    if state_key in forwarding_users:
        await delete_message(message)
        return

    username = (
        f"@{user.username}"
        if user.username
        else user.full_name
    )

    prompt = await bot.send_message(
        GROUP_2_ID,
        f"{esc(username)}, жду от тебя сообщение для пересылки."
    )

    forwarding_users[state_key] = prompt.message_id

    await delete_message(message)


@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text.regexp(r"^/qq(?:@\w+)?(?:\s|$)")
)
async def qq_command(message: Message):
    user = message.from_user

    if not user:
        await delete_message(message)
        return

    state_key = (message.chat.id, user.id)

    # Выключаем режим пересылки
    prompt_id = forwarding_users.pop(state_key, None)

    # Удаляем команду /qq
    await delete_message(message)

    if prompt_id is None:
        return

    # Сообщаем об отмене
    confirmation = await bot.send_message(
        GROUP_2_ID,
        "Отправка отменена ❌"
    )

    # Удаляем сообщение с упоминанием пользователя
    await safe_delete(
        message.chat.id,
        prompt_id,
    )

    # Удаляем подтверждение через 2 секунды
    await asyncio.sleep(2)
    await delete_message(confirmation)


@dp.message(
    F.chat.id == GROUP_2_ID,
    lambda m: (
        m.from_user is not None
        and (m.chat.id, m.from_user.id) in forwarding_users
        and not (m.text or "").startswith("/")
    )
)
async def forward_user_message(message: Message):
    user = message.from_user

    if not user:
        return

    state_key = (message.chat.id, user.id)
    prompt_id = forwarding_users.get(state_key)

    if prompt_id is None:
        return

    try:
        # Пересылаем исходное сообщение, в том числе фото
        await bot.forward_message(
            chat_id=GROUP_1_ID,
            from_chat_id=GROUP_2_ID,
            message_id=message.message_id,
        )

    except TelegramAPIError:
        logging.exception("Ошибка пересылки сообщения")

        error_message = await bot.send_message(
            GROUP_2_ID,
            "Не удалось отправить сообщение ❌"
        )

        await asyncio.sleep(3)
        await delete_message(error_message)
        return

    # Пересылка успешна — выключаем режим
    forwarding_users.pop(state_key, None)

    confirmation = await bot.send_message(
        GROUP_2_ID,
        "Отправка успешна ✅"
    )

    # Удаляем сообщение «жду от тебя сообщение»
    await safe_delete(
        message.chat.id,
        prompt_id,
    )

    # Само сообщение пользователя НЕ удаляем
    # Оно остаётся во второй группе

    await asyncio.sleep(2)
    await delete_message(confirmation)



# ---------- ПРЕДМЕТНЫЕ КОМАНДЫ ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text.startswith("/")
)
async def subject_command(message: Message):
    cmd = (
        message.text.split()[0]
        [1:]
        .split("@")[0]
        .lower()
    )

    group = COMMANDS.get(cmd)

    if not group:
        return

    await send_subject_command(message, group)

    # Удаляем вызов команды
    await delete_message(message)


# ---------- АВТОМАТИЧЕСКОЕ ОБНАРУЖЕНИЕ РАСПИСАНИЯ ----------

@dp.message(F.chat.id == GROUP_1_ID, F.text)
async def from_group_1(message: Message):
    text = extract_text(message.text)

    if not text:
        return

    if SCHEDULE_RE.match(text):
        save_schedule(text)

        # Отправляем расписание и фотографии ДЗ.
        await send_schedule(GROUP_2_ID, text)

    else:
        await bot.send_message(
            GROUP_2_ID,
            esc(text),
        )


# ---------- АВТОМАТИЧЕСКОЕ ОБНАРУЖЕНИЕ ТЕКСТОВОГО ДЗ ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.text,
    lambda m: (
        m.from_user is not None
        and (m.chat.id, m.from_user.id) not in pending_dz
        and (m.chat.id, m.from_user.id) not in forwarding_users
        and not m.text.startswith("/")
    )
)
async def homework_message(message: Message):
    parsed = parse_homework(message.text)

    if not parsed:
        return

    subject_key, body = parsed
    text = confirm_text(TIMER_SECONDS)

    try:
        sent = await bot.send_message(
            message.chat.id,
            text,
            reply_markup=cancel_kb(),
            reply_parameters=ReplyParameters(
                message_id=message.message_id,
                quote=body,
            ),
        )
    except TelegramBadRequest:
        sent = await message.reply(
            text,
            reply_markup=cancel_kb(),
        )

    pending.add((sent.chat.id, sent.message_id))

    task = asyncio.create_task(
        run_timer(sent, subject_key, body)
    )

    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


# ---------- АВТОМАТИЧЕСКОЕ ОБНАРУЖЕНИЕ ФОТО-ДЗ ----------

@dp.message(
    F.chat.id == GROUP_2_ID,
    F.photo,
    lambda m: (
        m.from_user is not None
        and (m.chat.id, m.from_user.id) not in pending_dz
        and (m.chat.id, m.from_user.id) not in forwarding_users
    )
)
@dp.message(
    F.chat.id == GROUP_2_ID,
    F.photo,
    lambda m: (
        m.from_user is not None
        and (m.chat.id, m.from_user.id) not in pending_dz
        and (m.chat.id, m.from_user.id) not in forwarding_users
    )
)
async def photo_homework_message(message: Message):
    if not message.caption:
        return

    parsed = parse_photo_homework(message.caption)

    if not parsed:
        return

    subject_key, body = parsed

    homework = {
        "type": "photo",
        "file_id": message.photo[-1].file_id,
        "caption": body,
        "source_chat_id": message.chat.id,
        "source_message_id": message.message_id,
    }

    # Вместо немедленного сохранения спрашиваем подтверждение.
    sent = await bot.send_message(
        message.chat.id,
        confirm_text(TIMER_SECONDS),
        reply_markup=cancel_kb(),
        reply_parameters=ReplyParameters(
            message_id=message.message_id,
            allow_sending_without_reply=True,
        ),
    )

    timer_key = (sent.chat.id, sent.message_id)
    pending.add(timer_key)

    task = asyncio.create_task(
        run_timer(sent, subject_key, homework)
    )

    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


# ---------- ОТКАЗ ОТ АВТОМАТИЧЕСКОЙ ЗАПИСИ ----------

@dp.callback_query(F.data == "hw_cancel")
async def cancel_homework(callback: CallbackQuery):
    msg = callback.message

    key = (msg.chat.id, msg.message_id)

    if key not in pending:
        await callback.answer("Уже поздно")
        return

    pending.discard(key)

    await callback.answer()

    await finish(
        msg,
        "Запись дз отменена ❌",
    )


# ---------- КОМАНДЫ TELEGRAM ----------

async def setup_commands():
    # Сначала команды, которые должны быть сверху
    commands = [
        BotCommand(
            command="dz",
            description="Записать ДЗ",
        ),
        BotCommand(
            command="ras",
            description="Последнее расписание",
        ),
    ]

    # Затем все остальные команды
    commands.extend(
        BotCommand(
            command=cmd,
            description=display(group),
        )
        for cmd, group in COMMANDS.items()
    )

    commands.extend([
        BotCommand(
            command="q",
            description="Переслать сообщение в первую группу",
        ),
        BotCommand(
            command="qq",
            description="Завершить пересылку",
        ),
    ])

    scope = BotCommandScopeChat(chat_id=GROUP_2_ID)

    try:
        await asyncio.gather(
            bot.set_my_commands(
                commands=commands,
                scope=scope,
                language_code="ru",
            ),
            bot.set_my_commands(
                commands=commands,
                scope=scope,
            ),
        )

    except TelegramAPIError as e:
        logging.warning(
            "Не удалось обновить команды: %s",
            e,
        )


# ---------- ЗАПУСК ----------

if not TOKEN:
    raise RuntimeError("Не указан BOT_TOKEN в .env")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    await setup_commands()

    logging.info("Бот запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
