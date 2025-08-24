import os
import sqlite3
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, flash, abort
)
from werkzeug.utils import secure_filename
from promptpay import qrcode as pp_qrcode

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'thaishare.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
QR_DIR = os.path.join(BASE_DIR, 'qrcodes')

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-change-me'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
app.config['UPLOAD_FOLDER'] = UPLOAD_DIR

# --------------------- DB helpers ---------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS shares (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               title TEXT NOT NULL,
               evidence_path TEXT,
               promptpay TEXT NOT NULL,
               people INTEGER NOT NULL,
               amount REAL NOT NULL,
               per_person REAL NOT NULL,
               qr_path TEXT NOT NULL,
               created_at TEXT NOT NULL
           )'''
    )
    conn.commit()
    conn.close()

# --------------------- Routes ---------------------
@app.route('/')
def index():
    conn = get_db()
    rows = conn.execute('SELECT * FROM shares ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('index.html', rows=rows)

@app.route('/new', methods=['GET'])
def new_share():
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('new.html', today=today)

@app.route('/create', methods=['POST'])
def create_share():
    date = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
    title = (request.form.get('title') or '').strip()
    promptpay = (request.form.get('promptpay') or '').strip()
    people = int(request.form.get('people') or 0)
    amount = float(request.form.get('amount') or 0)

    if not title or not promptpay or people <= 0 or amount <= 0:
        flash('กรอกข้อมูลให้ครบ และค่าต้องมากกว่า 0', 'error')
        return redirect(url_for('new_share'))

    per_person = round(amount / people, 2)

    # upload evidence
    evidence_path = None
    file = request.files.get('evidence')
    if file and file.filename:
        fname = secure_filename(file.filename)
        save_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{fname}"
        save_path = os.path.join(UPLOAD_DIR, save_name)
        file.save(save_path)
        evidence_path = save_name

    # build QR (ใช้ promptpay lib) — payload คิดยอด "ต่อคน"
    payload = pp_qrcode.generate_payload(promptpay, per_person)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO shares (date, title, evidence_path, promptpay, people, amount, per_person, qr_path, created_at)             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (date, title, evidence_path, promptpay, people, amount, per_person, '', datetime.now().isoformat())
    )
    new_id = cur.lastrowid

    # generate QR image file
    qr_filename = f"qr_{new_id}.png"
    qr_path_abs = os.path.join(QR_DIR, qr_filename)
    pp_qrcode.to_file(payload, qr_path_abs)

    # update row with qr_path
    cur.execute('UPDATE shares SET qr_path=? WHERE id=?', (qr_filename, new_id))
    conn.commit()
    conn.close()

    flash('บันทึกรายการแล้ว พร้อมสร้าง QR เรียบร้อย', 'ok')
    return redirect(url_for('detail', share_id=new_id))

@app.route('/share/<int:share_id>')
def detail(share_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM shares WHERE id=?', (share_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    return render_template('detail.html', row=row)


@app.route('/delete/<int:share_id>', methods=['POST'])
def delete_share(share_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM shares WHERE id=?', (share_id,)).fetchone()
    if row:
        # remove files if exist
        if row['evidence_path']:
            try:
                os.remove(os.path.join(UPLOAD_DIR, row['evidence_path']))
            except FileNotFoundError:
                pass
        if row['qr_path']:
            try:
                os.remove(os.path.join(QR_DIR, row['qr_path']))
            except FileNotFoundError:
                pass
        conn.execute('DELETE FROM shares WHERE id=?', (share_id,))
        conn.commit()
    conn.close()
    flash('ลบรายการเรียบร้อย', 'ok')
    return redirect(url_for('index'))


@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route('/qrcodes/<path:filename>')
def qrcodes(filename):
    return send_from_directory(QR_DIR, filename)

if __name__ == '__main__':
    # Flask 3.0+: ไม่มี before_first_request แล้ว — เรียก init_db() ตรงนี้
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
