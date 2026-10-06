import telebot
import requests
import sqlite3
import re
from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import os

BOT_TOKEN = os.environ.get("8803648566:AAHmG4XTMTDqfIHlWjBeDsKCGmQ18pxKnGQ")
ADMIN_CHAT_ID = 7929131842

app = Flask(__name__)
CORS(app)

def init_db():
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS points
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
    conn.commit()
    conn.close()
init_db()

def get_coordinates(address):
    # 🔒 ЖЕСТКАЯ ПРИВЯЗКА К СМОЛЕНСКУ
    # Бот сам добавит "г. Смоленск, " перед тем, что вы написали
    query = f"г. Смоленск, {address}"
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": "SmolenskMapBot/1.0"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except:
        pass
    return None, None

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id != ADMIN_CHAT_ID:
        return 

    if message.text is None:
        return 

    text = message.text.strip()
    
    if '-' in text:
        parts = text.rsplit('-', 1) 
        location_part = parts[0].strip()
        title = parts[1].strip()
        
        if not location_part or not title:
            bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название\nПример: Гагарина 5 - Офис")
            return

        coord_match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', location_part)
        
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            bot.reply_to(message, f"✅ Координаты приняты!\n📍 {title}")
        else:
            bot.reply_to(message, f"⏳ Ищу '{location_part}' в г. Смоленск...")
            lat, lon = get_coordinates(location_part)
            
        if lat and lon:
            conn = sqlite3.connect('points.db')
            c = conn.cursor()
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (?, ?, ?, ?, 'active')",
                     (title, location_part, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Точка '{title}' успешно добавлена на карту!")
        else:
            bot.reply_to(message, f"❌ Не удалось найти адрес: '{location_part}' в Смоленске. Проверьте написание.")
    else:
        bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название\nПримеры:\n• Гагарина 5 - Офис\n• ул. Ленина 10 - Склад\n• 54.781, 32.045 - Точка на поле")

@app.route('/')
def serve_website():
    return "Бот работает! API доступно."

@app.route('/get_points')
def get_points():
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    c.execute("SELECT id, title, address, lat, lon, status FROM points WHERE status != 'found'")
    points = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "status": row[5]} for row in c.fetchall()]
    conn.close()
    return jsonify(points)

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json
    point_id = data.get('id')
    status = data.get('status')
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    if status == 'found':
        c.execute("DELETE FROM points WHERE id = ?", (point_id,))
    else:
        c.execute("UPDATE points SET status = ? WHERE id = ?", (status, point_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port) 