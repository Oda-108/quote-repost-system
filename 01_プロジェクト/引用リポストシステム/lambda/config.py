"""
共通ユーティリティ + 設定
AWS SSM Parameter Store からシークレットを取得し、各Lambda関数で共有する
"""

import os
import json
import boto3
from functools import lru_cache

# AWS Clients
ssm = boto3.client("ssm", region_name="ap-northeast-1")
dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
sqs = boto3.client("sqs", region_name="ap-northeast-1")

# DynamoDB Tables
TABLE_PROCESSED = dynamodb.Table("QuoteRepost_ProcessedPosts")
TABLE_PROFILES = dynamodb.Table("QuoteRepost_AccountProfiles")
TABLE_TREND_KW = dynamodb.Table("QuoteRepost_TrendKeywords")
TABLE_HISTORY = dynamodb.Table("QuoteRepost_PostHistory")

# SQS Queue URLs
SQS_NEW_POST_QUEUE = os.environ.get("SQS_NEW_POST_QUEUE_URL", "")
SQS_RETRY_QUEUE = os.environ.get("SQS_RETRY_QUEUE_URL", "")


@lru_cache(maxsize=16)
def get_secret(name: str) -> str:
    """SSM Parameter Storeからシークレットを取得（キャッシュ付き）"""
    resp = ssm.get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def get_x_credentials() -> dict:
    """X API認証情報を取得"""
    return {
        "api_key": get_secret("/quote-repost/x-api-key"),
        "api_secret": get_secret("/quote-repost/x-api-secret"),
        "access_token": get_secret("/quote-repost/x-access-token"),
        "access_secret": get_secret("/quote-repost/x-access-secret"),
    }


def get_claude_api_key() -> str:
    return get_secret("/quote-repost/claude-api-key")


def get_discord_webhook_url() -> str:
    return get_secret("/quote-repost/discord-webhook-url")


def get_discord_bot_token() -> str:
    return get_secret("/quote-repost/discord-bot-token")


def get_monitored_accounts() -> list[dict]:
    """DynamoDBから監視対象アカウント一覧を取得"""
    response = TABLE_PROFILES.scan()
    return response.get("Items", [])


def get_trend_keywords() -> list[str]:
    """DynamoDBからトレンドキーワードリストを取得"""
    response = TABLE_TREND_KW.scan()
    return [item["keyword"] for item in response.get("Items", [])]


def is_post_processed(post_id: str) -> bool:
    """ポストIDが処理済みかチェック"""
    response = TABLE_PROCESSED.get_item(Key={"post_id": post_id})
    return "Item" in response


def mark_post_processed(post_id: str, author: str) -> None:
    """ポストIDを処理済みとしてマーク"""
    from datetime import datetime
    TABLE_PROCESSED.put_item(Item={
        "post_id": post_id,
        "author": author,
        "processed_at": datetime.utcnow().isoformat(),
    })


def save_post_history(post_data: dict) -> None:
    """投稿履歴をDynamoDBに保存"""
    TABLE_HISTORY.put_item(Item=post_data)


# Style Guidelines（デフォルト: 織田設定）
# 汎用版ではユーザーごとにDynamoDBから読み込む
DEFAULT_STYLE = {
    "first_person": ["俺", "自分"],
    "second_person": ["お前", "お前さん", "あなた", "君"],
    "forbidden_words": [
        "無理", "諦める", "できない", "設計",
        "頑張れ", "教えてくれ", "静かなる",
        "会社員やってる奴、大体ない",
        "これ、マジで本質や",
        "市場と対話して", "コレ、",
    ],
    "kansai_patterns": [
        r"やん[。！？\s]*$",
        r"なる[。！？\s]*$",
        r"[^し]や[。！？\s]*$",
        r"もうた[。！？\s]*$",
    ],
}
