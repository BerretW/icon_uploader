import os
import json
import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, send_file, abort
from PIL import Image
from passlib.hash import pbkdf2_sha256
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv("SECRET", "default-dev-key")
framework = os.getenv("FRAMEWORK", "vorp")
items_table = os.getenv("DB_TABLE", "items")

CONFIG_PATH = os.path.join("config", "config.json")
USERS_PATH = os.path.join("config", "users.json")


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
    with conn.cursor() as cur:
        where = "WHERE (item LIKE %s OR label LIKE %s)"
        if framework == "vorp":
            where = "WHERE (item LIKE %s OR label LIKE %s)"
        elif framework == "esx":
            where = "WHERE (name LIKE %s OR label LIKE %s)"
        # where = "WHERE (item LIKE %s OR label LIKE %s)"
        params = [f'%{search}%', f'%{search}%']

        cur.execute(f"SELECT COUNT(*) AS count FROM items {where}", params)
        total = cur.fetchone()['count']
        if framework == "vorp":
            cur.execute(f"SELECT * FROM {items_table} {where} ORDER BY item ASC LIMIT %s OFFSET %s", params + [per_page, offset])
        elif framework == "esx":
            cur.execute(f"SELECT * FROM {items_table} {where} ORDER BY name ASC LIMIT %s OFFSET %s", params + [per_page, offset])
        
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
            # vytvoř image podle name.png
            item['image'] = f"{item['name']}.png"

    has_next = offset + per_page < total

    return render_template('index.html',
                           items=items,
                           search=search,
                           icons=icons,
                           page=page,
                           has_next=has_next,
                           filter_missing=filter_missing,
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

# if __name__ == '__main__':
#     port = int(os.getenv("PORT", 5000))
#     app.run(host=os.getenv("IP", '0.0.0.0'), port=port)
