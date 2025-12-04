import os
import json
import hmac
import hashlib
import requests
from flask import Flask, request, abort

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# ===== ENV =====
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
APP_SECRET = os.getenv("APP_SECRET")

SHEET_URL = os.getenv("SHEET_URL")
SHEET_CREDENTIALS_JSON = os.getenv("SHEET_CREDENTIALS_JSON")

# ===== Google Sheets setup =====
def get_sheet():
    creds_dict = json.loads(SHEET_CREDENTIALS_JSON)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    return client.open_by_url(SHEET_URL).sheet1

sheet = get_sheet()

# ===== Send API: Private Reply to comment =====
def send_private_reply(comment_id, text):
    url = f"https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text}
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, params=params, json=payload, headers=headers, timeout=10)
    try:
        print("Send API response:", resp.status_code, resp.json())
    except Exception:
        print("Send API response (non-JSON):", resp.status_code, resp.text)
    return resp.status_code == 200

# ===== Keywords (KA/GEO + translit) =====
PRICE_KEYWORDS = [
    "ფასი", "ფასი რა აქვს", "რა ღირს", "ფასი მომწერეთ",
    "fasi", "ra girs", "fasi ra aqvs", "pasi", "pasi ra aqvs", "pasi momweret", "fasi momweret",
]

def normalize_text(s):
    # простая нормализация для поиска ключевых слов
    return (s or "").strip().lower()

# ===== Verify X-Hub-Signature-256 =====
def verify_signature(req):
    signature = req.headers.get("X-Hub-Signature-256")
    if not signature or not signature.startswith("sha256="):
        return False
    mac = hmac.new(APP_SECRET.encode("utf-8"), req.data, hashlib.sha256).hexdigest()
    expected = "sha256=" + mac
    return hmac.compare_digest(signature, expected)

# ===== Webhook =====
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Verification token mismatch", 403

    # POST
    if not verify_signature(request):
        abort(403, description="Invalid signature")

    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "feed":
                    value = change.get("value", {})
                    post_id = value.get("post_id")
                    comment_id = value.get("comment_id")
                    comment_message = normalize_text(value.get("message"))

                    if not comment_id:
                        continue  # у нас интерес — только комментарии

                    # ключевые слова → формируем ответ
                    if any(k in comment_message for k in PRICE_KEYWORDS):
                        # читаем таблицу
                        records = sheet.get_all_records()  # [{'PostID': '...', 'ProductName': '...', 'Price': '...'}, ...]
                        price = None
                        product_name = None
                        for row in records:
                            if str(row.get("PostID")).strip() == str(post_id).strip():
                                product_name = row.get("ProductName")
                                price = row.get("Price")
                                break

                        if price and product_name:
                            response_text = f"პროდუქტი {product_name} ღირს {price} ლარი."
                        else:
                            response_text = "სამწუხაროდ, ვერ ვიპოვე ეს პროდუქტი ცხრილში."

                        # Private Reply
                        send_private_reply(comment_id, response_text)
        return "EVENT_RECEIVED", 200
    except Exception as e:
        print("Error:", e)
        return "ERROR", 200  # Meta будет ретраить; 200 предотвращает бесконечные повторы

if __name__ == "__main__":
    # для локального теста; в Render используй gunicorn app:app
    app.run(host="0.0.0.0", port=5000)
