import telebot
import requests
import psycopg
import json
import re
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import threading
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8803648566:AAHmG4XTMTDqfIHlWjBeDsKCGmQ18pxKnGQ")
ADMIN_CHAT_ID = 7929131842
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://mapbotuser:r47l5ou0pDueVnus4tiD3d2w7hYQJ1vy@dpg-db4fc5ks728c73ajgig0-a.frankfurt-postgres.render.com/mapbotdb")

app = Flask(__name__)

# 1. Базовая настройка CORS
CORS(app)

# 2. ПУЛЕНЕПРОБИВАЕМАЯ защита CORS: добавляем заголовки к КАЖДОМУ ответу (включая OPTIONS preflight)
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response

def get_db_connection():
    return psycopg.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS points
                     (id SERIAL PRIMARY KEY,
                      title TEXT, address TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'active')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS parkings
                     (id SERIAL PRIMARY KEY,
                      title TEXT UNIQUE, address TEXT, lat REAL, lon REAL, 
                      available_count TEXT DEFAULT '?', dead_count TEXT DEFAULT '?', broken_count TEXT DEFAULT '?')''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS zones
                     (id SERIAL PRIMARY KEY,
                      coords JSONB,
                      comment TEXT)''')
        
        conn.commit()
        conn.close()
        print("✅ База данных успешно инициализирована!")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

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
    text_lower = text.lower()

    if text_lower == 'все p off':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM parkings")
        count = c.rowcount
        conn.commit()
        conn.close()
        bot.reply_to(message, f"🗑️ Удалено всех парковок: {count}")
        return

    if text_lower == 'last p off':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM parkings WHERE id = (SELECT MAX(id) FROM parkings)")
        if c.rowcount > 0:
            bot.reply_to(message, "🗑️ Последняя парковка успешно удалена.")
        else:
            bot.reply_to(message, "❌ Парковок не найдено.")
        conn.commit()
        conn.close()
        return

    parking_match = re.match(r'^(.+?)\s+([ДдСсПп]\d+(?:\s+[ДдСсПп]\d+)*)$', text)
    if parking_match:
        title = parking_match.group(1).strip()
        params_str = parking_match.group(2)
        
        avail = dead = broken = None
        params = re.findall(r'([ДдСсПп])(\d+)', params_str)
        for param_type, param_value in params:
            if param_type.lower() == 'д': avail = param_value
            elif param_type.lower() == 'с': dead = param_value
            elif param_type.lower() == 'п': broken = param_value
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT available_count, dead_count, broken_count FROM parkings WHERE title = %s", (title,))
        row = c.fetchone()
        
        if row:
            current_avail, current_dead, current_broken = row
            new_avail = avail if avail is not None else current_avail
            new_dead = dead if dead is not None else current_dead
            new_broken = broken if broken is not None else current_broken
            
            c.execute("UPDATE parkings SET available_count = %s, dead_count = %s, broken_count = %s WHERE title = %s", 
                     (new_avail, new_dead, new_broken, title))
            conn.commit()
            conn.close()
            
            response_parts = []
            if avail is not None: response_parts.append(f"В доступе: {avail}")
            if dead is not None: response_parts.append(f"Севшие: {dead}")
            if broken is not None: response_parts.append(f"Поломки: {broken}")
            
            bot.reply_to(message, f"✅ Парковка \"{title}\" обновлена: {', '.join(response_parts)}")
        else:
            bot.reply_to(message, f"❌ Парковка \"{title}\" не найдена в базе данных.")
        return

    if text_lower.endswith(' - p'):
        clean_text = text[:-4].strip()
        if '-' in clean_text:
            parts = clean_text.rsplit('-', 1) 
            location_part = parts[0].strip()
            title = parts[1].strip()
            
            if not location_part or not title:
                bot.reply_to(message, "⚠️ Формат: Адрес - Название - P")
                return

            coord_match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', location_part)
            if coord_match:
                lat = float(coord_match.group(1))
                lon = float(coord_match.group(2))
            else:
                bot.reply_to(message, f"⏳ Ищу '{location_part}' в г. Смоленск...")
                lat, lon = get_coordinates(location_part)
                
            if lat and lon:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO parkings (title, address, lat, lon) VALUES (%s, %s, %s, %s)",
                         (title, location_part, lat, lon))
                conn.commit()
                conn.close()
                bot.reply_to(message, f"✅ Парковка '{title}' успешно добавлена!")
            else:
                bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")
        else:
            bot.reply_to(message, "⚠️ Формат: Адрес - Название - P")
        return

    if '-' in text:
        parts = text.rsplit('-', 1) 
        location_part = parts[0].strip()
        title = parts[1].strip()
        
        if not location_part or not title:
            bot.reply_to(message, "⚠️ Формат: Адрес или Координаты - Название")
            return

        coord_match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', location_part)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
        else:
            bot.reply_to(message, f"⏳ Ищу '{location_part}' в г. Смоленск...")
            lat, lon = get_coordinates(location_part)
            
        if lat and lon:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO points (title, address, lat, lon, status) VALUES (%s, %s, %s, %s, 'active')",
                     (title, location_part, lat, lon))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Точка '{title}' успешно добавлена!")
        else:
            bot.reply_to(message, f"❌ Не удалось найти: '{location_part}' в Смоленске.")

# ==========================================
# 🌐 API ЭНДПОИНТЫ
# ==========================================

@app.route('/')
def serve_website():
    return "Бот работает! API доступно."

@app.route('/get_points')
def get_points():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, title, address, lat, lon, status FROM points WHERE status != 'found'")
        points = [{"id": row[0], "title": row[1], "address": row[2], "lat": row[3], "lon": row[4], "status": row[5]} for row in c.fetchall()]
        conn.close()
        return jsonify(points)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_status', methods=['POST'])
def update_status():
    try:
        data = request.json
        point_id = data.get('id')
        status = data.get('status')
        conn = get_db_connection()
        c = conn.cursor()
        if status == 'found':
            c.execute("DELETE FROM points WHERE id = %s", (point_id,))
        else:
            c.execute("UPDATE points SET status = %s WHERE id = %s", (status, point_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_parkings')
def get_parkings():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, title, address, lat, lon, available_count, dead_count, broken_count FROM parkings")
        parkings = []
        for row in c.fetchall():
            if row[3] is None or row[4] is None: 
                continue
            parkings.append({
                "id": row[0], "title": row[1] or "Без названия", "address": row[2] or "?", 
                "lat": float(row[3]), "lon": float(row[4]), 
                "available": row[5] if row[5] is not None else '?', 
                "dead": row[6] if row[6] is not None else '?', 
                "broken": row[7] if row[7] is not None else '?'
            })
        conn.close()
        return jsonify(parkings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_parking', methods=['POST'])
def update_parking():
    try:
        data = request.json
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE parkings SET available_count = %s, dead_count = %s, broken_count = %s WHERE id = %s", 
                  (data.get('available', '?'), data.get('dead', '?'), data.get('broken', '?'), data.get('id')))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_zones', methods=['GET', 'OPTIONS'])
def get_zones():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, coords, comment FROM zones")
        zones = [{"id": row[0], "coords": row[1], "comment": row[2]} for row in c.fetchall()]
        conn.close()
        return jsonify(zones)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add_zone', methods=['POST', 'OPTIONS'])
def add_zone():
    try:
        data = request.json
        coords = data.get('coords')
        comment = data.get('comment', '')
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO zones (coords, comment) VALUES (%s, %s)", (json.dumps(coords), comment))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

@app.route('/delete_zone', methods=['POST', 'OPTIONS'])
def delete_zone():
    try:
        data = request.json
        zone_id = data.get('id')
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM zones WHERE id = %s", (zone_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=8080) # Жестко задаем порт 8080 для Render
