# CLAUDE.md

AI アシスタント（Claude Code CLI / Claude Code on the web）がこのリポジトリで
作業するときの指針。

このファイルは **2部構成** です:

- **第1部: エヌプライム社 共通ルール** — 全リポジトリに同じ内容を置く
- **第2部: このリポジトリ（mitsumori-app）固有の情報**

第1部を更新したら、他のリポジトリ（`portal-app` / `shokufuda-app` /
`route-app` / `moritsuke-app`）の CLAUDE.md にも同じ更新を反映すること。

---

# 第1部: エヌプライム社 共通ルール

全リポジトリ共通。食事システム系（portal-app / shokufuda-app / route-app /
moritsuke-app）でも不動産系（mitsumori-app）でも同一。

## 開発者情報

- 株式会社エヌプライム / 株式会社エヌプライムソリューションズ 代表
  中塚勝利
- システム知識ほぼゼロ。バイブコーディング（AI に書いてもらう開発スタイル）
- 開発作業はすべて Claude Code（CLI または Web）経由で行う。
  コマンドプロンプトや通常チャット経由での手作業はコピペ破損の原因に
  なるため避ける。

## Git 基本ルール

- commit author は毎回インラインで指定する（global config は設定しない方針）:
  ```
  git -c user.name=victorykatsutoshi19860403-maker \
      -c user.email=victorykatsutoshi19860403@gmail.com \
      commit -m "..."
  ```
- `main` には直接 push しない。必ず作業用ブランチで作業し、PR 経由で
  取り込む。
- push 前に `git pull --rebase origin <branch>` を実行する
  （リモート側で Web UI 編集されている可能性があるため）。
- `git push -u origin <branch>`。ネットワークエラーは指数バックオフで
  最大4回リトライ（2秒/4秒/8秒/16秒）。
- ユーザーが明示的に依頼しない限り PR は作らない。

## push 前の必須チェック（事故防止）

過去に「意図せず大量のコードを削除してしまう」事故があった
（例: Gemini API 関連コードをまるごと意図せず削除し、次コミットで復旧）。
再発防止のため、push 前に以下を必ず実行:

1. **`git diff --stat`** で変更行数を確認
   - 「20行追加のつもりが100行削除」のような数字が出たら **必ず止まる**
2. **`git diff`** で実際の差分を目視
   - 削除されている行に「消す意図がなかったコード」が混ざっていないか
   - 関係のないファイルが混ざっていないか
3. **`wc -l <file>`** で前後の行数を比較
   - 大きく減っている場合は必ず止まって理由を確認

## 事故からの復旧パターン

- 直前コミットを取り消したい → **`git revert <SHA>`** で取り消しコミットを
  作る（force push 不要）
- ファイル単位で前のバージョンに戻したい →
  `git checkout HEAD~1 -- <file>`
- 間違ったコミットを実質的に上書きしたい → 新しい修正コミットを push
  （悪いコミットは履歴に残るが安全）
- `--force` push / `reset --hard` はユーザー明示の依頼がない限り使わない

## コードスタイル

- コメントは **日本語** で書く
- 設計方針を先に確認してからコードを書く
- 一度に大きく変えない（1機能ずつ）
- 変更前にバックアップ（現状のファイル内容）を把握してから進める
- 修正は **常に完全版ファイル** で行う（差分だけの提示は NG。コピペ破損の原因）

## commit メッセージ

- プレフィックスは英語の conventional-commit 風（`feat:` / `fix:` /
  `style:` / `refactor:` / `docs:` / `chore:`）
- プレフィックスのあとは **日本語** で内容を要約
- 例:
  - `feat: 備考欄を追加 (入力→見積書PDFに印字)`
  - `fix: 1日入居の場合は当月分のみ (日割り・翌月分なし)`
  - `docs: CLAUDE.md を2部構成に再編`

## 会話の使い分け

- **1タスク = 1会話**（バグ修正1件で1会話）
- 新会話の冒頭は「**CLAUDE.md を読んで現状把握して**」で統一
- 会話が長引いて context が肥大化したら別会話に切り替える
  （遅くなる・指示がブレる原因）

## Claude Code 系ツールの違い（混同注意）

| ツール | どこで動く | ファイル操作 | git 操作 | CLAUDE.md 自動読込 |
|---|---|---|---|---|
| **Claude Code CLI**（PC） | 自分の PC | ✅ ローカル直接 | ✅ ローカル | ✅ |
| **Claude Code on the web** | Anthropic クラウド | ✅ GitHub 経由 | ✅ クラウド | ✅ |
| **Claude.ai / Web Claude**（普通のチャット） | ブラウザ | ❌ 不可 | ❌ 不可 | ❌（手動で貼る必要あり） |

- CLAUDE.md を自動で読んでくれるのは上2つ（Claude Code 系）のみ
- 通常チャットに持っていく場合は、CLAUDE.md の内容を自分でコピペする
- Web版はセッションごとに **1リポジトリ** に固定される。別リポジトリを
  触りたいときは別セッションを開く

## リポジトリ一覧（エヌプライム系）

| リポジトリ | 役割 | 本番 URL |
|---|---|---|
| `mitsumori-app` | 不動産 初期費用見積書 PDF 生成 | （Render 個別） |
| `portal-app` | 食事システム3本を統合した SaaS | （Render、未デプロイ） |
| `shokufuda-app` | 食札並び替え（単体） | https://shokufuda-app.onrender.com |
| `route-app` | ルート表自動作成（単体） | https://route-app-x54i.onrender.com |
| `moritsuke-app` | 盛り付け指示書（単体） | （未デプロイ） |

食事システム4本の固有情報（差し替え判定 × vs ◎ / 食札スコアリング /
ルート表設定 / Stripe プラン 等）は **各リポジトリの第2部** に書く。
このリポジトリ（mitsumori-app）には食事システムの話は入れない。

---

# 第2部: このリポジトリ（mitsumori-app）固有の情報

## プロジェクト概要

`mitsumori-app` は 株式会社エヌプライム の、不動産リース初期費用の
見積書（見積書 PDF）を作成する単一ページ Web アプリ。

フロー:

1. エージェントがマイソク（物件資料 PDF）をアップロード
2. Gemini 2.5 Flash が初期費用項目を JSON として抽出
3. ユーザーがブラウザで項目 / 家賃 / 入居日 / 備考を編集
4. サーバーがブランド付き A4 PDF をレンダリング（1アップロードで複数物件
   が検出された場合は PDF の ZIP を返す）

すべてのユーザー向けテキストは日本語。指示がない限り変更しない。

## 技術スタック

- Python 3.12, Flask 3
- `google-genai`（モデル `gemini-2.5-flash`、PDF は base64 でインライン送信）
- `reportlab` + 組み込み日本語 CID フォント `HeiseiKakuGo-W5`
  （ゴシック、主フォント）、`HeiseiMin-W3`（明朝、登録のみで未使用。
  commit `25ba35d` で UI をゴシックに統一）
- `gunicorn`（`gthread`、1 worker × 4 threads、timeout 300s） — `Procfile` 参照。
  single worker は Gemini リクエストコストと Render 無料枠の
  メモリ制約のため意図的
- デプロイ先: Render。`PORT` は Render が注入

依存は `requirements.txt` でピン留め。理由なく緩めない。

## リポジトリ構成

```
mitsumori-app/
├── app.py            # Flask 本体: Gemini 呼び出し / PDF 生成 / HTML/CSS/JS 埋め込み
├── requirements.txt
├── Procfile
├── README.md         # ユーザー向け（日本語）
└── CLAUDE.md         # このファイル
```

すべて `app.py` に入っている。`templates/` / `static/` / JS バンドルは
**無い**。UI 全体は Python の生文字列定数 `INDEX_HTML` を
`render_template_string` で描画している。ユーザーから依頼がない限り
この構造を維持する。

## app.py マップ

おおよその行レンジ（ズレる可能性あり。必要なら grep で再確認）:

| 関心事 | 位置 |
|---|---|
| 会社定数・色・フォント・`APP_VERSION` | ~L30–L63 |
| Flask app + 20 MB アップロード上限 | ~L65–L67 |
| `extract_items_from_pdf` — Gemini プロンプト + JSON 正規化 | ~L72–L187 |
| `_coerce_amount` / `_amount_to_int` — 金額の数値/文字列ヘルパ | ~L190–L225 |
| `_wrap_text`, `_fmt_yen` — PDF テキストヘルパ | ~L230–L267 |
| `generate_estimate_pdf` — reportlab レイアウト | ~L270–L509 |
| `INDEX_HTML` — HTML / CSS / クライアント JS（1文字列） | ~L515–L1437 |
| ルーティング: `/`, `/favicon.ico`, `/healthz`, `/api/extract`, `/api/generate_pdf`, `/api/generate_zip` | ~L1440–L1549 |
| ローカル開発用の `app.run` | L1551–L1552 |

## HTTP ルート

- `GET  /` — `INDEX_HTML` を返す。`Cache-Control: no-store…` で
  デプロイ後にハードリロードせずに反映される（commit `442f64b`）。
  `APP_VERSION` がページに埋め込まれ、デプロイ確認に使える。
- `GET  /favicon.ico` — 1×1 PNG をインライン返却（ブラウザ 404 ノイズ対策）
- `GET  /healthz` — `ok` を返す。Render のヘルスチェック用
- `POST /api/extract` — `multipart/form-data`（`file=<pdf>`）。サイズ・
  非空・`%PDF` シグネチャを検証。正規化済みの
  `{"properties":[…]}` を返す
- `POST /api/generate_pdf` — 1物件分の JSON を受けて PDF を返す
- `POST /api/generate_zip` — `{"properties":[…]}` を受けて物件ごとの
  PDF を ZIP で返す。ファイル名は `見積書_{NN}_{property}.pdf`
  （Windows で使えない文字は置換）

## データ形状の契約

`extract_items_from_pdf` の正規化器は Gemini の3形式
（`{"properties":[…]}` / ベアリスト / 単一 dict）を受け取り、常に
`{"properties":[…]}` を返す。下流コードがこれに依存しているので保つこと。

物件単位の dict（フロント / `generate_estimate_pdf` 両方で使用）:

```json
{
  "property_name": "...",
  "address": "...",
  "occupancy_date": "YYYY-MM-DD",      // optional、UI 側で追加
  "items": [ {"name": "...", "amount": <int | str>} ],
  "total": <int>,
  "notes": "..."                        // optional、UI 側で追加
}
```

`REQUIRED_ITEMS`（家賃, 管理費, 敷金, 礼金, 仲介手数料, 保証会社料,
火災保険料, 鍵交換費用）は常に存在する。Gemini が省略した項目は
`amount=0` でバックフィルされる。

### 金額のポリモーフィズム（重要）

item の `amount` は **意図的に int（円）または文字列**
（`"別途"` / `"応相談"` / `"要相談"` / `"未定"`）のどちらか（commit `ad5d69b`）。

- `_coerce_amount` — 入力値を正規化。`,¥￥円` 付き数値文字列は int に。
  非数値文字列はそのまま通す
- `_amount_to_int` — **合計計算専用**。文字列は `0` に（合計から除外）
- `_fmt_yen` — 数値は `¥X,XXX`、文字列は生のまま出力

`amount` を触るコードを足すときは、表示（`_fmt_yen`）/ 合計（`_amount_to_int`）
/ 生ポリモーフィック値のどれが必要かを **明示的に判断** してから正しい
ヘルパを使うこと。

## PDF レンダリングの注意

- ページサイズ A4、マージン 20mm、フォントはモジュールインポート時に
  一度だけ登録
- ヘッダー / 合計バーはネイビー（`#1a2a3a`）+ ゴールド（`#c9a961`）。
  ドキュメント全体を `FONT_GOTHIC`（`HeiseiKakuGo-W5`）で描画
  （commit `676ede0` / `25ba35d` でタイポグラフィを統一）。
  **依頼がない限り明朝体を再導入しない**
- 長い項目リストは `y_cur < 50 * mm` でページ送り。継続ページでは
  簡易ヘッダ行を再描画
- 備考ブロックは残り 22mm を切ると新ページへ送る（commit `987ce4f`）。
  **黙って備考をドロップしない**。`…以下省略` を描画できるのはテキスト
  クリップ経路のみ

## フロントエンド（埋め込み JS）の挙動

エディタはフレームワークなしのバニラ JS。モジュールスコープで状態管理:

- `properties` — 物件ごとのフォーム状態配列
- `currentIdx` — アクティブタブ
- `saveCurrentForm()` ↔ `renderCurrentProperty()` が DOM と
  `properties[currentIdx]` を同期
- `buildPayloadFromProperty` が `monthly_rent` / `monthly_mgmt` /
  `occupancy_date` からサーバペイロードを組み立て、最後に `other_items`
  を足す

### 日割り家賃のルール

`calcBreakdown` と `buildPayloadFromProperty` にミラーで実装:

- `occupancy_date.getDate() === 1` → `家賃（M月分）` / `管理費（M月分）`
  の2行のみ（commit `8848ff6`）
- それ以外 → 当月の `日割り N日分` + **翌月分の全額** `家賃` / `管理費` 行

**同じロジックが2箇所にある（表示用 + ペイロード組立用）**。
変更するときは両方同時に更新し、ズレさせないこと。

### 金額入力

`.amount` は `type="text"`（`inputmode="numeric"`）で、`別途` / `応相談`
等も入力可。`parseAmount` は `{num, text, raw}` を返す。呼び出し側で
適切なフィールドを選ぶこと。

## 規約

- **ファイル境界**: 全部 `app.py` に置く。`templates/` や JS バンドラを
  明示的な依頼なしに追加しない
- **トップレベルに新規ファイルを増やさない**。`app.py` +
  `requirements.txt` + `Procfile` + `README.md` + `CLAUDE.md` のみ
- **APP_VERSION**: ユーザーに見える変更をリリースするときは日付を bump。
  アップロード画面に表示されるのでデプロイ反映確認が一番早い
- **`/` のキャッシュヘッダ**: no-store ヘッダを外さない。以前モバイル
  Safari で壊れていた（commit `442f64b`）

## 環境変数

| 変数 | 用途 |
|---|---|
| `GEMINI_API_KEY` | 必須。`extract_items_from_pdf` で使う Google AI Studio キー |
| `PORT` | Render が注入。`app.run` はローカルで 5000 にフォールバック |

`GEMINI_API_KEY` はリクエストごとに読み直すので、Render 側でローテート
しても再起動は不要。

## ローカル開発

```bash
cd mitsumori-app
python -m venv venv
# Windows
venv\Scripts\activate
# Unix
source venv/bin/activate

pip install -r requirements.txt
export GEMINI_API_KEY=xxxx
python app.py            # http://localhost:5000、debug=True
```

テスト / Linter / CI は **無い**。「完了」の定義:
(a) `python app.py` がエラーなく起動 /
(b) 単一物件 PDF でアップロード→編集→PDF が通る /
(c) 複数物件 PDF で ZIP フローが動く。
実 Gemini 呼び出しが試せない環境なら、stub するか「試せない」と明示する
（動いたと嘘を言わない）。

## やってはいけないこと

- `INDEX_HTML` を別テンプレートに分割する — 1ファイル構成は意図的
  （Render デプロイを単純に保つ）
- `amount` を global に int 強制する — int-or-string の契約に依存する
  コードが複数ある
- 備考や項目を黙って切り詰める — 既存は `…以下省略` を継続ページで
  描画するときだけ。可視性を保つ
- 明朝体（`HeiseiMin-W3`）を生成 PDF に再導入する — 将来互換のため
  登録だけ残してある
- `/api/extract` の `%PDF` シグネチャチェックをスキップする —
  ブラウザのファイルピッカー経由の誤用を防いでいる
