import os
import json
import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, send_file, abort
from PIL import Image
from passlib.hash import pbkdf2_sha256
from functools import wraps

app = Flask(__name__)
app.secret_key = 'supertajnyklic'

# Load config
with open('config.json') as f:
    config = json.load(f)

upload_dirs = config["upload_dirs"]

# Load users
with open('users.json') as f:
    users = json.load(f)

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

@app.route('/', methods=['GET'])
@login_required
def index():
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page
    search = request.args.get('search', '')

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM items WHERE item LIKE %s OR label LIKE %s", (f'%{search}%', f'%{search}%'))
        total = cur.fetchone()['count']

        cur.execute("SELECT item, label, image FROM items WHERE item LIKE %s OR label LIKE %s LIMIT %s OFFSET %s",
                    (f'%{search}%', f'%{search}%', per_page, offset))
        items = cur.fetchall()
    conn.close()

    icons = {}
    for path in upload_dirs:
        try:
            files = os.listdir(path)
            for f in files:
                if f.endswith('.png'):
                    icons[f] = os.path.join(path, f)
        except FileNotFoundError:
            pass

    has_next = offset + per_page < total

    return render_template('index.html', items=items, search=search, icons=icons, page=page, has_next=has_next)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
