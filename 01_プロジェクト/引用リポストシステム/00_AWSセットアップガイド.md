# AWSセットアップガイド（引用リポスト自動化システム用）

## 概要
このガイドでは、引用リポスト自動化システムに必要なAWSサービスのセットアップ手順を説明する。
AWS初心者でも順番に進めれば構築できるように設計。

---

## 必要なAWSサービス一覧

| サービス | 役割 | 月額目安 |
|---------|------|---------|
| IAM | ユーザー・権限管理 | 無料 |
| Lambda | 全ての処理ロジック | ~$2〜5 |
| EventBridge | 定期実行トリガー | 無料 |
| SQS | Lambda間のメッセージキュー | ~$0.5 |
| DynamoDB | データ保存（ポストID・KW・履歴） | ~$1〜3 |
| API Gateway | Discord Botからのwebhook受信 | ~$1 |
| CloudWatch | ログ・監視 | 無料枠内 |

**合計: 月$5〜10**

---

## Step 1: AWSアカウント作成

1. https://aws.amazon.com/ にアクセス
2. 「AWSアカウントを作成」をクリック
3. メールアドレス、パスワード、アカウント名を入力
4. クレジットカード登録（従量課金のため）
5. 電話番号認証
6. サポートプラン → 「ベーシック（無料）」を選択

> 注意: 初回12ヶ月は無料枠が大きいので、ほとんどのサービスが無料で使える

---

## Step 2: IAMユーザー作成（セキュリティ）

ルートアカウントで直接操作しないのがAWSのベストプラクティス。

1. AWSコンソール → IAM → 「ユーザー」
2. 「ユーザーを作成」
3. ユーザー名: `quote-repost-admin`
4. 「コンソールアクセスを提供」にチェック
5. 権限 → 「既存のポリシーを直接アタッチ」
   - `AmazonDynamoDBFullAccess`
   - `AWSLambda_FullAccess`
   - `AmazonSQSFullAccess`
   - `AmazonEventBridgeFullAccess`
   - `AmazonAPIGatewayAdministrator`
   - `CloudWatchLogsFullAccess`
6. アクセスキーを作成 → 「CLI」用途を選択
7. アクセスキーID とシークレットアクセスキーを安全に保存

---

## Step 3: AWS CLIインストール（Mac）

ローカルからAWSを操作するためのツール。

```bash
# Homebrewでインストール
brew install awscli

# 設定
aws configure
# AWS Access Key ID: (Step 2で取得したキー)
# AWS Secret Access Key: (Step 2で取得したシークレット)
# Default region name: ap-northeast-1 (東京リージョン)
# Default output format: json
```

動作確認:
```bash
aws sts get-caller-identity
# → アカウントIDが表示されればOK
```

---

## Step 4: DynamoDBテーブル作成

### 4-1. 処理済みポストIDテーブル

```bash
aws dynamodb create-table \
  --table-name QuoteRepost_ProcessedPosts \
  --attribute-definitions \
    AttributeName=post_id,AttributeType=S \
  --key-schema \
    AttributeName=post_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

### 4-2. アカウントプロファイルテーブル

```bash
aws dynamodb create-table \
  --table-name QuoteRepost_AccountProfiles \
  --attribute-definitions \
    AttributeName=account_id,AttributeType=S \
  --key-schema \
    AttributeName=account_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

### 4-3. トレンドキーワードテーブル

```bash
aws dynamodb create-table \
  --table-name QuoteRepost_TrendKeywords \
  --attribute-definitions \
    AttributeName=keyword,AttributeType=S \
  --key-schema \
    AttributeName=keyword,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

### 4-4. 投稿履歴テーブル

```bash
aws dynamodb create-table \
  --table-name QuoteRepost_PostHistory \
  --attribute-definitions \
    AttributeName=post_id,AttributeType=S \
    AttributeName=posted_at,AttributeType=S \
  --key-schema \
    AttributeName=post_id,KeyType=HASH \
    AttributeName=posted_at,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

---

## Step 5: SQSキュー作成

```bash
aws sqs create-queue \
  --queue-name QuoteRepost_NewPostQueue \
  --region ap-northeast-1

aws sqs create-queue \
  --queue-name QuoteRepost_RetryQueue \
  --region ap-northeast-1
```

---

## Step 6: Lambda関数の準備

Lambda関数は以下の4つを作成する（Step 3の実装フェーズで詳細構築）:

| Lambda名 | トリガー | 役割 |
|----------|---------|------|
| `qr-monitor` | EventBridge (5分) | X APIタイムライン監視 |
| `qr-generate` | SQS (NewPostQueue) | AI生成+校正+チェック |
| `qr-notify` | qr-generateから直接呼出 | Discord通知 |
| `qr-post` | API Gateway (Webhook) | X API投稿 |
| `qr-trend-collect` | EventBridge (週次) | トレンドKW収集 |
| `qr-engagement` | EventBridge (日次) | エンゲージメント取得 |

ランタイム: **Python 3.12**（anthropic SDK, tweepy, requests対応）

---

## Step 7: 環境変数の管理

Lambda関数に設定する環境変数（AWS Systems Manager Parameter Storeで安全に管理）:

```bash
# X API認証
aws ssm put-parameter --name "/quote-repost/x-api-key" --value "YOUR_KEY" --type SecureString
aws ssm put-parameter --name "/quote-repost/x-api-secret" --value "YOUR_SECRET" --type SecureString
aws ssm put-parameter --name "/quote-repost/x-access-token" --value "YOUR_TOKEN" --type SecureString
aws ssm put-parameter --name "/quote-repost/x-access-secret" --value "YOUR_SECRET" --type SecureString

# Claude API
aws ssm put-parameter --name "/quote-repost/claude-api-key" --value "YOUR_KEY" --type SecureString

# Discord
aws ssm put-parameter --name "/quote-repost/discord-webhook-url" --value "YOUR_URL" --type SecureString
aws ssm put-parameter --name "/quote-repost/discord-bot-token" --value "YOUR_TOKEN" --type SecureString
```

---

## 次のステップ

この初期セットアップ完了後、Step 3でLambda関数のコードを実装していく。
必要なAPIキーを事前に取得しておくこと:

- [ ] X API認証情報（X Developer Portalで取得）
- [ ] Claude API Key（Anthropic Consoleで取得）
- [ ] Discord Bot Token（Discord Developer Portalで取得）
- [ ] Discord Webhook URL（サーバー設定 → 連携サービス → Webhook）
