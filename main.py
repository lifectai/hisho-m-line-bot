import os
from fastapi import FastAPI, Request, HTTPException
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from gmail import get_unread_emails, create_reply_draft, send_reply, revise_draft
from calendar_service import get_today_events, get_tomorrow_events, add_event, update_event
from task_service import add_task, suggest_task, get_progress, complete_task
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone

load_dotenv()

app = FastAPI()
claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# APSchedulerの設定
scheduler = BackgroundScheduler()

def check_task_deadlines():
    """締切24時間以内のタスクをチェックしてLINEに通知する関数"""
    from supabase import create_client
    import os
    
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY")
    )
    
    result = supabase.table("tasks").select("*").in_(
        "status", ["未着手", "進行中"]
    ).execute()
    
    tasks = result.data
    now = datetime.now(timezone.utc)
    warning_tasks = []
    
    for task in tasks:
        if task.get("deadline"):
            deadline_str = task["deadline"]
            if "+" not in deadline_str and "Z" not in deadline_str:
                deadline = datetime.fromisoformat(deadline_str).replace(tzinfo=timezone.utc)
            else:
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            diff = deadline - now
            if 0 < diff.total_seconds() < 86400:
                warning_tasks.append(task)
    
    if warning_tasks:
        user_id = os.getenv("LINE_USER_ID")
        if user_id:
            lines = ["⚠️ 締切が近いタスクがあります！"]
            for task in warning_tasks:
                deadline_str = task["deadline"]
                if "+" not in deadline_str and "Z" not in deadline_str:
                    deadline = datetime.fromisoformat(deadline_str).replace(tzinfo=timezone.utc)
                else:
                    deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                lines.append(f"・{task['title']}（締切：{deadline.strftime('%m/%d %H:%M')}）")
            
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="\n".join(lines))
            )

from briefing_service import send_morning_briefing

# 1時間ごとに締切チェックを実行
scheduler.add_job(check_task_deadlines, 'interval', hours=1)

# 毎朝7時にブリーフィングを送信（日本時間）
scheduler.add_job(send_morning_briefing, 'cron', hour=7, minute=0, timezone='Asia/Tokyo')

scheduler.start()

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
    elif "今日の予定" in user_message:
        try:
            reply_text = get_today_events()
        except Exception as e:
            reply_text = f"予定取得中にエラーが発生しました：{str(e)}"
    
    elif "明日の予定" in user_message:
        try:
            reply_text = get_tomorrow_events()
        except Exception as e:
            reply_text = f"予定取得中にエラーが発生しました：{str(e)}"
    
    elif "追加して" in user_message and ("時" in user_message or "予定" in user_message):
        try:
            reply_text = add_event(user_message)
        except Exception as e:
            reply_text = f"予定追加中にエラーが発生しました：{str(e)}"
    
    elif "変更して" in user_message and "時" in user_message:
        try:
            reply_text = update_event(user_message)
        except Exception as e:
            reply_text = f"予定変更中にエラーが発生しました：{str(e)}"

    elif "タスクに追加" in user_message or "タスク追加" in user_message:
        try:
            reply_text = add_task(user_message)
        except Exception as e:
            reply_text = f"タスク追加中にエラーが発生しました：{str(e)}"
    
    elif "何やる" in user_message or "タスク提案" in user_message:
        try:
            reply_text = suggest_task()
        except Exception as e:
            reply_text = f"タスク提案中にエラーが発生しました：{str(e)}"
    
    elif "進捗どう" in user_message or "進捗確認" in user_message:
        try:
            reply_text = get_progress()
        except Exception as e:
            reply_text = f"進捗確認中にエラーが発生しました：{str(e)}"
    
    elif "完了にして" in user_message or "タスク完了" in user_message:
        try:
            reply_text = complete_task(user_message)
        except Exception as e:
            reply_text = f"タスク完了中にエラーが発生しました：{str(e)}"

    elif "締切チェック" in user_message:
        try:
            check_task_deadlines()
            reply_text = "締切チェックを実行しました。"
        except Exception as e:
            reply_text = f"締切チェック中にエラーが発生しました：{str(e)}"
    
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