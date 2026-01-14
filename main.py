
# A very simple Flask Hello World app for you to get started with...

from flask import Flask, request, session, redirect, render_template_string, jsonify
import sqlite3, hashlib, os, zipfile, uuid, json, subprocess, datetime, random, threading, time, smtplib
from email.mime.text import MIMEText
import telebot
import config

# ================= APP =================
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

os.makedirs(config.BOT_TEMPLATES_DIR, exist_ok=True)
os.makedirs(config.USER_BOTS_DIR, exist_ok=True)

# ================= DB =================
db = sqlite3.connect("data.db", check_same_thread=False)
cur = db.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT UNIQUE,
 created_at TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 target TEXT,
 code TEXT,
 expires_at TEXT,
 verified INTEGER
);

CREATE TABLE IF NOT EXISTS bots(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT,
 price INTEGER,
 zip_path TEXT,
 created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_bots(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT,
 bot_id INTEGER,
 active INTEGER,
 created_at TEXT
);

CREATE TABLE IF NOT EXISTS analytics(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT,
 date TEXT,
 bot_count INTEGER
);

CREATE TABLE IF NOT EXISTS global_analytics(
 date TEXT,
 users INTEGER,
 bots INTEGER,
 active_bots INTEGER
);
""")
db.commit()

# ================= HELPERS =================
def hash_user(u): return hashlib.sha256(u.encode()).hexdigest()

def generate_otp(): return str(random.randint(100000,999999))

def save_otp(target):
    code = generate_otp()
    expires = (datetime.datetime.now()+datetime.timedelta(minutes=1)).isoformat()
    cur.execute(
        "INSERT INTO otp_codes(target,code,expires_at,verified) VALUES(?,?,?,0)",
        (target, code, expires)
    )
    db.commit()
    return code

def verify_otp(target, code):
    cur.execute("""
      SELECT id FROM otp_codes
      WHERE target=? AND code=? AND verified=0
      AND expires_at > ?
      ORDER BY id DESC LIMIT 1
    """,(target, code, datetime.datetime.now().isoformat()))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE otp_codes SET verified=1 WHERE id=?", (row[0],))
        db.commit()
        return True
    return False

def log_user_analytics(username):
    cur.execute("SELECT COUNT(*) FROM user_bots WHERE username=?", (username,))
    count = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO analytics(username,date,bot_count) VALUES(?,?,?)",
        (username, datetime.date.today().isoformat(), count)
    )
    db.commit()

def log_global_analytics():
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM user_bots")
    bots = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM user_bots WHERE active=1")
    active = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO global_analytics VALUES(?,?,?,?)",
        (datetime.date.today().isoformat(), users, bots, active)
    )
    db.commit()

# ================= GMAIL OTP =================
def send_gmail(email, code):
    msg = MIMEText(f"Kirish kodingiz: {code}")
    msg["Subject"] = "OTP Login"
    msg["From"] = config.GMAIL_USER
    msg["To"] = email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        s.send_message(msg)

@app.route("/gmail_otp", methods=["POST"])
def gmail_otp():
    email = request.form["email"]
    code = save_otp(email)
    send_gmail(email, code)
    return "OK"

# ================= TELEGRAM OTP BOT =================
tg_bot = telebot.TeleBot(config.TG_LOGIN_BOT_TOKEN)
active_tg = {}

@tg_bot.message_handler(commands=["start"])
def tg_start(msg):
    chat_id = str(msg.chat.id)
    active_tg[chat_id] = True

    def loop():
        while active_tg.get(chat_id):
            code = save_otp(chat_id)
            tg_bot.send_message(chat_id, f"🔐 Login kodi: {code}")
            time.sleep(60)

    threading.Thread(target=loop).start()

def stop_tg(chat_id):
    active_tg[chat_id] = False

threading.Thread(target=lambda: tg_bot.infinity_polling()).start()

# ================= OTP VERIFY =================
@app.route("/verify_otp", methods=["POST"])
def verify():
    target = request.form["target"]
    code = request.form["code"]
    if verify_otp(target, code):
        session["user"] = hash_user(target)
        stop_tg(target)
        cur.execute("INSERT OR IGNORE INTO users(username,created_at) VALUES(?,?)",
                    (session["user"], datetime.datetime.now().isoformat()))
        db.commit()
        return "OK"
    return "ERROR"

# ================= DASHBOARD =================
@app.route("/")
def dashboard():
    if "user" not in session:
        return "Login first"

    u = session["user"]
    cur.execute("SELECT COUNT(*) FROM user_bots WHERE username=?", (u,))
    count = cur.fetchone()[0]

    cur.execute("""
    SELECT user_bots.id,bots.name,bots.price,user_bots.active
    FROM user_bots JOIN bots ON bots.id=user_bots.bot_id
    WHERE user_bots.username=?
    """,(u,))
    mybots = cur.fetchall()

    cur.execute("SELECT * FROM bots")
    allbots = cur.fetchall()

    return render_template_string("""
<script src="https://cdn.tailwindcss.com"></script>
<div class="p-4">
<div class="flex justify-between"><b>User</b><span>🤖 {{count}}</span></div>

<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
<div class="bg-white p-3 rounded">
<h3>➕ Yangi bot</h3>
{% for b in allbots %}
<form method=post action="/open">
<input type=hidden name=bot value="{{b[0]}}">
<b>{{b[1]}}</b> - {{b[2]}} so'm
<button class="block bg-blue-500 text-white px-2 py-1 mt-1">Ochish</button>
</form>
{% endfor %}
</div>

<div class="md:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
{% for b in mybots %}
<div class="border p-2 rounded">
<b>{{b[1]}}</b><br>
<a href="/toggle/{{b[0]}}">Toggle</a> |
<a href="/delete/{{b[0]}}">Delete</a>
</div>
{% endfor %}
</div>
</div>

<canvas id="c"></canvas>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
fetch("/analytics").then(r=>r.json()).then(d=>{
 new Chart(document.getElementById("c"),{
 type:"line",
 data:{labels:d.l, datasets:[{data:d.v,label:"Botlar"}]}
 })
})
</script>
</div>
""", count=count, mybots=mybots, allbots=allbots)

# ================= BOT ACTIONS =================
@app.route("/open", methods=["POST"])
def open_bot():
    u = session["user"]
    bid = request.form["bot"]
    cur.execute("INSERT INTO user_bots(username,bot_id,active,created_at) VALUES(?,?,1,?)",
                (u,bid,datetime.datetime.now().isoformat()))
    db.commit()
    log_user_analytics(u)
    log_global_analytics()
    return redirect("/")

@app.route("/toggle/<int:id>")
def toggle(id):
    cur.execute("SELECT active,username FROM user_bots WHERE id=?", (id,))
    a,u = cur.fetchone()
    cur.execute("UPDATE user_bots SET active=? WHERE id=?", (0 if a else 1, id))
    db.commit()
    log_user_analytics(u)
    return redirect("/")

@app.route("/delete/<int:id>")
def delete(id):
    cur.execute("SELECT username FROM user_bots WHERE id=?", (id,))
    u = cur.fetchone()[0]
    cur.execute("DELETE FROM user_bots WHERE id=?", (id,))
    db.commit()
    log_user_analytics(u)
    return redirect("/")

# ================= ANALYTICS =================
@app.route("/analytics")
def analytics():
    u = session["user"]
    cur.execute("SELECT date,bot_count FROM analytics WHERE username=?", (u,))
    d = cur.fetchall()
    return jsonify({"l":[x[0] for x in d], "v":[x[1] for x in d]})

@app.route("/admin/analytics")
def admin_analytics():
    if session.get("user") != hash_user(config.ADMIN_USERNAME):
        return "DENIED"
    cur.execute("SELECT * FROM global_analytics")
    return jsonify(cur.fetchall())

# ================= ADMIN =================
@app.route("/admin", methods=["GET","POST"])
def admin():
    if session.get("user") != hash_user(config.ADMIN_USERNAME):
        return "DENIED"

    if request.method=="POST":
        f=request.files["zip"]
        uid=str(uuid.uuid4())
        path=os.path.join(config.BOT_TEMPLATES_DIR,uid+".zip")
        f.save(path)
        cur.execute("INSERT INTO bots(name,price,zip_path,created_at) VALUES(?,?,?,?)",
                    (request.form["name"],request.form["price"],path,datetime.datetime.now().isoformat()))
        db.commit()

    cur.execute("SELECT * FROM bots")
    return render_template_string("""
<h2>Admin</h2>
<form method=post enctype=multipart/form-data>
<input name=name placeholder="Name">
<input name=price placeholder="Price">
<input type=file name=zip>
<button>Add</button>
</form>
<hr>
{% for b in bots %}{{b[1]}}<br>{% endfor %}
""", bots=cur.fetchall())

# ================= RUN =================
app.run(debug=True)
