#!/usr/bin/env python3
"""
SMA200 E1VFVN30 -> Telegram bot

Quy tắc:
- Lấy dữ liệu DAILY của E1VFVN30.
- Tính SMA200 từ giá đóng cửa.
- Chỉ chốt tín hiệu cho THÁNG ĐÃ KẾT THÚC.
- Giá đóng cửa cuối tháng > SMA200 cuối tháng:
    ETF 80% / CASH 20%
- Giá đóng cửa cuối tháng < SMA200 cuối tháng:
    ETF 20% / CASH 80%
- Chỉ gửi Telegram khi trạng thái của tháng đó khác trạng thái đã lưu.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# Vnstock 4.x: tài liệu hiện tại dùng vnstock.ui.Market.
# Fallback để tương thích một số môi trường/package cũ.
try:
    from vnstock.ui import Market
except ImportError:
    from vnstock_data import Market


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "sma200_bot.log"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("sma200")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Chưa có {CONFIG_FILE}. Hãy copy config.example.json thành config.json."
        )

    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    telegram = cfg.get("telegram", {})
    token = telegram.get("bot_token", "").strip()
    chat_id = str(telegram.get("chat_id", "")).strip()

    if not token or token == "YOUR_BOT_TOKEN":
        raise ValueError("Telegram bot_token chưa được cấu hình.")
    if not chat_id or chat_id == "YOUR_CHAT_ID":
        raise ValueError("Telegram chat_id chưa được cấu hình.")

    return cfg


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Không đọc được state.json; sẽ coi như chưa có trạng thái.")
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_FILE)


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("Vnstock trả về DataFrame rỗng.")

    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]

    # Một số nguồn/package có thể dùng "time" hoặc "date".
    time_col = next((c for c in ("time", "date", "datetime") if c in out.columns), None)
    if time_col is None:
        raise ValueError(f"Không tìm thấy cột thời gian. Columns={list(out.columns)}")

    close_col = next((c for c in ("close", "closing_price") if c in out.columns), None)
    if close_col is None:
        raise ValueError(f"Không tìm thấy cột close. Columns={list(out.columns)}")

    out["time"] = pd.to_datetime(out[time_col], errors="coerce")
    out["close"] = pd.to_numeric(out[close_col], errors="coerce")

    out = out.dropna(subset=["time", "close"]).copy()
    out = out.sort_values("time").drop_duplicates(subset=["time"], keep="last")
    out = out[["time", "close"]].reset_index(drop=True)

    if len(out) < 200:
        raise ValueError(
            f"Chỉ lấy được {len(out)} phiên, chưa đủ 200 phiên để tính SMA200."
        )

    out["sma200"] = out["close"].rolling(200, min_periods=200).mean()
    out = out.dropna(subset=["sma200"]).reset_index(drop=True)

    return out


def fetch_daily_data(symbol: str, years: int = 2) -> pd.DataFrame:
    # Lấy dư dữ liệu để chắc chắn đủ 200 phiên.
    end = date.today()
    start = end - timedelta(days=365 * years)

    logger.info("Lấy dữ liệu %s từ %s đến %s ...", symbol, start, end)

    mkt = Market()

    # API Unified UI hiện tại.
    try:
        df = mkt.etf(symbol).ohlcv(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1D",
        )
    except TypeError:
        # Fallback cho một số bản dùng length thay vì start/end.
        df = mkt.etf(symbol).ohlcv(
            length=600,
            interval="1D",
        )

    return normalize_ohlcv(df)


def get_last_completed_month_row(df: pd.DataFrame) -> pd.Series | None:
    """
    Chỉ chọn tháng đã kết thúc.
    Ví dụ chạy ngày 01/09:
      -> chọn phiên cuối tháng 08.
    Nếu dữ liệu mới nhất vẫn thuộc tháng trước:
      -> vẫn chọn tháng trước.
    Nếu vì lý do dữ liệu đã có tháng hiện tại:
      -> bỏ toàn bộ tháng hiện tại và chọn tháng gần nhất trước đó.
    """
    current_month = pd.Period(date.today(), freq="M")
    df = df.copy()
    df["month"] = df["time"].dt.to_period("M")

    completed = df[df["month"] < current_month].copy()

    if completed.empty:
        return None

    # Phiên cuối cùng trong tháng hoàn chỉnh gần nhất.
    last_month = completed["month"].max()
    rows = completed[completed["month"] == last_month]

    if rows.empty:
        return None

    return rows.iloc[-1]


def calculate_signal(row: pd.Series) -> dict:
    close = float(row["close"])
    sma200 = float(row["sma200"])
    month = str(row["month"])

    if close > sma200:
        state = "ETF80_CASH20"
        etf_pct = 80
        cash_pct = 20
        action = "🟢 GIỮ/MUA ETF"
    elif close < sma200:
        state = "ETF20_CASH80"
        etf_pct = 20
        cash_pct = 80
        action = "🔴 PHÒNG THỦ / CHUYỂN 80% SANG TIỀN MẶT"
    else:
        state = "ETF20_CASH80"
        etf_pct = 20
        cash_pct = 80
        action = "🟡 GIÁ = SMA200 → XỬ LÝ PHÒNG THỦ"

    diff_pct = (close / sma200 - 1.0) * 100.0

    return {
        "month": month,
        "date": row["time"].strftime("%Y-%m-%d"),
        "close": close,
        "sma200": sma200,
        "diff_pct": diff_pct,
        "state": state,
        "etf_pct": etf_pct,
        "cash_pct": cash_pct,
        "action": action,
    }


def format_message(symbol: str, signal: dict, previous_state: str | None) -> str:
    direction = (
        "TRẠNG THÁI THAY ĐỔI"
        if previous_state and previous_state != signal["state"]
        else "TRẠNG THÁI"
    )

    return (
        f"📊 SMA200 — {symbol}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Tháng chốt: {signal['month']}\n"
        f"Phiên cuối tháng: {signal['date']}\n\n"
        f"Giá đóng cửa: {signal['close']:.2f}\n"
        f"SMA200: {signal['sma200']:.2f}\n"
        f"Chênh lệch: {signal['diff_pct']:+.2f}%\n\n"
        f"{direction}\n"
        f"{signal['action']}\n\n"
        f"Phân bổ mục tiêu:\n"
        f"• ETF: {signal['etf_pct']}%\n"
        f"• Tiền mặt: {signal['cash_pct']}%\n\n"
        f"⚠️ Đây là tín hiệu theo quy tắc SMA200 80/20, "
        f"không phải lệnh giao dịch tự động."
    )


def telegram_send(cfg: dict, text: str) -> None:
    token = cfg["telegram"]["bot_token"]
    chat_id = str(cfg["telegram"]["chat_id"])

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API lỗi: {data}")

    logger.info("Đã gửi Telegram.")


def check_once(cfg: dict, force: bool = False, send: bool = True) -> dict:
    symbol = cfg.get("symbol", "E1VFVN30")
    years = int(cfg.get("history_years", 2))

    df = fetch_daily_data(symbol, years)
    row = get_last_completed_month_row(df)

    if row is None:
        raise RuntimeError(
            "Chưa có dữ liệu của một tháng đã hoàn tất. Không phát tín hiệu."
        )

    # period phải được thêm sau khi normalize; nếu không có thì bổ sung.
    row = row.copy()
    row["month"] = row["time"].to_period("M")

    signal = calculate_signal(row)

    state = load_state()
    previous_month = state.get("last_processed_month")
    previous_state = state.get("last_signal")

    logger.info(
        "Tháng=%s | close=%.2f | SMA200=%.2f | diff=%+.2f%% | state=%s",
        signal["month"],
        signal["close"],
        signal["sma200"],
        signal["diff_pct"],
        signal["state"],
    )

    is_new_month = previous_month != signal["month"]
    is_state_changed = previous_state != signal["state"]

    should_send = force or (is_new_month and is_state_changed)

    # Nếu muốn nhận thông báo trạng thái mỗi tháng, đổi config:
    # "notify_every_completed_month": true
    if cfg.get("notify_every_completed_month", False):
        should_send = force or is_new_month

    message = format_message(symbol, signal, previous_state)

    if send and should_send:
        telegram_send(cfg, message)
    elif send:
        logger.info("Không gửi Telegram: chưa có thay đổi trạng thái.")

    # Chỉ lưu trạng thái sau khi xử lý thành công.
    state.update(
        {
            "last_processed_month": signal["month"],
            "last_signal": signal["state"],
            "last_check_date": date.today().isoformat(),
            "last_close": signal["close"],
            "last_sma200": signal["sma200"],
        }
    )
    save_state(state)

    return signal


def main() -> int:
    parser = argparse.ArgumentParser(description="E1VFVN30 SMA200 Telegram Bot")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Kiểm tra tín hiệu hiện tại.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Gửi tin nhắn test Telegram.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ép gửi tín hiệu hiện tại dù trạng thái chưa đổi.",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Chỉ tính toán, không gửi Telegram.",
    )
    args = parser.parse_args()

    try:
        cfg = load_config()

        if args.test:
            telegram_send(
                cfg,
                "✅ SMA200 Bot\n\nTelegram connection OK.\n"
                "Bot đã kết nối thành công với VPS.",
            )
            return 0

        signal = check_once(
            cfg,
            force=args.force,
            send=not args.no_send,
        )

        print("\n===== SMA200 RESULT =====")
        print(f"Tháng:       {signal['month']}")
        print(f"Ngày:        {signal['date']}")
        print(f"Close:       {signal['close']:.2f}")
        print(f"SMA200:      {signal['sma200']:.2f}")
        print(f"Chênh lệch:  {signal['diff_pct']:+.2f}%")
        print(f"ETF:         {signal['etf_pct']}%")
        print(f"Cash:        {signal['cash_pct']}%")
        print(f"Tín hiệu:    {signal['action']}")
        print("=========================\n")

        return 0

    except Exception as exc:
        logger.exception("BOT ERROR: %s", exc)

        # Không gửi lỗi qua Telegram nếu chính việc cấu hình Telegram
        # có thể đang là nguyên nhân gây lỗi.
        try:
            cfg = load_config()
            telegram_send(
                cfg,
                "⚠️ SMA200 BOT ERROR\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "Bot KHÔNG phát tín hiệu giao dịch.",
            )
        except Exception:
            logger.exception("Không gửi được thông báo lỗi Telegram.")

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
