#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "==> Updating package list"
sudo apt-get update

echo "==> Installing Python"
sudo apt-get install -y python3 python3-venv python3-pip

echo "==> Creating virtual environment"
python3 -m venv .venv

echo "==> Activating venv"
source .venv/bin/activate

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing Python packages"
pip install -r requirements.txt

if [ ! -f config.json ]; then
    cp config.example.json config.json
    echo
    echo "=============================================="
    echo "Đã tạo config.json."
    echo "Hãy sửa bot_token và chat_id trước khi chạy."
    echo "=============================================="
fi

chmod +x bot.py

echo
echo "Cài đặt xong."
echo
echo "Test Telegram:"
echo "  source .venv/bin/activate && python bot.py --test"
echo
echo "Kiểm tra SMA200:"
echo "  source .venv/bin/activate && python bot.py --check --no-send"
