import os
import json
import base64
import re
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

    # ตรวจว่ามี 5 บรรทัดตรงเป๊ะ
    lines = text.strip().split("\\n")
    if len(lines) != 5:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณากรอกข้อมูล 6 บรรทัดให้ครบตามรูปแบบเท่านั้น")
        )
        return
    # ตรวจสอบ pattern ของแต่ละบรรทัด
    patterns = [
        r"^ชื่อ: .+",
        r"^แผนก: .+",
        r"^สาขา: .+",
        r"^ตำแหน่งงาน: .+",
        r"^เริ่มงาน: (\\d{2}-\\d{2}-\\d{4})$",
        r"^ประเภท: .+"
    ]

    data = {}
    for i, line in enumerate(lines):
        match = re.match(patterns[i], line)
        if not match:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ รูปแบบบรรทัดที่ {i+1} ไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง")
            )
            return
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

    try:
        name = data.get("ชื่อ", "")
        dept = data.get("แผนก", "")
        branch = data.get("สาขา", "")
        postion = data.get("ตำแหน่งาน", "")
        start = data.get("เริ่มงาน", "")
        emp_type = data.get("ประเภท", "")

        # รันรหัสพนักงานอัตโนมัติ
        existing = sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[6]) if len(last_row) >= 7 and last_row[6].isdigit() else 20000
        new_code = last_code + 1
        emp_code = str(new_code)

        # บันทึกลง Google Sheet
        sheet.append_row([name, dept, branch,postion, start, emp_type, user_id, emp_code])
        # ตอบกลับ
        confirmation_text = (
            f"✅ ลงทะเบียนสำเร็จ\n"
            f"รหัสพนักงาน: {emp_code}\n"
            f"ชื่อ: {name}\n"
            f"ตำแหน่งงาน: {postion}\n"
            f"สาขา: {branch}\n"
            f"วันเริ่มงาน: {start}\n"
            f"📌 โปรดแจ้งหัวหน้างานล่วงหน้าก่อนเริ่มงาน"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=confirmation_text)
        )
        
    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"เกิดข้อผิดพลาด: {str(e)}")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
