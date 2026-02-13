"""
qr-post: X API投稿 + 修正/スキップ処理 Lambda
トリガー: API Gateway (Discord Botからのリクエスト)
役割: 承認された案をX APIで引用リポスト投稿 / 修正依頼をSQSに返す
"""

import json
from datetime import datetime
import tweepy
from config import (
    get_x_credentials,
    save_post_history,
    sqs,
    SQS_NEW_POST_QUEUE,
)
import boto3

dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
table_processed = dynamodb.Table("QuoteRepost_ProcessedPosts")


def get_x_client_v2() -> tweepy.Client:
    """投稿用X API v2クライアント"""
    creds = get_x_credentials()
    return tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_secret"],
    )


def post_quote_repost(client: tweepy.Client, text: str, quoted_tweet_id: str) -> dict:
    """X APIで引用リポストを投稿"""
    response = client.create_tweet(
        text=text,
        quote_tweet_id=quoted_tweet_id,
    )
    return {
        "tweet_id": str(response.data["id"]),
        "text": response.data["text"],
    }


def lambda_handler(event, context):
    """API Gatewayトリガー: 承認/修正/スキップ処理"""

    # API Gatewayからのリクエストをパース
    body = json.loads(event.get("body", "{}"))
    action = body.get("action", "")  # "approve", "revise", "skip"
    post_id = body.get("post_id", "")
    draft_index = body.get("draft_index", 0)  # 0, 1, 2
    revision_instruction = body.get("instruction", "")

    print(f"Action: {action}, Post: {post_id}")

    # ─── 承認: X APIで投稿 ───
    if action == "approve":
        # DynamoDBから原稿データを取得
        response = table_processed.get_item(Key={"post_id": post_id})
        item = response.get("Item", {})
        drafts = json.loads(item.get("drafts", "[]"))

        if not drafts or draft_index >= len(drafts):
            return api_response(400, "Invalid draft index")

        selected_draft = drafts[draft_index]
        text = selected_draft.get("text", "")

        # X API投稿
        client = get_x_client_v2()
        try:
            result = post_quote_repost(client, text, post_id)

            # 投稿履歴を保存
            save_post_history({
                "post_id": result["tweet_id"],
                "posted_at": datetime.utcnow().isoformat(),
                "text": text,
                "quoted_post_id": post_id,
                "quoted_author": item.get("author", ""),
                "draft_type": selected_draft.get("type", ""),
                "score": selected_draft.get("total_score", 0),
                "trend_keywords_used": selected_draft.get("trend_keywords", {}).get("used_keywords", []),
                "engagement": {
                    "impressions": 0,
                    "likes": 0,
                    "retweets": 0,
                    "bookmarks": 0,
                    "replies": 0,
                },
            })

            return api_response(200, {
                "message": "Posted successfully",
                "tweet_id": result["tweet_id"],
            })

        except tweepy.TweepyException as e:
            print(f"X API error: {e}")
            return api_response(500, f"X API error: {str(e)}")

    # ─── 修正: SQSに再生成リクエスト ───
    elif action == "revise":
        response = table_processed.get_item(Key={"post_id": post_id})
        item = response.get("Item", {})

        revision_message = {
            "post_id": post_id,
            "text": item.get("original_text", ""),
            "author": item.get("author", ""),
            "author_profile": json.loads(item.get("author_profile", "{}")),
            "mode": item.get("mode", "normal"),
            "revision_instruction": revision_instruction,
        }

        sqs.send_message(
            QueueUrl=SQS_NEW_POST_QUEUE,
            MessageBody=json.dumps(revision_message, ensure_ascii=False),
        )

        return api_response(200, {"message": "Revision request sent"})

    # ─── スキップ ───
    elif action == "skip":
        table_processed.update_item(
            Key={"post_id": post_id},
            UpdateExpression="SET skipped = :t, skipped_at = :s",
            ExpressionAttributeValues={
                ":t": True,
                ":s": datetime.utcnow().isoformat(),
            },
        )
        return api_response(200, {"message": "Skipped"})

    return api_response(400, "Invalid action")


def api_response(status_code: int, body) -> dict:
    """API Gateway用レスポンス成形"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body if isinstance(body, dict) else {"message": body}, ensure_ascii=False),
    }
