import os
import json
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from anthropic import Anthropic

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def get_calendar_service():
    """Google Calendar APIに接続するための準備をする関数"""
    creds = None

    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json), SCOPES)
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_secret_json = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
            if client_secret_json:
                flow = InstalledAppFlow.from_client_config(
                    json.loads(client_secret_json), SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=8080)
            if not token_json:
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def get_today_events():
    """今日の予定を取得する関数"""
    service = get_calendar_service()

    # 今日の開始・終了時刻を設定
    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_of_day,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return "今日の予定はありません。"

    lines = ["📅 今日の予定："]
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date', ''))
        if 'T' in start:
            start_time = datetime.fromisoformat(start).strftime('%H:%M')
        else:
            start_time = '終日'
        lines.append(f"・{start_time} {event['summary']}")

    return "\n".join(lines)


def get_tomorrow_events():
    """明日の予定を取得する関数"""
    service = get_calendar_service()

    tomorrow = datetime.now() + timedelta(days=1)
    start_of_day = tomorrow.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
    end_of_day = tomorrow.replace(hour=23, minute=59, second=59).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_of_day,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return "明日の予定はありません。"

    lines = ["📅 明日の予定："]
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date', ''))
        if 'T' in start:
            start_time = datetime.fromisoformat(start).strftime('%H:%M')
        else:
            start_time = '終日'
        lines.append(f"・{start_time} {event['summary']}")

    return "\n".join(lines)


def add_event(instruction):
    """予定を追加する関数"""
    service = get_calendar_service()

    # Claudeに予定の詳細を抽出してもらう
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system="""予定追加の指示から以下をJSON形式で抽出してください。
今日の日付は """ + datetime.now().strftime('%Y-%m-%d') + """です。
{
  "title": "予定のタイトル",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "end_time": "HH:MM"
}
end_timeが不明な場合は1時間後にしてください。JSONのみ返答してください。""",
        messages=[{"role": "user", "content": instruction}]
    )

    event_info = json.loads(response.content[0].text.strip())

    # タイムゾーンを設定（日本時間）
    tz = 'Asia/Tokyo'
    start_dt = f"{event_info['date']}T{event_info['start_time']}:00"
    end_dt = f"{event_info['date']}T{event_info['end_time']}:00"

    event = {
        'summary': event_info['title'],
        'start': {'dateTime': start_dt, 'timeZone': tz},
        'end': {'dateTime': end_dt, 'timeZone': tz},
    }

    created_event = service.events().insert(
        calendarId='primary', body=event).execute()

    return f"✅ 予定を追加しました。\n・{event_info['date']} {event_info['start_time']} {event_info['title']}"


def update_event(instruction):
    """予定を変更する関数"""
    service = get_calendar_service()

    # Claudeに変更内容を抽出してもらう
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system="""予定変更の指示から以下をJSON形式で抽出してください。
今日の日付は """ + datetime.now().strftime('%Y-%m-%d') + """です。
{
  "search_keyword": "検索するキーワード",
  "date": "YYYY-MM-DD",
  "new_start_time": "HH:MM",
  "new_end_time": "HH:MM"
}
new_end_timeが不明な場合は1時間後にしてください。JSONのみ返答してください。""",
        messages=[{"role": "user", "content": instruction}]
    )

    change_info = json.loads(response.content[0].text.strip())

    # 該当日の予定を検索
    target_date = change_info['date']
    start_of_day = f"{target_date}T00:00:00Z"
    end_of_day = f"{target_date}T23:59:59Z"

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_of_day,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    target_event = None
    for event in events:
        if change_info['search_keyword'] in event.get('summary', ''):
            target_event = event
            break

    if not target_event:
        return f"「{change_info['search_keyword']}」という予定が見つかりませんでした。"

    # 予定を更新
    tz = 'Asia/Tokyo'
    target_event['start'] = {
        'dateTime': f"{target_date}T{change_info['new_start_time']}:00",
        'timeZone': tz
    }
    target_event['end'] = {
        'dateTime': f"{target_date}T{change_info['new_end_time']}:00",
        'timeZone': tz
    }

    service.events().update(
        calendarId='primary',
        eventId=target_event['id'],
        body=target_event
    ).execute()

    return f"✅ 予定を変更しました。\n・{target_event['summary']} → {change_info['new_start_time']}〜{change_info['new_end_time']}"