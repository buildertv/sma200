SMA200 E1VFVN30 -> Telegram
Bot chạy trên Ubuntu VPS, lấy dữ liệu Daily E1VFVN30 bằng Vnstock và tính SMA200.
Quy tắc
Đây là phiên bản 80/20:
Giá đóng cửa phiên cuối tháng > SMA200 cuối tháng
ETF: 80%
Tiền mặt: 20%
Giá đóng cửa phiên cuối tháng < SMA200 cuối tháng
ETF: 20%
Tiền mặt: 80%
Bot chỉ xét tháng đã kết thúc, không bán/mua chỉ vì giá intraday hoặc giữa tháng cắt SMA200.
Mặc định bot chỉ gửi Telegram khi trạng thái thay đổi.
1. Cài đặt
```bash
chmod +x install.sh
./install.sh
```
2. Tạo Telegram Bot
Trong Telegram:
Mở `@BotFather`
`/newbot`
Đặt tên bot
Lấy `BOT_TOKEN`
Sau đó mở chat với bot và gửi một tin nhắn bất kỳ.
Lấy `chat_id` bằng cách mở:
```text
https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
```
Tìm:
```json
"chat": {
  "id": 123456789
}
```
Nếu là group thì chat_id thường là số âm, ví dụ `-1001234567890`.
3. Cấu hình
```bash
nano config.json
```
Ví dụ:
```json
{
  "symbol": "E1VFVN30",
  "history_years": 2,
  "telegram": {
    "bot_token": "123456:ABC...",
    "chat_id": "123456789"
  },
  "notify_every_completed_month": false
}
```
4. Test Telegram
```bash
source .venv/bin/activate
python bot.py --test
```
5. Test tính SMA200, KHÔNG gửi Telegram
```bash
source .venv/bin/activate
python bot.py --check --no-send
```
6. Kiểm tra và gửi tín hiệu
```bash
source .venv/bin/activate
python bot.py --check
```
7. Ép gửi tín hiệu hiện tại
Chỉ dùng khi muốn kiểm tra Telegram:
```bash
source .venv/bin/activate
python bot.py --check --force
```
8. Cron
Khuyến nghị chạy mỗi ngày lúc 18:00:
```bash
crontab -e
```
Thêm:
```cron
0 18 * * * cd /opt/sma200_bot && /opt/sma200_bot/.venv/bin/python /opt/sma200_bot/bot.py --check >> /opt/sma200_bot/cron.log 2>&1
```
Bot tự bỏ qua tháng hiện tại và chỉ xử lý tháng đã kết thúc.
Ví dụ ngày 01/09:
lấy phiên giao dịch cuối tháng 08
tính Close cuối tháng 08
tính SMA200 tại phiên đó
quyết định 80/20 hoặc 20/80
nếu trạng thái thay đổi thì gửi Telegram
9. State
`state.json` dùng để chống gửi trùng.
Ví dụ:
```json
{
  "last_processed_month": "2026-08",
  "last_signal": "ETF20_CASH80",
  "last_check_date": "2026-09-01",
  "last_close": 33.9,
  "last_sma200": 34.88
}
```
Không xóa file này nếu không cần reset trạng thái.
10. Log
Log nằm ở:
```text
sma200_bot.log
cron.log
```
Lưu ý
Bot chỉ phát tín hiệu, không tự đặt lệnh mua/bán.
Nếu Vnstock/API lỗi, bot không tự chuyển sang CASH; nó báo lỗi và không phát tín hiệu.
Dữ liệu thị trường cần được kiểm tra trước khi dùng cho quyết định đầu tư thực tế.
