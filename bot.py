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
    
    # Таблица обычных точек (самокатов)
    c.execute('''CREATE TABLE IF NOT EXISTS points
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
    
    # ✅ ДОБАВЛЕНО: Таблица парковок с колонкой broken_count
    c.execute('''CREATE TABLE IF NOT EXISTS parkings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT UNIQUE, address TEXT, lat REAL, lon REAL, 
                  available_count TEXT DEFAULT '?', dead_count TEXT DEFAULT '?', broken_count TEXT DEFAULT '?')''')
    
    conn.commit()
    conn.close()

init_db()

def get_coordinates(address):
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
    if message.chat.id != ADMIN_CHAT_ID or message.text is None:
        return 

    text = message.text.strip()
    
    # ✅ ДОБАВЛЕНО: Логика парсинга команд для обновления парковок (Д, С, П в любом сочетании)
    parking_match = re.match(r'^(.+?)\s+([ДдСсПп]\d+(?:\s+[ДдСсПп]\d+)*)$', text)
    if parking_match:
        title = parking_match.group(1).strip()
        params_str = parking_match.group(2)
        
        # Парсим все найденные параметры
        avail = None
        dead = None
        broken = None
        
        params = re.findall(r'([ДдСсПп])(\d+)', params_str)
        for param_type, param_value in params:
            if param_type.lower() == 'д':
                avail = param_value
            elif param_type.lower() == 'с':
                dead = param_value
            elif param_type.lower() == 'п':
                broken = param_value
        
        # Получаем текущие данные из БД
        conn = sqlite3.connect('points.db')
        c = conn.cursor()
        c.execute("SELECT available_count, dead_count, broken_count FROM parkings WHERE title = ?", (title,))
        row = c.fetchone()
        
        if row:
            current_avail, current_dead, current_broken = row
            
            # Если параметр не передан, оставляем старое значение
            new_avail = avail if avail is not None else current_avail
            new_dead = dead if dead is not None else current_dead
            new_broken = broken if broken is not None else current_broken
            
            c.execute("UPDATE parkings SET available_count = ?, dead_count = ?, broken_count = ? WHERE title = ?", 
                     (new_avail, new_dead, new_broken, title))
            conn.commit()
            
            # Формируем красивый ответ
            response_parts = []
            if avail is not None: response_parts.append(f"В доступе: {avail}")
            if dead is not None: response_parts.append(f"Севшие: {dead}")
            if broken is not None: response_parts.append(f"Поломки: {broken}")
            
            bot.reply_to(message, f"✅ Парковка \"{title}\" обновлена: {', '.join(response_parts)}")
        else:
            bot.reply_to(message, f"❌ Парковка \"{title}\" не найдена в базе данных.")
        conn.close()
        return # Завершаем обработку, чтобы не сработало правило создания точки

    # Старая логика создания обычных точек (самокатов)
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
        bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название\nПримеры:\n• Гагарина 5 - Офис\n• ул. Ленина 10 - Склад\n• 54.781, 32.045 - Точка на поле\n\nДля парковок: Название Д10 С5 П2")

# --- API ЭНДПОИНТЫ ---

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

# ✅ ДОБАВЛЕНО: Эндпоинт для получения данных парковок (включая broken_count)
@app.route('/get_parkings')
def get_parkings():
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    c.execute("SELECT id, title, address, lat, lon, available_count, dead_count, broken_count FROM parkings")
    parkings = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "available": row[5], "dead": row[6], "broken": row[7]} for row in c.fetchall()]
    conn.close()
    return jsonify(parkings)

# ✅ ДОБАВЛЕНО: Эндпоинт для обновления данных парковки через интерфейс карты
@app.route('/update_parking', methods=['POST'])
def update_parking():
    data = request.json
    conn = sqlite3.connect('points.db')
    c = conn.cursor()
    c.execute("UPDATE parkings SET available_count = ?, dead_count = ?, broken_count = ? WHERE id = ?", 
              (data.get('available'), data.get('dead'), data.get('broken'), data.get('id')))
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
