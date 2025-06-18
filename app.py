import os
import json
import base64
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIAL_BASE64 = os.getenv("GOOGLE_CREDENTIAL_BASE64")

print("DEBUG: TOKEN =", LINE_CHANNEL_ACCESS_TOKEN)
print("DEBUG: SECRET =", LINE_CHANNEL_SECRET)
print("DEBUG: BASE64 =", GOOGLE_CREDENTIAL_BASE64 is not None)

app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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

        # รันรหัสพนักงานอัตโนมัติ
        existing = sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[6]) if len(last_row) >= 7 and last_row[6].isdigit() else 20000
        new_code = last_code + 1
        emp_code = str(new_code)

        # บันทึกลง Google Sheet
        sheet.append_row([name, dept, branch, start, emp_type, user_id, emp_code])

        # Flex Message
        flex = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    { "type": "text", "text": "ลงทะเบียนสำเร็จ 🎉", "weight": "bold", "size": "lg", "color": "#1DB446" },
                    { "type": "separator", "margin": "md" },
                    { "type": "text", "text": f"ชื่อ: {name}", "size": "md" },
                    { "type": "text", "text": f"รหัสพนักงาน: {emp_code}", "size": "md" },
                    { "type": "text", "text": f"แผนก: {dept}", "size": "sm", "color": "#888888" },
                    { "type": "text", "text": f"สาขา: {branch}", "size": "sm", "color": "#888888" },
                    { "type": "text", "text": f"เริ่มงาน: {start}", "size": "sm", "color": "#888888" },
                ]
            }
        }

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ลงทะเบียนสำเร็จ!")
        )
        line_bot_api.push_message(user_id, TextSendMessage(text="⬇️ ดูรายละเอียดด้านล่าง"))
        line_bot_api.push_message(user_id, FlexSendMessage(alt_text="ลงทะเบียนสำเร็จ", contents=flex))

    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"เกิดข้อผิดพลาด: {str(e)}")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
