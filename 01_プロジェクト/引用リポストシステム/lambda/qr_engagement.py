"""
qr-engagement: エンゲージメント収集 Lambda
トリガー: EventBridge (日次)
役割: 過去に投稿した引用リポストのIMP・いいね・RT等を取得してDynamoDBを更新
ダッシュボード用データの更新に使用
"""

import json
from datetime import datetime, timedelta
import tweepy
from config import get_x_credentials, TABLE_HISTORY


def get_x_client() -> tweepy.Client:
    creds = get_x_credentials()
    return tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_secret"],
    )


def lambda_handler(event, context):
    """過去14日間の投稿のエンゲージメントを取得して更新"""
    client = get_x_client()

    # 投稿履歴テーブルから直近14日分を取得
    cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()

    response = TABLE_HISTORY.scan(
        FilterExpression="posted_at >= :cutoff",
        ExpressionAttributeValues={":cutoff": cutoff},
    )

    posts = response.get("Items", [])
    updated_count = 0

    for post in posts:
        tweet_id = post["post_id"]

        try:
            tweet = client.get_tweet(
                id=tweet_id,
                tweet_fields=["public_metrics"],
            )

            if tweet.data and tweet.data.public_metrics:
                metrics = tweet.data.public_metrics
                engagement = {
                    "impressions": metrics.get("impression_count", 0),
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "bookmarks": metrics.get("bookmark_count", 0),
                    "replies": metrics.get("reply_count", 0),
                }

                # エンゲージメント率を計算
                imp = engagement["impressions"]
                total_eng = (
                    engagement["likes"]
                    + engagement["retweets"]
                    + engagement["bookmarks"]
                    + engagement["replies"]
                )
                engagement["rate"] = round(total_eng / imp * 100, 2) if imp > 0 else 0

                TABLE_HISTORY.update_item(
                    Key={
                        "post_id": tweet_id,
                        "posted_at": post["posted_at"],
                    },
                    UpdateExpression="SET engagement = :e, last_updated = :u",
                    ExpressionAttributeValues={
                        ":e": engagement,
                        ":u": datetime.utcnow().isoformat(),
                    },
                )
                updated_count += 1

        except tweepy.TweepyException as e:
            print(f"Error fetching metrics for {tweet_id}: {e}")
            continue

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Engagement updated for {updated_count}/{len(posts)} posts",
        }),
    }
