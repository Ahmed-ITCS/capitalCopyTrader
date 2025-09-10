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
    "api_key": "k2j6sIymvdnjy4Uf",
    "username": "ahmedkhawarbs@gmail.com",
    "password": "zatoonzatoonA1!",
    "app_id": "myapp"
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
        if acc_resp.status_code == 200:
            acc_id = acc_resp.json()["accounts"][0]["accountId"]
            return {"CST": cst, "X_SECURITY_TOKEN": x_sec, "ACCOUNT_ID": acc_id, "API_KEY": api_key}
        else:
            raise Exception(f"Account fetch failed: {acc_resp.text}")
    raise Exception(f"Session failed: {resp.text}")

def get_open_positions(session):
    headers = {
        "X-CAP-API-KEY": session["API_KEY"],
        "CST": session["CST"],
        "X-SECURITY-TOKEN": session["X_SECURITY_TOKEN"]
    }
    resp = requests.get("https://demo-api-capital.backend-capital.com/api/v1/positions", headers=headers)
    if resp.status_code == 200:
        return resp.json().get("positions", [])
    else:
        log_trade("SYSTEM", "⚠️", "", "", 0, 0, 0, "", f"Failed to fetch positions: {resp.text}")
        return []

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
    if sl is not None and sl > 0:
        payload["stopLevel"] = sl
    if tp is not None and tp > 0:
        payload["limitLevel"] = tp

    print(f"Order payload: {payload}")  # Debug: Log payload
    resp = requests.post("https://demo-api-capital.backend-capital.com/api/v1/positions", headers=headers, json=payload)
    print(f"API response: {resp.status_code} - {resp.text}")  # Debug: Log response

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
        positions = get_open_positions(bro_sess)
        print(f"Brother's positions: {positions}")  # Debug: Log raw positions
        for p in positions:
            pos = p.get('position', {})
            market = p.get('market', {})
            if not pos or not market:
                log_trade("SYSTEM", "⚠️", "", "", 0, 0, 0, "", "Invalid position or market data")
                continue
            try:
                epic = market['epic']
                direction = pos['direction']
                size = pos['size']
                sl = pos.get('stopLevel')  # Keep None if not present
                tp = pos.get('limitLevel')  # Keep None if not present
                print(f"Extracted: epic={epic}, direction={direction}, size={size}, sl={sl}, tp={tp}")  # Debug: Log extracted values
                key = (epic, direction, size, sl if sl is not None else 0, tp if tp is not None else 0)
                if key not in seen_positions:
                    seen_positions.add(key)
                    log_trade("NOUMAN", "📈", epic, direction, size, sl if sl is not None else 0, tp if tp is not None else 0)
                    success, result = place_market_order(you_sess, epic, direction, size, sl, tp)
                    if success:
                        log_trade("YOU", "✅", epic, direction, size, sl if sl is not None else 0, tp if tp is not None else 0, result)
                    else:
                        log_trade("YOU", "❌", epic, direction, size, sl if sl is not None else 0, tp if tp is not None else 0, "", result)
            except Exception as e:
                log_trade("YOU", "⚠️", epic, direction, size, sl if sl is not None else 0, tp if tp is not None else 0, "", str(e))
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