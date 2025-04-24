import asyncio
import aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from datetime import datetime
import logging
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import re
from datetime import datetime, timedelta
class CodeFSM(StatesGroup):
    waiting_for_code = State()
    waiting_summ = State()
    withdraw_send_ = State()
dp = Dispatcher(storage=MemoryStorage())

ADMIN_IDS = [7430202822]  # Админ ID
API_TOKEN="7962915576:AAGnnphRS8YMsBT12jbczCpmcbKRy9fZaC8"
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))




# ====== FSM Состояния ======
class CodeFSM(StatesGroup):
    waiting_for_code = State()
    waiting_summ = State()
    withdraw_send_ = State()

class SubmitNumber(StatesGroup):
    choosing_tariff = State()
    entering_number = State()
    waiting_confirmation = State()

class AdminAction(StatesGroup):
    confirming_status = State()

# ====== Тарифы ======
TARIFFS = {
    "30 min - 5$": {"label": "30 min - 5$"},
    "1h - 11$": {"label": "1h - 11$"},
    "2h - 17$": {"label": "2h - 17$"},
    "3h - 26$": {"label": "3h - 26$"}
}

# ====== База данных (в памяти) ======
user_data = {}  # user_id: {'balance': int, 'history': list}
submitted_numbers = []  # список сданных номеров
submission_queue = []
timeout_minutes = 1.5


# ====== Клавиатуры ======
def main_menu():
    kb = ReplyKeyboardBuilder()
    kb.button(text="📲 Сдать номер")
    kb.button(text="📋 Очередь")
    kb.button(text="📜 История")
    kb.button(text="🛠 Админка")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def tariff_keyboard():
    kb = InlineKeyboardBuilder()
    for tariff in TARIFFS:
        kb.button(text=tariff, callback_data=f"tariff:{tariff}")
    return kb.as_markup()

def confirm_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="confirm")
    return kb.as_markup()

# ====== Команды ======
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {"balance": 0, "history": []}
    await message.answer("Добро пожаловать в бот!", reply_markup=main_menu())

@dp.message(F.text == "📲 Сдать номер")
async def submit_number(message: Message, state: FSMContext):
    await state.set_state(SubmitNumber.choosing_tariff)
    await message.answer("Выберите тариф:", reply_markup=tariff_keyboard())

@dp.callback_query(F.data.startswith("tariff:"))
async def chosen_tariff(callback: CallbackQuery, state: FSMContext):
    tariff = callback.data.split(":", 1)[1]
    await state.update_data(tariff=tariff)
    await state.set_state(SubmitNumber.entering_number)
    await callback.message.answer("Введите номер, который хотите сдать:")
    await callback.answer()

@dp.message(SubmitNumber.entering_number)
async def entered_number(message: Message, state: FSMContext):
    raw = message.text.strip()
    phone = re.sub(r"[^\d+]", "", raw)  

    if phone.startswith("8"):
        phone = "+7" + phone[1:]
    elif phone.startswith("+7"):
        pass
    else:
        await message.answer("❌ Неверный формат. Введите российский номер, начинающийся с 8 или +7.")
        return

    if not re.fullmatch(r"\+7\d{10}", phone):
        await message.answer("❌ Некорректный номер. Формат: +7XXXXXXXXXX (11 цифр).")
        return

    await state.update_data(number=phone, timestamp=datetime.now())
    await state.set_state(SubmitNumber.waiting_confirmation)
    await message.answer(f"Вы ввели номер: {phone}\nНажмите для подтверждения:", reply_markup=confirm_keyboard())

async def remove_inactive_users():
    while True:
        now = datetime.now()
        to_remove = []
        for entry in submission_queue:
            if (now - entry['submitted']) > timedelta(minutes=timeout_minutes):
                to_remove.append(entry)

        for entry in to_remove:
            submission_queue.remove(entry)
            try:
                await bot.send_message(entry['user_id'], "⏳ Ваш номер был удалён из очереди из-за бездействия.")
            except:
                pass

        await asyncio.sleep(60)
@dp.callback_query(F.data == "confirm")
async def confirm_number(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    required_fields = ['number', 'tariff', 'timestamp']
    if any(field not in data for field in required_fields):
        await callback.message.answer("Ошибка: отсутствуют данные. Попробуйте начать сначала.")
        return

    entry = {
        "user_id": user_id,
        "username": callback.from_user.username or "без ника",
        "number": data['number'],
        "tariff": data['tariff'],
        "submitted": data['timestamp'],
        "status": "🟡 Ожидание"
    }
    submission_queue.append(entry)
    submitted_numbers.append(entry)
    user_data.setdefault(user_id, {"balance": 0, "history": []})
    user_data[user_id]["history"].append(entry)

    user_entries = [e for e in submission_queue if e['user_id'] == user_id]
    is_first_for_user = user_entries[0] == entry
    is_first_global = submission_queue[0] == entry

    if is_first_for_user and is_first_global:
        await notify_admin(entry)
        await callback.message.answer("Номер отправлен на проверку ✅")
    else:
        await callback.message.answer(f"Вы добавлены в очередь ✅\n🔢 Ваша позиция: {submission_queue.index(entry)+1}")

        # Уведомление при приближении к началу очереди
        if len(submission_queue) >= 2 and submission_queue[1]['user_id'] == user_id:
            await bot.send_message(user_id, "🔔 Вы следующий в очереди! Подготовьтесь к проверке номера.")

    await state.clear()
    await callback.answer()

async def notify_admin(entry):
    admin_text = (
        f"📥 Новый номер от @{entry['username']}\n"
        f"📱 Номер: {entry['number']}\n"
        f"📦 Тариф: {entry['tariff']}\n"
        f"🕓 Время: {entry['submitted'].strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"🔍 Для обработки используй команду /numbers"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🔑 Отправить код", callback_data=f"send_code:{entry['user_id']}"),
        InlineKeyboardButton(text="🚫 Отменить", callback_data=f"cancel_entry:{entry['user_id']}")
    ]
])
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=keyboard)
        except Exception as e:
            print(f"Ошибка отправки админу: {e}")
async def process_next_in_queue():
    if submission_queue:
        await notify_admin(submission_queue[0])
@dp.callback_query(F.data.startswith("cancel_entry:"))
async def cancel_submission(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.split(":")[1])
    action, idx = callback.data.split(":")[1:]
    idx = int(idx)
    removed = False
    for entry in list(submission_queue):
        if entry["user_id"] == user_id:
            entry = submitted_numbers.pop(idx)
            submission_queue.remove(entry)
            submitted_numbers.remove(entry)
            try:
                await bot.send_message(user_id, "🚫 Ваш номер был отменён админом и удалён из очереди.")
            except:
                pass
            removed = True
            break

    if removed:
        await callback.message.answer("Номер успешно отменён.")
        await process_next_in_queue()
    else:
        await callback.message.answer("Номер не найден или уже удалён.")

    await callback.answer()


@dp.callback_query(F.data.startswith("send_code:"))
async def ask_admin_to_enter_code(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещён.")
        return

    user_id = int(callback.data.split(":")[1])
    await state.set_state(CodeFSM.waiting_for_code)
    await state.update_data(target_user=user_id)
    await callback.message.answer(f"Введите код для пользователя {user_id}:")
    await callback.answer()
@dp.message(CodeFSM.waiting_for_code)
async def handle_admin_code_entry(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['target_user']
    code = message.text.strip()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить код", callback_data=f"confirm_code:{code}")]
    ])
    await bot.send_message(user_id, f"🔐 Ваш код: <code>{code}</code>\nНажмите 'Подтвердить код'.", reply_markup=markup)
    await message.answer("Код отправлен пользователю ✅")
    await state.clear()
@dp.callback_query(F.data.startswith("confirm_code:"))
async def confirm_code_(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await bot.send_message(user_id, text="Вы успешно подтвердили код!\n\nНе заходите на аккаунт, ожидайте сообщений.")
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f"Пользователь c ID [{user_id}] подтвердил код.")

    if submission_queue and submission_queue[0]["user_id"] == user_id:
        submission_queue.pop(0)
        await process_next_in_queue()
    await state.clear()

@dp.message(F.text == "📋 Очередь")
async def show_queue(message: Message):
    user_id = message.from_user.id
    if not submission_queue:
        await message.answer("Очередь пуста.")
        return

    position = next((i + 1 for i, e in enumerate(submission_queue) if e["user_id"] == user_id), None)
    queue_text = "\n".join([f"{i+1}) @{e['username']} | {e['number']} ({e['tariff']})" for i, e in enumerate(submission_queue)])
    if position:
        await message.answer(f"📋 Общая очередь:\n{queue_text}\n\n🔢 Ваша позиция в очереди: {position}")
    else:
        await message.answer(f"📋 Общая очередь:\n{queue_text}\n\nВы не в очереди.")
@dp.message(F.text == "📜 История")
async def show_history(message: Message):
    user_id = message.from_user.id
    history = user_data.get(user_id, {}).get("history", [])
    if not history:
        await message.answer("История пуста.")
    else:
        text = "".join([f"{i+1}) Номер: {e['number']}Тариф: {e['tariff']}Статус: {e['status']}" for i, e in enumerate(history)])
        await message.answer("📜 Ваша история:" + text)


@dp.message(F.text == "🛠 Админка")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    kb = ReplyKeyboardBuilder()
    kb.button(text="/numbers")
    await message.answer("🛠 Админ-панель", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "/numbers")
async def list_submitted_numbers(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not submitted_numbers:
        await message.answer("Нет сданных номеров.")
        return

    kb = InlineKeyboardBuilder()
    for i, entry in enumerate(submitted_numbers):
        label = f"{entry['number']} ({entry['tariff']})"
        kb.button(text=label, callback_data=f"number:{i}")
    await message.answer("📋 Сданные номера:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("number:"))
async def show_number_details(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    entry = submitted_numbers[idx]
    time = entry['submitted'].strftime('%d.%m.%Y %H:%M:%S')

    text = (
        f"Номер: {entry['number']}\n"
        f"Тариф: {entry['tariff']}\n"
        f"Пользователь: @{entry['username']}\n"
        f"Сдан: {time}\n"
        f"Статус: {entry['status']}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Не слет", callback_data=f"verdict:noslet:{idx}")
    kb.button(text="❌ Слет", callback_data=f"verdict:slet:{idx}")
    kb.button(text="🚫 Отмена", callback_data=f"verdict:cancel:{idx}")


    await callback.message.answer(text, reply_markup=kb.as_markup())
    await callback.answer()


async def update_status(idx, new_status, callback: CallbackQuery, reward_user=False):
    user_id = int(user_id)
    entry = submitted_numbers[idx]
    entry["status"] = new_status
    await callback.message.answer(f"Статус обновлён: {new_status}")
    await bot.send_message(user_id, text="Новый статус! Посмотрите историю.")
    await callback.answer()



@dp.callback_query(F.data.startswith("verdict:"))
async def handle_verdict(callback: CallbackQuery):
    try:
        action, idx = callback.data.split(":")[1:]
        idx = int(idx)

        entry = submitted_numbers[idx]
        user_id = entry["user_id"]
        number = entry["number"]
        tariff = entry["tariff"]
        submitted = entry["submitted"].strftime('%d.%m.%Y %H:%M:%S')
        if action == "noslet":
            text = (
                f"✅ Ваш номер {number} выстоял на тарифе {tariff}.\n"
                f"📅 Время сдачи: {submitted}\n"
                f"⏳ Отстоял до: сейчас"
            )
            entry["status"] = "✅ выстоял"
            entry = submitted_numbers.pop(idx)
        elif action == "slet":
            text = (
                f"❌ Увы, ваш номер {number} слетел на тарифе {tariff}.\n"
                f"📅 Время сдачи: {submitted}"
            )
            entry["status"] = "❌ слет"
            entry = submitted_numbers.pop(idx)
        elif action == "cancel":
            text = (
                f"🚫 Админ отменил ваш номер {number}.\n"
                f"📅 Время сдачи: {submitted}"
            )
            entry["status"] = "🚫 отменён"
            entry = submitted_numbers.pop(idx)
        else:
            await callback.answer("Неизвестное действие.")
            return

        await bot.send_message(user_id, text)
        await callback.answer("Сообщение отправлено.")
    except Exception as e:
        print(f"[handle_verdict] Ошибка: {e}")
        await callback.answer("Ошибка.")


# ====== Запуск ======
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
