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
SYSTEM_ACTIVE = os.getenv("SYSTEM_ACTIVE", "true").lower() == "true"

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

user_state = {}  # เก็บสถานะของผู้ใช้

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
    text = event.message.text.strip()
    user_id = event.source.user_id

    if not SYSTEM_ACTIVE:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ขณะนี้ระบบปิดให้บริการชั่วคราว"))
        return

    # คำสั่งยกเลิกการทำรายการ
    if text.lower() == "ยกเลิก":
        if user_id in user_state:
            del user_state[user_id]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❗️คุณได้ยกเลิกการทำรายการ\nกรุณาพิมพ์หมายเลขเมนูใหม่:\n\n1 → ลงทะเบียนพนักงานใหม่\n2 → เปลี่ยนประเภทและรหัสพนักงาน")
        )
        return

    # ถ้ายังไม่มีสถานะ ให้เลือกเมนูก่อน
    if user_id not in user_state:
        if text == "1":
            user_state[user_id] = "register"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="📋 กรุณากรอกข้อมูล 6 บรรทัด:\nชื่อ:\nแผนก:\nสาขา:\nตำแหน่ง:\nเริ่มงาน (DD-MM-YYYY):\nประเภท: รายวัน หรือ รายเดือน")
            )
            return
        elif text == "2":
            user_state[user_id] = "transfer"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🔁 กรุณากรอกข้อมูล 5 บรรทัด:\nชื่อ:\nรหัสพนักงานเดิม:\nตำแหน่งใหม่:\nประเภทใหม่: รายวัน หรือ รายเดือน\nวันที่มีผล (DD-MM-YYYY)")
            )
            return
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณาเลือกเมนูโดยพิมพ์หมายเลข:\n1 → ลงทะเบียนพนักงานใหม่\n2 → เปลี่ยนประเภทและรหัสพนักงาน")
            )
            return

    mode = user_state.get(user_id)

    if mode == "register":
        lines = text.splitlines()
        if len(lines) != 6:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ต้องกรอกข้อมูล 6 บรรทัดตามรูปแบบ"))
            return

        keys = ["ชื่อ", "แผนก", "สาขา", "ตำแหน่ง", "เริ่มงาน", "ประเภท"]
        data = {}
        for line in lines:
            if ':' not in line:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ทุกบรรทัดต้องมี ':'"))
                return
            key, val = line.split(':', 1)
            data[key.strip()] = val.strip()

        if not all(k in data for k in keys):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ขาดข้อมูล"))
            return

        emp_type = data["ประเภท"].lower()
        if emp_type == "รายวัน":
            worksheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif emp_type == "รายเดือน":
            worksheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ประเภทต้องเป็น รายวัน หรือ รายเดือน"))
            return

        existing = worksheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        emp_code = str(last_code + 1)

        now = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M")
        worksheet.append_row([
            data["ชื่อ"], data["แผนก"], data["สาขา"], data["ตำแหน่ง"],
            data["เริ่มงาน"], data["ประเภท"], user_id, emp_code, now
        ])

        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"✅ ลงทะเบียนสำเร็จ\nรหัสพนักงาน: {emp_code}\n📌 แจ้งหัวหน้างานก่อนเริ่มงาน"))
        del user_state[user_id]

    elif mode == "transfer":
        lines = text.splitlines()
        if len(lines) != 5:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ต้องกรอกข้อมูล 5 บรรทัดตามรูปแบบ"))
            return

        keys = ["ชื่อ", "รหัสพนักงานเดิม", "ตำแหน่งใหม่", "ประเภทใหม่", "วันที่มีผล"]
        data = {}
        for line in lines:
            if ':' not in line:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ทุกบรรทัดต้องมี ':'"))
                return
            key, val = line.split(':', 1)
            data[key.strip()] = val.strip()

        if not all(k in data for k in keys):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ขาดข้อมูล"))
            return

        new_type = data["ประเภทใหม่"].lower()
        if new_type == "รายวัน":
            worksheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif new_type == "รายเดือน":
            worksheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ประเภทใหม่ไม่ถูกต้อง"))
            return

        existing = worksheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        new_code = str(last_code + 1)

        now = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M")

        worksheet.append_row([
            data["ชื่อ"], "-", "-", data["ตำแหน่งใหม่"],
            data["วันที่มีผล"], data["ประเภทใหม่"], user_id, new_code, now
        ])

        history_sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")
        history_sheet.append_row([
            data["ชื่อ"], data["รหัสพนักงานเดิม"], new_code,
            data["ประเภทใหม่"], data["วันที่มีผล"], now
        ])

        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"🔄 ปรับประเภทสำเร็จ\nรหัสใหม่: {new_code}\n📌 บันทึกในประวัติการโอนย้าย"))
        del user_state[user_id]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
