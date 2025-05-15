import os
import json
import pymysql
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image

app = Flask(__name__)
with open('config.json') as f:
    config = json.load(f)

upload_dirs = config["upload_dirs"]

def get_db_connection():
    return pymysql.connect(**config["db"], cursorclass=pymysql.cursors.DictCursor)

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        search = request.args.get('search', '')
        query = "SELECT item, label, image FROM items WHERE item LIKE %s OR label LIKE %s"
        cur.execute(query, (f'%{search}%', f'%{search}%'))
        items = cur.fetchall()
    conn.close()
    return render_template('index.html', items=items, search=search)

@app.route('/upload/<item>', methods=['POST'])
def upload(item):
    file = request.files['icon']
    if file:
        filename = f"{item}.png"
        image = Image.open(file.stream).convert("RGBA")
        image = image.resize((98, 98))
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
