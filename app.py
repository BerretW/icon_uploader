import os
import json
import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, send_file, abort
from PIL import Image
from passlib.hash import pbkdf2_sha256
from functools import wraps
from datetime import datetime
from flask import jsonify

app = Flask(__name__)
import time

@app.before_request
def start_timer():
    request._start_time = time.time()

@app.after_request
def log_request(response):
    if hasattr(request, '_start_time'):
        duration = time.time() - request._start_time
        method = request.method
        path = request.path
        status = response.status_code
        user = session.get('user', 'anon')
        print(f"[{datetime.now().isoformat()}] {method} {path} ({status}) by {user} in {duration:.3f}s")
    return response

app.secret_key = os.getenv("SECRET", "default-dev-key")
framework = os.getenv("FRAMEWORK", "vorp")
items_table = os.getenv("DB_TABLE", "items")
order_collumn = os.getenv("ORDER_COLUMN", "label")
CONFIG_PATH = os.path.join("config", "config.json")
USERS_PATH = os.path.join("config", "users.json")

SAFECOORDS_PATH = os.path.join("config", "safecoords.json")


def load_safecoords():
    if not os.path.exists(SAFECOORDS_PATH):
        os.makedirs(os.path.dirname(SAFECOORDS_PATH), exist_ok=True)
        default_data = {
            "Valentine": "vector3(-278.5, 804.1, 119.3), 89.0"
        }
        with open(SAFECOORDS_PATH, "w") as f:
            json.dump(default_data, f, indent=2)
        return default_data
    with open(SAFECOORDS_PATH) as f:
        return json.load(f)

def save_safecoords(data):
    with open(SAFECOORDS_PATH, "w") as f:
        json.dump(data, f, indent=2)

import logging

LOG_PATH = os.path.join("config", "debug.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    encoding='utf-8'
)

can_add_item = os.getenv("CAN_ADD_ITEM", "false").lower() == "true"

lang = os.getenv("LANG", "cs")

translations = {
    "cs": {
        "title": "Správa ikon itemů",
        "search": "Hledat item...",
        "no_icon": "Žádná ikona",
        "upload": "Nahrát",
        "label": "Label",
        "weight": "Váha",
        "desc": "Popis",
        "save": "Uložit",
        "users": "Uživatelé",
        "logout": "Odhlásit",
        "filter": "Pouze bez ikon",
        "filter_btn": "Filtrovat",
        "prev": "« Předchozí",
        "next": "Další »",
        "page": "Stránka"
    },
    "en": {
        "title": "Item Icon Manager",
        "search": "Search item...",
        "no_icon": "No icon",
        "upload": "Upload",
        "label": "Label",
        "weight": "Weight",
        "desc": "Description",
        "save": "Save",
        "users": "Users",
        "logout": "Logout",
        "filter": "Only without icons",
        "filter_btn": "Filter",
        "prev": "« Previous",
        "next": "Next »",
        "page": "Page"
    }
}

T = translations[lang]
# starting print version
print("version: 1.0.0")

if not os.path.exists(USERS_PATH):
    users_data = {
        "admin": pbkdf2_sha256.hash(os.getenv("ADMIN_PASSWORD", "admin"))
    }
    os.makedirs("config", exist_ok=True)
    with open(USERS_PATH, "w") as f:
        json.dump(users_data, f, indent=2)

if not os.path.exists(CONFIG_PATH):
    config_data = {
        "db": {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", 3306)),
            "database": os.getenv("DB_NAME", "test"),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", "")
        },
        "upload_dirs": ["/data/main","/data/dev","/data/web"]
    }
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=2)

def load_users():
    with open(USERS_PATH) as f:
        return json.load(f)

def save_users(users):
    with open(USERS_PATH, 'w') as f:
        json.dump(users, f, indent=2)

def log_user_action(action, username):
    with open('users.log', 'a') as f:
        f.write(f"[{datetime.now().isoformat()}] {action}: {username}\n")

def is_admin():
    return session.get('user') == 'admin'

# Config
with open(CONFIG_PATH) as f:
    config = json.load(f)

upload_dirs = config["upload_dirs"]

def get_db_connection():
    return pymysql.connect(**config["db"], cursorclass=pymysql.cursors.DictCursor)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_users()
        username = request.form['username']
        password = request.form['password']
        if username in users and pbkdf2_sha256.verify(password, users[username]):
            session['user'] = username
            return redirect(url_for('index'))
        return render_template('login.html', error="Špatné přihlášení")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/image/<filename>')
@login_required
def serve_image(filename):
    for path in upload_dirs:
        filepath = os.path.join(path, filename)
        if os.path.isfile(filepath):
            return send_file(filepath)
    abort(404)

@app.route('/')
@login_required
def index():
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    search = request.args.get('search', '')
    filter_missing = request.args.get('filter') == 'missing'

    conn = get_db_connection()
    # vypiš dostupné slopupce ve vybrané tabulce a databázi pomocí SHOW COLUMNS FROM items;
    with conn.cursor() as cur:
        try:
            cur.execute(f"SHOW COLUMNS FROM {items_table};")
            columns = cur.fetchall()
            print(f"\nDEBUG | Sloupce v tabulce `{items_table}`:")
            for col in columns:
                print(f"- {col['Field']} ({col['Type']})")
        except Exception as e:
            print("CHYBA při získávání sloupců tabulky:", e)




    with conn.cursor() as cur:
        params = [f'%{search}%', f'%{search}%']
        if framework == "vorp":
            where_clause = "WHERE (item LIKE %s OR label LIKE %s)"
        elif framework == "esx":
            where_clause = "WHERE (name LIKE %s OR label LIKE %s)"
        else:
            where_clause = "WHERE (label LIKE %s OR label LIKE %s)"

        # Dotaz na počet záznamů – BEZ f-string pro params!
        query = f"SELECT COUNT(*) AS count FROM {items_table} {where_clause}"
        cur.execute(query, params)
        total = cur.fetchone()['count']

        # Dotaz na samotná data – stejné WHERE, stejný params
        query = f"SELECT * FROM {items_table} {where_clause} ORDER BY {order_collumn} DESC LIMIT %s OFFSET %s"
        cur.execute(query, params + [per_page, offset])
        items = cur.fetchall()
        conn.close()

    # Načti dostupné ikony
    icons = {}
    for path in upload_dirs:
        try:
            for f in os.listdir(path):
                if f.endswith('.png'):
                    icons[f] = os.path.join(path, f)
        except FileNotFoundError:
            pass

    # Pokud filtrujeme chybějící soubory, ověř existenci fyzicky
    if filter_missing:
        items = [item for item in items if not item['image'] or item['image'] not in icons]
    # pokud je vybrán esx framework tak u každého itemu doplníme do item jeho name tak aby byl kompatibilní s tabulkou items
    if framework == "esx":
        for item in items:
            item['item'] = item['name']
            # vytvoř image podle name.png pokud item.image neexistuje
            if not item['image']:
                item['image'] = f"{item['name']}.png"
            # item['image'] = f"{item['name']}.png"

    has_next = offset + per_page < total

    return render_template('index.html',
                           items=items,
                           search=search,
                           icons=icons,
                           page=page,
                           has_next=has_next,
                           filter_missing=filter_missing,
                           can_add_item=can_add_item,
                            show_characters_button=(framework == "vorp"),
                            T=T)


@app.route('/upload/<item>', methods=['POST'])
@login_required
def upload(item):
    file = request.files['icon']
    if file:
        filename = f"{item}.png"
        image = Image.open(file.stream).convert("RGBA").resize((98, 98))
        for path in upload_dirs:
            os.makedirs(path, exist_ok=True)
            image.save(os.path.join(path, filename))
        conn = get_db_connection()
        if framework == "vorp":
            with conn.cursor() as cur:
                cur.execute("UPDATE %s SET image=%s WHERE item=%s", (items_table, filename, item))
        conn.commit()
        conn.close()
    return redirect(url_for('index'))

@app.route('/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if not is_admin():
        return abort(403)

    users = load_users()
    error = None

    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username')

        if action == 'add':
            password = request.form.get('password')
            if not username or not password:
                error = "Zadej jméno i heslo."
            elif username in users:
                error = "Uživatel už existuje."
            else:
                users[username] = pbkdf2_sha256.hash(password)
                save_users(users)
                log_user_action("Přidán uživatel", username)

        elif action == 'delete':
            if username == 'admin':
                error = "Admina nelze smazat."
            elif username in users:
                users.pop(username)
                save_users(users)
                log_user_action("Smazán uživatel", username)

        elif action == 'change':
            password = request.form.get('new_password')
            if not password:
                error = "Zadej nové heslo."
            elif username == 'admin':
                error = "Heslo admina nelze měnit."
            elif username in users:
                users[username] = pbkdf2_sha256.hash(password)
                save_users(users)
                log_user_action("Změna hesla", username)

    return render_template('users.html', users=users, current_user=session.get('user'), error=error)
from flask import jsonify

@app.route('/update/<item>', methods=['POST'])
@login_required
def update_item(item):
    label = request.form.get('label', '').strip()
    weight = request.form.get('weight', '').replace(',', '.')
    desc = request.form.get('desc', '').strip()

    try:
        weight = float(weight)
    except ValueError:
        return jsonify(success=False, message="Neplatná váha")

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE items
            SET label=%s, weight=%s, `desc`=%s, updated_at=NOW()
            WHERE item=%s
        """, (label, weight, desc, item))
    conn.commit()
    conn.close()

    return jsonify(success=True)


@app.route('/add-item', methods=['POST'])
@login_required
def add_item():
    if not can_add_item:
        return abort(403)

    item = request.form.get('item', '').strip()
    label = request.form.get('label', '').strip()
    weight = request.form.get('weight', '0.25').replace(',', '.')
    desc = request.form.get('desc', 'nice item').strip()

    try:
        weight = float(weight)
    except ValueError:
        return redirect(url_for('index'))

    conn = get_db_connection()
    with conn.cursor() as cur:
        if framework == "vorp":
            cur.execute("""
                INSERT INTO items (item, label, weight, `desc`, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (item, label, weight, desc))
        elif framework == "esx":
            cur.execute("""
                INSERT INTO items (name, label, weight)
                VALUES (%s, %s, %s)
            """, (item, label, int(weight)))  # ESX má weight jako INT
    conn.commit()
    conn.close()

    return redirect(url_for('index'))

@app.route('/characters')
@login_required
def characters():
    if framework != "vorp":
        return abort(403)

    search = request.args.get("search", "").strip()
    isdead_filter = request.args.get("isdead", "")
    hp_filter = request.args.get("hp", "")
    hp_op = request.args.get("hp_op", ">")

    query = """
        SELECT charidentifier, identifier, steamname, firstname, lastname, money, health, isdead, coords
        FROM characters
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                LOWER(identifier) LIKE %s OR
                LOWER(steamname) LIKE %s OR
                LOWER(firstname) LIKE %s OR
                LOWER(lastname) LIKE %s OR
                CAST(charidentifier AS CHAR) LIKE %s OR
                CAST(money AS CHAR) LIKE %s
            )
        """
        like_search = f"%{search.lower()}%"
        params.extend([like_search] * 4)
        params.extend([f"%{search}%", f"%{search}%"])

    if isdead_filter in ["0", "1"]:
        query += " AND isdead = %s"
        params.append(isdead_filter)

    if hp_filter.isdigit():
        query += f" AND health {hp_op} %s"
        params.append(int(hp_filter))

    query += " ORDER BY charidentifier DESC LIMIT 100"

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(query, params)
        characters = cur.fetchall()

    for char in characters:
        try:
            c = json.loads(char["coords"])
            char["coords_string"] = f'vector3({c["x"]}, {c["y"]}, {c["z"]}), {c.get("heading", 0)}'
        except Exception:
            char["coords_string"] = "vector3(0.0, 0.0, 0.0), 0.0"

    safecoords = load_safecoords()
    conn.close()
    return render_template("characters.html",
                           characters=characters,
                           safecoords=safecoords,
                           search=search,
                           isdead_filter=isdead_filter,
                           hp_filter=hp_filter,
                           hp_op=hp_op,
                           T=T)



@app.route('/characters/update/<int:charidentifier>', methods=['POST'])
@login_required
def update_character(charidentifier):
    logging.debug(f"Zahájena aktualizace charakteru {charidentifier}")

    if framework != "vorp":
        logging.debug("Zrušeno: framework není vorp")
        return abort(403)

    identifier = request.form.get("identifier", "").strip()
    health = request.form.get("health", "").strip()
    isdead = int(request.form.get("isdead", 0))
    coords_str = request.form.get("coords", "").strip()

    logging.debug(f"Form data: identifier={identifier}, health={health}, isdead={isdead}, coords={coords_str}")

    try:
        vector_part, heading_part = coords_str.split("),")
        vector_part = vector_part.replace("vector3(", "")
        x, y, z = map(float, vector_part.split(","))
        heading = float(heading_part.strip())
        coords_dict = {"x": x, "y": y, "z": z, "heading": heading}
        coords_json = json.dumps(coords_dict)
    except Exception as e:
        logging.error(f"Chyba parsování coords: {e}")
        return f"<h2 style='color:red'>Chybný formát coords: {e}</h2><a href='/characters'>Zpět</a>"

    try:
        health = int(health)
    except ValueError:
        logging.error("Neplatné zdraví")
        return f"<h2 style='color:red'>Neplatné zdraví</h2><a href='/characters'>Zpět</a>"

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE characters
            SET identifier=%s, health=%s, isdead=%s, coords=%s
            WHERE charidentifier=%s
        """, (identifier, health, isdead, coords_json, charidentifier))
        logging.debug(f"Změněno řádků: {cur.rowcount}")
    conn.commit()
    conn.close()

    logging.debug("Aktualizace dokončena")
    return redirect(url_for("characters"))



@app.route('/safecoords', methods=['GET', 'POST'])
@login_required
def safecoords_editor():
    if not is_admin():
        return abort(403)

    data = load_safecoords()
    message = ""

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('name', '').strip()
        value = request.form.get('value', '').strip()

        if action == 'add':
            if not name or not value.startswith("vector3"):
                message = "Neplatný vstup – zkontroluj formát."
            else:
                data[name] = value
                save_safecoords(data)
                message = f"Přidáno: {name}"

        elif action == 'delete' and name in data:
            del data[name]
            save_safecoords(data)
            message = f"Smazáno: {name}"

        elif action == 'update' and name in data:
            data[name] = value
            save_safecoords(data)
            message = f"Aktualizováno: {name}"

    return render_template("safecoords.html", safecoords=data, message=message)




# if __name__ == '__main__':
#     port = int(os.getenv("PORT", 5000))
#     app.run(host=os.getenv("IP", '0.0.0.0'), port=port)
