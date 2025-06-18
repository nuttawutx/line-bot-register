import os
import json
import base64
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import gspread
from oauth2client.service_account import ServiceAccountCredentials


app = Flask(__name__)
from dotenv import load_dotenv
load_dotenv()

# ENV Vars
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIAL_BASE64 = os.getenv("GOOGLE_CREDENTIAL_BASE64")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Decode Google credential JSON
cred_path = "google-credentials.json"
if GOOGLE_CREDENTIAL_BASE64:
    with open(cred_path, "w") as f:
        f.write(base64.b64decode(GOOGLE_CREDENTIAL_BASE64).decode("utf-8"))

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scope)
client = gspread.authorize(creds)
sheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    user_id = event.source.user_id

    # Simple parser by line (ชื่อ, แผนก, สาขา, เริ่มงาน, ประเภท)
    lines = text.strip().split("\n")
    data = {}
    for line in lines:
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

    try:
        name = data.get("ชื่อ", "")
        dept = data.get("แผนก", "")
        branch = data.get("สาขา", "")
        start = data.get("เริ่มงาน", "")
        emp_type = data.get("ประเภท", "")

        # Append to Google Sheet
        sheet.append_row([name, dept, branch, start, emp_type, user_id])

        reply = f"ลงทะเบียนสำเร็จ 🎉\nรหัสของคุณจะได้รับภายหลังทางระบบ"
    except Exception as e:
        reply = f"เกิดข้อผิดพลาด: {str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
