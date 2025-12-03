import os
import json
import datetime
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio

# Fix for environments like Replit/Jupyter
nest_asyncio.apply()

# ---------------------------
# CONFIGURATION
# ---------------------------
BOT_TOKEN = os.environ.get("GATE_ONV", "YOUR_TEST_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "794603519"))
DB_FILE = "members.json"

# ---------------------------
# DATABASE FUNCTIONS
# ---------------------------
def load_db():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

# ---------------------------
# SCHEDULER
# ---------------------------
scheduler = AsyncIOScheduler()

async def send_reminder(user_id: str, text: str, app):
    try:
        await app.bot.send_message(chat_id=int(user_id), text=text)
    except Exception as e:
        print(f"Error sending reminder to {user_id}: {e}")

async def kick_user(user_id: str, app):
    db = load_db()
    if user_id not in db:
        return
    info = db[user_id]

    kicked_groups = []
    for group_id in info.get("groups", []):
        try:
            await app.bot.ban_chat_member(chat_id=int(group_id), user_id=int(user_id))
            kicked_groups.append(group_id)
        except Exception as e:
            print(f"Error kicking {user_id} from {group_id}: {e}")

    info["status"] = "kicked"
    save_db(db)

    # Notify user
    try:
        await app.bot.send_message(chat_id=int(user_id),
                                   text="❌ You have been removed from your groups for missing your payment.")
    except:
        pass

    # Notify admin
    await app.bot.send_message(chat_id=ADMIN_ID,
                               text=f"⚠️ User {user_id} has been kicked from groups: {kicked_groups} due to overdue payment.")

def schedule_tasks(user_id: str, app):
    db = load_db()
    if user_id not in db:
        return

    info = db[user_id]
    due_date = datetime.datetime.strptime(info["due_date"], "%Y-%m-%d")
    one_day_before = due_date - datetime.timedelta(days=1)
    one_day_after = due_date + datetime.timedelta(days=1)

    # Cancel existing jobs
    for job in scheduler.get_jobs():
        if job.id.startswith(f"{user_id}_"):
            job.remove()

    # Schedule reminders and kick
    scheduler.add_job(send_reminder,
                      trigger='date',
                      run_date=one_day_before,
                      args=[user_id, "⚠️ Your Ride Marches membership fee is due tomorrow. Please pay 50 ETB.", app],
                      id=f"{user_id}_reminder_before")
    scheduler.add_job(send_reminder,
                      trigger='date',
                      run_date=due_date,
                      args=[user_id, "⏳ Your Ride Marches membership fee is due today. Please pay 50 ETB.", app],
                      id=f"{user_id}_reminder_due")
    scheduler.add_job(kick_user,
                      trigger='date',
                      run_date=one_day_after,
                      args=[user_id, app],
                      id=f"{user_id}_kick")

# ---------------------------
# COMMAND HANDLERS
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("You have successfully started Ride Marches.")

async def membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /membership <user_id> <group_id_1> [<group_id_2> ...]")
        return

    user_id = context.args[0]
    group_ids = [int(g) for g in context.args[1:]]

    db = load_db()
    today = datetime.date.today()
    due = today + datetime.timedelta(days=7)

    if user_id in db:
        db[user_id]["groups"] = list(set(db[user_id].get("groups", []) + group_ids))
        db[user_id]["last_paid"] = str(today)
        db[user_id]["due_date"] = str(due)
        db[user_id]["status"] = "active"
    else:
        db[user_id] = {
            "last_paid": str(today),
            "due_date": str(due),
            "groups": group_ids,
            "status": "active"
        }

    save_db(db)
    await update.message.reply_text(f"Membership added/updated for {user_id}. Next due date: {due}")
    await context.bot.send_message(chat_id=int(user_id),
                                   text="Your Ride Marches membership has started. Weekly fee: 50 ETB.")

    schedule_tasks(user_id, context.application)

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /confirm <user_id>")
        return

    user_id = context.args[0]
    db = load_db()

    if user_id not in db:
        await update.message.reply_text("User not found")
        return

    today = datetime.date.today()
    new_due = today + datetime.timedelta(days=7)
    db[user_id]["last_paid"] = str(today)
    db[user_id]["due_date"] = str(new_due)
    db[user_id]["status"] = "active"
    save_db(db)

    await update.message.reply_text(f"Payment confirmed for {user_id}. New due date: {new_due}")
    await context.bot.send_message(chat_id=int(user_id),
                                   text="Your weekly payment is confirmed. Thank you!")

    schedule_tasks(user_id, context.application)

# ---------------------------
# MAIN FUNCTION
# ---------------------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("membership", membership))
    app.add_handler(CommandHandler("confirm", confirm))

    # Start scheduler after app is built
    scheduler.start()

    print("Bot is running...")
    await app.run_polling()

# ---------------------------
# RUN BOT
# ---------------------------
if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()

    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
