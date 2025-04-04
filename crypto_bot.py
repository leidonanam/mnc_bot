import os
import requests
import time
import telebot
import logging
from threading import Thread
from datetime import datetime
from flask import Flask
import pytz

# === Cấu hình Logging ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === Cấu hình Telegram Bot ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Token của bot từ BotFather
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")     # ID chat của nhóm hoặc người dùng
if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("⚠️ Hãy đảm bảo bạn thiết lập TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID trong biến môi trường!")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# Danh sách coin theo dõi
WATCHLIST = {"BTC", "ETH", "ADA", "CAKE", "PI", "SOL", "TRUMP", "XRP", "DOGE", "TRX"}

# === Flask App giữ bot "sống" ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# === Lệnh /help ===
@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "📌 Danh sách lệnh:\n"
        "/start - Bắt đầu bot\n"
        "/status - Kiểm tra trạng thái bot\n"
        "/p [coin] [khung thời gian] - Xem giá và % thay đổi của coin\n"
        "Ví dụ: /p BTC ETH dom 15m (xem giá BTC, ETH & BTC Dominance, thay đổi so với 15 phút trước)"
    )
    bot.send_message(message.chat.id, help_text)

# === Lệnh /start ===
@bot.message_handler(commands=['start'])
def start_bot(message):
    bot.send_message(message.chat.id, "🤖 Bot Crypto đã khởi động! Gõ /help để xem danh sách lệnh.")

# === Lệnh /status ===
@bot.message_handler(commands=['status'])
def check_status(message):
    bot.send_message(message.chat.id, "✅ Bot đang hoạt động bình thường!")

# Lấy BTC Dominance từ CoinGecko
def get_btc_dominance():
    url = "https://api.coingecko.com/api/v3/global"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data['data']['market_cap_percentage']['btc']
    return None

# Lệnh /p để kiểm tra giá nhiều coin
def get_price_change(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Vui lòng nhập lệnh đúng định dạng: /p [coin1] [coin2] ... [thời gian]")
            return

        coins = [coin.upper() for coin in parts[1:-1]]
        timeframe = parts[-1] if len(parts) > 2 else "15m"
        reply_texts = []

        for coin in coins:
            if coin in {"BTC.D", "DOM"}:  # Kiểm tra BTC Dominance
                btc_dominance = get_btc_dominance()
                if btc_dominance is None:
                    reply_texts.append("⚠️ Không thể lấy dữ liệu BTC Dominance!")
                else:
                    reply_texts.append(f"📊 BTC Dominance hiện tại: {btc_dominance:.2f}% (khung thời gian: {timeframe})")
            else:
                url = f"https://api.mexc.com/api/v3/ticker/24hr?symbol={coin}USDT"
                response = requests.get(url)
                if response.status_code != 200:
                    reply_texts.append(f"⚠️ Không thể lấy dữ liệu giá {coin}!")
                else:
                    data = response.json()
                    last_price = float(data["lastPrice"])
                    price_change_percent = float(data["priceChangePercent"])
                    reply_texts.append(f"💰 {coin}: {last_price:.4f} USDT ({price_change_percent:+.2f}%)")

        msg = bot.reply_to(message, "\n".join(reply_texts))
        time.sleep(30)  # Xóa sau 30 giây
        bot.delete_message(message.chat.id, msg.message_id)
        bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        logging.error(f"Lỗi trong get_price_change: {e}")

bot.message_handler(commands=['p'])(get_price_change)

# === Lệnh FOMO/FUD chỉ hoạt động từ 7h sáng đến 21h30 ===
def check_price_changes():
    tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(tz).time()
    start_time = datetime.strptime("07:00", "%H:%M").time()
    end_time = datetime.strptime("21:30", "%H:%M").time()

    # Chỉ gửi thông báo trong khung giờ từ 7:00 - 21:30
    if start_time <= now <= end_time:
        url = "https://api.mexc.com/api/v3/klines"
        alerts = []

        for coin in WATCHLIST:
            try:
                # Gửi yêu cầu lấy dữ liệu trong khung thời gian 10 phút (2 nến)
                params = {
                    "symbol": f"{coin}USDT",
                    "interval": "5m",
                    "limit": 2  # Lấy 2 nến gần nhất (10 phút)
                }
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                if len(data) < 2:
                    logging.warning(f"Dữ liệu không đủ cho {coin} trong khung 10 phút.")
                    continue

                # Lấy thông tin giá từ 2 nến gần nhất
                prev_candle = data[-2]
                current_candle = data[-1]
                open_price = float(prev_candle[1])  # Giá mở nến trước
                close_price = float(current_candle[4])  # Giá đóng nến hiện tại

                # Tính biến động giá theo phần trăm
                price_change_percent = ((close_price - open_price) / open_price) * 100

                # Gửi cảnh báo nếu biến động vượt 5%
                if abs(price_change_percent) > 5:
                    alert_type = "🚀 FOMO 🚀" if price_change_percent > 0 else "😱 FUD 😱"
                    bot.send_message(
                        CHAT_ID,
                        f"{alert_type} {coin} biến động {price_change_percent:+.2f}% trong 10 phút!"
                    )
            except requests.RequestException as e:
                logging.error(f"Lỗi khi truy vấn dữ liệu cho {coin}: {e}")
            except Exception as e:
                logging.error(f"Lỗi không mong muốn khi xử lý {coin}: {e}")

def start_price_monitor():
    while True:
        check_price_changes()  # Kiểm tra biến động giá
        time.sleep(600)  # Chu kỳ kiểm tra: mỗi 10 phút

# Chạy theo dõi giá trong luồng riêng
Thread(target=start_price_monitor, daemon=True).start()

# === Chạy bot ===
if __name__ == "__main__":
    keep_alive()
    bot.polling(none_stop=True, timeout=30, interval=1)