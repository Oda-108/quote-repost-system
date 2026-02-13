"""
qr-notify: Discord通知 Lambda
トリガー: qr-generateから非同期呼び出し
役割: 検証済み3案をDiscord Webhookで通知
"""

import json
import requests
from config import get_discord_webhook_url


def format_notification(post_id: str, original_text: str, author: str, drafts: list[dict]) -> str:
    """Discord通知メッセージを成形"""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        "**新規引用リポスト候補**",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"**元ポスト** ({author}):",
        f"> {original_text[:300]}{'...' if len(original_text) > 300 else ''}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, draft in enumerate(drafts, 1):
        score = draft.get("total_score", 0)
        draft_type = draft.get("type", "")
        text = draft.get("text", "")
        trend_kw = draft.get("trend_keywords", {})
        kw_str = f" | KW: {', '.join(trend_kw.get('used_keywords', []))}" if trend_kw.get("has_trend_kw") else ""

        lines.extend([
            "",
            f"**{i}. {draft_type}　{score}点**{kw_str}",
            f"```",
            text,
            f"```",
        ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"選択: `1` / `2` / `3`",
        f"修正: `修正 {{修正指示}}`",
        f"スキップ: `skip`",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ])

    return "\n".join(lines)


def lambda_handler(event, context):
    """メインハンドラー: Discord Webhookで通知送信"""
    post_id = event["post_id"]
    original_text = event["original_text"]
    author = event["author"]
    drafts = event["drafts"]

    webhook_url = get_discord_webhook_url()
    message = format_notification(post_id, original_text, author, drafts)

    # Discord Webhookは2000文字制限があるため、長い場合は分割
    if len(message) <= 2000:
        payload = {"content": message, "username": "QuoteRepostBot"}
        response = requests.post(webhook_url, json=payload)
    else:
        # 分割送信
        chunks = split_message(message, 2000)
        for chunk in chunks:
            payload = {"content": chunk, "username": "QuoteRepostBot"}
            response = requests.post(webhook_url, json=payload)

    # 投稿候補データをメタデータとして保存（後でpost関数が参照）
    import boto3
    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("QuoteRepost_ProcessedPosts")
    table.update_item(
        Key={"post_id": post_id},
        UpdateExpression="SET drafts = :d, notification_sent = :t",
        ExpressionAttributeValues={
            ":d": json.dumps(drafts, ensure_ascii=False),
            ":t": True,
        },
    )

    print(f"Notification sent for post {post_id}")
    return {"statusCode": 200, "body": "Notification sent"}


def split_message(text: str, max_length: int) -> list[str]:
    """メッセージを最大文字数で分割"""
    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += "\n" + line if current_chunk else line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
