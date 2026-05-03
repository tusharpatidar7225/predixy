from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import yfinance as yf
import re
import os
from lstm_model import predict_prices, predict_intraday_prices
app = Flask(__name__)
CORS(app)

DATABASE = "database.db"


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

        hist = hist.dropna()

        times = []
        prices = []
        opens = []
        highs = []
        lows = []
        closes = []

        for index, row in hist.iterrows():
            times.append(index.strftime("%H:%M"))

            o = round(float(row["Open"]), 2)
            h = round(float(row["High"]), 2)
            l = round(float(row["Low"]), 2)
            c = round(float(row["Close"]), 2)

            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(c)
            prices.append(c)

        day_open = float(hist["Open"].iloc[0])
        day_high = float(hist["High"].max())
        day_low = float(hist["Low"].min())
        volume = int(hist["Volume"].sum())

        return jsonify({
            "times": times,

            # line graph ke liye
            "prices": prices,

            # candlestick ke liye arrays
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,

            # info cards ke liye
            "day_open": round(day_open, 2),
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
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
        import numpy as np
        import pandas as pd

        # Today actual data
        stock = yf.Ticker(symbol)
        today_hist = stock.history(period="1d", interval="5m", auto_adjust=False)

        if today_hist.empty:
            return jsonify({"times": [], "prices": []}), 200

        # Market timing
        if symbol.endswith(".NS"):
            open_hour, open_minute = 9, 15
            close_hour, close_minute = 15, 30
        else:
            open_hour, open_minute = 9, 30
            close_hour, close_minute = 16, 0

        first_index = today_hist.index[0]
        market_open = first_index.replace(hour=open_hour, minute=open_minute)
        market_close = first_index.replace(hour=close_hour, minute=close_minute)

        # Full day 5-min time labels
        full_times = []
        t = market_open
        while t <= market_close:
            full_times.append(t)
            t += timedelta(minutes=5)

        full_labels = [x.strftime("%H:%M") for x in full_times]

        # Past 60 days intraday data
        past = yf.download(
            symbol,
            period="60d",
            interval="5m",
            auto_adjust=False,
            progress=False
        )

        if past is None or past.empty:
            return jsonify({"times": full_labels, "prices": []}), 200

        # Close column handle
        close = past["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        df = pd.DataFrame({"Close": close}).dropna()
        df["time"] = df.index.strftime("%H:%M")
        df["date"] = df.index.date

        # Har day ka open se relative movement nikalo
        patterns = []

        for date, group in df.groupby("date"):
            group = group.copy()
            group = group.copy()
            if len(group) < 20:
                continue

            day_open = float(group["Close"].iloc[0])
            if day_open <= 0:
                continue

            movement = {}

            for i, time_key in enumerate(full_labels):
                if i < len(group):
                    price = float(group["Close"].iloc[i])
                    movement[time_key] = ((price - day_open) / day_open) * 100

            patterns.append(movement)

        if not patterns:
            return jsonify({"times": full_labels, "prices": []}), 200

        # Average historical intraday pattern
        avg_pattern = []

        for time_key in full_labels:
            vals = [p[time_key] for p in patterns if time_key in p]

            if vals:
                avg_pattern.append(float(np.mean(vals)))
            else:
                avg_pattern.append(0.0)

        # Today open ke according predicted price
        today_open = float(today_hist["Open"].iloc[0])

        predicted_prices = []
        for pct_move in avg_pattern:
            price = today_open * (1 + pct_move / 100)
            predicted_prices.append(round(float(price), 2))

        # Actual data ke trend ke according prediction ko adjust karo
        actual_close = float(today_hist["Close"].iloc[-1])
        actual_last_time = today_hist.index[-1].strftime("%H:%M")

        if actual_last_time in full_labels:
            idx = full_labels.index(actual_last_time)

            if idx < len(predicted_prices):
                predicted_at_now = predicted_prices[idx]
                adjustment = actual_close - predicted_at_now

                # Smooth adjustment: start se end tak gradually apply
                for i in range(len(predicted_prices)):
                    if i <= idx:
                        factor = i / max(idx, 1)
                    else:
                        factor = 1

                    predicted_prices[i] = round(
                        predicted_prices[i] + adjustment * factor,
                        2
                    )

        # Thodi natural volatility add karo, fixed seed so refresh pe graph stable rahe
        seed = sum(ord(c) for c in symbol)
        rng = np.random.default_rng(seed)

        for i in range(1, len(predicted_prices) - 1):
            noise = rng.normal(0, today_open * 0.0008)
            predicted_prices[i] = round(predicted_prices[i] + noise, 2)

        return jsonify({
            "times": full_labels,
            "prices": predicted_prices
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
