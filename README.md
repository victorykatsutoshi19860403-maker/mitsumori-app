# mitsumori-app

初期費用見積書作成 Web アプリ（株式会社エヌプライム）

## 概要

不動産のマイソク PDF をアップロードすると、Gemini API が初期費用項目を自動抽出します。
内容を確認・編集して、プロ仕様の見積書 PDF を出力できます。

## フロー

```
[マイソクPDF] → [Gemini API で項目抽出] → [確認・編集画面] → [見積書PDF ダウンロード]
```

## 抽出項目

- 物件名 / 所在地
- 家賃 / 管理費 / 敷金 / 礼金
- 仲介手数料 / 保証会社料 / 火災保険料 / 鍵交換費用
- その他費用（マイソクに記載の全項目）
- 合計金額

## 技術スタック

- **Backend**: Python 3.12 / Flask
- **AI**: Google Gemini API (`google-genai`, gemini-2.5-flash, PDF を base64 で直接送信)
- **PDF 生成**: reportlab (日本語 CID フォント HeiseiMin-W3 / HeiseiKakuGo-W5)
- **Server**: gunicorn (gthread, 1 worker × 4 threads, timeout 300s)

## 環境変数

| 変数名 | 用途 |
|--------|------|
| `GEMINI_API_KEY` | Google AI Studio の API キー |
| `PORT` | ポート番号（Render が自動設定） |

## ローカル起動

```bash
cd mitsumori-app
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
set GEMINI_API_KEY=xxxx          # Windows
python app.py                    # http://localhost:5000
```

## Render デプロイ

- `Procfile` に gunicorn 起動コマンド記載済み
- 環境変数 `GEMINI_API_KEY` を Render 側で設定
- Python バージョン: 3.12 を推奨

## 会社情報（PDF 印字）

```
株式会社エヌプライム
東京都港区新橋2-20-15 新橋駅前ビル1号館4階 フィルポート
TEL  03-6228-5808
MAIL info@nprime.co.jp
```

## ファイル構成

```
mitsumori-app/
├── app.py            # Flask 本体（抽出 API / PDF 生成 / 埋め込み HTML）
├── requirements.txt
├── Procfile
└── README.md
```
