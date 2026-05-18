import json
import os
import base64
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from anthropic import Anthropic

# GmailのAPIで使う権限（スコープ）
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_gmail_service():
    """Gmail APIに接続するための準備をする関数"""
    creds = None
    
    # 環境変数からtoken情報を読み込む（Railway用）
    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json), SCOPES)
    
    # ローカル環境ではtoken.jsonから読み込む
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # 認証情報がない・期限切れの場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # ローカルのみ再認証可能
            client_secret_json = os.getenv("GOOGLE_CLIENT_SECRET_JSON")
            if client_secret_json:
                flow = InstalledAppFlow.from_client_config(
                    json.loads(client_secret_json), SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=8080)
            
            # ローカルの場合のみtoken.jsonに保存
            if not token_json:
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
    
    return build('gmail', 'v1', credentials=creds)


def get_unread_emails():
    """直近5日間の未読メールを取得して要約する関数"""
    service = get_gmail_service()
    
    # 5日前の日付を計算
    five_days_ago = (datetime.now() - timedelta(days=5)).strftime('%Y/%m/%d')
    
    # 未読メールを検索
    query = f'is:unread after:{five_days_ago}'
    results = service.users().messages().list(
        userId='me', q=query, maxResults=5).execute()
    
    messages = results.get('messages', [])
    
    if not messages:
        return "直近5日間の未読メールはありません。"
    
    email_summaries = []
    
    for message in messages:
        msg = service.users().messages().get(
            userId='me', id=message['id'], format='full').execute()
        
        # ヘッダーから件名と送信者を取得
        headers = msg['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '件名なし')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '送信者不明')
        
        # 本文を取得
        body = get_email_body(msg)
        
        # Claudeで要約
        summary = summarize_email(subject, sender, body)
        email_summaries.append(summary)
    
    return "\n\n".join(email_summaries)


def get_email_body(msg):
    """メールの本文を取得する関数"""
    body = ""
    
    if 'parts' in msg['payload']:
        for part in msg['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
                    break
    else:
        data = msg['payload']['body'].get('data', '')
        if data:
            body = base64.urlsafe_b64decode(data).decode('utf-8')
    
    return body[:1000]  # 最初の1000文字のみ


def summarize_email(subject, sender, body):
    """Claudeでメールを要約する関数"""
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system="メールを3行以内で要約してください。重要度（高/中/低）も判定してください。添付ファイルや画像がある場合は必ず「添付あり：要確認」と記載してください。",
        messages=[{
            "role": "user",
            "content": f"件名：{subject}\n送信者：{sender}\n本文：{body}"
        }]
    )
    
    return f"📧 {subject}\n{response.content[0].text}"

# セッション管理（下書きを一時保存）
email_sessions = {}


def create_reply_draft(user_id, instruction):
    """返信メールの下書きを作成する関数"""
    service = get_gmail_service()
    
    # 直近の未読メールを1件取得
    results = service.users().messages().list(
        userId='me', q='is:unread', maxResults=1).execute()
    messages = results.get('messages', [])
    
    if not messages:
        return "返信できる未読メールが見つかりません。"
    
    msg = service.users().messages().get(
        userId='me', id=messages[0]['id'], format='full').execute()
    
    headers = msg['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '件名なし')
    sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
    message_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), '')
    
    # Claudeで返信文を作成
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system="メールの返信文を作成してください。日本語で丁寧に、簡潔に書いてください。",
        messages=[{
            "role": "user",
            "content": f"件名：{subject}\n送信者：{sender}\n指示：{instruction}"
        }]
    )
    
    draft_text = response.content[0].text
    
    # セッションに保存
    email_sessions[user_id] = {
        "draft": draft_text,
        "to": sender,
        "subject": f"Re: {subject}",
        "message_id": message_id,
        "original_id": messages[0]['id']
    }
    
    return f"📝 下書きを作成しました。\n\n宛先：{sender}\n件名：Re: {subject}\n\n{draft_text}\n\n「送信して」で送信、「修正して＋内容」で修正できます。"


def send_reply(user_id):
    """下書きのメールを送信する関数"""
    if user_id not in email_sessions:
        return "送信する下書きがありません。先に「〇〇に返信して」と指示してください。"
    
    session = email_sessions[user_id]
    service = get_gmail_service()
    
    import email.mime.text
    import base64
    
    msg = email.mime.text.MIMEText(session["draft"])
    msg['To'] = session["to"]
    msg['Subject'] = session["subject"]
    msg['In-Reply-To'] = session["message_id"]
    
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    
    service.users().messages().send(
        userId='me',
        body={'raw': raw, 'threadId': session.get('thread_id', '')}
    ).execute()
    
    # セッションを削除
    del email_sessions[user_id]
    
    return f"✅ メールを送信しました。\n宛先：{session['to']}\n件名：{session['subject']}"


def revise_draft(user_id, instruction):
    """下書きを修正する関数"""
    if user_id not in email_sessions:
        return "修正する下書きがありません。先に「〇〇に返信して」と指示してください。"
    
    session = email_sessions[user_id]
    
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system="メールの返信文を修正してください。日本語で丁寧に、簡潔に書いてください。",
        messages=[{
            "role": "user",
            "content": f"現在の下書き：{session['draft']}\n修正指示：{instruction}"
        }]
    )
    
    new_draft = response.content[0].text
    email_sessions[user_id]["draft"] = new_draft
    
    return f"📝 下書きを修正しました。\n\n{new_draft}\n\n「送信して」で送信、「修正して＋内容」で再修正できます。"