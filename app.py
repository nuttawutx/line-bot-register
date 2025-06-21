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
user_states = {}

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
            TextSendMessage(text="⚠️ ขณะนี้ระบบลงทะเบียนปิดให้บริการชั่วคราว\nโปรดลองใหม่อีกครั้งภายหลัง")
        )
        return

    text = event.message.text.strip()
    user_id = event.source.user_id

    if user_id not in user_states:
        if text == "1":
            user_states[user_id] = "register"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณากรอกข้อมูล 6 บรรทัดตามนี้:\nชื่อ:\nแผนก:\nสาขา:\nตำแหน่ง:\nเริ่มงาน (DD-MM-YYYY):\nประเภท: รายวัน หรือ รายเดือน")
            )
            return
        elif text == "2":
            user_states[user_id] = "change_type"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณากรอกข้อมูล 4 บรรทัดตามนี้:\nรหัสพนักงานเดิม:\nชื่อ:\nประเภทเดิม:\nประเภทใหม่:")
            )
            return
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณาพิมพ์ 1 เพื่อลงทะเบียนใหม่ หรือ 2 เพื่อเปลี่ยนประเภท")
            )
            return

    state = user_states[user_id]

    if state == "register":
        lines = text.splitlines()
        if len(lines) != 6:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ต้องกรอกข้อมูล 6 บรรทัดให้ครบถ้วน")
            )
            return

        keys = ["ชื่อ", "แผนก", "สาขา", "ตำแหน่ง", "เริ่มงาน", "ประเภท"]
        data = {}
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

        if set(data.keys()) != set(keys):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ข้อมูลไม่ครบหรือพิมพ์ผิด โปรดตรวจสอบอีกครั้ง")
            )
            return

        emp_type = data["ประเภท"].strip().lower()
        if emp_type == "รายวัน":
            sheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif emp_type == "รายเดือน":
            sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ประเภทต้องเป็น 'รายวัน' หรือ 'รายเดือน'"))
            return

        existing = sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        new_code = str(last_code + 1)

        tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

        sheet.append_row([
            data["ชื่อ"], data["แผนก"], data["สาขา"], data["ตำแหน่ง"],
            data["เริ่มงาน"], emp_type, user_id, new_code, now
        ])

        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"✅ ลงทะเบียนสำเร็จ\nรหัสพนักงาน: {new_code}\nชื่อ: {data['ชื่อ']}\nประเภท: {emp_type}\n⏰ {now}"
        ))
        user_states.pop(user_id)

    elif state == "change_type":
        lines = text.splitlines()
        if len(lines) != 4:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ต้องกรอกข้อมูล 4 บรรทัดให้ครบถ้วน")
            )
            return

        keys = ["รหัสพนักงานเดิม", "ชื่อ", "ประเภทเดิม", "ประเภทใหม่"]
        data = {}
        for line in lines:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            data[key.strip()] = val.strip()

        if set(data.keys()) != set(keys):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="❌ ข้อมูลไม่ครบหรือพิมพ์ผิด โปรดตรวจสอบอีกครั้ง"))
            return

        old_type = data["ประเภทเดิม"].strip().lower()
        new_type = data["ประเภทใหม่"].strip().lower()

        if old_type == new_type:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="❌ ประเภทใหม่ต้องไม่ซ้ำกับประเภทเดิม"))
            return

        if new_type == "รายวัน":
            target_sheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif new_type == "รายเดือน":
            target_sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="❌ ประเภทต้องเป็น 'รายวัน' หรือ 'รายเดือน'"))
            return

        existing = target_sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        new_emp_code = str(last_code + 1)

        tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

        # เพิ่มข้อมูลใหม่ไปยัง sheet ประเภทใหม่
        target_sheet.append_row([
            data["ชื่อ"], "-", "-", "-", now, new_type, user_id, new_emp_code, now
        ])

        # บันทึกประวัติลง TransferHistory
        transfer_sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")
        transfer_sheet.append_row([
            data["ชื่อ"], data["รหัสพนักงานเดิม"], old_type, new_type, new_emp_code, now
        ])

        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"✅ ปรับประเภทสำเร็จ\nรหัสใหม่: {new_emp_code}\nประเภทใหม่: {new_type}\n⏰ {now}"
        ))
        user_states.pop(user_id)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
