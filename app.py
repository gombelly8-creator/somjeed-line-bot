import os
import re
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import anthropic
from supabase import create_client

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

configuration = Configuration(access_token=LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def save_memory(user_id, content, category="general"):
    supabase.table("memories").insert({
        "user_id": user_id,
        "content": content,
        "category": category
    }).execute()


def get_memories(user_id):
    result = supabase.table("memories")\
        .select("content, category, created_at")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()
    if not result.data:
        return "ยังไม่มีข้อมูลที่จำไว้"
    memories = []
    for m in result.data:
        date = m["created_at"][:10]
        memories.append(f"- [{m['category']}] {m['content']} ({date})")
    return "\n".join(memories)


def save_conversation(user_id, role, message):
    supabase.table("conversations").insert({
        "user_id": user_id,
        "role": role,
        "message": message
    }).execute()


def get_recent_conversation(user_id):
    result = supabase.table("conversations")\
        .select("role, message")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(10)\
        .execute()
    if not result.data:
        return []
    messages = list(reversed(result.data))
    return [{"role": m["role"], "content": m["message"]} for m in messages]


def ask_somjeed(user_id, user_message):
    memories = get_memories(user_id)
    history = get_recent_conversation(user_id)

    system_prompt = f"""คุณคือ "น้องส้มจี๊ด" AI Assistant ใน LINE ที่มีบุคลิกสดใส จี๊ดจ๊าด น่ารัก
พูดภาษาไทยเป็นหลัก ใช้ภาษาที่เป็นกันเอง อบอุ่น และสนุกสนาน

ความสามารถพิเศษ:
1. จำข้อมูลสำคัญของผู้ใช้ได้ เช่น ชื่อ งานอดิเรก ความชอบ
2. ถ้าผู้ใช้บอกข้อมูลสำคัญ ให้ตอบกลับและแจ้งว่าจำไว้แล้ว
3. นำความจำมาใช้ในการสนทนาให้เป็นธรรมชาติ

ข้อมูลที่จำไว้เกี่ยวกับผู้ใช้คนนี้:
{memories}

คำแนะนำ:
- ถ้าผู้ใช้บอกข้อมูลส่วนตัว ให้ตอบและใส่ [SAVE_MEMORY: หมวด | ข้อมูล] ท้ายข้อความ
- ตอบกระชับ ไม่เกิน 3-4 ประโยค
- ใส่ emoji บ้างแต่ไม่มากเกินไป 🍊"""

    history.append({"role": "user", "content": user_message})

    response = ai_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=history
    )

    reply = response.content[0].text

    if "[SAVE_MEMORY:" in reply:
        try:
            parts = reply.split("[SAVE_MEMORY:")
            for part in parts[1:]:
                memory_data = part.split("]")[0]
                cat, content = memory_data.split("|")
                save_memory(user_id, content.strip(), cat.strip())
            reply = re.sub(r'\[SAVE_MEMORY:[^\]]*\]', '', reply).strip()
        except:
            pass

    save_conversation(user_id, "user", user_message)
    save_conversation(user_id, "assistant", reply)

    return reply


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text
    reply = ask_somjeed(user_id, user_message)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )


@app.route("/", methods=["GET"])
def home():
    return "น้องส้มจี๊ด พร้อมให้บริการแล้ว! 🍊"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
