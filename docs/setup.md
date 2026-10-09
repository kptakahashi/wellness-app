# セットアップ手順(自分用の本番、全部無料)

費用ゼロで動かす構成です。カード登録は要りません。所要時間は合計で30分ほどです。

| 役割 | サービス | 無料枠 | 補足 |
|---|---|---|---|
| サーバー | [Render](https://render.com) (Web Service, Docker) | 月750時間(ワークスペース全体で共有) | 15分アクセスがないと休眠。次のアクセスで約1分かけて起きる |
| DB | [Neon](https://neon.tech) (Postgres) | 0.5GB | 休眠しても接続で即復帰。Render 無料枠はディスクが消えるので SQLite は使えない |
| 定時処理 | [cron-job.org](https://cron-job.org) | 無料 | 休眠中はアプリ内スケジューラが止まるので、外から毎晩起こす |

750時間の考え方: 休眠中は消費しません。スマホは30分ごとに同期するので、本番は「15分起きて15分寝る」の繰り返しで月360時間程度。デモは誰かが見た時だけ起きるので、合計で枠内に収まります。

## 0. 先に用意するもの

| もの | 取り方 |
|---|---|
| Claude Code の長期トークン | PC の PowerShell で `claude setup-token` を実行。表示された `sk-ant-oat...` をメモ帳に控える(画面には二度と出ない)。[公式: Agent SDK を Claude プランで使う](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) |
| Google カレンダーの非公開 iCal URL | [Google カレンダー設定](https://calendar.google.com/calendar/r/settings) → 左の「マイカレンダーの設定」で対象カレンダー → 「カレンダーの統合」→ **iCal 形式の非公開 URL** をコピー。[公式ヘルプ](https://support.google.com/calendar/answer/37648) |
| APP_TOKEN | 自分で決める長いランダム文字列(例: パスワード生成ツールで32文字)。スマホアプリとサーバーの合言葉 |
| RingConn → Health Connect | RingConn アプリ → Me → Data Management → Connect to Health Connect → Sync を ON。[RingConn 公式ガイド](https://ringconn.com/blogs/guides/health-connect-sync) |

## 1. Neon で Postgres を作る(3分)

1. [https://neon.tech](https://neon.tech) → **Sign up** → GitHub でログイン
2. **Create project**。Project name は `wellness-app`、Region は **Asia Pacific (Singapore)**。他は既定のまま
3. 作成直後の画面(または **Dashboard → Connect**)に出る **Connection string** をコピー。`postgresql://neondb_owner:...@ep-....ap-southeast-1.aws.neon.tech/neondb?sslmode=require` の形。これが `DATABASE_URL`

## 2. Render にデプロイする(10分)

1. [https://dashboard.render.com](https://dashboard.render.com) → **Sign up** → GitHub でログイン。GitHub 連携の画面が出たら `wellness-app` リポジトリへのアクセスを許可
2. 右上 **New → Blueprint**
3. リポジトリ一覧から `kptakahashi/wellness-app` を **Connect**
4. Blueprint name は何でもよい。`render.yaml` が読まれ、`wellness-app` と `wellness-app-demo` の2サービスが並ぶ
5. `wellness-app` の環境変数欄に入力:
   - `APP_TOKEN`: 0 で決めた合言葉
   - `DATABASE_URL`: Neon の接続文字列
   - `CLAUDE_CODE_OAUTH_TOKEN`: `claude setup-token` の値
   - `CALENDAR_ICS_URLS`: iCal 非公開 URL(複数ならカンマ区切り)
   `wellness-app-demo` は入力不要
6. **Apply**。初回のビルドは Node と Claude Code CLI を入れるため 5〜8分かかる
7. 終わったら各サービスのページ上部に URL が出る。`https://wellness-app-xxxx.onrender.com/healthz` を開いて `{"status":"ok"}` が出れば完成。デモの方は `https://wellness-app-demo-xxxx.onrender.com/` を開くと合成データで動く

参考: [Render Blueprint の公式ドキュメント](https://render.com/docs/infrastructure-as-code)、[無料枠の仕様](https://render.com/docs/free)

API キー方式にしたいときは環境変数 `INFERENCE_BACKEND=api` と `ANTHROPIC_API_KEY` を設定。

## 3. cron-job.org で夜の準備を予約する(5分)

休眠中の Render を起こして、その日の推定カードを作らせます。cron-job.org の待機は30秒、Render の復帰は約1分なので、**「起こす」と「処理する」を分けて2件**登録します。処理の方はサーバーが即座に受け付けてバックグラウンドで実行するので、30秒で切られても問題ありません。

1. [https://cron-job.org](https://cron-job.org) → **Sign up** → メール認証
2. **Create cronjob** で1件目(起こす):
   - Title: `wake`
   - URL: `https://wellness-app-xxxx.onrender.com/healthz`
   - Schedule: **Every day at 20:55**。Timezone を **Asia/Tokyo** に
   - Save
3. 2件目(今日の推定を作る):
   - Title: `evening`
   - URL: `https://wellness-app-xxxx.onrender.com/api/jobs/evening`
   - **Advanced** タブ → Request method: **POST**
   - **Headers** に追加: Key `X-Api-Token`、Value は APP_TOKEN
   - Schedule: **Every day at 21:00**、Asia/Tokyo
   - Save
4. 3件目(週次の傾向):
   - URL: `https://wellness-app-xxxx.onrender.com/api/jobs/weekly`、POST、同じヘッダー
   - Schedule: **Sunday 20:30**、Asia/Tokyo

テスト: cron-job.org の各ジョブの **Run now** を押し、evening の応答が `{"ok":true,"status":"scheduled"}` または `"already_prepared"` なら OK。

## 4. Android アプリを入れる(5分)

`dist/wellness-app-collector-debug.apk`(または `cd android && ./gradlew assembleDebug`)をスマホへ送る(Google ドライブ、USB、何でも)。開くと「提供元不明のアプリ」の警告が出るので、設定で一時的に許可してインストール。

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

22時(アプリで変更可)にリマインド通知。タップすると `https://.../?token=...` が開く。Chrome の「ホーム画面に追加」で PWA にしておくと楽。開いた瞬間に「読み込み中…」が1分ほど続くことがあるが、Render が起きているだけなので待つ。

## 6. 朝のひとこと

PWA の設定タブに「朝のひとこと」欄。キーボードのマイクで話すだけ。

## 別の選択肢

- **Render Starter(月7ドル)**: 休眠がなくなり、cron の「起こす」ジョブが不要になる。費用をかけてよくなったらここから
- **Fly.io**: `backend/fly.toml` を同梱。常時起動、SQLite のままでよいが、カード登録が必要で月数百円
- **自宅 PC + Tailscale**: データが家から出ない。常時起動の PC が要る
- **Cloudflare Workers + D1**: 無料で休眠もないが、バックエンドの全面書き直しが必要で、Claude Code の契約では AI を動かせない(API 課金になる)

## トラブルシュート

| 症状 | 見るところ |
|---|---|
| 健康 0件 | RingConn 側の Health Connect 同期が ON か。Health Connect アプリ → データとアクセス → RingConn にデータがあるか |
| 決済通知が来ない | 通知の読み取り権限。PayPay/カードアプリの通知が OS で有効か。アプリ内のパッケージ名リスト |
| 利用統計 0件 | 使用状況へのアクセス。再起動後に 1 回同期 |
| 同期が「失敗: timeout」 | Render の起動待ち。30分後に自動で再実行される |
| カードが出ない | Render の **Logs** で推定の失敗を確認。失敗時は rules にフォールバックするので何かは出るはず |
| Render から「free hours」の警告メール | 750時間に近づいている。デモを一時停止(Suspend)するか、同期間隔を延ばす |
