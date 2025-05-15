import os
import json
import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, send_file, abort
from PIL import Image
from passlib.hash import pbkdf2_sha256
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supertajnyklic'

def load_users():
    with open('users.json') as f:
        return json.load(f)

def save_users(users):
    with open('users.json', 'w') as f:
        json.dump(users, f, indent=2)

def log_user_action(action, username):
    with open('users.log', 'a') as f:
        f.write(f"[{datetime.now().isoformat()}] {action}: {username}\n")

def is_admin():
    return session.get('user') == 'admin'

# Config
with open('config.json') as f:
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
        params = [f'%{search}%', f'%{search}%']

        if filter_missing:
            where += " AND (image IS NULL OR image = '')"

        cur.execute(f"SELECT COUNT(*) AS count FROM items {where}", params)
        total = cur.fetchone()['count']

        cur.execute(f"SELECT id, item, label, image FROM items {where} ORDER BY id DESC LIMIT %s OFFSET %s", params + [per_page, offset])
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

    has_next = offset + per_page < total

    return render_template('index.html',
                           items=items,
                           search=search,
                           icons=icons,
                           page=page,
                           has_next=has_next,
                           filter_missing=filter_missing)


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
        with conn.cursor() as cur:
            cur.execute("UPDATE items SET image=%s WHERE item=%s", (filename, item))
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
