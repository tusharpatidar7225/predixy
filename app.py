from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import yfinance as yf
import re
import os

app = Flask(__name__)
CORS(app)

DATABASE = "database.db"

# ---------------- DATABASE INIT ----------------
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                email TEXT UNIQUE,
                password TEXT
            )
        """)
        conn.commit()

init_db()

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return send_from_directory(".", "loginsignup.html")
@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')
@app.route("/dashboard")
def dashboard():
    return send_from_directory(".", "frontpage.html")

@app.route("/wishlist")
def wishlist():
    return send_from_directory(".", "wishlist.html")

@app.route("/stock/<symbol>")
def stock_page(symbol):
    return send_from_directory(".", "stock.html")

@app.route("/logout")
def logout():
    return send_from_directory(".", "loginsignup.html")

# ---------------- REAL TIME PRICE ----------------
@app.route("/get_price/<symbol>")
def get_price(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1d", interval="1m")

        if hist.empty:
            return jsonify({"error": "No data"}), 400

        current_price = float(hist["Close"].iloc[-1])
        previous_close = float(hist["Close"].iloc[0])

        change = current_price - previous_close
        percent = (change / previous_close) * 100

        return jsonify({
            "price": round(current_price, 2),
            "change": round(change, 2),
            "percent": round(percent, 2),
            "previous_close": round(previous_close, 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    gmail_pattern = r'^[a-zA-Z0-9._%+-]+@gmail\.com$'

    if not re.match(gmail_pattern, data["email"]):
        return jsonify({"message": "Only @gmail.com email allowed"}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (username,email,password) VALUES (?,?,?)",
                (data["username"], data["email"], data["password"])
            )
            conn.commit()
            user_id = c.lastrowid

        return jsonify({
            "message": "Account created",
            "user_id": user_id
        }), 200

    except sqlite3.IntegrityError:
        return jsonify({"message": "Email already exists"}), 400

    except Exception:
        return jsonify({"message": "Server error"}), 500

# ---------------- LOGIN ----------------
@app.route("/login", methods=["POST"])
def login():
    data = request.json

    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM users WHERE email=? AND password=?",
            (data["email"], data["password"])
        )
        user = c.fetchone()

    if user:
        return jsonify({"user_id": user[0]}), 200
    else:
        return jsonify({"message": "Invalid email or password"}), 401

# ---------------- GRAPH DATA ----------------
@app.route("/get_graph/<symbol>")
def get_graph(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1d", interval="5m", auto_adjust=False)

        if hist.empty:
            return jsonify({"error": "No intraday data found"}), 400

        times = []
        prices = []

        for index, row in hist.iterrows():
            times.append(index.strftime("%H:%M"))
            prices.append(round(float(row["Close"]), 2))

        day_open = float(hist["Open"].iloc[0])
        day_high = float(hist["High"].max())
        day_low = float(hist["Low"].min())
        volume = int(hist["Volume"].sum())

        daily_hist = stock.history(period="10d", interval="1d", auto_adjust=False)
        daily_hist = daily_hist.dropna(subset=["Close"])

        previous_close = None
        if len(daily_hist) >= 2:
            previous_close = float(daily_hist["Close"].iloc[-2])
        elif len(daily_hist) == 1:
            previous_close = float(daily_hist["Close"].iloc[-1])

        return jsonify({
            "times": times,
            "prices": prices,
            "open": round(day_open, 2),
            "high": round(day_high, 2),
            "low": round(day_low, 2),
            "previous_close": round(previous_close, 2) if previous_close is not None else None,
            "volume": volume
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
