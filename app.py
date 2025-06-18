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


    # เพิ่มตัวแปร FLAG สำหรับเปิด/ปิดระบบ และจัดการข้อความตอบกลับหากระบบถูกปิดชั่วคราว
closed_mode_code = ""\
    # เพิ่ม ENV สำหรับเปิด/ปิดระบบ
SYSTEM_ACTIVE = os.getenv("SYSTEM_ACTIVE", "false").lower() == "false"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not SYSTEM_ACTIVE:
        # ตอบกลับทันทีถ้าระบบถูกปิด
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ ขณะนี้ระบบลงทะเบียนปิดให้บริการชั่วคราว\nโปรดลองใหม่อีกครั้งภายหลัง")
        )
        return

    text = event.message.text
    user_id = event.source.user_id

    # ตรวจว่ามี 6 บรรทัดตรงเป๊ะ
    lines = text.strip().splitlines()
    if len(lines) != 6:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ ต้องกรอกข้อมูล 6 บรรทัดเท่านั้น:\nชื่อ:\nแผนก:\nสาขา:\nตำแหน่ง:\nเริ่มงาน (DD-MM-YYYY):\nประเภท:")
        )
        return
    expected_keys = {"ชื่อ", "แผนก", "สาขา", "ตำแหน่ง", "เริ่มงาน", "ประเภท"}

    data = {}
    for line in lines:
        if ":" not in line:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ ทุกบรรทัดต้องมีเครื่องหมาย ':' เช่น ตำแหน่ง: เจ้าหน้าที่")
            )
            return
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        data[key] = val

    if set(data.keys()) != expected_keys:
        missing = expected_keys - set(data.keys())
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"❌ ขาดข้อมูล: {', '.join(missing)}")
        )
        return

    if not re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', data["เริ่มงาน"]):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ รูปแบบวันเริ่มงานไม่ถูกต้อง (ต้องเป็น DD-MM-YYYY)")
        )
        return


    try:
        name = data.get("ชื่อ", "")
        dept = data.get("แผนก", "")
        branch = data.get("สาขา", "")
        postion = data.get("ตำแหน่ง", "")
        start = data.get("เริ่มงาน", "")
        emp_type = data.get("ประเภท", "")

        # รันรหัสพนักงานอัตโนมัติ
        existing = sheet.get_all_values()
        last_row = existing[-1] if len(existing) > 1 else []
        last_code = int(last_row[7]) if len(last_row) >= 8 and last_row[7].isdigit() else 20000
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
