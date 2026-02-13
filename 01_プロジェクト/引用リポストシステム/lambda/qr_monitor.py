"""
qr-monitor: X APIタイムライン監視 Lambda
トリガー: EventBridge (5分間隔)
役割: 15アカウントの新規ポストを検出し、SQSに送信
"""

import json
import tweepy
from config import (
    get_x_credentials,
    get_monitored_accounts,
    is_post_processed,
    mark_post_processed,
    sqs,
    SQS_NEW_POST_QUEUE,
)


def get_x_client() -> tweepy.Client:
    """X API v2クライアントを作成"""
    creds = get_x_credentials()
    return tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_secret"],
    )


def fetch_recent_tweets(client: tweepy.Client, user_id: str, max_results: int = 10) -> list[dict]:
    """ユーザーの最新ツイートを取得"""
    try:
        response = client.get_users_tweets(
            id=user_id,
            max_results=max_results,
            tweet_fields=["created_at", "public_metrics", "text"],
            exclude=["retweets", "replies"],
        )
        if response.data is None:
            return []

        tweets = []
        for tweet in response.data:
            tweets.append({
                "id": str(tweet.id),
                "text": tweet.text,
                "created_at": tweet.created_at.isoformat() if tweet.created_at else "",
                "metrics": {
                    "like_count": tweet.public_metrics.get("like_count", 0),
                    "retweet_count": tweet.public_metrics.get("retweet_count", 0),
                    "reply_count": tweet.public_metrics.get("reply_count", 0),
                    "bookmark_count": tweet.public_metrics.get("bookmark_count", 0),
                    "impression_count": tweet.public_metrics.get("impression_count", 0),
                } if tweet.public_metrics else {},
            })
        return tweets
    except tweepy.TweepyException as e:
        print(f"Error fetching tweets for user {user_id}: {e}")
        return []


def lambda_handler(event, context):
    """メインハンドラー: 全監視アカウントの新規ポストを検出"""
    client = get_x_client()
    accounts = get_monitored_accounts()
    new_posts_count = 0

    print(f"Monitoring {len(accounts)} accounts...")

    for account in accounts:
        account_id = account["account_id"]
        user_id = account.get("x_user_id", "")

        if not user_id:
            print(f"Skipping {account_id}: no x_user_id configured")
            continue

        tweets = fetch_recent_tweets(client, user_id)

        for tweet in tweets:
            post_id = tweet["id"]

            # 処理済みチェック
            if is_post_processed(post_id):
                continue

            # 新規ポスト発見
            print(f"New post detected: {account_id} - {post_id}")

            # SQSに送信
            message = {
                "post_id": post_id,
                "text": tweet["text"],
                "author": account_id,
                "author_profile": {
                    "account_id": account.get("account_id", ""),
                    "primary_theme": account.get("primary_theme", ""),
                    "thinking_pattern": account.get("thinking_pattern", ""),
                    "vocabulary_features": account.get("vocabulary_features", ""),
                    "hook_style": account.get("hook_style", ""),
                    "quote_angle": account.get("quote_angle", ""),
                    "best_quote_type": account.get("best_quote_type", ""),
                },
                "metrics": tweet["metrics"],
                "created_at": tweet["created_at"],
                "mode": "normal",  # デフォルト通常モード
            }

            sqs.send_message(
                QueueUrl=SQS_NEW_POST_QUEUE,
                MessageBody=json.dumps(message, ensure_ascii=False),
            )

            # 処理済みとしてマーク
            mark_post_processed(post_id, account_id)
            new_posts_count += 1

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Monitoring complete. {new_posts_count} new posts detected.",
            "accounts_monitored": len(accounts),
            "new_posts": new_posts_count,
        }),
    }
