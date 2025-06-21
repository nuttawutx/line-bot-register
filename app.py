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

user_state = {}

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

    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id not in user_state:
        if text == "1":
            user_state[user_id] = "registering"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณากรอกข้อมูล:\nชื่อ:\nแผนก:\nสาขา:\nตำแหน่ง:\nเริ่มงาน: (DD-MM-YYYY)\nประเภท:")
            )
        elif text == "2":
            user_state[user_id] = "transferring"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณากรอกข้อมูลเปลี่ยนประเภท:\nชื่อ:\nตำแหน่ง:\nประเภทใหม่:\nวันมีผล:(DD-MM-YYYY)")
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="กรุณาพิมพ์ 1 หรือ 2 เท่านั้น:\n1 → ลงทะเบียนรหัสใหม่\n2 → เปลี่ยนประเภทและรหัสพนักงาน")
            )
        return

    state = user_state[user_id]
    lines = text.splitlines()
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

    if state == "registering" and len(lines) == 6:
        data = {}
        for line in lines:
            if ':' not in line: continue
            key, val = line.split(':', 1)
            data[key.strip()] = val.strip()

        if not re.match(r'\d{1,2}-\d{1,2}-\d{4}', data.get("เริ่มงาน", "")):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ รูปแบบวันเริ่มงานไม่ถูกต้อง"))
            return

        emp_type = data.get("ประเภท", "").strip().lower()
        if emp_type == "รายวัน":
            worksheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
            default_code = 90000
        elif emp_type == "รายเดือน":
            worksheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
            default_code = 20000
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ประเภทไม่ถูกต้อง"))
            return

        existing = worksheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else default_code
        new_code = str(last_code + 1)

        worksheet.append_row([
            data.get("ชื่อ", ""), data.get("แผนก", ""), data.get("สาขา", ""),
            data.get("ตำแหน่ง", ""), data.get("เริ่มงาน", ""), emp_type,
            user_id, new_code, now
        ])

        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"✅ ลงทะเบียนสำเร็จ\nรหัสพนักงาน: {new_code}\nชื่อ: {data['ชื่อ']}\nตำแหน่ง: {data['ตำแหน่ง']}\nประเภท: {emp_type}"
        ))
        user_state.pop(user_id, None)

    elif state == "transferring" and len(lines) == 4:
        data = {}
        for line in lines:
            if ':' not in line: continue
            key, val = line.split(':', 1)
            data[key.strip()] = val.strip()

        emp_name = data.get("ชื่อ", "")
        new_type = data.get("ประเภทใหม่", "").strip().lower()
        if not re.match(r'\d{1,2}-\d{1,2}-\d{4}', data.get("วันมีผล", "")):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ วันมีผลไม่ถูกต้อง"))
            return

        old_sheet = client.open("HR_EmployeeList").worksheet("DailyEmployee")
        new_sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee")
        if new_type == "รายวัน":
            old_sheet, new_sheet = new_sheet, old_sheet
            default_code = 90000
        else:
            default_code = 20000

        rows = old_sheet.get_all_values()
        header, data_rows = rows[0], rows[1:]
        updated = False
        for idx, row in enumerate(data_rows, start=2):
            if row[0] == emp_name:
                last_row = new_sheet.get_all_values()
                last_code = int(last_row[-1][7]) if len(last_row) > 1 and last_row[-1][7].isdigit() else default_code
                new_code = str(last_code + 1)
                new_data = row[:6] + [user_id, new_code, now]
                new_data[5] = new_type
                new_sheet.append_row(new_data)
                old_sheet.delete_rows(idx)
                trans_sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")
                trans_sheet.append_row([emp_name, row[5], new_type, data.get("วันมีผล"), now])
                line_bot_api.reply_message(event.reply_token, TextSendMessage(
                    text=f"✅ เปลี่ยนประเภทสำเร็จ\nรหัสใหม่: {new_code}\nชื่อ: {emp_name}\nประเภท: {new_type}"
                ))
                updated = True
                break

        if not updated:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ไม่พบข้อมูลพนักงาน"))

        user_state.pop(user_id, None)

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ รูปแบบข้อมูลไม่ถูกต้อง"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
