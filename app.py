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

SYSTEM_ACTIVE = os.getenv("SYSTEM_ACTIVE", "true").lower() == "true"
user_states = {}  # ติดตามสถานะของผู้ใช้

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
    if not SYSTEM_ACTIVE:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ ระบบปิดให้บริการชั่วคราว")
        )
        return

    text = event.message.text.strip()
    user_id = event.source.user_id

    # เลือกโหมดการทำงาน
    if text == "1":
        user_states[user_id] = "register"
        line_bot_api.reply_message(
    event.reply_token,
    TextSendMessage(text="📄 กรุณาพิมพ์ข้อมูลพนักงานใหม่ 6 บรรทัด:\nชื่อ:\nแผนก:\nสาขา:\nตำแหน่ง:\nเริ่มงาน (DD-MM-YYYY):\nประเภท:")
)
        
        return
    elif text == "2":
        user_states[user_id] = "change"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔄 กรุณาพิมพ์ข้อมูลการเปลี่ยนประเภท 3 บรรทัด:\nรหัสพนักงานเดิม:\nประเภทใหม่:\nวันที่มีผล (DD-MM-YYYY):")
        )
        return

    state = user_states.get(user_id)

    if state == "register":
        lines = text.splitlines()
        if len(lines) != 6:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ต้องกรอก 6 บรรทัดตามแบบที่กำหนด")
            )
            return

        data = {}
        for line in lines:
            if ":" not in line:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="❌ ทุกบรรทัดต้องมี ':'")
                )
                return
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

        required_keys = {"ชื่อ", "แผนก", "สาขา", "ตำแหน่ง", "เริ่มงาน", "ประเภท"}
        if set(data.keys()) != required_keys:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ข้อมูลไม่ครบถ้วนหรือผิดรูปแบบ")
            )
            return

        if not re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', data["เริ่มงาน"]):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ รูปแบบวันเริ่มงานไม่ถูกต้อง")
            )
            return

        emp_type = data["ประเภท"].lower()
        if emp_type == "รายวัน":
            sheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif emp_type == "รายเดือน":
            sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ประเภทต้องเป็น รายวัน หรือ รายเดือน")
            )
            return

        existing = sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        emp_code = str(last_code + 1)

        tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

        sheet.append_row([
            data["ชื่อ"], data["แผนก"], data["สาขา"], data["ตำแหน่ง"],
            data["เริ่มงาน"], data["ประเภท"], user_id, emp_code, now
        ])

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ ลงทะเบียนสำเร็จ\nรหัสพนักงาน: {emp_code}")
        )
        user_states.pop(user_id, None)

    elif state == "change":
        lines = text.splitlines()
        if len(lines) != 3:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ต้องกรอก 3 บรรทัดตามแบบที่กำหนด")
            )
            return

        emp_code_old, emp_type_new, effect_date = [line.split(":", 1)[1].strip() if ":" in line else "" for line in lines]

        if emp_type_new not in ["รายวัน", "รายเดือน"]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ประเภทใหม่ไม่ถูกต้อง")
            )
            return

        sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")
        tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

        sheet.append_row([emp_code_old, emp_type_new, effect_date, user_id, now])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔄 บันทึกการเปลี่ยนประเภทเรียบร้อย")
        )
        user_states.pop(user_id, None)

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="กรุณาพิมพ์ 1 เพื่อเริ่มลงทะเบียน หรือ 2 เพื่อเปลี่ยนประเภทพนักงาน")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
