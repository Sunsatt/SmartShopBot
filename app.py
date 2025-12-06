import os, json, hmac, hashlib, re, requests
from flask import Flask, request, abort, jsonify

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# --- Environment Variables ---
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
APP_SECRET = os.getenv("APP_SECRET")
SHEET_URL = os.getenv("SHEET_URL")
SHEET_CREDENTIALS_JSON = os.getenv("SHEET_CREDENTIALS_JSON")

# --- Lazy sheet client ---
_sheet = None
def get_sheet():
    global _sheet
    if _sheet is not None:
        return _sheet
    creds_dict = json.loads(SHEET_CREDENTIALS_JSON)
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(credentials)
    _sheet = client.open_by_url(SHEET_URL).sheet1
    return _sheet

# --- Private Reply API ---
def send_private_reply(comment_id, text):
    url = f"https://graph.facebook.com/v24.0/{comment_id}/private_replies"
    headers = {
        "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": text
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    print("📤 Private Reply API:", resp.status_code, body)
    return 200 <= resp.status_code < 300

# --- Keywords ---
PRICE_KEYWORDS = [
    "ფასი", "ფასი რა აქვს", "რა ღირს", "ფასი მომწერეთ",
    "fasi", "ra girs", "fasi ra aqvs", "pasi", "pasi ra aqvs", "pasi momweret", "fasi momweret",
    "цена", "сколько стоит", "стоимость", "почем", "сколько"
]
PUNCT = re.compile(r"[^\w\s\u10A0-\u10FF]", re.UNICODE)

def normalize_text(s):
    t = (s or "").lower().strip()
    t = PUNCT.sub("", t)
    return re.sub(r"\s+", " ", t)

def is_price_question(text):
    t = normalize_text(text)
    return any(k in t for k in PRICE_KEYWORDS)

# --- Signature verification ---
def verify_signature(req):
    sig = req.headers.get("X-Hub-Signature-256")
    if not sig:
        return True
    if not sig.startswith("sha256="):
        return False
    mac = hmac.new(APP_SECRET.encode("utf-8"), req.data, hashlib.sha256).hexdigest()
    expected = "sha256=" + mac
    return hmac.compare_digest(sig, expected)

# --- Health check ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "alive"}), 200

# --- Webhook ---
@app.route("/webhook", methods=["GET", "POST"])
@app.route("/webhook/", methods=["GET", "POST"])  # на всякий случай
def webhook():
    print(f"➡️ {request.method} {request.path}")

    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Verification token mismatch", 403

    if not verify_signature(request):
        abort(403, description="Invalid signature")

    data = request.get_json(silent=True) or {}
    print("📩 Webhook POST:", json.dumps(data, indent=2, ensure_ascii=False))

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "feed":
                    continue
                v = change.get("value", {}) or {}
                if v.get("item") != "comment" or v.get("verb") != "add":
                    continue

                post_id = v.get("post_id")
                comment_id = v.get("comment_id")
                message = v.get("message", "")

                print(f"🧾 post_id={post_id} | 💬 comment_id={comment_id} | 🔍 text={message}")

                if not comment_id or not message:
                    continue
                if not is_price_question(message):
                    continue

                response_text = "სამწუხაროდ, ვერ ვიპოვე ეს პროდუქტი ცხრილში."
                try:
                    sheet = get_sheet()
                    records = sheet.get_all_records()
                    for row in records:
                        if str(row.get("PostID", "")).strip() == str(post_id).strip():
                            product_name = row.get("ProductName")
                            price = row.get("Price")
                            if product_name and price:
                                response_text = f"პროდუქტი {product_name} ღირს {price} ლარი."
                            break
                except Exception as e:
                    print("⚠️ Sheets error:", str(e))

                send_private_reply(comment_id, response_text)
    except Exception as e:
        print("❌ Handler error:", str(e))

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render задаёт PORT
    app.run(host="0.0.0.0", port=port)
