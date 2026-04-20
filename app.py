# -*- coding: utf-8 -*-
"""
mitsumori-app : 初期費用見積書作成 Webアプリ
  1. マイソク PDF をアップロード
  2. Gemini API (base64) で初期費用項目を抽出
  3. 確認・編集画面 (項目追加/削除/金額修正)
  4. 見積書 PDF をダウンロード (reportlab)
"""
import os
import io
import json
import base64
import re
import zipfile
from datetime import datetime

from flask import Flask, request, jsonify, send_file, render_template_string

from google import genai
from google.genai import types as genai_types

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import stringWidth


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
COMPANY_NAME = "株式会社エヌプライム"
COMPANY_ADDRESS_1 = "東京都港区新橋2-20-15"
COMPANY_ADDRESS_2 = "新橋駅前ビル1号館4階 フィルポート"
COMPANY_TEL = "03-6228-5808"
COMPANY_MAIL = "info@nprime.co.jp"

# 必須項目 (編集画面で初期表示されるデフォルト行)
REQUIRED_ITEMS = [
    "家賃", "管理費", "敷金", "礼金",
    "仲介手数料", "保証会社料", "火災保険料", "鍵交換費用",
]

GEMINI_MODEL = "gemini-2.5-flash"

# アプリのバージョン (キャッシュ確認用)
APP_VERSION = "2026.04.20-a"

# reportlab 内蔵の日本語 CID フォント
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
FONT_GOTHIC = "HeiseiKakuGo-W5"
FONT_MINCHO = "HeiseiMin-W3"

# カラーパレット (ネイビー × ゴールド)
COLOR_NAVY = HexColor("#1a2a3a")
COLOR_GOLD = HexColor("#c9a961")
COLOR_GRAY_DARK = HexColor("#333333")
COLOR_GRAY_LIGHT = HexColor("#e5e5e5")
COLOR_GRAY_BG = HexColor("#f7f5f0")


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB


# ---------------------------------------------------------------------------
# Gemini 呼び出し
# ---------------------------------------------------------------------------
def extract_items_from_pdf(pdf_bytes: bytes) -> dict:
    """マイソク PDF を Gemini に渡して初期費用情報を抽出する"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")

    client = genai.Client(api_key=api_key)

    prompt = (
        "あなたは不動産マイソク（物件資料PDF）から初期費用情報を抽出する専門家です。\n"
        "添付のPDFには **1つまたは複数の物件情報** が含まれている可能性があります。\n"
        "物件ごとに初期費用情報を抽出し、以下の形式で **JSON のみ** を出力してください。\n"
        "コードブロック記号や説明文は一切不要です。\n"
        "\n"
        "出力JSONスキーマ:\n"
        "{\n"
        '  "properties": [\n'
        "    {\n"
        '      "property_name": "物件名 (文字列)",\n'
        '      "address":       "所在地 (文字列)",\n'
        '      "items": [\n'
        '        {"name": "項目名", "amount": 金額(整数,円)}\n'
        "      ],\n"
        '      "total": 合計金額(整数,円)\n'
        "    }\n"
        "    // 物件が複数ある場合はここに物件数分のオブジェクトを追加\n"
        "  ]\n"
        "}\n"
        "\n"
        "物件の判定ルール:\n"
        "  - 複数物件が並列に掲載されている場合は properties に物件ごとのオブジェクトを追加\n"
        "  - 同一物件の表裏・間取り図・物件概要などページが分かれているだけの場合は 1つ にまとめる\n"
        "  - 物件が1件の場合でも必ず properties 配列 (要素1) で返す\n"
        "\n"
        "各物件の items 配列には以下を必ず含めてください (PDF に記載がなければ amount=0):\n"
        "  - 家賃 / 管理費 / 敷金 / 礼金\n"
        "  - 仲介手数料 / 保証会社料 / 火災保険料 / 鍵交換費用\n"
        "さらに PDF に記載されている初期費用に関わる項目 (消毒料・事務手数料・"
        "室内清掃費・安心サポート料・害虫駆除費 等) も全て items に追加すること。\n"
        "\n"
        "ルール:\n"
        "  - 金額は整数 (円単位)。『85,000円』→ 85000、『家賃1ヶ月分』等で金額不明なら 0\n"
        "  - PDFで『別途』『応相談』『要相談』『未定』等と書かれていれば amount はその文字列をそのまま返す\n"
        "    (例: {\"name\": \"仲介手数料\", \"amount\": \"別途\"})\n"
        "  - 見つからない情報は空文字 \"\" を返す\n"
        "  - JSON 以外のテキスト (説明・前置き・コードフェンス) を絶対に出力しない\n"
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            genai_types.Part.from_bytes(
                data=pdf_bytes, mime_type="application/pdf",
            ),
            prompt,
        ],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    raw = (response.text or "").strip()
    # 念のためコードフェンスを除去
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini 出力の JSON 解析に失敗: {e}\n---\n{raw[:500]}")

    # 新旧フォーマット吸収: {properties:[...]} でも従来の単一物件でもOKにする
    if isinstance(data, dict) and "properties" in data and isinstance(data["properties"], list):
        props = data["properties"]
    elif isinstance(data, list):
        props = data
    else:
        props = [data] if isinstance(data, dict) else []

    normalized = []
    for p in props:
        if not isinstance(p, dict):
            continue
        p.setdefault("property_name", "")
        p.setdefault("address", "")
        p.setdefault("items", [])
        p.setdefault("total", 0)

        # 必須項目を補完
        existing = {i.get("name", "") for i in p["items"] if isinstance(i, dict)}
        for req in REQUIRED_ITEMS:
            if req not in existing:
                p["items"].append({"name": req, "amount": 0})

        # 金額は整数 OR 文字列 ("別途" 等) を許容
        for item in p["items"]:
            item["name"] = str(item.get("name", ""))
            raw = item.get("amount", 0)
            item["amount"] = _coerce_amount(raw)

        try:
            p["total"] = int(p.get("total", 0) or 0)
        except (TypeError, ValueError):
            p["total"] = sum(_amount_to_int(i["amount"]) for i in p["items"])

        normalized.append(p)

    if not normalized:
        # 物件が1つも認識できなかった場合のフォールバック
        normalized.append({
            "property_name": "", "address": "",
            "items": [{"name": r, "amount": 0} for r in REQUIRED_ITEMS],
            "total": 0,
        })

    return {"properties": normalized}


# ---------------------------------------------------------------------------
# 金額の正規化 (int または "別途" 等の文字列を許容)
# ---------------------------------------------------------------------------
def _coerce_amount(raw):
    """raw が数値化できれば int を返し、『別途』等の文字列なら str のまま返す"""
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return 0
        # カンマ・¥・円・空白を除去して数値化を試みる
        cleaned = re.sub(r"[,¥￥円\s]", "", s)
        try:
            return int(float(cleaned))
        except ValueError:
            # 『別途』『応相談』などはそのまま返す
            return s
    return 0


def _amount_to_int(v) -> int:
    """合計計算用: 数値にできる場合のみ int、不可なら 0"""
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(re.sub(r"[,¥￥円\s]", "", v)))
        except ValueError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# PDF 生成
# ---------------------------------------------------------------------------
def _wrap_text(text: str, font_name: str, font_size: float, max_width: float):
    """PDF 内のテキストを max_width 以内で改行する (日本語も1文字ずつ計測)"""
    out = []
    for para in (text or "").split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        for ch in para:
            test = cur + ch
            if stringWidth(test, font_name, font_size) > max_width:
                if cur:
                    out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
    return out


def _fmt_yen(v) -> str:
    """金額表示: 数値なら ¥X,XXX、文字列なら『別途』等をそのまま返す"""
    if isinstance(v, (int, float)):
        try:
            return f"¥{int(v):,}"
        except (TypeError, ValueError):
            return "¥0"
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "¥0"
        try:
            return f"¥{int(float(re.sub(r'[,¥￥円\s]', '', s))):,}"
        except ValueError:
            return s  # 別途・応相談 等はそのまま
    return "¥0"


def generate_estimate_pdf(data: dict) -> bytes:
    """見積書 PDF をバイト列で返す"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ---- ヘッダー帯 (ネイビー) ----
    c.setFillColor(COLOR_NAVY)
    c.rect(0, H - 18 * mm, W, 18 * mm, stroke=0, fill=1)

    # ゴールド細線
    c.setFillColor(COLOR_GOLD)
    c.rect(0, H - 20 * mm, W, 0.8 * mm, stroke=0, fill=1)

    # タイトル
    c.setFillColor(COLOR_GOLD)
    c.setFont(FONT_GOTHIC, 22)
    c.drawString(20 * mm, H - 12 * mm, "御  見  積  書")

    # 右: ブランド表記
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(FONT_GOTHIC, 9)
    c.drawRightString(W - 20 * mm, H - 9 * mm, "ESTIMATE  /  INITIAL COST")
    c.setFont(FONT_GOTHIC, 8)
    c.drawRightString(W - 20 * mm, H - 14 * mm, "N-PRIME Co., Ltd.")

    # ---- 発行情報 ----
    issue_date = datetime.now().strftime("%Y年%m月%d日")
    quote_num = datetime.now().strftime("NP-%Y%m%d-%H%M")
    y = H - 30 * mm
    c.setFillColor(COLOR_GRAY_DARK)
    c.setFont(FONT_GOTHIC, 9)
    c.drawRightString(W - 20 * mm, y, f"見積番号 : {quote_num}")
    c.drawRightString(W - 20 * mm, y - 5 * mm, f"発行日   : {issue_date}")

    # ---- 会社情報 (右) ----
    cy = H - 50 * mm
    c.setFont(FONT_GOTHIC, 13)
    c.setFillColor(COLOR_NAVY)
    c.drawRightString(W - 20 * mm, cy, COMPANY_NAME)

    # ゴールドのアンダーライン
    c.setFillColor(COLOR_GOLD)
    c.rect(W - 60 * mm, cy - 1.8 * mm, 40 * mm, 0.4 * mm, stroke=0, fill=1)

    c.setFont(FONT_GOTHIC, 8.5)
    c.setFillColor(COLOR_GRAY_DARK)
    c.drawRightString(W - 20 * mm, cy - 6 * mm, COMPANY_ADDRESS_1)
    c.drawRightString(W - 20 * mm, cy - 10 * mm, COMPANY_ADDRESS_2)
    c.drawRightString(W - 20 * mm, cy - 14 * mm, f"TEL  {COMPANY_TEL}")
    c.drawRightString(W - 20 * mm, cy - 18 * mm, f"MAIL  {COMPANY_MAIL}")

    # ---- 挨拶文 ----
    gy = H - 80 * mm
    c.setFont(FONT_GOTHIC, 10.5)
    c.setFillColor(COLOR_GRAY_DARK)
    c.drawString(20 * mm, gy, "下記の通りお見積り申し上げます。ご査収のほど宜しくお願い申し上げます。")

    # ---- 物件情報ボックス ----
    # 入居日の整形
    occ_raw = (data.get("occupancy_date") or "").strip()
    occ_str = ""
    if occ_raw:
        try:
            _dt = datetime.strptime(occ_raw, "%Y-%m-%d")
            occ_str = _dt.strftime("%Y年%m月%d日")
        except ValueError:
            occ_str = occ_raw

    # 入居日がある場合は3行 (高さ 27mm)、ない場合は2行 (20mm)
    has_occ = bool(occ_str)
    box_h = 27 * mm if has_occ else 20 * mm

    py = H - 95 * mm
    c.setFillColor(COLOR_GRAY_BG)
    c.rect(20 * mm, py - box_h, W - 40 * mm, box_h, stroke=0, fill=1)

    # 左のゴールド帯
    c.setFillColor(COLOR_GOLD)
    c.rect(20 * mm, py - box_h, 1.2 * mm, box_h, stroke=0, fill=1)

    c.setFont(FONT_GOTHIC, 9)
    c.setFillColor(COLOR_NAVY)
    c.drawString(26 * mm, py - 6 * mm, "PROPERTY")
    c.setFont(FONT_GOTHIC, 11)
    c.setFillColor(COLOR_GRAY_DARK)
    c.drawString(26 * mm, py - 12 * mm, f"物件名  {data.get('property_name', '') or '—'}")
    c.drawString(26 * mm, py - 17.5 * mm, f"所在地  {data.get('address', '') or '—'}")
    if has_occ:
        c.drawString(26 * mm, py - 23 * mm, f"入居日  {occ_str}")

    # ---- 項目表 ----
    items = data.get("items", [])
    # 物件情報ボックスの下に 8mm 余白
    table_top = py - box_h - 8 * mm

    # ヘッダー行
    c.setFillColor(COLOR_NAVY)
    c.rect(20 * mm, table_top - 8 * mm, W - 40 * mm, 8 * mm, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(FONT_GOTHIC, 10)
    c.drawString(26 * mm, table_top - 5.5 * mm, "項　　目")
    c.drawRightString(W - 26 * mm, table_top - 5.5 * mm, "金　　額")

    # データ行
    row_h = 7.5 * mm
    y_cur = table_top - 8 * mm
    computed_total = 0

    for idx, it in enumerate(items):
        name = it.get("name", "")
        raw_amount = it.get("amount", 0)
        amount = _amount_to_int(raw_amount)  # 合計計算用 (別途 等は 0)
        computed_total += amount

        y_cur -= row_h

        # 改ページ処理
        if y_cur < 50 * mm:
            c.showPage()
            y_cur = H - 30 * mm
            # 続き行のヘッダーだけ簡易再描画
            c.setFillColor(COLOR_NAVY)
            c.rect(20 * mm, y_cur, W - 40 * mm, 8 * mm, stroke=0, fill=1)
            c.setFillColor(HexColor("#ffffff"))
            c.setFont(FONT_GOTHIC, 10)
            c.drawString(26 * mm, y_cur + 2.5 * mm, "項　　目 (続き)")
            c.drawRightString(W - 26 * mm, y_cur + 2.5 * mm, "金　　額")
            y_cur -= row_h

        # ゼブラ背景
        if idx % 2 == 1:
            c.setFillColor(HexColor("#fafaf7"))
            c.rect(20 * mm, y_cur, W - 40 * mm, row_h, stroke=0, fill=1)

        # 下罫線 (うすい灰)
        c.setStrokeColor(COLOR_GRAY_LIGHT)
        c.setLineWidth(0.3)
        c.line(20 * mm, y_cur, W - 20 * mm, y_cur)

        c.setFillColor(COLOR_GRAY_DARK)
        c.setFont(FONT_GOTHIC, 10.5)
        c.drawString(26 * mm, y_cur + 2.5 * mm, name)
        c.setFont(FONT_GOTHIC, 10.5)
        # 数値なら ¥X,XXX、『別途』等の文字列ならそのまま印字
        c.drawRightString(W - 26 * mm, y_cur + 2.5 * mm, _fmt_yen(raw_amount))

    # 表外枠 (ネイビー)
    c.setStrokeColor(COLOR_NAVY)
    c.setLineWidth(0.8)
    c.rect(20 * mm, y_cur, W - 40 * mm, (table_top - y_cur), stroke=1, fill=0)

    # ---- 合計 ----
    # 優先: フォーム側で送られた total, 空なら items の合計 (別途等の文字列は除外)
    total = _amount_to_int(data.get("total", 0))
    if total <= 0:
        total = computed_total

    total_h = 14 * mm
    total_top = y_cur - 4 * mm
    c.setFillColor(COLOR_NAVY)
    c.rect(20 * mm, total_top - total_h, W - 40 * mm, total_h, stroke=0, fill=1)

    # ゴールド細線
    c.setFillColor(COLOR_GOLD)
    c.rect(20 * mm, total_top - total_h + total_h - 0.5 * mm,
           W - 40 * mm, 0.5 * mm, stroke=0, fill=1)

    c.setFillColor(HexColor("#ffffff"))
    c.setFont(FONT_GOTHIC, 12)
    c.drawString(26 * mm, total_top - total_h + 4.5 * mm, "合　計　金　額  (税込)")
    c.setFillColor(COLOR_GOLD)
    # 金額はすべて FONT_GOTHIC で統一 (項目表と同じ書体)
    c.setFont(FONT_GOTHIC, 17)
    c.drawRightString(W - 26 * mm, total_top - total_h + 4 * mm, _fmt_yen(total))

    # ---- 備考 ----
    notes = (data.get("notes") or "").strip()
    if notes:
        notes_title_y = total_top - total_h - 8 * mm
        footer_reserved_y = 25 * mm

        # スペースが狭すぎる場合は次ページへ (無音で省略しない)
        if notes_title_y - footer_reserved_y < 22 * mm:
            c.showPage()
            notes_title_y = H - 25 * mm  # 新ページの上部に配置

        # ラベル
        c.setFillColor(COLOR_NAVY)
        c.setFont(FONT_GOTHIC, 9)
        c.drawString(20 * mm, notes_title_y, "■ 備　考")
        c.setFillColor(COLOR_GOLD)
        c.rect(20 * mm, notes_title_y - 1.8 * mm, 18 * mm, 0.4 * mm, stroke=0, fill=1)

        box_top    = notes_title_y - 4 * mm
        box_bottom = footer_reserved_y
        # 枠
        c.setStrokeColor(COLOR_GRAY_LIGHT)
        c.setLineWidth(0.5)
        c.rect(20 * mm, box_bottom, W - 40 * mm, box_top - box_bottom,
               stroke=1, fill=0)
        # 左のゴールド縦帯
        c.setFillColor(COLOR_GOLD)
        c.rect(20 * mm, box_bottom, 0.8 * mm, box_top - box_bottom,
               stroke=0, fill=1)

        # テキスト (自動改行)
        text_font = FONT_GOTHIC
        text_size = 10.0
        line_h    = 4.8 * mm
        max_w     = W - 52 * mm
        wrapped = _wrap_text(notes, text_font, text_size, max_w)

        c.setFillColor(COLOR_GRAY_DARK)
        c.setFont(text_font, text_size)
        y = box_top - 5 * mm
        for line in wrapped:
            if y < box_bottom + 3 * mm:
                c.setFillColor(HexColor("#888888"))
                c.drawRightString(W - 24 * mm, box_bottom + 2 * mm, "…以下省略")
                break
            c.drawString(25 * mm, y, line)
            y -= line_h

    # ---- フッター ----
    fy = 18 * mm
    c.setFillColor(COLOR_GOLD)
    c.rect(20 * mm, fy + 3 * mm, W - 40 * mm, 0.3 * mm, stroke=0, fill=1)
    c.setFillColor(COLOR_GRAY_DARK)
    c.setFont(FONT_GOTHIC, 8)
    c.drawString(20 * mm, fy - 2 * mm,
                 "※ 本見積は発行日より30日間有効です。金額・条件は予告なく変更となる場合がございます。")
    # 全体をゴシック体 (HeiseiKakuGo-W5) で統一
    c.setFont(FONT_GOTHIC, 9)
    c.setFillColor(COLOR_NAVY)
    c.drawRightString(W - 20 * mm, fy - 2 * mm, COMPANY_NAME)

    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ルーティング
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>初期費用見積書 作成システム | N-PRIME</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;600;700&family=Noto+Sans+JP:wght@300;400;500;700&family=Cormorant+Garamond:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --navy:#1a2a3a;
    --navy-dark:#0f1a26;
    --gold:#c9a961;
    --gold-soft:#d9bf7a;
    --ivory:#f7f5f0;
    --ink:#2a2a2a;
    --line:#dcd7cb;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    font-family:"Noto Sans JP",system-ui,sans-serif;
    color:var(--ink);
    background:
      radial-gradient(1200px 600px at 80% -10%, rgba(201,169,97,.10), transparent 60%),
      radial-gradient(900px 500px at -10% 110%, rgba(26,42,58,.09), transparent 60%),
      var(--ivory);
    min-height:100vh;
    line-height:1.6;
  }
  .topbar{
    background:var(--navy);
    color:#fff;
    padding:14px 32px;
    display:flex;align-items:center;justify-content:space-between;
    border-bottom:2px solid var(--gold);
  }
  .brand{
    font-family:"Cormorant Garamond",serif;
    font-size:22px;letter-spacing:.12em;
    color:var(--gold);
  }
  .brand small{
    font-family:"Noto Sans JP",sans-serif;
    font-size:10px;color:#c9c4b8;letter-spacing:.2em;margin-left:10px;
    font-weight:400;
  }
  .tagline{font-size:11px;color:#c9c4b8;letter-spacing:.2em}

  main{max-width:980px;margin:48px auto;padding:0 24px}

  h1.title{
    font-family:"Noto Sans JP",sans-serif;
    font-weight:700;
    font-size:30px;
    letter-spacing:.08em;
    color:var(--navy);
    margin:0 0 6px;
  }
  h1.title .en{
    display:block;
    font-family:"Cormorant Garamond",serif;
    font-weight:500;
    font-size:13px;
    letter-spacing:.3em;
    color:var(--gold);
    margin-bottom:8px;
  }
  .lead{color:#555;margin:6px 0 28px;font-size:14px}

  .card{
    background:#fff;
    border:1px solid var(--line);
    border-radius:2px;
    box-shadow:0 20px 40px -24px rgba(26,42,58,.25);
    padding:28px 32px;
    position:relative;
  }
  .card::before{
    content:"";position:absolute;top:0;left:0;width:3px;height:100%;
    background:linear-gradient(180deg,var(--gold),var(--gold-soft));
  }

  .section-label{
    font-family:"Cormorant Garamond",serif;
    font-size:12px;letter-spacing:.3em;color:var(--gold);
    margin-bottom:6px;
  }
  .section-title{
    font-family:"Noto Sans JP",sans-serif;
    font-weight:600;font-size:18px;color:var(--navy);
    margin:0 0 18px;
  }

  .drop{
    display:block;
    border:1.5px dashed #bcb59f;
    border-radius:3px;
    padding:48px 24px;
    text-align:center;
    transition:.2s;
    background:#fcfbf7;
    cursor:pointer;
    position:relative;
  }
  .drop.on{border-color:var(--gold);background:#fbf5e8}
  .drop p{margin:6px 0;color:#666}
  .drop .big{
    font-family:"Noto Sans JP",sans-serif;
    font-size:15px;color:var(--navy);margin-bottom:6px;
  }
  .drop input{display:none}
  .file-chip{
    display:inline-block;padding:6px 14px;margin-top:10px;
    background:var(--navy);color:#fff;border-radius:2px;
    font-size:13px;letter-spacing:.05em;
  }

  .btn{
    display:inline-flex;align-items:center;gap:10px;
    padding:13px 32px;
    background:var(--navy);color:#fff;
    border:none;cursor:pointer;
    font-family:"Noto Sans JP",sans-serif;
    font-size:14px;letter-spacing:.15em;
    transition:.2s;
    border-radius:1px;
  }
  .btn:hover{background:var(--navy-dark);box-shadow:0 6px 18px -8px rgba(0,0,0,.4)}
  .btn:disabled{background:#aaa;cursor:not-allowed;box-shadow:none}
  .btn.gold{background:var(--gold);color:var(--navy-dark)}
  .btn.gold:hover{background:var(--gold-soft)}
  .btn.ghost{background:transparent;color:var(--navy);border:1px solid var(--navy)}
  .btn.ghost:hover{background:var(--navy);color:#fff}

  .actions{margin-top:22px;text-align:center}

  /* --- 編集画面 --- */
  #edit{display:none}
  .meta-grid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:18px;
    margin-bottom:22px;
  }
  .field label{
    display:block;
    font-family:"Cormorant Garamond",serif;
    font-size:11px;letter-spacing:.25em;color:var(--gold);
    margin-bottom:4px;
  }
  .field input{
    width:100%;
    padding:10px 12px;
    border:1px solid var(--line);
    border-bottom:2px solid var(--navy);
    background:#fcfbf7;
    font-size:14px;font-family:inherit;
    border-radius:1px;
    outline:none;
    transition:.2s;
  }
  .field input:focus{background:#fff;border-bottom-color:var(--gold)}
  .field textarea{
    width:100%;
    padding:12px 14px;
    border:1px solid var(--line);
    border-bottom:2px solid var(--navy);
    background:#fcfbf7;
    font-size:13px;font-family:inherit;line-height:1.7;
    border-radius:1px;outline:none;resize:vertical;
    transition:.2s;
  }
  .field textarea:focus{background:#fff;border-bottom-color:var(--gold)}
  .hint{font-size:11px;color:#888;line-height:1.5;padding-top:8px}

  /* --- 家賃・管理費 ブロック --- */
  .rent-block{
    margin-top:18px;
    padding:20px 22px;
    background:#fcfbf7;
    border-left:3px solid var(--gold);
    border-radius:2px;
  }
  .rent-title{
    font-family:"Noto Sans JP",sans-serif;
    font-weight:600;font-size:14px;
    color:var(--navy);letter-spacing:.1em;
    margin:4px 0 14px;
  }
  .rent-inputs{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:16px;
    margin-bottom:14px;
  }
  .breakdown{
    background:#fff;
    border:1px solid var(--line);
    padding:8px 14px;
  }
  .bd-row{
    display:flex;justify-content:space-between;align-items:center;
    padding:7px 0;
    border-bottom:1px dashed #ebe6d7;
    font-size:13px;
  }
  .bd-row:last-child{border-bottom:none}
  .bd-name{color:var(--navy);font-family:"Noto Sans JP",sans-serif}
  .bd-amt{font-family:"Noto Sans JP",sans-serif;color:var(--ink);font-weight:500}
  .bd-empty{color:#999;font-size:12px;padding:10px 0;text-align:center}
  .subhead{
    margin-top:26px;
    padding-bottom:6px;
    border-bottom:1px solid var(--line);
  }
  .subhead .section-label{margin-bottom:2px}
  .subhead h3{
    font-family:"Noto Sans JP",sans-serif;
    font-weight:600;font-size:14px;
    color:var(--navy);letter-spacing:.1em;
    margin:0 0 8px;
  }

  /* --- 物件タブ (複数物件の時のみ表示) --- */
  .prop-tabs{
    display:none;
    flex-wrap:wrap;gap:4px;
    margin-bottom:22px;padding:5px;
    background:#f2ede0;
    border:1px solid var(--line);
    border-radius:2px;
  }
  .prop-tabs.on{display:flex}
  .prop-tab{
    background:transparent;border:none;
    padding:8px 16px;cursor:pointer;
    font-family:"Noto Sans JP",sans-serif;font-size:13px;
    color:#555;letter-spacing:.05em;
    border-radius:1px;
    transition:.15s;
    max-width:260px;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  }
  .prop-tab:hover:not(.active){background:#ebe4d2;color:var(--navy)}
  .prop-tab.active{
    background:var(--navy);color:var(--gold);
    font-weight:500;
  }
  .prop-count{
    display:inline-block;
    padding:3px 10px;margin-left:10px;
    background:var(--gold);color:var(--navy-dark);
    font-family:"Cormorant Garamond",serif;
    font-size:11px;letter-spacing:.2em;
    border-radius:1px;
    vertical-align:middle;
  }

  table.items{
    width:100%;border-collapse:collapse;margin-top:8px;
    font-size:14px;
  }
  table.items thead th{
    background:var(--navy);color:#fff;
    text-align:left;padding:10px 12px;
    font-family:"Noto Sans JP",sans-serif;
    font-weight:500;letter-spacing:.1em;font-size:12px;
  }
  table.items thead th.right{text-align:right}
  table.items thead th.center{text-align:center;width:60px}
  table.items tbody tr{border-bottom:1px solid var(--line)}
  table.items tbody tr:nth-child(even){background:#fafaf5}
  table.items td{padding:6px 8px}
  table.items input.name{
    width:100%;border:none;background:transparent;
    padding:8px 6px;font-size:14px;font-family:inherit;outline:none;
    border-bottom:1px solid transparent;
  }
  table.items input.name:focus{border-bottom-color:var(--gold);background:#fff}
  table.items input.amount{
    width:100%;
    text-align:right;border:none;background:transparent;
    padding:8px 6px;font-size:14px;font-family:"Noto Sans JP",sans-serif;outline:none;
    border-bottom:1px solid transparent;
  }
  table.items input.amount:focus{border-bottom-color:var(--gold);background:#fff}
  table.items td.del{text-align:center}
  .del-btn{
    background:transparent;border:1px solid #c88;color:#b44;
    width:28px;height:28px;border-radius:50%;
    cursor:pointer;font-size:14px;line-height:1;
    transition:.2s;
  }
  .del-btn:hover{background:#b44;color:#fff}

  .add-row{
    margin-top:12px;
    padding:8px 16px;
    background:transparent;
    border:1px dashed var(--navy);color:var(--navy);
    cursor:pointer;font-size:13px;
    letter-spacing:.1em;
    transition:.2s;
  }
  .add-row:hover{background:var(--navy);color:#fff;border-style:solid}

  .total-box{
    margin-top:22px;
    background:var(--navy);color:#fff;
    padding:18px 24px;
    display:flex;justify-content:space-between;align-items:center;
    border-top:3px solid var(--gold);
  }
  .total-box .lbl{
    font-family:"Noto Sans JP",sans-serif;
    font-size:15px;letter-spacing:.2em;
  }
  .total-box .val{
    font-family:"Cormorant Garamond",serif;
    font-size:28px;color:var(--gold);letter-spacing:.05em;
  }

  .two-btn{margin-top:26px;display:flex;gap:14px;justify-content:flex-end}

  /* --- ローディング --- */
  #loading{display:none;margin-top:18px;text-align:center;color:#555}
  .spinner{
    display:inline-block;width:18px;height:18px;
    border:2px solid #ddd;border-top-color:var(--gold);border-radius:50%;
    animation:spin 1s linear infinite;vertical-align:middle;margin-right:8px;
  }
  @keyframes spin{to{transform:rotate(360deg)}}

  .err{
    display:none;
    margin-top:14px;padding:10px 14px;
    background:#fff0f0;border-left:3px solid #c55;color:#922;font-size:13px;
  }

  footer{
    text-align:center;color:#999;font-size:11px;
    padding:28px 16px;letter-spacing:.15em;
  }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">N · PRIME<small>株式会社エヌプライム</small></div>
  <div class="tagline">INITIAL COST ESTIMATE</div>
</div>

<main>
  <h1 class="title"><span class="en">ESTIMATE  /  INITIAL COST</span>初期費用 見積書作成</h1>
  <p class="lead">マイソク PDF をアップロードすると、AI が初期費用項目を自動抽出します。内容を確認・編集し、プロ仕様の見積書 PDF を出力できます。</p>

  <!-- ========== アップロード ========== -->
  <section id="upload" class="card">
    <div class="section-label">STEP 01</div>
    <h2 class="section-title">マイソク PDF をアップロード</h2>

    <label id="drop" class="drop">
      <div class="big">📄  PDF ファイルを選択  /  ここへドラッグ&ドロップ</div>
      <p>対応形式: PDF  /  最大 20MB</p>
      <div id="chip" class="file-chip" style="display:none"></div>
      <input type="file" id="file" accept="application/pdf">
    </label>

    <div class="actions">
      <button id="btn-extract" class="btn" disabled>
        AI で項目を抽出する  →
      </button>
    </div>
    <div id="loading"><span class="spinner"></span>Gemini が PDF を解析中... (20〜60秒)</div>
    <div id="err-up" class="err"></div>
  </section>

  <!-- ========== 編集 ========== -->
  <section id="edit" class="card" style="margin-top:28px">
    <div class="section-label">STEP 02</div>
    <h2 class="section-title">抽出結果の確認・編集<span id="prop-count" class="prop-count" style="display:none"></span></h2>

    <!-- 物件タブ (複数物件の場合のみ表示) -->
    <div id="prop-tabs" class="prop-tabs"></div>

    <div class="meta-grid">
      <div class="field">
        <label>PROPERTY NAME / 物件名</label>
        <input id="f-property" type="text" placeholder="物件名">
      </div>
      <div class="field">
        <label>ADDRESS / 所在地</label>
        <input id="f-address" type="text" placeholder="所在地">
      </div>
      <div class="field">
        <label>MOVE-IN DATE / 入居日</label>
        <input id="f-occupancy" type="date">
      </div>
      <div class="field">
        <label>&nbsp;</label>
        <div class="hint">※ 入居日から月末までの日割り家賃・管理費 ＋ 翌月分を自動計算します</div>
      </div>
    </div>

    <!-- 家賃・管理費ブロック -->
    <div class="rent-block">
      <div class="section-label">RENT &amp; MAINTENANCE</div>
      <h3 class="rent-title">家賃 ・ 管理費 （入居日を基に日割り自動計算）</h3>
      <div class="rent-inputs">
        <div class="field">
          <label>月額家賃 (円)</label>
          <input id="f-monthly-rent" type="number" step="1" value="0">
        </div>
        <div class="field">
          <label>月額管理費 (円)</label>
          <input id="f-monthly-mgmt" type="number" step="1" value="0">
        </div>
      </div>
      <div class="breakdown" id="breakdown"></div>
    </div>

    <!-- その他項目 -->
    <div class="subhead">
      <div class="section-label">OTHER COSTS</div>
      <h3>その他 初期費用項目</h3>
      <div class="hint" style="padding-top:0">金額欄には数字のほか「別途」「応相談」等の文字列も入力可能です。文字列は合計金額の計算から除外されます。</div>
    </div>

    <table class="items">
      <thead>
        <tr>
          <th style="width:55%">項目名</th>
          <th class="right" style="width:35%">金額 (円)</th>
          <th class="center">削除</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>

    <button type="button" class="add-row" id="btn-add">＋ 項目を追加</button>

    <!-- 備考 -->
    <div class="subhead" style="margin-top:28px">
      <div class="section-label">REMARKS</div>
      <h3>備　考</h3>
      <div class="hint" style="padding-top:0">自由記入欄。ここに書いた内容は見積書PDFの末尾にそのまま印字されます（改行も反映）</div>
    </div>
    <div class="field" style="margin-top:10px">
      <textarea id="f-notes" rows="4" placeholder="例:&#10;・更新料なし&#10;・保証会社必須（初回 家賃1ヶ月分、月額 2,200円）&#10;・駐車場別途 月額15,000円（2台まで可）&#10;・退去時の室内クリーニング費 45,000円（税別）を別途申し受けます"></textarea>
    </div>

    <div class="total-box">
      <div class="lbl">合計金額 (税込)</div>
      <div class="val" id="total-display">¥0</div>
    </div>

    <div class="two-btn">
      <button class="btn ghost" id="btn-back">← やり直す</button>
      <button class="btn" id="btn-zip" style="display:none">全物件まとめて ZIP ダウンロード ⭳</button>
      <button class="btn gold" id="btn-pdf">この物件の見積書 PDF  ▼</button>
    </div>
    <div id="err-ed" class="err"></div>
  </section>
</main>

<footer>© N-PRIME Co., Ltd. &nbsp;·&nbsp; {{ year }} &nbsp;·&nbsp; <span style="color:#bbb;font-family:'Cormorant Garamond',serif">v{{ version }}</span></footer>

<script>
const $ = s => document.querySelector(s);
const drop = $("#drop"), fileIn = $("#file"), chip = $("#chip");
const btnExtract = $("#btn-extract");
const loadBox = $("#loading");
const errUp = $("#err-up"), errEd = $("#err-ed");
const up = $("#upload"), ed = $("#edit");

let selectedFile = null;

/* --- Drag & Drop --- */
/* ページ全体で既定動作 (ブラウザがPDFを開く) をブロック */
["dragover","drop"].forEach(e =>
  document.addEventListener(e, ev => ev.preventDefault(), false)
);

/* ドロップはドロップゾーン内のみ受け付ける */
["dragenter","dragover"].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault();
  ev.stopPropagation();
  drop.classList.add("on");
}));
drop.addEventListener("dragleave", ev => {
  ev.preventDefault();
  ev.stopPropagation();
  drop.classList.remove("on");
});
drop.addEventListener("drop", ev => {
  ev.preventDefault();
  ev.stopPropagation();
  drop.classList.remove("on");
  const f = ev.dataTransfer?.files?.[0];
  if(f) setFile(f);
});
fileIn.addEventListener("change", e => {
  const f = e.target.files?.[0];
  if(f) setFile(f);
});
function setFile(f){
  if(f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")){
    showErr(errUp, "PDF ファイルを選択してください");
    return;
  }
  selectedFile = f;
  chip.textContent = "📎 " + f.name + "  (" + (f.size/1024/1024).toFixed(2) + "MB)";
  chip.style.display = "inline-block";
  btnExtract.disabled = false;
  hideErr(errUp);
}

/* --- 抽出 --- */
btnExtract.addEventListener("click", async () => {
  if(!selectedFile) return;
  btnExtract.disabled = true;
  loadBox.style.display = "block";
  hideErr(errUp);

  const fd = new FormData();
  fd.append("file", selectedFile);

  try{
    const res = await fetch("/api/extract", {method:"POST", body:fd});
    const data = await res.json();
    if(!res.ok){ throw new Error(data.error || "抽出に失敗しました"); }

    // data.properties: [{property_name, address, items, total}, ...]
    initProperties(data.properties || []);
    up.style.display = "none";
    ed.style.display = "block";
    window.scrollTo({top:0, behavior:"smooth"});
  }catch(e){
    showErr(errUp, e.message);
    btnExtract.disabled = false;
  }finally{
    loadBox.style.display = "none";
  }
});

/* --- 編集画面レンダリング --- */
const occEl = () => $("#f-occupancy");
const rentEl = () => $("#f-monthly-rent");
const mgmtEl = () => $("#f-monthly-mgmt");
const bdEl = () => $("#breakdown");
const tabsEl = () => $("#prop-tabs");

/* ----- 複数物件の状態管理 ----- */
let properties = [];   // [{property_name, address, occupancy_date, monthly_rent, monthly_mgmt, other_items}]
let currentIdx = 0;

function defaultOccDate(){
  const d = new Date();
  d.setMonth(d.getMonth() + 1);
  d.setDate(1);
  return d.toISOString().slice(0, 10);
}

function splitItems(items){
  let mr = 0, mm = 0;
  const others = [];
  (items || []).forEach(it => {
    const nm = (it.name || "").trim();
    if(nm === "家賃"){ mr = Number(it.amount) || 0; }
    else if(nm === "管理費"){ mm = Number(it.amount) || 0; }
    else { others.push(it); }
  });
  return {mr, mm, others};
}

function initProperties(arr){
  properties = arr.map(p => {
    const sp = splitItems(p.items);
    return {
      property_name: p.property_name || "",
      address: p.address || "",
      occupancy_date: defaultOccDate(),
      monthly_rent: sp.mr,
      monthly_mgmt: sp.mm,
      other_items: sp.others,
      notes: "",
    };
  });
  if(properties.length === 0){
    properties.push({
      property_name:"", address:"", occupancy_date:defaultOccDate(),
      monthly_rent:0, monthly_mgmt:0, other_items:[], notes:"",
    });
  }
  currentIdx = 0;
  renderTabs();
  renderCurrentProperty();
}

/* 現在のフォーム内容を properties[currentIdx] に書き戻す */
function saveCurrentForm(){
  const p = properties[currentIdx];
  if(!p) return;
  p.property_name  = $("#f-property").value.trim();
  p.address        = $("#f-address").value.trim();
  p.occupancy_date = occEl().value;
  p.monthly_rent   = Number(rentEl().value) || 0;
  p.monthly_mgmt   = Number(mgmtEl().value) || 0;
  p.other_items    = [];
  document.querySelectorAll("#tbody tr").forEach(tr => {
    const n = tr.querySelector(".name").value.trim();
    const av = tr.querySelector(".amount").value;
    if(n){
      const pa = parseAmount(av);
      // 数値なら number、『別途』等なら string で保存
      p.other_items.push({name:n, amount: pa.text !== null ? pa.text : pa.num});
    }
  });
  p.notes = $("#f-notes").value;
}

/* properties[currentIdx] をフォームに流し込む */
function renderCurrentProperty(){
  const p = properties[currentIdx];
  if(!p) return;
  $("#f-property").value = p.property_name;
  $("#f-address").value  = p.address;
  occEl().value  = p.occupancy_date;
  rentEl().value = p.monthly_rent;
  mgmtEl().value = p.monthly_mgmt;

  const tb = $("#tbody"); tb.innerHTML = "";
  p.other_items.forEach(it => addRow(it.name, it.amount));

  $("#f-notes").value = p.notes || "";

  renderBreakdown();
  recalcTotal();
}

/* タブ描画 */
function renderTabs(){
  const container = tabsEl();
  const countEl = $("#prop-count");
  const zipBtn = $("#btn-zip");

  if(properties.length <= 1){
    container.classList.remove("on");
    container.innerHTML = "";
    countEl.style.display = "none";
    zipBtn.style.display = "none";
    return;
  }

  container.classList.add("on");
  countEl.style.display = "inline-block";
  countEl.textContent = `${properties.length} 物件`;
  zipBtn.style.display = "inline-flex";

  container.innerHTML = properties.map((p,i) => {
    const label = (p.property_name || `物件 ${i+1}`);
    return `<button class="prop-tab ${i===currentIdx?'active':''}" data-idx="${i}" title="${escapeHtml(label)}">
      ${i+1}. ${escapeHtml(label)}
    </button>`;
  }).join("");

  container.querySelectorAll(".prop-tab").forEach(btn => {
    btn.addEventListener("click", ev => {
      saveCurrentForm();
      currentIdx = Number(ev.currentTarget.dataset.idx);
      renderTabs();
      renderCurrentProperty();
      window.scrollTo({top:0, behavior:"smooth"});
    });
  });
}

/* 物件名が編集されたら該当タブのラベルも即反映 */
document.addEventListener("input", ev => {
  if(ev.target && ev.target.id === "f-property" && properties.length > 1){
    const tab = document.querySelector(`.prop-tab[data-idx="${currentIdx}"]`);
    if(tab){
      const label = ev.target.value || `物件 ${currentIdx+1}`;
      tab.textContent = `${currentIdx+1}. ${label}`;
      tab.title = label;
    }
  }
});
/* amount 表示: 数値なら そのまま数字、文字列(別途等)なら文字列そのまま */
function amountToInput(v){
  if(v === null || v === undefined || v === "") return "";
  if(typeof v === "number") return String(v);
  const s = String(v).trim();
  // 数値化できればそれを、できなければ文字列のまま
  const cleaned = s.replace(/[,¥￥円\s]/g, "");
  if(cleaned !== "" && !isNaN(Number(cleaned))) return cleaned;
  return s;
}
/* 入力値を解析 → {num: 数値(計算用), text: 文字列ならそれ|null} */
function parseAmount(s){
  const v = String(s||"").trim();
  if(!v) return {num:0, text:null, raw:0};
  const cleaned = v.replace(/[,¥￥円\s]/g, "");
  if(cleaned !== "" && !isNaN(Number(cleaned))){
    const n = Number(cleaned);
    return {num:n, text:null, raw:n};
  }
  return {num:0, text:v, raw:v};  // 『別途』等
}

function addRow(name="", amount=0){
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="name" type="text" value="${escapeHtml(name)}"></td>
    <td><input class="amount" type="text" inputmode="numeric" value="${escapeHtml(amountToInput(amount))}" placeholder="金額 または 別途"></td>
    <td class="del"><button type="button" class="del-btn" title="削除">✕</button></td>
  `;
  tr.querySelector(".amount").addEventListener("input", recalcTotal);
  tr.querySelector(".del-btn").addEventListener("click", () => { tr.remove(); recalcTotal(); });
  $("#tbody").appendChild(tr);
}

/* --- 日割り計算 --- */
function calcBreakdown(){
  const ds = occEl().value;
  const r  = Number(rentEl().value) || 0;
  const m  = Number(mgmtEl().value) || 0;
  if(!ds) return null;
  const d = new Date(ds + "T00:00:00");
  if(isNaN(d.getTime())) return null;
  const y = d.getFullYear(), mo = d.getMonth(), dd = d.getDate();
  const lastDay = new Date(y, mo + 1, 0).getDate();

  // 1日入居: 当月分のみ (日割り・翌月分なし)
  if(dd === 1){
    return {
      rows: [
        {name: `家賃（${mo+1}月分）`,   amount: r},
        {name: `管理費（${mo+1}月分）`, amount: m},
      ],
      dateLabel: `${y}年${mo+1}月${dd}日`,
    };
  }

  // 2日以降: 日割り + 翌月分
  const days = lastDay - dd + 1;
  const nm = (mo === 11) ? 0 : mo + 1;
  const proRent = Math.round(r * days / lastDay);
  const proMgmt = Math.round(m * days / lastDay);
  return {
    rows: [
      {name: `家賃（${mo+1}月${dd}日〜${mo+1}月${lastDay}日 日割り ${days}日分）`, amount: proRent},
      {name: `家賃（${nm+1}月分）`, amount: r},
      {name: `管理費（${mo+1}月${dd}日〜${mo+1}月${lastDay}日 日割り ${days}日分）`, amount: proMgmt},
      {name: `管理費（${nm+1}月分）`, amount: m},
    ],
    dateLabel: `${y}年${mo+1}月${dd}日`,
  };
}
function renderBreakdown(){
  const b = calcBreakdown();
  if(!b){
    bdEl().innerHTML = '<div class="bd-empty">入居日を入力すると日割り計算結果がここに表示されます</div>';
    return;
  }
  bdEl().innerHTML = b.rows.map(r => `
    <div class="bd-row">
      <div class="bd-name">${escapeHtml(r.name)}</div>
      <div class="bd-amt">¥${(r.amount||0).toLocaleString()}</div>
    </div>`).join("");
}

function recalcTotal(){
  let sum = 0;
  const b = calcBreakdown();
  if(b) b.rows.forEach(r => sum += (r.amount || 0));
  document.querySelectorAll("#tbody input.amount").forEach(i => {
    sum += parseAmount(i.value).num;  // 『別途』等は 0 扱い
  });
  $("#total-display").textContent = "¥" + sum.toLocaleString();
}

/* 入居日・月額家賃・月額管理費の変更監視 */
document.addEventListener("input", ev => {
  if(ev.target.matches("#f-occupancy,#f-monthly-rent,#f-monthly-mgmt")){
    renderBreakdown();
    recalcTotal();
  }
});
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

$("#btn-add").addEventListener("click", () => addRow("", 0));
$("#btn-back").addEventListener("click", () => {
  ed.style.display = "none";
  up.style.display = "block";
  btnExtract.disabled = false;
});

/* 1物件分のpayloadを作る (入居日・月額家賃/管理費から日割りを組み立て) */
function buildPayloadFromProperty(p){
  const items = [];
  // 入居日ベースの日割り計算 (1日入居は当月のみ)
  const d = p.occupancy_date ? new Date(p.occupancy_date + "T00:00:00") : null;
  if(d && !isNaN(d.getTime())){
    const y = d.getFullYear(), mo = d.getMonth(), dd = d.getDate();
    const lastDay = new Date(y, mo+1, 0).getDate();
    const r = Number(p.monthly_rent)||0, m = Number(p.monthly_mgmt)||0;
    if(dd === 1){
      items.push({name:`家賃（${mo+1}月分）`,   amount:r});
      items.push({name:`管理費（${mo+1}月分）`, amount:m});
    } else {
      const days = lastDay - dd + 1;
      const nm = (mo === 11) ? 0 : mo + 1;
      items.push({name:`家賃（${mo+1}月${dd}日〜${mo+1}月${lastDay}日 日割り ${days}日分）`, amount:Math.round(r*days/lastDay)});
      items.push({name:`家賃（${nm+1}月分）`, amount:r});
      items.push({name:`管理費（${mo+1}月${dd}日〜${mo+1}月${lastDay}日 日割り ${days}日分）`, amount:Math.round(m*days/lastDay)});
      items.push({name:`管理費（${nm+1}月分）`, amount:m});
    }
  }
  // その他項目 (amount は number or string『別途』など)
  (p.other_items||[]).forEach(it => items.push({name:it.name, amount:it.amount}));
  const total = items.reduce((s,i) => {
    const n = (typeof i.amount === "number") ? i.amount : parseAmount(i.amount).num;
    return s + n;
  }, 0);
  return {
    property_name: p.property_name,
    address: p.address,
    occupancy_date: p.occupancy_date,
    items, total,
    notes: p.notes || "",
  };
}

/* --- 単体 PDF 生成 (現在のタブの物件) --- */
$("#btn-pdf").addEventListener("click", async () => {
  saveCurrentForm();
  const p = properties[currentIdx];
  const payload = buildPayloadFromProperty(p);
  // デバッグ: F12 コンソールで payload を確認できるように (備考 が入っているか等)
  console.log("[mitsumori-app] PDF payload:", {
    property_name: payload.property_name,
    address: payload.address,
    occupancy_date: payload.occupancy_date,
    items_count: payload.items.length,
    notes_length: (payload.notes || "").length,
    notes_preview: (payload.notes || "").slice(0, 60),
  });
  if(payload.items.length === 0){
    showErr(errEd, "少なくとも1行は項目を入力してください"); return;
  }

  hideErr(errEd);
  const btn = $("#btn-pdf");
  btn.disabled = true; btn.textContent = "生成中...";
  try{
    const res = await fetch("/api/generate_pdf", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload),
    });
    if(!res.ok){
      const e = await res.json().catch(() => ({error:"PDF 生成に失敗"}));
      throw new Error(e.error || "PDF 生成に失敗");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const fn = "見積書_" + (payload.property_name || "物件") + "_" +
      new Date().toISOString().slice(0,10) + ".pdf";
    a.href = url; a.download = fn; a.click();
    URL.revokeObjectURL(url);
  }catch(e){
    showErr(errEd, e.message);
  }finally{
    btn.disabled = false;
    btn.textContent = "この物件の見積書 PDF  ▼";
  }
});

/* --- 全物件まとめて ZIP --- */
$("#btn-zip").addEventListener("click", async () => {
  saveCurrentForm();
  const payload = { properties: properties.map(buildPayloadFromProperty) };
  hideErr(errEd);
  const btn = $("#btn-zip");
  btn.disabled = true; btn.textContent = "ZIP 生成中...";
  try{
    const res = await fetch("/api/generate_zip", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload),
    });
    if(!res.ok){
      const e = await res.json().catch(() => ({error:"ZIP 生成に失敗"}));
      throw new Error(e.error || "ZIP 生成に失敗");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "見積書一式_" + new Date().toISOString().slice(0,10) + ".zip";
    a.click();
    URL.revokeObjectURL(url);
  }catch(e){
    showErr(errEd, e.message);
  }finally{
    btn.disabled = false;
    btn.textContent = "全物件まとめて ZIP ダウンロード ⭳";
  }
});

function showErr(el, msg){ el.textContent = "⚠ " + msg; el.style.display = "block"; }
function hideErr(el){ el.style.display = "none"; }
</script>
</body>
</html>
"""


@app.route("/")
def index():
    # 常に最新版の HTML/JS を取得させる (更新後のキャッシュ問題対策)
    resp = app.make_response(render_template_string(
        INDEX_HTML, year=datetime.now().year, version=APP_VERSION))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/favicon.ico")
def favicon():
    # 404 対策: 1x1 の透明画像を返す (ブラウザコンソールのノイズを消すため)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001010000000037"
        "6ef9240000001049444154789c626001000000ffff03000006000557bfab"
        "d40000000049454e44ae426082"
    )
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """PDF を受け取り Gemini で初期費用項目を抽出する"""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "ファイルが添付されていません"}), 400
    pdf_bytes = f.read()
    if len(pdf_bytes) == 0:
        return jsonify({"error": "空のファイルです"}), 400
    # 簡易シグネチャチェック
    if not pdf_bytes.startswith(b"%PDF"):
        return jsonify({"error": "PDF ファイルではありません"}), 400

    try:
        data = extract_items_from_pdf(pdf_bytes)
    except Exception as e:
        app.logger.exception("extract failed")
        return jsonify({"error": f"抽出エラー: {e}"}), 500

    return jsonify(data)


@app.route("/api/generate_pdf", methods=["POST"])
def api_generate_pdf():
    """編集済みデータから見積書 PDF を生成して返す"""
    data = request.get_json(silent=True) or {}
    if not data.get("items"):
        return jsonify({"error": "項目が空です"}), 400

    # デバッグログ (Render の Logs で確認できる)
    app.logger.info(
        "generate_pdf: prop=%r items=%d notes_len=%d",
        data.get("property_name", ""),
        len(data.get("items", [])),
        len((data.get("notes") or "")),
    )

    try:
        pdf_bytes = generate_estimate_pdf(data)
    except Exception as e:
        app.logger.exception("pdf generation failed")
        return jsonify({"error": f"PDF 生成エラー: {e}"}), 500

    fname = f"mitsumori_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=fname,
    )


@app.route("/api/generate_zip", methods=["POST"])
def api_generate_zip():
    """複数物件の見積書 PDF を一括生成して ZIP で返す"""
    data = request.get_json(silent=True) or {}
    props = data.get("properties", [])
    if not props:
        return jsonify({"error": "物件データがありません"}), 400

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, p in enumerate(props, start=1):
                if not p.get("items"):
                    continue
                pdf_bytes = generate_estimate_pdf(p)
                name = (p.get("property_name") or f"物件{i}").strip()
                # Windows/Mac で使えないファイル名文字を置換
                safe = re.sub(r'[\\/*?:"<>|]', "_", name)[:80]
                zf.writestr(f"見積書_{i:02d}_{safe}.pdf", pdf_bytes)
    except Exception as e:
        app.logger.exception("zip generation failed")
        return jsonify({"error": f"ZIP 生成エラー: {e}"}), 500

    zip_fname = f"見積書一式_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(
        io.BytesIO(buf.getvalue()),
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_fname,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
