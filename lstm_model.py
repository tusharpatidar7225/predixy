import os
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Input

MODEL_DIR = "model_cache"


def ensure_model_dir():
    if not os.path.exists(MODEL_DIR):
        os.makedirs(MODEL_DIR)


def get_model_path(symbol):
    safe_symbol = symbol.replace("/", "_").replace("^", "_")
    return os.path.join(MODEL_DIR, f"{safe_symbol}.keras")


def build_model(input_shape):
    model = Sequential([
        Input(shape=input_shape),
        LSTM(50, return_sequences=True),
        LSTM(50),
        Dense(25, activation="relu"),
        Dense(1)
    ])
    model.compile(optimizer="adam", loss="mean_squared_error")
    return model


def extract_close_series(df):
    if df is None or df.empty:
        return None

    # Case 1: normal single-level columns
    if "Close" in df.columns:
        close_series = df["Close"]
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]
        return close_series.dropna()

    # Case 2: MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        for col in df.columns:
            if "Close" in col:
                close_series = df[col]
                if isinstance(close_series, pd.DataFrame):
                    close_series = close_series.iloc[:, 0]
                return close_series.dropna()

    # Case 3: fallback by checking any column containing 'Close'
    for col in df.columns:
        if "Close" in str(col):
            close_series = df[col]
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            return close_series.dropna()

    return None


def fetch_stock_data(symbol):
    df = yf.download(
        symbol,
        period="5y",
        interval="1d",
        auto_adjust=False,
        progress=False
    )

    if df is None or df.empty:
        return None

    close_series = extract_close_series(df)
    if close_series is None or close_series.empty:
        return None

    close_values = close_series.astype(float).values

    if len(close_values) < 120:
        return None

    return close_values


def prepare_training_data(close_values, lookback=120):
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_data = scaler.fit_transform(close_values.reshape(-1, 1))

    X, y = [], []
    for i in range(lookback, len(scaled_data)):
        X.append(scaled_data[i - lookback:i, 0])
        y.append(scaled_data[i, 0])

    if len(X) == 0:
        return None, None, None, None

    X = np.array(X)
    y = np.array(y)
    X = X.reshape((X.shape[0], X.shape[1], 1))

    return X, y, scaler, scaled_data


def train_and_save_model(symbol, close_values, model_path):
    X, y, scaler, scaled_data = prepare_training_data(close_values)

    if X is None:
        return None, None, None

    model = build_model((X.shape[1], 1))
    model.fit(X, y, epochs=8, batch_size=16, verbose=0)
    model.save(model_path)

    return model, scaler, scaled_data


def load_or_train_model(symbol):
    ensure_model_dir()

    close_values = fetch_stock_data(symbol)
    if close_values is None:
        return None, None, None

    model_path = get_model_path(symbol)

    X, y, scaler, scaled_data = prepare_training_data(close_values)
    if X is None:
        return None, None, None

    if os.path.exists(model_path):
        try:
            model = load_model(model_path)
            return model, scaler, scaled_data
        except Exception:
            pass

    model, scaler, scaled_data = train_and_save_model(symbol, close_values, model_path)
    if model is None:
        return None, None, None

    return model, scaler, scaled_data


def predict_prices(symbol):
    lookback = 120

    model, scaler, scaled_data = load_or_train_model(symbol)

    if model is None or scaler is None or scaled_data is None:
        return None

    if len(scaled_data) < lookback:
        return None

    last_window = scaled_data[-lookback:].copy()
    future_scaled = []

    for _ in range(30):
        x_input = last_window.reshape(1, lookback, 1)
        pred = model.predict(x_input, verbose=0)
        pred_value = float(pred[0][0])
        future_scaled.append(pred_value)

        pred_row = np.array([[pred_value]])
        last_window = np.vstack((last_window[1:], pred_row))

    future_prices = scaler.inverse_transform(
        np.array(future_scaled).reshape(-1, 1)
    ).flatten()

    return {
        "next_day": round(float(future_prices[0]), 2),
        "week": round(float(future_prices[6]), 2),
        "month": round(float(future_prices[29]), 2)
    }

def predict_intraday_prices(symbol, steps=60):
    df = yf.download(
        symbol,
        period="60d",
        interval="5m",
        auto_adjust=False,
        progress=False
    )

    close_series = extract_close_series(df)
    if close_series is None or close_series.empty or len(close_series) < 120:
        return None

    close_values = close_series.astype(float).values

    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_data = scaler.fit_transform(close_values.reshape(-1, 1))

    lookback = 60
    X, y = [], []

    for i in range(lookback, len(scaled_data)):
        X.append(scaled_data[i - lookback:i, 0])
        y.append(scaled_data[i, 0])

    X = np.array(X).reshape(-1, lookback, 1)
    y = np.array(y)

    model = build_model((lookback, 1))
    model.fit(X, y, epochs=5, batch_size=16, verbose=0)

    last_60 = scaled_data[-lookback:].copy()
    future_scaled = []

    for _ in range(steps):
        x_input = last_60.reshape(1, lookback, 1)
        pred = model.predict(x_input, verbose=0)
        pred_value = float(pred[0][0])
        future_scaled.append(pred_value)
        last_60 = np.vstack((last_60[1:], [[pred_value]]))

    future_prices = scaler.inverse_transform(
        np.array(future_scaled).reshape(-1, 1)
    ).flatten()

    return [round(float(x), 2) for x in future_prices]
