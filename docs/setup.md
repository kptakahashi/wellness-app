# セットアップ手順(自分用の本番、全部無料)

費用ゼロで動かす構成です。カード登録は要りません。

| 役割 | サービス | 無料枠 | 補足 |
|---|---|---|---|
| サーバー | Render (Web Service, Docker) | 月750時間 | 15分アクセスがないと休眠。次のアクセスで約1分かけて起きる |
| DB | Neon (Postgres) | 0.5GB | 休眠しても接続で即復帰。Render 無料枠はディスクが消えるので SQLite は使わない |
| 定時処理 | cron-job.org | 無料 | 休眠中はアプリ内スケジューラが止まるので、外から毎晩叩いて起こす |

## 0. 用意するもの

- Android 9 以降のスマホ。Android 14 以降なら Health Connect は内蔵。13 以前は Play ストアから「ヘルスコネクト」を入れる
- RingConn アプリ → Me → Data Management → Connect to Health Connect → Sync を ON
- Google カレンダーの「iCal 形式の非公開 URL」(設定 → 対象カレンダー → 「カレンダーの統合」)
- Claude Code の長期トークン: 自分の PC で `claude setup-token` を実行して表示される値
- GitHub、Render、Neon、cron-job.org のアカウント(すべて無料、GitHub ログインで作れる)

## 1. Neon で Postgres を作る(2分)

1. https://neon.tech → Sign up(GitHub ログイン可)→ New Project。リージョンは Singapore が近い
2. ダッシュボードの「Connection string」をコピー。`postgresql://...@....neon.tech/neondb?sslmode=require` の形

## 2. Render にデプロイする(5分)

1. https://render.com → Sign up(GitHub ログイン可)
2. New → Blueprint → リポジトリ `kptakahashi/wellness-app` を選ぶ → `render.yaml` が読まれ、`wellness-app` と `wellness-app-demo` の2サービスが提案される
3. `wellness-app` の環境変数を入力:
   - `APP_TOKEN`: 長いランダム文字列(自分で決める。スマホアプリにも入れる)
   - `DATABASE_URL`: Neon の接続文字列
   - `CLAUDE_CODE_OAUTH_TOKEN`: `claude setup-token` の値
   - `CALENDAR_ICS_URLS`: iCal 非公開 URL(複数ならカンマ区切り)
4. Apply。数分で `https://wellness-app-xxxx.onrender.com` が生える
5. `https://wellness-app-xxxx.onrender.com/healthz` が `{"status":"ok"}` を返せば OK

API キー方式にしたいときは `INFERENCE_BACKEND=api` と `ANTHROPIC_API_KEY` を設定。

## 3. cron-job.org で夜の準備を予約する(3分)

休眠中の Render を起こして、その日の推定カードを作らせます。

1. https://cron-job.org → Sign up → Create cronjob
2. URL: `https://wellness-app-xxxx.onrender.com/api/jobs/evening`
   - Request method: **POST**
   - Headers: `X-Api-Token: <APP_TOKEN>`
   - Schedule: 毎日 21:00(タイムゾーンを Asia/Tokyo に)
   - Timeout: 最大(起動に1分かかるため)
3. もう1件: `/api/jobs/weekly` を 日曜 20:30 に POST(週次の傾向)

## 4. Android アプリを入れる

`dist/wellness-app-collector-debug.apk`(または `cd android && ./gradlew assembleDebug`)をスマホへ。「提供元不明のアプリ」を一時的に許可してインストール。

アプリを開いて:

1. サーバー URL(`https://wellness-app-xxxx.onrender.com`)と APP_TOKEN を入れて「保存して自動同期を開始」
2. 「Health Connect を許可」→ 全項目 ON
3. 「使用状況へのアクセスを許可」→ 設定画面で Wellness app Collector を ON
4. 「通知の読み取りを許可」→ 設定画面で Wellness app Collector を ON
5. 「位置情報と通知を許可」→ 許可。続けて「常に許可」にする
6. 「今すぐ同期」→ ログに「健康 N件 / 利用統計 N件 / 送信 N件」と出れば OK(初回は Render の起動待ちで1分ほどかかる)
7. 「サーバー接続テスト」→ event_counts に数字が入っていれば届いている

電池の最適化で止められる機種(Xiaomi、OPPO など)は、設定 → アプリ → Wellness app Collector → バッテリー → 制限なし。

## 5. 夜の確認

22時(アプリで変更可)にリマインド通知。タップすると `https://.../?token=...` が開く。Chrome の「ホーム画面に追加」で PWA にしておくと楽。

## 6. 朝のひとこと

PWA の設定タブに「朝のひとこと」欄。キーボードのマイクで話すだけ。

## 別の選択肢

- **Fly.io**: `backend/fly.toml` を同梱。常時起動で休眠なし、SQLite のままでよいが、カード登録が必要で月数百円
- **自宅 PC + Tailscale**: データが家から出ない。常時起動の PC が要る

## トラブルシュート

| 症状 | 見るところ |
|---|---|
| 健康 0件 | RingConn 側の Health Connect 同期が ON か。Health Connect アプリ → データとアクセス → RingConn にデータがあるか |
| 決済通知が来ない | 通知の読み取り権限。PayPay/カードアプリの通知が OS で有効か。アプリ内のパッケージ名リスト |
| 利用統計 0件 | 使用状況へのアクセス。再起動後に 1 回同期 |
| 同期が「失敗: timeout」 | Render の起動待ち。数分後に再実行される。頻発するなら cron-job.org に `/healthz` を 10分おき GET で追加して起こしておく |
| カードが出ない | Render の Logs で推定の失敗を確認。失敗時は rules にフォールバックするので何かは出るはず |
