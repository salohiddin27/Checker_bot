import os
from dotenv import load_dotenv
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, BotCommand
)

# --- KONFIGURATSIYA
load_dotenv()
API_TOKEN = os.getenv('BOT_TOKEN')

admin_id_raw = os.getenv('ADMIN_ID', '')
ADMIN_IDS = [int(i.strip()) for i in admin_id_raw.split(',') if i.strip()]

OVOZ_BERISH_LINKI = "https://openbudget.uz/boards/initiatives/initiative/53/77c5ee52-c435-4996-9e47-817b79671b70"


# --- MA'LUMOTLAR BAZASI ---
def init_db():
    conn = sqlite3.connect("ovoz_bot.db")
    cursor = conn.cursor()
    # Users jadvali: user_id, ism, o'z telefon raqami va to'plagan ballari
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (
                          user_id
                          INTEGER
                          PRIMARY
                          KEY,
                          full_name
                          TEXT,
                          phone
                          TEXT,
                          score
                          INTEGER
                          DEFAULT
                          0
                      )''')
    conn.commit()
    conn.close()


# --- HOLATLAR (FSM) ---
class Register(StatesGroup):
    full_name = State()
    phone = State()


class Vote(StatesGroup):
    vote_phone = State()
    photo = State()


bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# --- TUGMALAR ---
def main_menu():
    kb = [
        [KeyboardButton(text="Ovoz berdim ✅")],
        [KeyboardButton(text="Mening hisobim 📊")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def phone_kb():
    kb = [[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)


# --- START VA RO'YXATDAN O'TISH ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("ovoz_bot.db")
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        await message.answer(f"Xush kelibsiz, {user[1]}!", reply_markup=main_menu())
    else:
        await message.answer(
            "Assalomu alaykum! Botdan foydalanish uchun ro'yxatdan o'tishingiz kerak.\n\nTo'liq ism-familiyangizni kiriting:")
        await state.set_state(Register.full_name)


@dp.message(Register.full_name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Rahmat. Endi o'z telefon raqamingizni pastdagi tugma orqali yuboring:",
                         reply_markup=phone_kb())
    await state.set_state(Register.phone)


@dp.message(Register.phone, F.contact)
async def reg_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_phone = message.contact.phone_number

    conn = sqlite3.connect("ovoz_bot.db")
    conn.execute("""
            INSERT OR REPLACE INTO users (user_id, full_name, phone, score) 
            VALUES (?, ?, ?, COALESCE((SELECT score FROM users WHERE user_id = ?), 0))
        """, (message.from_user.id, data['full_name'], user_phone, message.from_user.id))
    conn.commit()
    conn.close()

    await message.answer("Tabriklaymiz! Ro'yxatdan muvaffaqiyatli o'tdingiz.", reply_markup=main_menu())
    await state.clear()


# --- OVOZ BERISH VA HISOBOT YUBORISH ---
@dp.message(F.text == "Ovoz berdim ✅")
async def vote_start(message: types.Message, state: FSMContext):
    await message.answer(
        f"🔗 Ovoz berish uchun havola: {OVOZ_BERISH_LINKI}\n\n"
        "Ovoz bergan telefon raqamingizni yozib yuboring:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Vote.vote_phone)


@dp.message(Vote.vote_phone)
async def vote_num(message: types.Message, state: FSMContext):
    # Foydalanuvchi yuborgan ovoz berilgan raqamni saqlaymiz
    await state.update_data(vote_phone=message.text)
    await message.answer("Endi ushbu raqam bilan ovoz berganingizni tasdiqlovchi skrinshotni (rasm shaklida) yuboring:")
    await state.set_state(Vote.photo)


@dp.message(Vote.photo, F.photo)
async def vote_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id  # Eng sifatli rasmni olamiz

    # Admin uchun tasdiqlash tugmalari
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"ok_{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"no_{message.from_user.id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                caption=f"🔔 Yangi hisobot!\n👤 Kimdan: {message.from_user.full_name}\n📞 Ovoz berilgan raqam: {data['vote_phone']}",
                reply_markup=markup
            )
        except Exception as e:
            logging.error(f"Adminga ({admin_id}) yuborishda xatolik: {e}")

    await message.answer("Hisobotingiz qabul qilindi. Admin tasdiqlashini kuting.", reply_markup=main_menu())
    await state.clear()


# --- ADMIN VERIFIKATSIYASI ---
@dp.callback_query(F.data.startswith("ok_") | F.data.startswith("no_"))
async def admin_verify(callback: types.CallbackQuery):
    action, user_id = callback.data.split("_")
    user_id = int(user_id)

    if action == "ok":
        conn = sqlite3.connect("ovoz_bot.db")
        conn.execute("UPDATE users SET score = score + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        await bot.send_message(user_id, "✅ Sizning ovozingiz tasdiqlandi va balingizga qo'shildi!")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ HOLAT: TASDIQLANDI")
    else:
        await bot.send_message(user_id,
                               "❌ Ovozingiz rad etildi. Ma'lumotlarni to'g'ri yuborganingizga ishonch hosil qiling.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ HOLAT: RAD ETILDI")

    await callback.answer()


# --- STATISTIKA ---
@dp.message(F.text == "Mening hisobim 📊")
async def my_stats(message: types.Message):
    conn = sqlite3.connect("ovoz_bot.db")
    user = conn.execute("SELECT score FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        await message.answer(f"📊 Sizning jami to'plagan ovozlaringiz: {user[0]} ta")


@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect("ovoz_bot.db")
    users = conn.execute("SELECT full_name, score FROM users ORDER BY score DESC").fetchall()
    conn.close()

    text = "🏆 Foydalanuvchilar reytingi (Ovozlar soni):\n\n"
    for i, u in enumerate(users, 1):
        text += f"{i}. {u[0]} — {u[1]} ta\n"

    if not users: text = "Hozircha hech kim ro'yxatdan o'tmagan."
    await message.answer(text)

@dp.message(Command("clear_db"))
async def clear_database(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect("ovoz_bot.db")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()

    await message.answer("✅ Ma'lumotlar bazasi to'liq tozalandi!")


async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    await bot.set_my_commands([BotCommand(command='start', description='Botni yangilash 🔄')])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

