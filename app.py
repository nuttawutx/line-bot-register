import os
import json
import base64
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from datetime import datetime
import pytz

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIAL_BASE64 = os.getenv("GOOGLE_CREDENTIAL_BASE64")

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

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

SYSTEM_ACTIVE = os.getenv("SYSTEM_ACTIVE", "true").lower() == "true"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not SYSTEM_ACTIVE:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ ขณะนี้ระบบลงทะเบียนปิดให้บริการชั่วคราว\nโปรดลองใหม่อีกครั้งภายหลัง")
        )
        return

    text = event.message.text.strip()
    user_id = event.source.user_id

    # ฟังก์ชัน: เปลี่ยนประเภทพนักงาน
    if text.lower().startswith("เปลี่ยนประเภท"):
        lines = text.strip().splitlines()
        if len(lines) != 5:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณากรอกข้อมูล 5 บรรทัดให้ครบถ้วน:\nเปลี่ยนประเภท\nชื่อ: ...\nรหัสเดิม: ...\nประเภทใหม่: รายวัน/รายเดือน\nมีผลวันที่: DD-MM-YYYY")
            )
            return

        try:
            name = lines[1].split(":", 1)[1].strip()
            old_code = lines[2].split(":", 1)[1].strip()
            new_type = lines[3].split(":", 1)[1].strip().lower()
            effective_date = lines[4].split(":", 1)[1].strip()

            if new_type not in ["รายวัน", "รายเดือน"]:
                raise ValueError("ประเภทใหม่ต้องเป็น รายวัน หรือ รายเดือน เท่านั้น")
            if not re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', effective_date):
                raise ValueError("รูปแบบวันที่ไม่ถูกต้อง ต้องเป็น DD-MM-YYYY")

            # ดึง Sheet เป้าหมาย
            if new_type == "รายวัน":
                worksheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
                default_code = 90000
            else:
                worksheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
                default_code = 20000

            existing = worksheet.get_all_values()
            last_row = existing[-1] if len(existing) > 1 else []
            last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
            new_code = str(last_code + 1)

            # บันทึกเข้า Worksheet ใหม่
            tz = pytz.timezone('Asia/Bangkok')
            timestamp = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
            worksheet.append_row([name, "-", "-", "-", effective_date, new_type, user_id, new_code, timestamp])

            # บันทึกประวัติการโอนย้าย
            transfer_sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")
            transfer_sheet.append_row([name, old_code, new_code, new_type, effective_date, timestamp])

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f"✅ เปลี่ยนประเภทสำเร็จ\nชื่อ: {name}\nรหัสใหม่: {new_code}\nประเภท: {new_type}\nมีผลวันที่: {effective_date}"
                )
            )

        except Exception as e:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ เกิดข้อผิดพลาด: {str(e)}")
            )
        return

    # ส่วนอื่น ๆ ของโค้ด handle_message (เช่น ลงทะเบียนใหม่) ใส่ต่อได้ตามเดิม...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
