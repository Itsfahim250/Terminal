import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import subprocess
import os
import uuid
import html
import requests
import signal
import time

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
FIREBASE_DB_URL = "https://strikexo-55b1d-default-rtdb.firebaseio.com"
BOT_TOKEN = '7992380671:AAGDHNnO8ETONZb0oIjv0sa-aMFa4qCwAgQ'  # আপনার টোকেন দিন
ADMIN_ID = "8789987504"  # আপনার টেলিগ্রাম আইডি দিন

bot = telebot.TeleBot(BOT_TOKEN)

current_directories = {}
user_states = {}  # ইউজারের বর্তমান স্টেট মনে রাখার জন্য

# ==========================================
# 🔄 AUTO-RECOVERY SYSTEM
# ==========================================
def restore_running_bots():
    print("🔄 Checking Firebase for previously running bots...")
    try:
        resp = requests.get(f"{FIREBASE_DB_URL}/running_terminals.json")
        bots = resp.json() if resp.status_code == 200 and resp.json() else {}
        if not bots: return
        
        for bot_id, data in bots.items():
            cmd = data.get('command')
            cwd = data.get('directory')
            try:
                process = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                requests.patch(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json", json={"pid": process.pid})
                print(f"✅ Restored:[{cmd}]")
            except Exception as e:
                print(f"❌ Failed to restore [{cmd}]: {e}")
    except Exception as e:
        pass

# ==========================================
# 🤖 TELEGRAM BOT LOGIC & UI
# ==========================================
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🚀 Create New Bot"), KeyboardButton("📜 View My Bots"))
    return markup

@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = str(message.chat.id)
    # এখানে চাইলে সাবস্ক্রিপশন চেক রাখতে পারেন, আপাতত অ্যাডমিন চেক রাখা হলো
    if user_id != ADMIN_ID:
        bot.reply_to(message, "⛔ Access Denied! Contact Admin.")
        return
        
    bot.reply_to(message, "✅ **Termux Manager is Ready!**\nনিচের মেনু থেকে অপশন সিলেক্ট করুন:", reply_markup=main_menu(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "🚀 Create New Bot")
def create_new_bot(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID: return
        
    user_states[user_id] = "waiting_for_command"
    bot.reply_to(message, "⌨️ **Please send your terminal command.**\n(Example: `python3 mybot.py`)", parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "📜 View My Bots")
def view_my_bots(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID: return

    resp = requests.get(f"{FIREBASE_DB_URL}/running_terminals.json")
    all_bots = resp.json() if resp.status_code == 200 and resp.json() else {}
    
    # শুধুমাত্র এই ইউজারের বটগুলো ফিল্টার করা হচ্ছে
    user_bots = {k: v for k, v in all_bots.items() if v.get("user_id") == user_id}
    
    if not user_bots:
        bot.reply_to(message, "⚠️ আপনার কোনো বট বর্তমানে ব্যাকগ্রাউন্ডে চলছে না।")
        return
        
    for bot_id, data in user_bots.items():
        cmd = data.get("command")
        pid = data.get("pid")
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✏️ Edit Code", callback_data=f"edit_{bot_id}"))
        markup.add(InlineKeyboardButton("🗑️ Delete & Stop", callback_data=f"del_{bot_id}"))
        
        msg = f"🤖 **Bot ID:** `{bot_id}`\n\n**Command:** `{cmd}`\n**PID:** `{pid}`"
        bot.send_message(user_id, msg, reply_markup=markup, parse_mode="Markdown")

# ==========================================
# 🎛️ INLINE BUTTON ACTIONS (EDIT & DELETE)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def handle_delete_bot(call):
    bot_id = call.data.split('_')[1]
    
    resp = requests.get(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json")
    if resp.json():
        pid = resp.json().get('pid')
        try: os.kill(int(pid), signal.SIGTERM) # Process Kill
        except: pass
        
        requests.delete(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json")
        bot.answer_callback_query(call.id, "✅ Bot successfully stopped and deleted!")
        bot.edit_message_text("🗑️ **This bot has been deleted and stopped.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "Bot not found or already deleted.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_'))
def handle_edit_bot(call):
    bot_id = call.data.split('_')[1]
    user_id = str(call.message.chat.id)
    
    resp = requests.get(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json")
    data = resp.json()
    if not data:
        bot.answer_callback_query(call.id, "Bot not found!")
        return

    cmd = data.get('command', '')
    cwd = data.get('directory', '')

    # কমান্ড থেকে ফাইলের নাম বের করা (যেমন: python bot.py থেকে bot.py)
    filename = None
    for part in cmd.split():
        if part.endswith(('.py', '.sh', '.js', '.txt')):
            filename = part
            break
            
    if not filename:
        bot.answer_callback_query(call.id, "Cannot edit this type of command.", show_alert=True)
        return

    file_path = os.path.join(cwd, filename)
    
    if not os.path.exists(file_path):
        bot.answer_callback_query(call.id, "File not found in Termux!", show_alert=True)
        return

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
            
        # ইউজারের স্টেট পরিবর্তন করে এডিট মোডে নেওয়া হলো
        user_states[user_id] = {"mode": "editing", "bot_id": bot_id, "file_path": file_path, "cmd": cmd, "cwd": cwd}
        
        bot.send_message(user_id, f"📝 **Editing:** `{filename}`\n\nএখানে আপনার সম্পূর্ণ নতুন কোডটি মেসেজ হিসেবে পেস্ট করে পাঠিয়ে দিন। বট নিজ দায়িত্বে সেটি আপডেট করে রিস্টার্ট করে নিবে।", parse_mode="Markdown")
        
        # কোড বড় হলে টেলিগ্রাম এরর দেয়, তাই ডকুমেন্ট হিসেবে পাঠানো সবচেয়ে নিরাপদ
        with open(file_path, 'rb') as doc:
            bot.send_document(user_id, doc, caption="আপনার বর্তমান কোডটি উপরে দেওয়া হলো।")
            
        bot.answer_callback_query(call.id, "Send the new code.")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)

# ==========================================
# ⚙️ TERMINAL ENGINE & MESSAGE HANDLER
# ==========================================
@bot.message_handler(func=lambda message: True)
def terminal_engine(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID: return

    # ---------------------------------------------
    # ✏️ EDIT MODE LOGIC
    # ---------------------------------------------
    state_data = user_states.get(user_id)
    if isinstance(state_data, dict) and state_data.get("mode") == "editing":
        file_path = state_data["file_path"]
        bot_id = state_data["bot_id"]
        cmd = state_data["cmd"]
        cwd = state_data["cwd"]
        
        bot.reply_to(message, "⏳ Updating code and restarting bot...")
        
        try:
            # ১. নতুন কোড ফাইলে সেভ করা
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(message.text)
                
            # ২. আগের প্রসেস কিল করা
            resp = requests.get(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json")
            if resp.json():
                try: os.kill(int(resp.json().get('pid')), signal.SIGTERM)
                except: pass
                
            # ৩. নতুন করে কোডটি রান করা
            process = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # ৪. ফায়ারবেসে নতুন PID আপডেট করা
            requests.patch(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json", json={"pid": process.pid})
            
            user_states[user_id] = "idle" # স্টেট ক্লিয়ার করা হলো
            bot.reply_to(message, f"✅ **Success!** কোড সফলভাবে আপডেট করা হয়েছে এবং বট নতুন করে ব্যাকগ্রাউন্ডে রিস্টার্ট হয়েছে!\n\n**New PID:** `{process.pid}`", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Error updating code: {e}")
        return

    # ---------------------------------------------
    # 🚀 NEW BOT CREATION & COMMAND LOGIC
    # ---------------------------------------------
    if user_states.get(user_id) != "waiting_for_command":
        bot.reply_to(message, "দয়া করে মেনু থেকে '🚀 Create New Bot' বাটনটি চাপুন।")
        return

    command = message.text
    user_states[user_id] = "idle"
    
    if user_id not in current_directories: current_directories[user_id] = os.getcwd()
    cwd = current_directories[user_id]

    if command.startswith("python ") or command.startswith("python3 ") or command.startswith("node ") or command.startswith("bash "):
        bot.reply_to(message, "⚙️ Starting script in background...")
        try:
            process = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            bot_id = str(uuid.uuid4())[:8] 
            data = {"user_id": user_id, "command": command, "directory": cwd, "pid": process.pid}
            requests.put(f"{FIREBASE_DB_URL}/running_terminals/{bot_id}.json", json=data)
            
            bot.reply_to(message, f"✅ **Running in Background!**\n\n**PID:** `{process.pid}`\n\nআপনি `📜 View My Bots` মেনু থেকে এটি কন্ট্রোল করতে পারবেন।", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Failed: `{html.escape(str(e))}`", parse_mode="Markdown")
        return

    # সাধারণ কমান্ড (যেমন apt update, ls)
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
        output = result.stdout if result.stdout else result.stderr
        if not output: output = "✅ Executed successfully."
        if len(output) > 4000: output = output[:4000] + "\n...[Truncated]"
        bot.reply_to(message, f"```bash\n{output}\n```", parse_mode="Markdown")
    except Exception as e:
         bot.reply_to(message, f"❌ **Error:**\n```bash\n{str(e)}\n```", parse_mode="Markdown")

if __name__ == "__main__":
    restore_running_bots()  # Auto Recovery
    print("Terminal Bot is running smoothly...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)