from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import yfinance as yf
import re
import os
from lstm_model import predict_prices, predict_intraday_prices
app = Flask(__name__)
CORS(app)
if not os.path.exists("/data"):
    os.makedirs("/data")
DATABASE = "/data/database.db"

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

        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(user_id, symbol),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.commit()


init_db()


@app.route("/")
def home():
    return send_from_directory(".", "loginsignup.html")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(".", "sitemap.xml")


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


@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    gmail_pattern = r"^[a-zA-Z0-9._%+-]+@gmail\.com$"

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


@app.route("/login", methods=["POST"])
def login():
    data = request.json

    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, username FROM users WHERE email=? AND password=?",
            (data["email"], data["password"])
        )
        user = c.fetchone()

    if user:
        return jsonify({
            "user_id": user[0],
            "username": user[1]
        }), 200
    else:
        return jsonify({"message": "Invalid email or password"}), 401


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

        return jsonify({
            "times": times,
            "prices": prices,
            "open": round(day_open, 2),
            "high": round(day_high, 2),
            "low": round(day_low, 2),
            "volume": volume
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/get_prediction/<symbol>")
def get_prediction(symbol):
    try:
        result = predict_prices(symbol)

        if result is None:
            return jsonify({
                "success": False,
                "message": f"Prediction unavailable for {symbol}. Data enough nahi mila ya model train/load nahi hua.",
                "next_day": None,
                "week": None,
                "month": None
            }), 400

        return jsonify({
            "success": True,
            "message": f"Prediction generated for {symbol}",
            "next_day": result["next_day"],
            "week": result["week"],
            "month": result["month"]
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Prediction error: {str(e)}",
            "next_day": None,
            "week": None,
            "month": None
        }), 500


@app.route("/watchlist/<int:user_id>", methods=["GET"])
def get_watchlist(user_id):
    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT symbol, name FROM watchlist WHERE user_id=? ORDER BY id DESC",
                (user_id,)
            )
            rows = c.fetchall()

        items = [{"symbol": row[0], "name": row[1]} for row in rows]
        return jsonify({"watchlist": items}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watchlist/add", methods=["POST"])
def add_to_watchlist():
    data = request.json
    user_id = data.get("user_id")
    symbol = data.get("symbol")
    name = data.get("name")

    if not user_id or not symbol or not name:
        return jsonify({"message": "Missing fields"}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR IGNORE INTO watchlist (user_id, symbol, name) VALUES (?, ?, ?)",
                (user_id, symbol, name)
            )
            conn.commit()

        return jsonify({"message": "Added to watchlist"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watchlist/remove", methods=["POST"])
def remove_from_watchlist():
    data = request.json
    user_id = data.get("user_id")
    symbol = data.get("symbol")

    if not user_id or not symbol:
        return jsonify({"message": "Missing fields"}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
                (user_id, symbol)
            )
            conn.commit()

        return jsonify({"message": "Removed from watchlist"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watchlist/check", methods=["POST"])
def check_watchlist():
    data = request.json
    user_id = data.get("user_id")
    symbol = data.get("symbol")

    if not user_id or not symbol:
        return jsonify({"message": "Missing fields"}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id FROM watchlist WHERE user_id=? AND symbol=?",
                (user_id, symbol)
            )
            row = c.fetchone()

        return jsonify({"saved": bool(row)}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/get_intraday_prediction/<symbol>")
def get_intraday_prediction(symbol):
    try:
        from datetime import timedelta

        stock = yf.Ticker(symbol)
        hist_today = stock.history(period="1d", interval="5m", auto_adjust=False)

        if hist_today.empty:
            return jsonify({"times": [], "prices": []}), 200

        last_index = hist_today.index[-1]

        close_hour, close_minute = (15, 30) if symbol.endswith(".NS") else (16, 0)
        close_time = last_index.replace(hour=close_hour, minute=close_minute)

        future_times = []
        next_time = last_index + timedelta(minutes=5)

        while next_time <= close_time:
            future_times.append(next_time)
            next_time += timedelta(minutes=5)

        steps = len(future_times)

        predicted_prices = predict_intraday_prices(symbol, steps=steps)

        if predicted_prices is None:
            return jsonify({"times": [], "prices": []}), 200

        return jsonify({
            "times": [t.strftime("%H:%M") for t in future_times],
            "prices": predicted_prices
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
