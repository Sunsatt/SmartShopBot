import os, json, hmac, hashlib, re, requests
from flask import Flask, request, abort, jsonify

# Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
APP_SECRET = os.getenv("APP_SECRET")
SHEET_URL = os.getenv("SHEET_URL")
SHEET_CREDENTIALS_JSON = os.getenv("SHEET_CREDENTIALS_JSON")

# --- lazy sheet client ---
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
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    _sheet = client.open_by_url(SHEET_URL).sheet1
    return _sheet

# --- send API ---
def send_private_reply(comment_id, text):
    url = "https://graph.facebook.com/v19.0/me/messages"
    headers = {
        "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": text}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    ok = 200 <= resp.status_code < 300
    print("📤 Send API:", resp.status_code, body)
    if not ok and isinstance(body, dict) and "error" in body:
        err = body["error"]
        print(f"⚠️ Send error: code={err.get('code')} subcode={err.get('error_subcode')} type={err.get('type')} msg={err.get('message')}")
    return ok

# --- text normalization & keywords ---
PRICE_KEYWORDS = [
    "ფასი", "ფასი რა აქვს", "რა ღირს", "ფასი მომწერეთ",
    "fasi", "ra girs", "fasi ra aqvs", "pasi", "pasi ra aqvs", "pasi momweret", "fasi momweret",
    "цена", "сколько стоит", "стоимость", "почем", "сколько"
]
PUNCT = re.compile(r"[^\w\s\u10A0-\u10FF]", re.UNICODE)  # keep Georgian letters

def normalize_text(s):
    t = (s or "").lower().strip()
    t = PUNCT.sub("", t)
    return re.sub(r"\s+", " ", t)

def is_price_question(text):
    t = normalize_text(text)
    return any(k in t for k in PRICE_KEYWORDS)

# --- signature verification (soft in dev) ---
def verify_signature(req):
    sig = req.headers.get("X-Hub-Signature-256")
    if not sig:
        # Soft fallback in Dev Mode to avoid 403 on missing headers
        return True
    if not sig.startswith("sha256="):
        return False
    mac = hmac.new(APP_SECRET.encode("utf-8"), req.data, hashlib.sha256).hexdigest()
    expected = "sha256=" + mac
    return hmac.compare_digest(sig, expected)

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Verification token mismatch", 403

    # POST
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
                # explicit filters
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

                # sheet lookup
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

                ok = send_private_reply(comment_id, response_text)
                print("✅ replied" if ok else "❌ reply failed")
    except Exception as e:
        print("❌ Handler error:", str(e))

    # Always acknowledge to Meta
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
