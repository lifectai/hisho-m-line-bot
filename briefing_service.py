import os
from linebot import LineBotApi
from linebot.models import TextSendMessage
from dotenv import load_dotenv
from calendar_service import get_today_events
from task_service import suggest_task
from gmail import get_unread_emails

load_dotenv()

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))


def send_morning_briefing():
    """毎朝7時に今日の予定・タスク・メールをまとめてLINEに送る関数"""

    user_id = os.getenv("LINE_USER_ID")
    if not user_id:
        print("LINE_USER_IDが設定されていません")
        return

    lines = ["☀️ おはようございます！本日のブリーフィングです。\n"]

    # 今日の予定
    try:
        events = get_today_events()
        lines.append(f"📅 予定\n{events}")
    except Exception as e:
        lines.append(f"📅 予定：取得失敗（{str(e)[:30]}）")

    # 優先タスクTop3
    try:
        tasks = suggest_task()
        lines.append(f"\n✅ タスク\n{tasks}")
    except Exception as e:
        lines.append(f"\n✅ タスク：取得失敗（{str(e)[:30]}）")

    # 未読重要メール
    try:
        emails = get_unread_emails()
        lines.append(f"\n📧 メール\n{emails}")
    except Exception as e:
        lines.append(f"\n📧 メール：取得失敗（{str(e)[:30]}）")

    message = "\n".join(lines)

    # 300文字を超えた場合は切り詰める
    if len(message) > 300:
        message = message[:297] + "..."

    line_bot_api.push_message(
        user_id,
        TextSendMessage(text=message)
    )
    print(f"朝ブリーフィング送信完了：{len(message)}文字")