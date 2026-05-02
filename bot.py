import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from market import SERVERS, fetch_items_dict, fetch_marketplace, get_item_name_id, strip_enchant, WORKER
from database import init_db, get_user, update_user, get_all_active_users
import requests

# ─── Глобальный словарь предметов (id→name) ─────────────────────
ITEMS_DICT = {}

async def refresh_items():
    global ITEMS_DICT
    try:
        ITEMS_DICT = fetch_items_dict()
        print("Items loaded:", len(ITEMS_DICT))
    except Exception as e:
        print("Failed to load items:", e)

# ─── Telegram-отправка ──────────────────────────────────────────
async def send_telegram(chat_id: int, text: str, token: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        return r.ok
    except:
        return False

# ─── Утилиты для клавиатур ─────────────────────────────────────
def main_keyboard():
    buttons = [
        [InlineKeyboardButton("🌍 Выбрать сервер", callback_data="choose_server")],
        [InlineKeyboardButton("➕ Добавить предмет", callback_data="add_item")],
        [InlineKeyboardButton("📋 Мой список", callback_data="list")],
        [InlineKeyboardButton("🗑 Удалить предмет", callback_data="delete_item")],
        [InlineKeyboardButton("▶️ Запустить мониторинг", callback_data="start_monitor"),
         InlineKeyboardButton("⏹ Остановить", callback_data="stop_monitor")],
    ]
    return InlineKeyboardMarkup(buttons)

def server_keyboard(selected_id=None):
    btns = []
    for srv in SERVERS:
        label = srv["label"]
        if srv["id"] == selected_id:
            label = "✅ " + label
        btns.append([InlineKeyboardButton(label, callback_data=f"set_server_{srv['id']}")])
    btns.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(btns)

# ─── Команды ────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await refresh_items()
    user = update.effective_user
    db_user = get_user(user.id)
    text = (
        f"Привет, {user.full_name}! Я бот-мониторинг рынка Arizona RP.\n"
        f"Твой сервер: {SERVERS[db_user['server_id']]['label']}\n"
        f"Отслеживается предметов: {len(db_user['watchlist'])}\n"
        f"Мониторинг: {'🟢 активен' if db_user['monitor_active'] else '🔴 остановлен'}"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())

# ─── Обработчики кнопок ────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    db_user = get_user(user_id)

    if data == "back_to_main":
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=main_keyboard()
        )
    elif data == "choose_server":
        await query.edit_message_text(
            "Выбери сервер:",
            reply_markup=server_keyboard(db_user["server_id"])
        )
    elif data.startswith("set_server_"):
        srv_id = int(data.split("_")[2])
        update_user(user_id, server_id=srv_id)
        db_user = get_user(user_id)
        await query.edit_message_text(
            f"Сервер изменён на {SERVERS[srv_id]['label']}",
            reply_markup=main_keyboard()
        )
    elif data == "add_item":
        await query.edit_message_text(
            "Введи данные в формате:\n`Название предмета, макс.цена, валюта`\n"
            "Пример: `Хлопок, 130, VC$`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="back_to_main")]])
        )
        context.user_data["awaiting_item"] = True
    elif data == "list":
        wl = db_user["watchlist"]
        if wl:
            msg = "Твой список отслеживания:\n"
            for item in wl:
                msg += f"• {item['name']} ≤ {item['max_price']} {item['currency']}\n"
        else:
            msg = "Список пуст."
        await query.edit_message_text(msg, reply_markup=main_keyboard())
    elif data == "delete_item":
        await query.edit_message_text("Введи номер предмета для удаления (из списка).", reply_markup=main_keyboard())
        context.user_data["awaiting_delete"] = True
    elif data == "start_monitor":
        if not db_user["watchlist"]:
            await query.edit_message_text("❌ Добавь сначала предметы для отслеживания.", reply_markup=main_keyboard())
            return
        update_user(user_id, monitor_active=True)
        await query.edit_message_text("✅ Мониторинг запущен!", reply_markup=main_keyboard())
    elif data == "stop_monitor":
        update_user(user_id, monitor_active=False)
        await query.edit_message_text("⏹ Мониторинг остановлен.", reply_markup=main_keyboard())

# ─── Обработка текстовых сообщений (добавление предмета, удаление) ──
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    db_user = get_user(user_id)

    if context.user_data.get("awaiting_item"):
        context.user_data["awaiting_item"] = False
        try:
            parts = [p.strip() for p in text.split(",")]
            name = parts[0]
            max_price = int(parts[1].replace(" ", ""))
            currency = parts[2].upper()
            if currency not in ("VC$", "SA$"):
                raise ValueError
        except:
            await update.message.reply_text("Неверный формат. Попробуй ещё раз.", reply_markup=main_keyboard())
            return

        # Сразу выполняем поиск по текущему серверу
        srv_id = db_user["server_id"]
        srv = next(s for s in SERVERS if s["id"] == srv_id)
        currency_actual = "VC$" if srv_id == 0 else "SA$"
        if currency != currency_actual:
            await update.message.reply_text(
                f"На сервере {srv['label']} используется {currency_actual}, а ты указал {currency}. "
                "Валюта автоматически исправлена.",
                reply_markup=main_keyboard()
            )
            currency = currency_actual

        # Поиск всех текущих предложений
        try:
            lavkas = fetch_marketplace(srv_id)
        except Exception as e:
            await update.message.reply_text(f"Ошибка загрузки лавок: {e}")
            return

        found_offers = []
        for lk in lavkas:
            items_sell = lk.get("items_sell") or []
            price_sell = lk.get("price_sell") or []
            username = lk.get("username", "Unknown")
            lavka_uid = lk.get("LavkaUid", 0)
            for i, raw_id in enumerate(items_sell):
                num_id, enchant = get_item_name_id(raw_id)
                if num_id is None:
                    continue
                item_name_base = ITEMS_DICT.get(num_id, f"#{num_id}")
                item_name_full = f"{item_name_base} (+{enchant})" if enchant else item_name_base
                if name.lower() not in item_name_full.lower():
                    continue
                price = int(price_sell[i]) if i < len(price_sell) else 0
                found_offers.append(
                    f"• {item_name_full} — {price:,} {currency_actual} "
                    f"(лавка #{lavka_uid}, {username})"
                )

        # Добавляем в watchlist
        wl = db_user["watchlist"]
        wl.append({"name": name, "max_price": max_price, "currency": currency})
        update_user(user_id, watchlist=wl)

        msg = f"✅ <b>{name}</b> добавлен в отслеживание (≤ {max_price} {currency})\n\n"
        if found_offers:
            msg += f"🔍 Текущие предложения ({len(found_offers)}):\n" + "\n".join(found_offers[:20])
            if len(found_offers) > 20:
                msg += f"\n... и ещё {len(found_offers) - 20}"
        else:
            msg += "ℹ️ Сейчас предложений с таким названием нет."
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=main_keyboard())

    elif context.user_data.get("awaiting_delete"):
        context.user_data["awaiting_delete"] = False
        try:
            idx = int(text) - 1
            wl = db_user["watchlist"]
            if 0 <= idx < len(wl):
                removed = wl.pop(idx)
                update_user(user_id, watchlist=wl)
                await update.message.reply_text(f"Удалён: {removed['name']}", reply_markup=main_keyboard())
            else:
                await update.message.reply_text("Неверный номер.", reply_markup=main_keyboard())
        except:
            await update.message.reply_text("Ошибка.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("Используй кнопки меню.", reply_markup=main_keyboard())

# ─── Фоновый мониторинг ─────────────────────────────────────────
async def monitor_loop(app: Application):
    while True:
        await asyncio.sleep(60)  # проверка раз в минуту
        try:
            active_users = get_all_active_users()
            for user_id in active_users:
                db_user = get_user(user_id)
                # проверяем, не пора ли (по интервалу)
                last_key = f"last_check_{user_id}"
                now = asyncio.get_event_loop().time()
                if last_key in app.bot_data and now - app.bot_data[last_key] < db_user["interval_min"] * 60:
                    continue
                app.bot_data[last_key] = now

                srv_id = db_user["server_id"]
                srv = next(s for s in SERVERS if s["id"] == srv_id)
                currency = "VC$" if srv_id == 0 else "SA$"
                try:
                    lavkas = fetch_marketplace(srv_id)
                except:
                    continue
                notified_set = db_user["notified"]
                new_offers = []
                for lk in lavkas:
                    items_sell = lk.get("items_sell") or []
                    price_sell = lk.get("price_sell") or []
                    username = lk.get("username", "Unknown")
                    lavka_uid = lk.get("LavkaUid", 0)
                    for i, raw_id in enumerate(items_sell):
                        num_id, enchant = get_item_name_id(raw_id)
                        if num_id is None:
                            continue
                        item_name_base = ITEMS_DICT.get(num_id, f"#{num_id}")
                        item_name_full = f"{item_name_base} (+{enchant})" if enchant else item_name_base
                        price = int(price_sell[i]) if i < len(price_sell) else 0
                        for watch in db_user["watchlist"]:
                            if watch["currency"] != currency:
                                continue
                            if watch["name"].lower() not in item_name_full.lower():
                                continue
                            if price > watch["max_price"]:
                                continue
                            key = f"{strip_enchant(item_name_full).lower()}|{username}|{lavka_uid}|{price}"
                            if key in notified_set:
                                continue
                            new_offers.append(
                                f"🔔 <b>{item_name_full}</b> — {price:,} {currency} (≤ {watch['max_price']})\n"
                                f"Владелец: {username}, Лавка #{lavka_uid}\nСервер: {srv['label']}"
                            )
                            notified_set.add(key)
                if new_offers:
                    token = app.bot.token
                    for msg in new_offers:
                        await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
                    update_user(user_id, notified=notified_set)
        except Exception as e:
            logging.exception("Monitor loop error:")

# ─── Запуск ─────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token("YOUR_BOT_TOKEN_HERE").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Запускаем фоновую задачу мониторинга
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_loop(app))

    # Сначала стартуем бота
    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()