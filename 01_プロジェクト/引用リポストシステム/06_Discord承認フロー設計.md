# Discord承認フロー設計

## 概要
Lambda関数からDiscord Webhookで引用リポスト3案を通知し、
ユーザーの反応（承認/修正/スキップ）をAPI Gateway + Lambda経由で受け取る。

---

## Discord Bot の準備

### 1. Discord Developer Portalでの設定

1. https://discord.com/developers/applications にアクセス
2. 「New Application」→ 名前: `QuoteRepostBot`
3. Bot → 「Add Bot」
4. TOKEN をコピー → AWS SSM に保存
5. OAuth2 → URL Generator:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Add Reactions`
6. 生成されたURLでサーバーに招待

### 2. Webhook作成

1. Discord サーバー → 使用チャンネルの設定
2. 連携サービス → Webhook → 新しいWebhook
3. Webhook URL をコピー → AWS SSM に保存

### 3. 専用チャンネル作成

`#引用リポスト` チャンネルを作成（通知で他のチャットが埋もれないように）

---

## 通知メッセージフォーマット

Lambda `qr-notify` が以下のJSON構造をDiscord Webhookに送信:

```python
def send_discord_notification(original_post, author, drafts):
    """Discord Webhookに3案を送信"""
    
    message = f"""━━━━━━━━━━━━━━━━━━━━━
**新規引用リポスト候補**
━━━━━━━━━━━━━━━━━━━━━

**元ポスト** ({author}):
> {original_post}

━━━━━━━━━━━━━━━━━━━━━

**1. {drafts[0]['type']}　{drafts[0]['score']}点**
```
{drafts[0]['text']}
```

**2. {drafts[1]['type']}　{drafts[1]['score']}点**
```
{drafts[1]['text']}
```

**3. {drafts[2]['type']}　{drafts[2]['score']}点**
```
{drafts[2]['text']}
```

━━━━━━━━━━━━━━━━━━━━━
選択: `1` / `2` / `3`
修正: `修正 {修正指示}`
スキップ: `skip`
━━━━━━━━━━━━━━━━━━━━━"""

    payload = {
        "content": message,
        "username": "QuoteRepostBot"
    }
    
    requests.post(DISCORD_WEBHOOK_URL, json=payload)
```

---

## ユーザー反応の受信

### Discord Bot方式（推奨）

Discord Botがチャンネルのメッセージを監視し、反応に応じてAPI Gatewayにリクエスト送信。

```python
import discord

client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_message(message):
    if message.channel.name != "引用リポスト":
        return
    if message.author.bot:
        return
    
    content = message.content.strip()
    
    # 案の選択
    if content in ["1", "2", "3"]:
        # API Gatewayにリクエスト → Lambda qr-post が X APIで投稿
        await call_post_api(draft_index=int(content) - 1)
        await message.reply(f"案{content}を投稿しました")
    
    # 修正依頼
    elif content.startswith("修正"):
        revision_instruction = content.replace("修正", "").strip()
        # SQSに修正リクエストを送信 → Lambda qr-generate が再生成
        await call_revision_api(instruction=revision_instruction)
        await message.reply("修正して再生成中...")
    
    # スキップ
    elif content.lower() == "skip":
        await message.reply("スキップしました")
```

---

## 修正フロー

```
ユーザー: "修正 もっと攻撃的に。数字を入れて"
    ↓
Discord Bot → API Gateway → Lambda
    ↓
Lambda: 元のプロンプト + 修正指示 → Claude API再生成
    ↓
校正 + チェック（同じパイプライン）
    ↓
Discord通知（修正案を同チャンネルに送信）
    ↓
ユーザー: "2" → 投稿
```

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| Claude API タイムアウト | 30秒待ってリトライ（最大2回） |
| X API 投稿失敗 | エラー内容をDiscordに通知、手動投稿を促す |
| 文字数オーバー | 校正エンジンで検出、警告付きで通知 |
| 不正な入力 | "1, 2, 3, skip, 修正 のいずれかで回答してください" と返信 |

---

## API Gateway設定

Discord BotからのアクションをLambdaにルーティング:

```
POST /api/quote-repost/approve
  → Lambda: qr-post（X APIで投稿）
  Body: { "draft_index": 0, "post_id": "xxx" }

POST /api/quote-repost/revise
  → Lambda: qr-generate（再生成）
  Body: { "instruction": "修正指示", "original_post_id": "xxx" }

POST /api/quote-repost/skip
  → Lambda: ログ記録のみ
  Body: { "post_id": "xxx" }
```
