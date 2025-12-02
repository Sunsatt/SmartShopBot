from flask import Flask, request
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# Токены
VERIFY_TOKEN = "smartshop123"   # тот же, что укажешь в настройках Webhook
PAGE_ACCESS_TOKEN = "YOUR_PAGE_ACCESS_TOKEN"  # заменишь на свой токен из Meta

# Подключение к Google Sheets
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("SmartShopProducts").sheet1

# Ключевые слова для фильтрации (цена)
PRICE_KEYWORDS = [
    "fasi", "ra girs", "fasi ra aqvs", "pasi", "pasi ra aqvs",
    "ფასი", "ფასი რა აქვს", "რა ღირს", "ფასი მომწერეთ",
    "pasi momweret", "fasi momweret"
]

def get_product_by_post(post_id):
    """Ищем товар по Post ID в таблице"""
    records = sheet.get_all_records()
    for row in records:
        if str(row["Post ID"]) == str(post_id):
            return row
    return None

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Подтверждение Webhook
        token_sent = request.args.get("hub.verify_token")
        return request.args.get("hub.challenge") if token_sent == VERIFY_TOKEN else "Invalid token"
    
    if request.method == "POST":
        data = request.get_json()
        for entry in data.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                if messaging_event.get("message"):
                    sender_id = messaging_event["sender"]["id"]
                    message_text = messaging_event["message"].get("text", "").lower()
                    
                    # Проверка на ключевые слова
                    if any(keyword.lower() in message_text for keyword in PRICE_KEYWORDS):
                        post_id = messaging_event.get("post_id")  # ID поста
                        product = get_product_by_post(post_id) if post_id else None
                        
                        if product:
                            send_message(sender_id, f"{product['Product Name']} стоит {product['Price']}. გსურთ შეკვეთა?")
                        else:
                            send_message(sender_id, "ფასი уточняется, ჩვენი მენეჯერი მალე მოგწერთ.")
                    else:
                        send_message(sender_id, "მადლობა შეტყობინებისთვის! ჩვენი მენეჯერი მალე მოგწერთ.")
        return "OK", 200

def send_message(recipient_id, message_text):
    """Отправка ответа клиенту"""
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    headers = {"Content-Type": "application/json"}
    requests.post(url, json=payload, headers=headers)

if __name__ == "__main__":
    app.run(port=5000)
