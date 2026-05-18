import os
from fastapi import FastAPI, Request, HTTPException
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from gmail import get_unread_emails, create_reply_draft, send_reply, revise_draft

load_dotenv()

app = FastAPI()
claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

@app.get("/")
def read_root():
    return {"status": "秘書M稼働中"}

@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id
    
    # キーワードで処理を振り分け
    if "メール確認" in user_message:
        try:
            reply_text = get_unread_emails()
        except Exception as e:
            reply_text = f"メール取得中にエラーが発生しました：{str(e)}"
    
    elif "返信して" in user_message:
        try:
            reply_text = create_reply_draft(user_id, user_message)
        except Exception as e:
            reply_text = f"下書き作成中にエラーが発生しました：{str(e)}"
    
    elif "送信して" in user_message:
        try:
            reply_text = send_reply(user_id)
        except Exception as e:
            reply_text = f"送信中にエラーが発生しました：{str(e)}"
    
    elif "修正して" in user_message:
        try:
            reply_text = revise_draft(user_id, user_message)
        except Exception as e:
            reply_text = f"修正中にエラーが発生しました：{str(e)}"
    
    else:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system="あなたは昇悟さん専用の秘書Mです。簡潔に、具体的に答えてください。",
            messages=[{"role": "user", "content": user_message}]
        )
        reply_text = response.content[0].text
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )