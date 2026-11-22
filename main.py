import asyncio
import os
import re
import sqlite3
import html
import uuid
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    ReplyParameters,
    BotCommand,
    BotCommandScopeChat,
)
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

# Первая группа: сюда отправляют расписание.
SOURCE_GROUP_ID = int(os.getenv("SOURCE_GROUP_ID", "0"))

# Вторая группа: здесь бот читает ДЗ и публикует готовое расписание.
TARGET_GROUP_ID = int(os.getenv("TARGET_GROUP_ID", "0"))

ACCESS_CODE = os.getenv("ACCESS_CODE", "Анаконда")

if not TOKEN:
    raise ValueError("Не указан BOT_TOKEN в файле .env")

router = Router()
DB_NAME = "homework.db"

# Активные таймеры подтверждения ДЗ: token -> событие отмены.
pending_homework = {}
# Ожидающие выбора предмета для команды /dz.
pending_dz_selections = {}

# Ожидающие сообщения для команды /q: (chat_id, user_id) -> ID сообщений.
pending_q_messages = {}


async def finish_q_attempt(message: Message, success: bool):
    """Завершает попытку /q и удаляет четыре сообщения."""
    if not message.from_user:
        return False

    key = (message.chat.id, message.from_user.id)
    pending = pending_q_messages.pop(key, None)

    if not pending:
        return False

    sent_successfully = False

    if success:
        try:
            if SOURCE_GROUP_ID == 0:
                raise ValueError("Не указан SOURCE_GROUP_ID")

            # Копируем исходное сообщение (текст, фото или файл)
            # в первую группу, откуда оно передаётся в MAX.
            await message.bot.copy_message(
                chat_id=SOURCE_GROUP_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent_successfully = True
        except Exception as error:
            print(f"Не удалось передать сообщение в MAX: {error}")

    if not success:
        status_text = "Попытка отправки сообщения в MAX прервана ❌"
    elif sent_successfully:
        status_text = "Попытка отправки сообщения в MAX успешна ✅"
    else:
        status_text = "Не удалось отправить сообщение в MAX ❌"

    status = await message.answer(status_text)

    # Даём пользователю время увидеть результат, затем удаляем всю цепочку.
    await asyncio.sleep(2)

    message_ids = [
        pending["command_message_id"],
        pending["prompt_message_id"],
        message.message_id,
        status.message_id,
    ]

    results = await asyncio.gather(
        *[
            message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=message_id,
            )
            for message_id in message_ids
            if message_id is not None
        ],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, Exception):
            print(f"Не удалось удалить сообщение из попытки /q: {result}")

    return True



HOMEWORK_COMMANDS = {
    "dz": "сохранить сообщение как ДЗ",
    "istoriya": "история",
    "biologiya": "биология",
    "fizika": "физика",
    "himiya": "химия",
    "russkiy": "русский язык",
    "literatura": "литература",
    "obshchestvo": "обществознание",
    "geografiya": "география",
    "algebra_baza": "алгебра",
    "geometriya_baza": "геометрия",
    "veroyatnost_baza": "вероятность",
    "informatika_baza": "информатика",
    "angliyskiy_profil": "иностранный язык",
    "new": "узнать информацию о последнем обновлении",
    "q": "отправить фото/текст/файл в MAX",
    "qq": "Отмена отправки в MAX",
    "ras": "отправить последнее расписание",
}

NEW_MESSAGE = (
    "Обновление Бота до версии 2.2!\n\n"
    "<b>⭐ Нововведения!</b>\n"
    "<blockquote>"
    "1. Добавлена возможность отправлять фото/файл в МАХ.\n"
    "2. Слегка изменен дизайн указания дз."
    "</blockquote>\n\n"
    "<b>🛠️ Исправления!</b>\n"
    "<blockquote>"
    "1. При отправке объявления в расписании бот указывал на него дз.\n"
    "2. При объявлении в расписании бот приписывает его к уроку"
    "</blockquote>"
)


# Канонические названия предметов и варианты их написания.
SUBJECTS = {
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
        "вероятность профилю", "вероятность, профилю",
    ],
    "русский язык": [
        "русский язык", "русскому языку", "русский", "русскому",
    ],
    "литература": [
        "литература", "литературе", "литра", "литре", "лит-ра", "лит-ре",
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

# Если в расписании предмет указан без уточнения,
# проверяем ДЗ сразу для базы и профиля.
SHARED_SUBJECTS = {
    "информатика": [
        ("информатика база", "Информатика база"),
        ("информатика профиль", "Информатика профиль"),
    ],
    "иностранный": [
        ("иностранный язык база", "Иностранный база"),
        ("иностранный язык профиль", "Иностранный профиль"),
    ],
    "иностранный язык": [
        ("иностранный язык база", "Иностранный база"),
        ("иностранный язык профиль", "Иностранный профиль"),
    ],
    "английский": [
        ("иностранный язык база", "Иностранный база"),
        ("иностранный язык профиль", "Иностранный профиль"),
    ],
    "алгебра": [
        ("алгебра база", "Алгебра база"),
        ("алгебра профиль", "Алгебра профиль"),
    ],
    "геометрия": [
        ("геометрия база", "Геометрия база"),
        ("геометрия профиль", "Геометрия профиль"),
    ],
    "вероятность": [
        ("вероятность база", "Вероятность база"),
        ("вероятность профиль", "Вероятность профиль"),
    ],
}

def get_schedule_homework_subjects(item):
    """Возвращает предметы, по которым нужно искать ДЗ для урока."""

    canonical = item["canonical"]
    display = item["display"]

    # Если в расписании уже указана база или профиль,
    # проверяем только этот конкретный предмет.
    if canonical:
        return [(canonical, display)]

    normalized = re.sub(
        r"[\s,]+", " ", display.lower()
    ).strip().strip(" .,:;")

    # Если уточнения нет — проверяем и базу, и профиль.
    if normalized in SHARED_SUBJECTS:
        return SHARED_SUBJECTS[normalized]

    # Для остальных предметов оставляем старое поведение.
    return [(None, display)]

def get_homework_lookup_subjects(name):
    """Определяет, по каким предметам искать ДЗ по запросу из чата."""

    cleaned = name.strip().strip(" .,:;")
    normalized = re.sub(
        r"[\s,]+", " ", cleaned.casefold()
    ).strip()

    # Если предмет указан точно, например «История»
    # или «Информатика профиль».
    canonical = subject_from_name(cleaned)

    if canonical:
        return [(canonical, cleaned)]

    # Если предмет указан без уточнения,
    # например «Информатика», проверяем базу и профиль.
    if normalized in SHARED_SUBJECTS:
        return SHARED_SUBJECTS[normalized]

    return []


async def send_homework_by_subject(message: Message, subject_name: str):
    """Отправляет сохранённое ДЗ по запрошенному предмету."""

    subjects = get_homework_lookup_subjects(subject_name)

    if not subjects:
        await message.answer(
            f"Не удалось распознать предмет: {html.escape(subject_name)}"
        )
        return

    output = []
    photo_replies = []

    for canonical, display_name in subjects:
        photo = get_homework_photo(canonical)
        task = get_homework(canonical)

        if photo:
            photo_replies.append((display_name, photo))


        elif task:

            output.append(

                f"<b>{html.escape(display_name)}:</b>\n"

                f"<blockquote>{html.escape(task)}</blockquote>"

            )

        else:
            output.append(
                f"<b>{html.escape(display_name)}:</b>\n"
                f"<blockquote>не нашел:(</blockquote>"
            )

    # Отправляем текстовый результат, только если он есть.
    if output:
        await message.answer(
            "\n".join(output),
            parse_mode="HTML",
        )


    # Удаляем команду, которой запросили ДЗ.
    try:
        await message.delete()
    except Exception as error:
        print(f"Не удалось удалить команду запроса ДЗ: {error}")

    # Если ДЗ — фотография, дополнительно отвечаем на исходное фото.
    for display_name, photo in photo_replies:
        _file_id, source_chat_id, source_message_id = photo

        try:
            await message.bot.send_message(
                chat_id=source_chat_id,
                text=f"ДЗ {display_name}:",
                reply_parameters=ReplyParameters(
                    message_id=source_message_id,
                    allow_sending_without_reply=True,
                ),
            )
        except Exception as error:
            print(f"Не удалось ответить на фото по предмету {display_name}: {error}")



async def start_dz_selection(message: Message):
    """Показывает клавиатуру выбора предмета для команды /dz."""

    # Проверяем, что /dz отправлена ответом на другое сообщение.
    original = message.reply_to_message

    if not original:
        await message.answer(
            "Ответь командой /dz на сообщение, которое хочешь сохранить."
        )
        return

    # Получаем текст исходного сообщения.
    task_text = original.text or original.caption or ""

    # Проверяем, есть ли в сообщении фотография.
    photo_file_id = None

    if original.photo:
        photo_file_id = original.photo[-1].file_id

    # Не разрешаем сохранять пустые сообщения и неподдерживаемые файлы.
    if not task_text and not photo_file_id:
        await message.answer(
            "Можно сохранить только текстовое сообщение или фотографию."
        )
        return

    # Создаём уникальный номер выбора.
    token = uuid.uuid4().hex

    # Запоминаем исходное сообщение и пользователя.
    pending_dz_selections[token] = {
        "user_id": message.from_user.id,
        "chat_id": original.chat.id,
        "message_id": original.message_id,
        "task": task_text,
        "photo_file_id": photo_file_id,
    }

    # Запоминаем, какой пользователь сейчас выбирает предмет.
    pending_dz_selections[token]["token"] = token

    # Создаём кнопки с названиями предметов.
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=subject.capitalize())
            ]
            for subject in SUBJECTS
        ] + [
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    pointer = await message.answer(
        "👇",
        reply_markup=keyboard,
    )

    pending_dz_selections[token]["command_message_id"] = message.message_id
    pending_dz_selections[token]["pointer_message_id"] = pointer.message_id


async def finish_dz_selection(message: Message, subject: str):
    """Сохраняет исходное сообщение как ДЗ выбранного предмета."""

    user_id = message.from_user.id

    # Ищем незавершённый выбор этого пользователя.
    token = None
    selection = None

    for current_token, data in pending_dz_selections.items():
        if data["user_id"] == user_id:
            token = current_token
            selection = data
            break

    if not selection:
        return False

    # Если выбрана отмена — ничего не сохраняем.
    if subject == "❌ Отмена":
        # Сохраняем ID сообщений, которые нужно удалить.
        command_message_id = selection.get("command_message_id")
        pointer_message_id = selection.get("pointer_message_id")

        # Удаляем незавершённый выбор.
        pending_dz_selections.pop(token, None)

        # Отправляем подтверждение и убираем клавиатуру.
        confirmation = await message.answer(
            f"ДЗ по предмету «{subject}» успешно сохранено! ✅",
            reply_markup=ReplyKeyboardRemove(),
        )


        # Одновременно удаляем все четыре сообщения.
        messages_to_delete = [
            command_message_id,
            pointer_message_id,
            message.message_id,
            confirmation.message_id,
        ]

        for message_id in messages_to_delete:
            if message_id:
                try:
                    await message.bot.delete_message(
                        chat_id=message.chat.id,
                        message_id=message_id,
                    )
                except Exception as error:
                    print(
                        f"Не удалось удалить сообщение {message_id}: {error}"
                    )

        return True

    # Проверяем, существует ли такой предмет.
    canonical = subject_from_name(subject)

    if not canonical:
        await message.answer(
            "Не удалось определить предмет. Выбери его кнопкой."
        )
        return True

    # Если исходное сообщение было фотографией.
    if selection["photo_file_id"]:
        save_homework_photo(
            subject=canonical,
            file_id=selection["photo_file_id"],
            chat_id=selection["chat_id"],
            message_id=selection["message_id"],
        )

    # Если исходное сообщение было текстом.
    else:
        task = selection["task"].strip()

        # Убираем название предмета из начала задания,
        # если оно уже присутствует в сообщении.
        _, match = find_subject_match(task)

        if match and match.start() == 0:
            task = task[match.end():]
            task = re.sub(r"^[\s:—–\-.,]+", "", task)

        save_homework(
            subject=canonical,
            task=task,
            source=selection["task"],
        )

    # Запоминаем ID команды и указателя.
    command_message_id = selection.get("command_message_id")
    pointer_message_id = selection.get("pointer_message_id")

    # Удаляем незавершённый выбор.
    pending_dz_selections.pop(token, None)

    # Отправляем подтверждение и убираем клавиатуру.
    confirmation = await message.answer(
        f"ДЗ по предмету «{subject}» успешно сохранено! ✅",
        reply_markup=ReplyKeyboardRemove(),
    )


    # Собираем ID всех четырёх сообщений.
    messages_to_delete = [
        command_message_id,
        pointer_message_id,
        message.message_id,
        confirmation.message_id,
    ]

    # Создаём запросы на удаление всех сообщений.
    delete_tasks = [
        message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=message_id,
        )
        for message_id in messages_to_delete
        if message_id is not None
    ]

    # Запускаем удаление одновременно.
    results = await asyncio.gather(
        *delete_tasks,
        return_exceptions=True,
    )

    # Выводим ошибки, если какие-то сообщения удалить не удалось.
    for result in results:
        if isinstance(result, Exception):
            print(f"Ошибка при удалении сообщения: {result}")

    return True



@router.callback_query(F.data.startswith("dz_cancel:"))
async def cancel_dz_selection(callback: CallbackQuery):
    token = callback.data.split(":", 1)[1]

    selection = pending_dz_selections.get(token)

    if not selection:
        await callback.answer("Выбор уже завершён.")
        return

    if callback.from_user.id != selection["user_id"]:
        await callback.answer(
            "Эту клавиатуру открыл другой пользователь.",
            show_alert=True,
        )
        return

    pending_dz_selections.pop(token, None)

    await callback.message.edit_text(
        "Сохранение ДЗ отменено ❌"
    )

    await callback.answer("Отменено.")


def build_subject_patterns():
    variants = []
    for subject, aliases in SUBJECTS.items():
        for alias in aliases:
            words = re.findall(r"\w+", alias.lower())
            if not words:
                continue
            pattern = r"(?<!\w)" + r"[\s,]+".join(
                re.escape(word) for word in words
            ) + r"(?!\w)"
            variants.append((len(alias), subject, pattern))
    variants.sort(reverse=True)
    return variants


SUBJECT_PATTERNS = build_subject_patterns()


def find_subject_match(line):
    for _, subject, pattern in SUBJECT_PATTERNS:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return subject, match
    return None, None


def subject_from_name(name):
    cleaned = re.sub(r"[/,:;.!]+$", "", name.strip()).strip()
    normalized = re.sub(r"[\s,]+", " ", cleaned.casefold()).strip()
    for subject, aliases in SUBJECTS.items():
        candidates = [subject] + aliases
        for candidate in candidates:
            candidate_normalized = re.sub(
                r"[\s,]+", " ", candidate.casefold()
            ).strip()
            if normalized == candidate_normalized:
                return subject
    # Не используем find_subject_match для определения точного названия:
    # эта функция ищет предмет внутри строки и может принять
    # «Геометрия» за начало «Геометрия база» или «Геометрия профиль».
    # Точные варианты уже проверены выше.
    return None


def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS homework (
                subject TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY,
                authorized_at TEXT NOT NULL
            )
        """)
        # Фотографии хранятся отдельно, чтобы не менять старую таблицу homework.
        db.execute("""
            CREATE TABLE IF NOT EXISTS homework_photos (
                subject TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Храним последнее опубликованное расписание.
        db.execute("""
            CREATE TABLE IF NOT EXISTS last_schedule (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

def save_last_schedule(text):
        """Сохраняет последнее опубликованное расписание."""
        with sqlite3.connect(DB_NAME) as db:
            db.execute("""
                INSERT INTO last_schedule (id, text, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = excluded.updated_at
            """, (text, datetime.now().isoformat()))

def get_last_schedule():
        """Возвращает последнее сохранённое расписание."""
        with sqlite3.connect(DB_NAME) as db:
            row = db.execute(
                "SELECT text FROM last_schedule WHERE id = 1"
            ).fetchone()

        return row[0] if row else None


def save_homework(subject, task, source):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            INSERT INTO homework (subject, task, updated_at, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET
                task = excluded.task,
                updated_at = excluded.updated_at,
                source = excluded.source
        """, (subject, task, datetime.now().isoformat(), source))
        # Новое текстовое ДЗ заменяет старую фотографию по предмету.
        db.execute("DELETE FROM homework_photos WHERE subject = ?", (subject,))


def save_homework_photo(subject, file_id, chat_id, message_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("DELETE FROM homework WHERE subject = ?", (subject,))
        db.execute("""
            INSERT INTO homework_photos
                (subject, file_id, source_chat_id, source_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET
                file_id = excluded.file_id,
                source_chat_id = excluded.source_chat_id,
                source_message_id = excluded.source_message_id,
                updated_at = excluded.updated_at
        """, (
            subject, file_id, chat_id, message_id, datetime.now().isoformat()
        ))


def get_homework(subject):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute(
            "SELECT task FROM homework WHERE subject = ?", (subject,)
        ).fetchone()
    return row[0] if row else None


def get_homework_photo(subject):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute("""
            SELECT file_id, source_chat_id, source_message_id
            FROM homework_photos WHERE subject = ?
        """, (subject,)).fetchone()
    return row


def is_user_authorized(user_id):
    with sqlite3.connect(DB_NAME) as db:
        row = db.execute(
            "SELECT 1 FROM authorized_users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None


def authorize_user(user_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute(
            """INSERT OR IGNORE INTO authorized_users (user_id, authorized_at)
               VALUES (?, ?)""",
            (user_id, datetime.now().isoformat()),
        )


def split_subject_segments(text):
    # Косая черта и перенос строки могут разделять два предмета одного урока.
    return [
        part.strip()
        for part in re.split(r"[/\n]+", text)
        if part.strip()
    ]


def subjects_in_text(text):
    found = []
    for line in text.splitlines():
        for segment in re.split(r"/+", line):
            subject, _ = find_subject_match(segment)
            if subject and subject not in found:
                found.append(subject)
    if not found:
        subject, _ = find_subject_match(text)
        if subject:
            found.append(subject)
    return found


def process_message(text):
    """Находит текстовые задания. Ничего не сохраняет самостоятельно."""
    lines = text.splitlines()
    found = []

    for index, line in enumerate(lines):
        # Поддерживаем несколько предметов, разделённых косой чертой.
        segments = re.split(r"/+", line)
        for segment in segments:
            subject, match = find_subject_match(segment)
            if not subject:
                continue

            task = segment[match.end():].strip()
            task = re.sub(r"^[\s:—–\-.,]+", "", task)
            task = re.sub(
                r"^(?:дз|д/з|домашнее задание)\s*[:\-—]?\s*",
                "",
                task,
                flags=re.IGNORECASE,
            )

            if not task:
                for next_line in lines[index + 1:]:
                    candidate = next_line.strip()
                    if not candidate:
                        continue
                    next_subject, _ = find_subject_match(candidate)
                    if next_subject:
                        break
                    task = candidate
                    break

            if task and len(task) >= 2:
                # Удаляем возможные остатки разделителей.
                task = task.strip(" /")
                if task and not any(item[0] == subject for item in found):
                    found.append((subject, task))

    return found


def parse_schedule(text):
    """Разбирает расписание, в том числе заголовок «Имя: Расписание...»."""
    lessons = []
    current = None
    title = "Расписание"

    lines = text.splitlines()
    if lines:
        # Удаляем имя перед заголовком: «Михаил: Расписание...».
        lines[0] = re.sub(
            r"^\s*[^:\n]{1,60}:\s*(?=расписание\b)",
            "",
            lines[0],
            flags=re.IGNORECASE,
        )
        # Если заголовок и первый урок находятся на одной строке,
        # переносим номер урока на новую строку.
        inline_header = re.match(
            r"^(.*?\bрасписание\b.*?)(?=\s+\d+(?:\s*,\s*\d+)*(?:[.)]\s*|\s+урок(?:и|а)?\s+))",
            lines[0],
            flags=re.IGNORECASE,
        )
        if inline_header:
            lines[0] = (
                inline_header.group(1).strip()
                + "\n"
                + lines[0][inline_header.end():].strip()
            )

    normalized_text = "\n".join(lines)
    nonempty = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    if nonempty and not re.match(r"^\d+(?:\s*,\s*\d+)*(?:[.)]\s*|\s+урок(?:и|а)?\s+)", nonempty[0], re.IGNORECASE):
        title = nonempty[0]

    for raw_line in normalized_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        numbered = re.match(r"^(\d+(?:\s*,\s*\d+)*)(?:[.)]\s*|\s+урок(?:и|а)?\s+)(.*)$", line, re.IGNORECASE)
        if numbered:
            current = {
                "number": numbered.group(1),
                "parts": [numbered.group(2).strip()] if numbered.group(2).strip() else [],
                "pedklass": False,
            }
            lessons.append(current)
            continue

        if current is None:
            continue

        if line.casefold() == "педкласс":
            current["pedklass"] = True
        else:
            current["parts"].append(line)

    for lesson in lessons:
        raw = "\n".join(lesson["parts"])
        parts = split_subject_segments(raw)
        lesson["subjects"] = []
        for part in parts:
            display = re.sub(r"\s+", " ", part).strip().strip(" ,")
            if not display:
                continue
            canonical = subject_from_name(display)
            lesson["subjects"].append({
                "display": display,
                "canonical": canonical,
            })

        if lesson["pedklass"] and lesson["subjects"]:
            lesson["subjects"][-1]["display"] += " / Педкласс"

    return title, lessons


async def ask_to_confirm_homework(
    message: Message,
    subject: str,
    task: str,
    source: str,
    photo_file_id=None,
):
    """Спрашивает подтверждение ДЗ; без отказа сохраняет через 10 секунд."""
    token = uuid.uuid4().hex
    cancel_event = asyncio.Event()
    pending_homework[token] = cancel_event

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Отказ",
                callback_data=f"reject_hw:{token}",
            )
        ]]
    )

    reply_parameters = ReplyParameters(
        message_id=message.message_id,
        quote=(
            task
            if task and task in (message.text or "")
            else None
        ),
        allow_sending_without_reply=True,
    )

    try:
        confirmation = await message.bot.send_message(
            chat_id=message.chat.id,
            text="Это ДЗ?\n(10 сек.)",
            reply_markup=keyboard,
            reply_parameters=reply_parameters,
        )

        remaining = 10

        for _ in range(5):
            try:
                await asyncio.wait_for(
                    cancel_event.wait(),
                    timeout=2,
                )

                pending_homework.pop(token, None)
                await confirmation.edit_text(
                    "Запись ДЗ отменена ❌",
                    reply_markup=None,
                )
                await asyncio.sleep(2)
                await confirmation.delete()
                return

            except asyncio.TimeoutError:
                remaining -= 2

                if remaining > 0:
                    await confirmation.edit_text(
                        f"Это ДЗ?\n({remaining} сек.)",
                        reply_markup=keyboard,
                    )

        pending_homework.pop(token, None)

        # Если это фотография — сохраняем её.
        if photo_file_id:
            save_homework_photo(
                subject=subject,
                file_id=photo_file_id,
                chat_id=message.chat.id,
                message_id=message.message_id,
            )
        else:
            # Если это текст — сохраняем текст.
            save_homework(subject, task, source)

        await confirmation.edit_text(
            "Запись ДЗ успешна ✅",
            reply_markup=None,
        )
        await asyncio.sleep(2)
        await confirmation.delete()

    except asyncio.CancelledError:
        pending_homework.pop(token, None)
        raise

    except Exception:
        pending_homework.pop(token, None)
        raise


@router.callback_query(F.data.startswith("reject_hw:"))
async def reject_homework(callback: CallbackQuery):
    token = callback.data.split(":", 1)[1]
    cancel_event = pending_homework.get(token)
    if cancel_event:
        cancel_event.set()
        await callback.answer("Запись ДЗ отменяется!")
    else:
        await callback.answer(
            "Время для отмены уже закончилось.",
            show_alert=True,
        )


@router.message(Command("id"))
async def get_chat_id(message: Message):
    await message.answer(
        f"ID этого чата: `{message.chat.id}`",
        parse_mode="Markdown"
    )


@router.message(Command("start"), F.chat.type == "private")
async def start_private_chat(message: Message):
    if message.from_user and is_user_authorized(message.from_user.id):
        await message.answer(
            "Доступ уже подтверждён. Отправьте расписание в первую группу."
        )
    else:
        await message.answer("Приветствую! Введите кодовое слово.")


@router.message(F.chat.type == "private", F.text)
async def check_access_code(message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    if is_user_authorized(user_id):
        await message.answer(
            "Доступ уже подтверждён. Отправьте расписание в первую группу."
        )
        return

    if message.text.strip().casefold() == ACCESS_CODE.strip().casefold():
        authorize_user(user_id)
        await message.answer(
            "Доступ подтверждён, можете отправлять расписание в первую группу."
        )
    else:
        await message.answer("Неверное кодовое слово. Попробуйте ещё раз.")


# Первая группа: бот только получает расписание и ничего туда не отправляет.
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def receive_schedule_or_homework(message: Message):
    if message.chat.id == SOURCE_GROUP_ID:
        # Пересылаем сообщения, начинающиеся с «Михаил: "»
        # или «Михаил: «», во вторую группу.
        match = re.match(
            r"^\s*Анна Ефремова\s*:\s*",
            message.text,
            flags=re.IGNORECASE,
        )

        # Пересылаем объявления Анны,
        # но не пересылаем расписание без обработки.
        if match and not re.search(
                r"\bрасписание\b",
                message.text,
                flags=re.IGNORECASE,
        ):
            if TARGET_GROUP_ID != 0:
                clean_text = message.text[match.end():].strip()

                if clean_text:
                    await message.bot.send_message(
                        chat_id=TARGET_GROUP_ID,
                        text=clean_text,
                    )
            return


        if TARGET_GROUP_ID == 0:
            print("Не указан TARGET_GROUP_ID в .env")
            return

        # Разбираем расписание только для поиска предметов и ДЗ.
        title, lessons = parse_schedule(message.text)

        # Убираем имя автора из исходного сообщения.
        original_lines = message.text.splitlines()

        if original_lines:
            original_lines[0] = re.sub(
                r"^\s*Анна Ефремова\s*:\s*",
                "",
                original_lines[0],
                count=1,
                flags=re.IGNORECASE,
            )

        # Берём всё содержимое после заголовка как есть.
        schedule_body = "\n".join(original_lines[1:]).strip("\n")

        # Формируем только заголовок, остальной текст не перестраиваем.
        output = [
            f"<b>📚 {html.escape(title)}</b>"
        ]

        if schedule_body:
            output.append(html.escape(schedule_body))

        photo_replies = []
        homework_output = []
        seen_homework = set()

        # Ищем ДЗ по распознанным предметам.
        for lesson in lessons:
            subjects = lesson["subjects"]

            for item in subjects:
                display_name = item["display"]

                clean_display = re.sub(
                    r"\s*/\s*педкласс$",
                    "",
                    display_name,
                    flags=re.IGNORECASE,
                ).strip()

                normalized = re.sub(
                    r"[\s,]+", " ", clean_display.casefold()
                ).strip(" .,:;")

                # Неизвестные объявления не считаем предметами.
                if (
                    not item["canonical"]
                    and normalized not in SHARED_SUBJECTS
                ):
                    continue

                homework_subjects = get_schedule_homework_subjects(item)

                for canonical, homework_display in homework_subjects:
                    key = canonical or homework_display.casefold()

                    if key in seen_homework:
                        continue

                    seen_homework.add(key)

                    if canonical:
                        photo = get_homework_photo(canonical)
                        task = get_homework(canonical)
                    else:
                        photo = None
                        task = None

                    homework_name = re.sub(
                        r"\s*/\s*педкласс$",
                        "",
                        homework_display,
                        flags=re.IGNORECASE,
                    )

                    homework_name = re.sub(
                        r"\s*,\s*",
                        " ",
                        homework_name,
                    ).strip()

                    if photo:
                        homework_output.append(
                            f"<b>{html.escape(homework_name)}:</b> "
                            "<i>(отметил ниже)</i>"
                        )
                        photo_replies.append((homework_name, photo))

                    elif task:
                        homework_output.append(
                            f"<b>{html.escape(homework_name)}:</b>\n"
                            f"<blockquote>{html.escape(task)}</blockquote>"
                        )

                    else:
                        homework_output.append(
                            f"<b>{html.escape(homework_name)}:</b>\n"
                            f"<blockquote>не нашел:(</blockquote>"
                        )

        # Добавляем блок ДЗ после исходного расписания.
        output.append("")
        output.append("<b>📝 ДЗ:</b>")

        if homework_output:
            output.extend(homework_output)
        else:
            output.append("Домашних заданий нет.")

        schedule_text = "\n".join(output)

        schedule_message = await message.bot.send_message(
            chat_id=TARGET_GROUP_ID,
            text=schedule_text,
            parse_mode="HTML",
        )

        # Сохраняем готовое сообщение для команды /ras.
        save_last_schedule(schedule_text)

        # Отвечаем на исходные фотографии с ДЗ.
        for display_name, photo in photo_replies:
            _file_id, source_chat_id, source_message_id = photo

            try:
                await message.bot.send_message(
                    chat_id=source_chat_id,
                    text=f"ДЗ {display_name}:",
                    reply_parameters=ReplyParameters(
                        message_id=source_message_id,
                        allow_sending_without_reply=True,
                    ),
                )
            except Exception as error:
                print(
                    f"Не удалось ответить на фото по предмету "
                    f"{display_name}: {error}"
                )

        print(
            f"Расписание из группы {SOURCE_GROUP_ID} опубликовано "
            f"в группе {TARGET_GROUP_ID}. "
            f"ID сообщения: {schedule_message.message_id}"
        )
        return


    # Вторая группа: сообщения с ДЗ. Бот здесь ничего не отвечает,
    # пока не публикует готовое расписание по сообщению из первой группы.
    if message.chat.id == TARGET_GROUP_ID:
        if message.from_user and message.from_user.is_bot:
            return

        # Пока пользователь ожидает отправки, /qq отменяет её,
        # а любое другое текстовое сообщение считается содержимым для MAX.
        if message.from_user:
            q_key = (message.chat.id, message.from_user.id)
            command_text = message.text.strip().split()[0].split("@")[0]

            if command_text == "/qq":
                if await finish_q_attempt(message, success=False):
                    return
                return

            if q_key in pending_q_messages:
                await finish_q_attempt(message, success=True)
                return

        # Обработка команд получения ДЗ.
        if message.text.startswith("/"):
            command = message.text.split()[0]
            command = command.split("@")[0].lstrip("/")

            # Команда /q — начать отправку сообщения в MAX.
            if command == "q":
                if not message.from_user:
                    return

                key = (message.chat.id, message.from_user.id)

                # Если у пользователя уже есть активная попытка, не создаём вторую.
                if key in pending_q_messages:
                    await message.answer(
                        "У тебя уже есть активная попытка. "
                        "Отправь сообщение или /qq для отмены."
                    )
                    return

                if SOURCE_GROUP_ID == 0:
                    await message.answer("Не указана первая группа.")
                    return

                username = (
                    f"@{message.from_user.username}"
                    if message.from_user.username
                    else message.from_user.full_name
                )

                prompt = await message.answer(
                    f"{username}, жду сообщение/фото/файл."
                )

                pending_q_messages[key] = {
                    "command_message_id": message.message_id,
                    "prompt_message_id": prompt.message_id,
                }
                return

            # Команда /ras — повторно отправить последнее расписание.
            if command == "ras":
                last_schedule = get_last_schedule()

                if last_schedule:
                    await message.bot.send_message(
                        chat_id=TARGET_GROUP_ID,
                        text=last_schedule,
                        parse_mode="HTML",
                    )
                else:
                    await message.answer(
                        "Пока нет сохранённого расписания."
                    )

                # Удаляем сообщение с командой /ras.
                try:
                    await message.delete()
                except Exception as error:
                    print(
                        f"Не удалось удалить команду /ras: {error}"
                    )

                return

            if command == "dz":
                await start_dz_selection(message)
                return

            subject_name = HOMEWORK_COMMANDS.get(command)


            if command == "new":
                await message.bot.send_message(
                    chat_id=TARGET_GROUP_ID,
                    text=NEW_MESSAGE,
                    parse_mode="HTML",
                )
                return

            if subject_name:
                await send_homework_by_subject(
                    message,
                    subject_name,
                )
            return
        # Если пользователь выбирает предмет для команды /dz.
        if await finish_dz_selection(
                message,
                message.text.strip(),
        ):
            return

        found_homework = process_message(message.text)
        for subject, task in found_homework:
            asyncio.create_task(
                ask_to_confirm_homework(
                    message,
                    subject,
                    task,
                    message.text,
                )
            )


# Фотографии с подписью-предметом читаем только во второй группе.
@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.photo,
)
async def collect_photo_homework(message: Message):
    if message.chat.id != TARGET_GROUP_ID:
        return

    if message.from_user and message.from_user.is_bot:
        return

    # Если пользователь ожидает отправки через /q, фото завершает попытку.
    if await finish_q_attempt(message, success=True):
        return

    caption = message.caption or ""
    subjects = subjects_in_text(caption)

    if not subjects:
        print(
            "Получена фотография без распознанного предмета. "
            "Добавьте название предмета в подпись к фото."
        )
        return

    file_id = message.photo[-1].file_id

    for subject in subjects:
        asyncio.create_task(
            ask_to_confirm_homework(
                message=message,
                subject=subject,
                task=caption,
                source=caption,
                photo_file_id=file_id,
            )
        )



@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.document,
)
async def collect_q_document(message: Message):
    """Принимает файл как содержимое активной попытки /q."""
    if message.chat.id != TARGET_GROUP_ID:
        return

    if message.from_user and message.from_user.is_bot:
        return

    await finish_q_attempt(message, success=True)


async def main():
    init_db()

    if SOURCE_GROUP_ID == 0:
        print("ВНИМАНИЕ: SOURCE_GROUP_ID (первая группа с расписанием) не указан.")
    if TARGET_GROUP_ID == 0:
        print("ВНИМАНИЕ: TARGET_GROUP_ID (вторая группа с ДЗ и публикацией) не указан.")

    bot = Bot(token=TOKEN)

    # Регистрируем команды только для второй группы.
    commands = [
        BotCommand(
            command=command,
            description=f"{subject}",
        )
        for command, subject in HOMEWORK_COMMANDS.items()
    ]

    await bot.set_my_commands(
        commands=commands,
        scope=BotCommandScopeChat(chat_id=TARGET_GROUP_ID),
        language_code="ru",
    )

    dp = Dispatcher()
    dp.include_router(router)

    print("Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
