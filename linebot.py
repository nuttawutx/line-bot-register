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
from datetime import datetime
import pytz
from dotenv import load_dotenv

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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u26a0\ufe0f ระบบปิดให้บริการชั่วคราว"))
        return

    text = event.message.text.strip()
    user_id = event.source.user_id
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

    if text.startswith("เปลี่ยนประเภท:"):
        lines = text.splitlines()
        if len(lines) < 6:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c ข้อมูลไม่ครบถ้วน"))
            return
        old_code = lines[1].split(":",1)[1].strip()
        name = lines[2].split(":",1)[1].strip()
        old_type = lines[3].split(":",1)[1].strip().lower()
        new_type = lines[4].split(":",1)[1].strip().lower()
        start = lines[5].split(":",1)[1].strip()

        if new_type not in ["รายวัน", "รายเดือน"]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c ประเภทใหม่ไม่ถูกต้อง"))
            return

        try:
            source_sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee" if old_type == "รายเดือน" else "DailyEmployee")
            target_sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee" if new_type == "รายเดือน" else "DailyEmployee")
            history_sheet = client.open("HR_EmployeeList").worksheet("TransferHistory")

            all_rows = source_sheet.get_all_values()
            found = False
            for i, row in enumerate(all_rows):
                if len(row) >= 8 and row[7] == old_code:
                    found = True
                    position = row[2]
                    branch = row[1]
                    old_data = row

                    target_rows = target_sheet.get_all_values()
                    last_row = target_rows[-1] if len(target_rows) > 1 else []
                    last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else (20000 if new_type == "รายเดือน" else 90000)
                    new_code = str(last_code + 1)

                    target_sheet.append_row([name, branch, position, start, new_type, user_id, new_code, now])
                    history_sheet.append_row([now, old_code, new_code, name, branch, position, position, old_type, new_type, start, user_id, "เปลี่ยนประเภท"])

                    source_sheet.delete_rows(i + 1)
                    reply = f"\u2705 เปลี่ยนประเภทสำเร็จ\nรหัสใหม่: {new_code}\nประเภทใหม่: {new_type}"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    break
            if not found:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c ไม่พบรหัสพนักงานเดิม"))
        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"เกิดข้อผิดพลาด: {str(e)}"))

    elif text.count(":") == 6:
        lines = text.splitlines()
        data = {}
        for line in lines:
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip()] = val.strip()

        name = data.get("ชื่อ", "")
        dept = data.get("แผนก", "")
        branch = data.get("สาขา", "")
        position = data.get("ตำแหน่ง", "")
        start = data.get("เริ่มงาน", "")
        emp_type = data.get("ประเภท", "").strip().lower()

        if not re.match(r'^\d{2}-\d{2}-\d{4}$', start):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c รูปแบบวันเริ่มงานไม่ถูกต้อง (DD-MM-YYYY)"))
            return

        if emp_type not in ["รายวัน", "รายเดือน"]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c ประเภทต้องเป็น 'รายวัน' หรือ 'รายเดือน'"))
            return

        try:
            sheet = client.open("HR_EmployeeList").worksheet("MonthlyEmployee" if emp_type == "รายเดือน" else "DailyEmployee")
            all_data = sheet.get_all_values()
            last_row = all_data[-1] if len(all_data) > 1 else []
            last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else (20000 if emp_type == "รายเดือน" else 90000)
            new_code = str(last_code + 1)

            sheet.append_row([name, branch, position, start, emp_type, user_id, new_code, now])
            reply = (
                f"\u2705 ลงทะเบียนสำเร็จ\n"
                f"รหัสพนักงาน: {new_code}\n"
                f"ชื่อ: {name}\n"
                f"ตำแหน่ง: {position}\n"
                f"สาขา: {branch}\n"
                f"วันเริ่มงาน: {start}"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"เกิดข้อผิดพลาด: {str(e)}"))

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\u274c รูปแบบข้อความไม่ถูกต้อง"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
