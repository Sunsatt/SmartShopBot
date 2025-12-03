import os
import json
import requests
from flask import Flask, request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

# Ключевые слова для фильтрации (цена)
PRICE_KEYWORDS = [
    "fasi", "ra girs", "fasi ra aqvs", "pasi", "pasi ra aqvs",
    "ფასი", "ფასი რა აქვს", "რა ღირს", "ფასი მომწერეთ",
    "pasi momweret", "fasi momweret"
]

# Переменные окружения
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
SHEET_RANGE = os.getenv("GOOGLE_SHEETS_RANGE")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Настройка Google Sheets API
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# Функция отправки сообщения обратно клиенту
def send_message(recipient_id, text):
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    print("Send API response:", response.json())

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Invalid token", 403

    if request.method == "POST":
        data = request.json
        try:
            messaging_event = data["entry"][0]["messaging"][0]
            sender_id = messaging_event["sender"]["id"]
            message_text = messaging_event["message"]["text"].lower()

            # Проверка ключевых слов
            if any(keyword in message_text for keyword in PRICE_KEYWORDS):
                result = sheet.values().get(
                    spreadsheetId=SHEET_ID,
                    range=SHEET_RANGE
                ).execute()
                values = result.get("values", [])

                post_id = message_text.strip()
                price = None
                for row in values:
                    if row[0].lower() == post_id:
                        price = row[1]
                        break

                if price:
                    response_text = f"ფასი ამ პროდუქტისათვის არის {price} ლარი."
                else:
                    response_text = "სამწუხაროდ, ვერ ვიპოვე ეს პროდუქტი ცხრილში."
            else:
                response_text = "გთხოვთ მიუთითოთ პროდუქტის ID ან სიტყვა 'ფასი'."

            send_message(sender_id, response_text)

        except Exception as e:
            print("Error:", e)

        return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
