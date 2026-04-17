from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import yfinance as yf
import re
import os

# ================================================
#           APP INITIALIZATION & CONFIG
# ================================================
app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing for all routes

DATABASE = "database.db"  # SQLite database file name


# ================================================
#           DATABASE INITIALIZATION
# ================================================
def init_db():
    """
    Creates the 'users' table if it doesn't already exist.
    Called once when the server starts.
    """
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

init_db()  # Run DB initialization on startup


# ================================================
#           PAGE ROUTES (HTML SERVING)
# ================================================

@app.route("/")
def home():
    """Serve the Login/Signup page as the homepage."""
    return send_from_directory(".", "loginsignup.html")


@app.route('/sitemap.xml')
def sitemap():
    """Serve the sitemap.xml file for SEO purposes."""
    return send_from_directory('.', 'sitemap.xml')


@app.route("/dashboard")
def dashboard():
    """Serve the main dashboard/frontpage after login."""
    return send_from_directory(".", "frontpage.html")


@app.route("/wishlist")
def wishlist():
    """Serve the wishlist page where users can view saved stocks."""
    return send_from_directory(".", "wishlist.html")


@app.route("/stock/<symbol>")
def stock_page(symbol):
    """
    Serve the stock detail page for a given stock symbol.
    Example: /stock/AAPL => shows stock.html for Apple
    """
    return send_from_directory(".", "stock.html")


@app.route("/logout")
def logout():
    """Logout route - redirects user back to Login/Signup page."""
    return send_from_directory(".", "loginsignup.html")


# ================================================
#           REAL-TIME STOCK PRICE API
# ================================================

@app.route("/get_price/<symbol>")
def get_price(symbol):
    """
    Fetch real-time stock price for a given symbol using yFinance.
    Returns current price, change, percent change, and previous close.
    
    Example: GET /get_price/AAPL
    """
    try:
        stock = yf.Ticker(symbol)

        # Fetch today's 1-minute interval data
        hist = stock.history(period="1d", interval="1m")

        if hist.empty:
            return jsonify({"error": "No data"}), 400

        # Latest close = current price | First close = reference for change
        current_price = float(hist["Close"].iloc[-1])
        previous_close = float(hist["Close"].iloc[0])

        # Calculate absolute and percentage change
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


# ================================================
#           USER SIGNUP API
# ================================================

@app.route("/signup", methods=["POST"])
def signup():
    """
    Register a new user account.
    
    Expects JSON: { "username": "", "email": "", "password": "" }
    - Only @gmail.com emails are allowed.
    - Returns user_id on success.
    """
    data = request.json

    # Validate that only Gmail addresses are accepted
    gmail_pattern = r'^[a-zA-Z0-9._%+-]+@gmail\.com$'
    if not re.match(gmail_pattern, data["email"]):
        return jsonify({"message": "Only @gmail.com email allowed"}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()

            # Insert new user into the database
            c.execute(
                "INSERT INTO users (username,email,password) VALUES (?,?,?)",
                (data["username"], data["email"], data["password"])
            )
            conn.commit()
            user_id = c.lastrowid  # Get the auto-generated ID of new user

        return jsonify({
            "message": "Account created",
            "user_id": user_id
        }), 200

    except sqlite3.IntegrityError:
        # Triggered when email already exists (UNIQUE constraint)
        return jsonify({"message": "Email already exists"}), 400

    except Exception:
        return jsonify({"message": "Server error"}), 500


# ================================================
#           USER LOGIN API
# ================================================

@app.route("/login", methods=["POST"])
def login():
    """
    Authenticate an existing user.
    
    Expects JSON: { "email": "", "password": "" }
    - Returns user_id and username on success.
    - Returns 401 if credentials are invalid.
    """
    data = request.json

    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()

        # Check if a user exists with matching email & password
        c.execute(
            "SELECT id, username FROM users WHERE email=? AND password=?",
            (data["email"], data["password"])
        )
        user = c.fetchone()

    if user:
        # Login successful - return user info
        return jsonify({
            "user_id": user[0],
            "username": user[1]
        }), 200
    else:
        # No matching record found - invalid credentials
        return jsonify({"message": "Invalid email or password"}), 401


# ================================================
#           STOCK GRAPH DATA API
# ================================================

@app.route("/get_graph/<symbol>")
def get_graph(symbol):
    """
    Fetch intraday stock data for charting (5-minute intervals).
    Also returns key stats: open, high, low, volume, previous close.
    
    Example: GET /get_graph/TSLA
    """
    try:
        stock = yf.Ticker(symbol)

        # Fetch today's data at 5-minute intervals for the chart
        hist = stock.history(period="1d", interval="5m", auto_adjust=False)

        if hist.empty:
            return jsonify({"error": "No intraday data found"}), 400

        times = []
        prices = []

        # Build time and price arrays for the chart
        for index, row in hist.iterrows():
            times.append(index.strftime("%H:%M"))          # Format time as HH:MM
            prices.append(round(float(row["Close"]), 2))   # Round to 2 decimal places

        # Calculate key daily statistics from intraday data
        day_open = float(hist["Open"].iloc[0])
        day_high = float(hist["High"].max())
        day_low = float(hist["Low"].min())
        volume = int(hist["Volume"].sum())

        # Fetch last 10 days of daily data to find previous close
        daily_hist = stock.history(period="10d", interval="1d", auto_adjust=False)
        daily_hist = daily_hist.dropna(subset=["Close"])  # Remove any rows with no close price

        # Get the second-to-last close as the "previous close"
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


# ================================================
#           SERVER ENTRY POINT
# ================================================

if __name__ == "__main__":
    # Use PORT from environment (for deployment) or default to 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
