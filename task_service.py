import os
from supabase import create_client
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)
claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def add_task(instruction):
    """タスクを追加する関数"""
    
    # Claudeにタスク情報を抽出してもらう
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system="""タスク追加の指示から以下をJSON形式で抽出してください。
{
  "title": "タスク名",
  "priority": 重要度(1-5の数字),
  "urgency": 緊急度(1-5の数字)
}
重要度・緊急度が不明な場合は3にしてください。JSONのみ返答してください。""",
        messages=[{"role": "user", "content": instruction}]
    )
    
    raw = response.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    
    import json
    task_info = json.loads(raw)
    
    # Supabaseに保存
    result = supabase.table("tasks").insert({
        "title": task_info["title"],
        "priority": task_info["priority"],
        "urgency": task_info["urgency"],
        "status": "未着手"
    }).execute()
    
    return f"✅ タスクを追加しました。\n・{task_info['title']}（重要度:{task_info['priority']} 緊急度:{task_info['urgency']}）"


def suggest_task():
    """今やるべきタスクを提案する関数"""
    
    # 未着手・進行中のタスクを取得（重要度×緊急度の高い順）
    result = supabase.table("tasks").select("*").in_(
        "status", ["未着手", "進行中"]
    ).execute()
    
    tasks = result.data
    
    if not tasks:
        return "現在タスクはありません。「〇〇をタスクに追加して」で追加できます。"
    
    # 重要度×緊急度でスコアを計算してソート
    for task in tasks:
        task["score"] = task["priority"] * task["urgency"]
    
    tasks.sort(key=lambda x: x["score"], reverse=True)
    top_tasks = tasks[:3]
    
    lines = ["🎯 今やるべきタスク TOP3："]
    for i, task in enumerate(top_tasks, 1):
        lines.append(f"{i}. {task['title']}（重要度:{task['priority']} 緊急度:{task['urgency']}）")
    
    return "\n".join(lines)


def get_progress():
    """今日の進捗を確認する関数"""
    
    result = supabase.table("tasks").select("*").execute()
    tasks = result.data
    
    if not tasks:
        return "タスクがまだありません。"
    
    total = len(tasks)
    done = len([t for t in tasks if t["status"] == "完了"])
    in_progress = len([t for t in tasks if t["status"] == "進行中"])
    not_started = len([t for t in tasks if t["status"] == "未着手"])
    
    lines = [
        f"📊 タスク進捗：",
        f"・完了：{done}件",
        f"・進行中：{in_progress}件",
        f"・未着手：{not_started}件",
        f"・合計：{total}件"
    ]
    
    return "\n".join(lines)


def complete_task(instruction):
    """タスクを完了にする関数"""
    
    # 未着手・進行中のタスクを取得
    result = supabase.table("tasks").select("*").in_(
        "status", ["未着手", "進行中"]
    ).execute()
    
    tasks = result.data
    
    if not tasks:
        return "完了にできるタスクがありません。"
    
    # Claudeに該当タスクを特定してもらう
    task_list = "\n".join([f"id:{t['id']} タイトル:{t['title']}" for t in tasks])
    
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        system=f"""以下のタスク一覧から、指示に最も合うタスクのIDをそのまま返してください。IDのみ返答してください。
タスク一覧：
{task_list}""",
        messages=[{"role": "user", "content": instruction}]
    )
    
    task_id = response.content[0].text.strip()
    
    # タスクを完了に更新
    supabase.table("tasks").update(
        {"status": "完了"}
    ).eq("id", task_id).execute()
    
    target = next((t for t in tasks if t["id"] == task_id), None)
    title = target["title"] if target else "タスク"
    
    return f"✅ 「{title}」を完了にしました！"