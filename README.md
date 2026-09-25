# cursor-spend

Cursor チームの利用量・追加課金をローカルブラウザで確認するダッシュボード。

Python 標準ライブラリのみ。ビルド不要。ダッシュボードの表示・更新に **追加の Cursor 課金は発生しない**（読み取り専用 API のみ使用）。

## 必要環境

- macOS（現状 `state.vscdb` のパスが macOS 固定）
- Python 3.10+
- Cursor デスクトップアプリに **ログイン済み** であること

## 使い方

```bash
git clone git@github.com:kke-me/cursor-spend.git
cd cursor-spend
python3 refresh.py --serve
```

ブラウザで http://127.0.0.1:8765/ を開く。

- 起動時に API から最新データを取得し `snapshot.js` を生成する
- 画面右上の **更新** ボタン、または `GET /refresh` で再取得できる

`--serve` なしでスナップショットだけ更新する場合:

```bash
python3 refresh.py
```

## 画面の見方

| 表示 | 意味 |
| --- | --- |
| 今サイクルの追加課金 | 現在の課金サイクル内の On-demand 合計 |
| Cursor Models / Other Models バー | 各プールの使用率（%） |
| プラン | 契約プラン名・席単価 |
| チーム | チーム spend メーター（使用額 / 上限） |
| サイクル | 課金期間（開始 – 終了） |
| バジェット更新 | サイクル終了＝次回リセット日時（日本時間） |
| モデル別履歴 | Included / On-demand ごとの直近利用（最大4件表示） |

注記（Usage 合計と spend メーターの差）は、差が $0.05 以上のときのみ表示される。

## 仕組み

```
Cursor アプリ (ログイン済み)
  └─ state.vscdb に accessToken を保存
         ↓
refresh.py ──→ api2.cursor.sh (Bearer 認証)
         ↓
snapshot.js (window.SNAPSHOT = {...})
         ↓
index.html (Tailwind CDN + 素の JS)
```

### 認証

Cursor アプリがローカルに保存したアクセストークンを使う。別途 API キーは不要。

| 項目 | 内容 |
| --- | --- |
| 取得元 | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| SQLite キー | `cursorAuth/accessToken` |
| 送信 | `Authorization: Bearer <token>` |

トークンはログインセッション相当。**他人に共有しないこと。** `snapshot.js` も課金・利用履歴を含むため Git 管理対象外（`.gitignore` 済み）。

### 利用 API

ベース URL: `https://api2.cursor.sh`

| エンドポイント | 用途 |
| --- | --- |
| `GET /auth/full_stripe_profile` | チーム ID 取得 |
| `POST .../GetCurrentPeriodUsage` | 課金サイクル、プール使用率、spend メーター |
| `POST .../GetPlanInfo` | プラン名・席単価 |
| `POST .../GetFilteredUsageEvents` | 利用イベント（100件 × 最大20ページ） |

Cursor アプリのダッシュボードと同系統の **非公開 API**。仕様変更で動かなくなる可能性がある。

### 集計ロジック

1. **課金サイクル** — `billingCycleStart` / `billingCycleEnd` でイベントをフィルタ
2. **モデル分類**
   - **Cursor Models**: `autoBucketModels` 登録、`default`、または `grok-` / `composer-` / `cursor-` / `vega` 接頭辞
   - **Other Models**: 上記以外
3. **イベント種別**
   - `USAGE_EVENT_KIND_INCLUDED_IN_BUSINESS` → Included
   - `USAGE_EVENT_KIND_USAGE_BASED` → On-demand（追加課金）
4. サイクル内イベントをモデル別に集計。全イベントを `uses[]`、On-demand のみ `onDemand[]` に格納

### ファイル構成

```
cursor-spend/
├── refresh.py    # データ取得 + 簡易 HTTP サーバー (127.0.0.1:8765)
├── index.html    # UI
├── snapshot.js   # 生成データ（git 管理外）
└── README.md
```

## 配布

| 方式 | 向き |
| --- | --- |
| 各自ローカル実行 | **推奨** — 各自の Cursor セッションで取得 |
| `snapshot.js` のみ共有 | 静的確認用。更新ボタンは使えない |
| 共有サーバーで常時公開 | **非推奨** — トークン・権限の集中リスク |

## 制限

- **macOS のみ**（`state.vscdb` パス固定。他 OS は `refresh.py` の `VSCDB` を書き換える必要あり）
- **非公式 API** — Cursor 側の変更で壊れる可能性
- **イベント上限** — 最大 2,000 件（100 × 20 ページ）。超過分は集計に入らない
- **権限** — トークン所有者が Cursor 上で閲覧できる範囲のデータのみ
- **ローカルのみ** — サーバーは `127.0.0.1:8765` にバインド

## ライセンス

MIT
