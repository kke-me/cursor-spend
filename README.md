# cursor-spend

Cursor チームの利用量・追加課金をローカルブラウザで確認するダッシュボード。

Python 標準ライブラリのみ。ビルド不要。表示・更新に **追加の Cursor 課金は発生しない**。

![cursor-spend ダッシュボード](docs/screenshot.png)

## 必要環境

- macOS / Windows / Linux
- Python 3.10+
- Cursor デスクトップアプリに **ログイン済み**

## 使い方

```bash
git clone git@github.com:kke-me/cursor-spend.git
cd cursor-spend
python refresh.py --serve
```

http://127.0.0.1:8765/ を開く。右上 **更新** または `GET /refresh` で再取得。

## 仕組み

```
Cursor (ログイン済み) → state.vscdb (accessToken)
  → refresh.py → api2.cursor.sh
  → snapshot.js → index.html
```

### 認証

Cursor がローカル保存したトークンを使う。API キー不要。

| OS | `state.vscdb` |
| --- | --- |
| macOS | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |
| Windows | `%APPDATA%\Cursor\User\globalStorage\state.vscdb` |
| Linux | `~/.config/Cursor/User/globalStorage/state.vscdb` |

`CURSOR_VSCDB` 環境変数でパス上書き可。トークンと `snapshot.js` は共有しない（`.gitignore` 済み）。

### API

`https://api2.cursor.sh` — Cursor ダッシュボードと同系統の **非公開 API**。

| エンドポイント | 用途 |
| --- | --- |
| `GET /auth/full_stripe_profile` | チーム ID |
| `POST .../GetCurrentPeriodUsage` | サイクル・プール使用率・spend |
| `POST .../GetPlanInfo` | プラン |
| `POST .../GetFilteredUsageEvents` | 利用イベント（最大 2,000 件） |

### 集計

見出しの金額は On-demand イベント合計。Cursor 請求画面の値（`individualUsed`）は横に小さく表示。

- サイクル: `billingCycleStart` / `End` でフィルタ
- Cursor Models: イベントのプールフィールド、なければ `autoBucketModels` / `default`、最後に `grok-` / `composer-` / `cursor-` / `vega`
- Other Models: 上記以外
- 知らない `kind` は合計に入れず `unknownKinds` に残す
- イベント合計とメーターの差が $0.05 以上なら `drift` を出す

`drift` や未分類が出たら、`fixtures/payload.json` を今のレスポンス形に合わせて直し、`python -m unittest` を通す。

## 制限

- 非公式 API（仕様変更で壊れる可能性）
- トークン所有者が閲覧できる範囲のデータのみ
- サーバーは `127.0.0.1:8765` のみ

## ライセンス

MIT
