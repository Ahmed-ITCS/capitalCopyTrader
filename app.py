from flask import Flask, render_template, request, redirect, url_for, jsonify
import threading, time, requests, sqlite3
from datetime import datetime
import os

app = Flask(__name__)

mirror_thread = None
stop_flag = False
bot_status = "Stopped"
DB_PATH = "trades.db"

BROTHER_CREDENTIALS = {
    "api_key": "k2j6sIymvdnjy4Uf",
    "username": "ahmedkhawarbs@gmail.com",
    "password": "zatoonzatoonA1!",
    "app_id": "myapp"
}

YOUR_CREDENTIALS = {
    "api_key": "P8NeJSsUXWni16AI",
    "username": "ahmedkhawar.80@gmail.com",
    "password": "zatoonzatoonA1!",
    "app_id": "myapp1"
}

POLL_INTERVAL = 1

def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        source TEXT,
                        status TEXT,
                        epic TEXT,
                        direction TEXT,
                        size REAL,
                        sl REAL,
                        tp REAL,
                        order_id TEXT,
                        message TEXT
                    )''')
        conn.commit()
        conn.close()

def log_trade(source, status, epic, direction, size, sl, tp, order_id="", message=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO trades (
                    timestamp, source, status, epic, direction, size, sl, tp, order_id, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               source, status, epic, direction, size, sl, tp, order_id, message))
    conn.commit()
    conn.close()

def start_session(username, password, api_key, app_id):
    headers = {"X-CAP-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"identifier": username, "password": password, "appId": app_id}
    resp = requests.post("https://demo-api-capital.backend-capital.com/api/v1/session", json=payload, headers=headers)
    if resp.status_code == 200:
        cst = resp.headers.get("CST")
        x_sec = resp.headers.get("X-SECURITY-TOKEN")
        acc_resp = requests.get(
            "https://demo-api-capital.backend-capital.com/api/v1/accounts",
            headers={"X-CAP-API-KEY": api_key, "CST": cst, "X-SECURITY-TOKEN": x_sec}
        )
        acc_id = acc_resp.json()["accounts"][0]["accountId"]
        return {"CST": cst, "X_SECURITY_TOKEN": x_sec, "ACCOUNT_ID": acc_id, "API_KEY": api_key}
    raise Exception("Session failed: " + resp.text)

def get_open_positions(session):
    headers = {
        "X-CAP-API-KEY": session["API_KEY"],
        "CST": session["CST"],
        "X-SECURITY-TOKEN": session["X_SECURITY_TOKEN"]
    }
    resp = requests.get("https://demo-api-capital.backend-capital.com/api/v1/positions", headers=headers)
    return resp.json().get("positions", []) if resp.status_code == 200 else []

def place_market_order(session, epic, direction, size, sl, tp):
    headers = {
        "X-CAP-API-KEY": session["API_KEY"],
        "CST": session["CST"],
        "X-SECURITY-TOKEN": session["X_SECURITY_TOKEN"],
        "Content-Type": "application/json"
    }
    payload = {
        "epic": epic,
        "direction": direction,
        "size": size,
        "orderType": "MARKET",
        "timeInForce": "FILL_OR_KILL",
        "accountId": session["ACCOUNT_ID"]
    }
    if sl:
        payload["stopLevel"] = sl
    if tp:
        payload["limitLevel"] = tp

    resp = requests.post("https://demo-api-capital.backend-capital.com/api/v1/positions", headers=headers, json=payload)

    if resp.status_code == 200:
        data = resp.json()
        return True, data.get("dealId", "")
    else:
        return False, resp.text

def mirror_trades():
    global stop_flag, bot_status
    bot_status = "Running"
    seen_positions = set()
    try:
        bro_sess = start_session(**BROTHER_CREDENTIALS)
        you_sess = start_session(**YOUR_CREDENTIALS)
    except Exception as e:
        log_trade("SYSTEM", "❌", "", "", 0, 0, 0, "", str(e))
        bot_status = "Error"
        return

    while not stop_flag:
        for p in get_open_positions(bro_sess):
            pos = p.get('position', {})
            market = p.get('market', {})
            if not pos or not market:
                continue
            try:
                epic = market['epic']
                direction = pos['direction']
                size = pos['size']
                sl = pos.get('stopLevel', 0) or 0
                tp = pos.get('limitLevel', 0) or 0
                key = (epic, direction, size, sl, tp)
                if key not in seen_positions:
                    seen_positions.add(key)
                    log_trade("NOUMAN", "📈", epic, direction, size, sl, tp)
                    success, result = place_market_order(you_sess, epic, direction, size, sl, tp)
                    if success:
                        log_trade("YOU", "✅", epic, direction, size, sl, tp, result)
                    else:
                        log_trade("YOU", "❌", epic, direction, size, sl, tp, "", result)
            except Exception as e:
                log_trade("YOU", "⚠️", epic, direction, size, 0, 0, "", str(e))
        time.sleep(POLL_INTERVAL)
    bot_status = "Stopped"

def fetch_trades():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT timestamp, source, status, epic, direction, size, sl, tp, order_id, message FROM trades ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return rows

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/data")
def data():
    return jsonify({
        "status": bot_status,
        "trades": fetch_trades()
    })

@app.route("/start", methods=["POST"])
def start():
    global mirror_thread, stop_flag
    stop_flag = False
    if not mirror_thread or not mirror_thread.is_alive():
        mirror_thread = threading.Thread(target=mirror_trades)
        mirror_thread.start()
    return redirect(url_for("dashboard"))

@app.route("/stop", methods=["POST"])
def stop():
    global stop_flag
    stop_flag = True
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)