"""
qr-generate: 引用リポスト3案生成 + 校正 + チェック Lambda
トリガー: SQS (NewPostQueue)
役割: AI生成 → 校正 → アルゴリズムチェック → 通知Lambdaを呼び出し
"""

import json
import re
from datetime import datetime
import anthropic
import boto3
from config import (
    get_claude_api_key,
    get_trend_keywords,
    DEFAULT_STYLE,
)

lambda_client = boto3.client("lambda", region_name="ap-northeast-1")

# ──────────────────────────────────────
# System Prompt（04_引用リポスト生成プロンプト.md の内容）
# ──────────────────────────────────────

SYSTEM_PROMPT = """あなたは専属「引用リポストライターAI」である。

あなたの使命は、元ポストの「構造を盗み、自分の魂を注入」すること。
パクりではない。元ポストが示した真理を、自分の言葉・経験・思想で再構築し、
読んだ人間が「この引用の方がやべぇ」と思う一文を生み出すこと。

## 出力ルール
- 3案を生成（それぞれ異なる構成パターン + 異なる感情設計）
- 案A: リスペクト型（同意 + 上乗せ）
- 案B: 逆説型（別角度から切り込み）
- 案C: 発展型（独自の思想に展開）

## フック（1行目）の鉄則
感情だけで止まる一文にすること。思考フック不要でもOK。

## 改行ルール
自然な呼吸のリズムで改行。機械的な1行ずつ区切りではなく、読んでて心地いい流れ。

## 感情設計
- ネガ→ポジ転換
- ポジ→超ポジ
- 共感→気づき→行動意欲
- 衝撃→冷静分析→結論

## CTA
押し付けではなく、読んだ人が自然に「行動したい」と感じる構造。

## 禁止事項
- 禁止ワード: 無理、諦める、できない、設計、頑張れ（単独）
- 関西弁の語尾: やん、なる、や（文末）、もうた
- 絵文字禁止
- Markdown記法禁止（**太字**等）
- 元ポストのコピー禁止

## 出力フォーマット（JSON）
以下のJSON形式で出力してください。JSONのみ出力し、他のテキストは含めないでください。
{
  "drafts": [
    {
      "type": "リスペクト型",
      "text": "引用リポスト本文",
      "hook_type": "フック手法名",
      "structure": "構成パターン名",
      "emotion_flow": "感情の流れ",
      "score_self_assessment": {
        "hook_strength": 0,
        "structure_fit": 0,
        "emotion_design": 0,
        "specificity": 0,
        "bookmark_trigger": 0,
        "char_optimal": 0,
        "reading_pleasure": 0,
        "theme_freshness": 0,
        "brand_consistency": 0,
        "natural_cta": 0,
        "total": 0
      }
    }
  ]
}
"""

LONG_MODE_ADDITION = """
## 文字数
長文モード: 1,000〜1,500文字で生成してください。
"""

NORMAL_MODE_ADDITION = """
## 文字数
通常モード: 140〜280文字で生成してください。
"""


# ──────────────────────────────────────
# AI生成
# ──────────────────────────────────────

def generate_drafts(
    original_text: str,
    author_profile: dict,
    style_guidelines: str,
    trend_keywords: list[str],
    mode: str = "normal",
    revision_instruction: str | None = None,
) -> dict:
    """Claude APIで3案を生成"""
    client = anthropic.Anthropic(api_key=get_claude_api_key())

    mode_prompt = LONG_MODE_ADDITION if mode == "long" else NORMAL_MODE_ADDITION
    system = SYSTEM_PROMPT + mode_prompt

    user_content = f"""## 元ポスト
{original_text}

## 投稿者プロファイル
テーマ: {author_profile.get('primary_theme', '不明')}
思考パターン: {author_profile.get('thinking_pattern', '不明')}
語彙特徴: {author_profile.get('vocabulary_features', '不明')}
フック手法: {author_profile.get('hook_style', '不明')}
引用の切り口: {author_profile.get('quote_angle', '')}

## Style Guidelines
一人称: {', '.join(DEFAULT_STYLE['first_person'])}
二人称: {', '.join(DEFAULT_STYLE['second_person'])}

## トレンドキーワード（自然に1つ以上織り込むこと）
{', '.join(trend_keywords[:20])}

## モード
{mode}"""

    if revision_instruction:
        user_content += f"\n\n## 修正指示\n{revision_instruction}"

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    # JSONパース
    response_text = response.content[0].text
    # JSON部分を抽出（コードブロック内の場合も対応）
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError(f"Failed to parse JSON from Claude response: {response_text[:200]}")


# ──────────────────────────────────────
# 校正エンジン
# ──────────────────────────────────────

def proofread(text: str, style: dict = DEFAULT_STYLE) -> dict:
    """校正チェック: 禁止ワード、語尾、文字数、Markdown、絵文字"""
    issues = []
    corrected = text

    # 1. 禁止ワードチェック
    for word in style["forbidden_words"]:
        if word in corrected:
            issues.append({"type": "forbidden_word", "word": word, "severity": "warning"})

    # 2. 関西弁チェック
    for pattern in style["kansai_patterns"]:
        if re.search(pattern, corrected, re.MULTILINE):
            issues.append({"type": "kansai_dialect", "pattern": pattern, "severity": "error"})

    # 3. Markdown削除
    markdown_patterns = [
        (r"\*\*(.+?)\*\*", r"\1"),  # **太字**
        (r"^#+\s", ""),             # 見出し
        (r"^-\s", ""),              # リスト
    ]
    for pattern, replacement in markdown_patterns:
        if re.search(pattern, corrected, re.MULTILINE):
            corrected = re.sub(pattern, replacement, corrected, flags=re.MULTILINE)
            issues.append({"type": "markdown_removed", "severity": "auto_fixed"})

    # 4. 絵文字削除
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
        "\U00002600-\U000026FF]+",
        flags=re.UNICODE,
    )
    if emoji_pattern.search(corrected):
        corrected = emoji_pattern.sub("", corrected)
        issues.append({"type": "emoji_removed", "severity": "auto_fixed"})

    # 5. 文字数チェック
    char_count = len(corrected)
    issues.append({"type": "char_count", "count": char_count, "severity": "info"})

    return {
        "original": text,
        "corrected": corrected,
        "char_count": char_count,
        "issues": issues,
        "has_critical_issues": any(i["severity"] == "error" for i in issues),
    }


# ──────────────────────────────────────
# アルゴリズムチェック（具体性のみ自動、残りはAI自己採点を使用）
# ──────────────────────────────────────

def check_specificity(text: str) -> int:
    """数字・金額・人数の含有をチェック"""
    score = 0
    if re.search(r"\d+", text):
        score += 3
    if re.search(r"[\d,]+万|[\d,]+円|[\d,]+億|月収[\d,]+|年収[\d,]+|年商[\d,]+", text):
        score += 4
    if re.search(r"\d+人|\d+ヶ月|\d+日|\d+年|\d+時間|\d+回|\d+%", text):
        score += 3
    return min(score, 10)


def check_trend_keywords(text: str, trend_keywords: list[str]) -> dict:
    """トレンドKWが含まれているかチェック"""
    used = [kw for kw in trend_keywords if kw in text]
    return {
        "has_trend_kw": len(used) > 0,
        "used_keywords": used,
        "count": len(used),
    }


def validate_draft(draft: dict, trend_keywords: list[str]) -> dict:
    """1案の品質を総合検証"""
    text = draft["text"]

    # 校正
    proof = proofread(text)

    # 具体性チェック（自動）
    specificity_score = check_specificity(proof["corrected"])

    # トレンドKW
    trend_check = check_trend_keywords(proof["corrected"], trend_keywords)

    # AIの自己採点を取得（生成時に含まれる）
    ai_score = draft.get("score_self_assessment", {})
    # 具体性だけ自動計算で上書き
    ai_score["specificity"] = specificity_score
    total = sum(v for k, v in ai_score.items() if k != "total")
    ai_score["total"] = total

    return {
        "type": draft["type"],
        "text": proof["corrected"],
        "original_text": text,
        "char_count": proof["char_count"],
        "proofread_issues": proof["issues"],
        "has_critical_issues": proof["has_critical_issues"],
        "score": ai_score,
        "total_score": total,
        "trend_keywords": trend_check,
        "hook_type": draft.get("hook_type", ""),
        "structure": draft.get("structure", ""),
        "emotion_flow": draft.get("emotion_flow", ""),
    }


# ──────────────────────────────────────
# メインハンドラー
# ──────────────────────────────────────

def lambda_handler(event, context):
    """SQSトリガー: 新規ポストに対して3案生成+校正+チェック"""
    for record in event.get("Records", []):
        message = json.loads(record["body"])

        post_id = message["post_id"]
        original_text = message["text"]
        author = message["author"]
        author_profile = message["author_profile"]
        mode = message.get("mode", "normal")
        revision_instruction = message.get("revision_instruction")

        print(f"Processing post {post_id} from {author} (mode: {mode})")

        # トレンドKW取得
        trend_keywords = get_trend_keywords()

        # AI生成（最大2回リトライ）
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = generate_drafts(
                    original_text=original_text,
                    author_profile=author_profile,
                    style_guidelines="",  # System Promptに組み込み済み
                    trend_keywords=trend_keywords,
                    mode=mode,
                    revision_instruction=revision_instruction,
                )
                break
            except Exception as e:
                print(f"Generation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries:
                    print(f"All retries failed for post {post_id}")
                    return {"statusCode": 500, "body": str(e)}

        # 各案を検証
        validated_drafts = []
        for draft in result.get("drafts", []):
            validated = validate_draft(draft, trend_keywords)
            validated_drafts.append(validated)

        # 60点未満の案は除外
        go_drafts = [d for d in validated_drafts if d["total_score"] >= 60]

        if not go_drafts:
            print(f"All drafts scored below 60 for post {post_id}. Skipping.")
            return {"statusCode": 200, "body": "All drafts rejected"}

        # 通知Lambdaを呼び出し
        notification_payload = {
            "post_id": post_id,
            "original_text": original_text,
            "author": author,
            "drafts": go_drafts,
            "trend_keywords_available": trend_keywords[:10],
        }

        lambda_client.invoke(
            FunctionName="qr-notify",
            InvocationType="Event",  # 非同期
            Payload=json.dumps(notification_payload, ensure_ascii=False).encode("utf-8"),
        )

        print(f"Notification sent for post {post_id} with {len(go_drafts)} drafts")

    return {"statusCode": 200, "body": "Processing complete"}
