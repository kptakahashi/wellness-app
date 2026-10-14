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

環境変数 `RAW_EVENT_RETENTION_DAYS`(既定 90)で生データの保管日数を変えられる。`0` で無期限。

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

## 7. 確認カードの答え方

- 選択肢を押す。入力欄に何か書いてから押すと、その文は補足メモとして一緒に保存される
- 選択肢に無い答えは、入力欄に書いて「送信」(Enter でも可)。書いた文そのものが答えになる。例: 「カレーうどん」「行っていない」「3人で割り勘」

## 8. 場所の扱い(自宅・職場・店)

- **自宅**は聞きません。深夜 1〜5 時に端末がある場所を 3 晩以上見た時点で自動的に「自宅」になります
- **職場**も、平日 10〜16 時に 5 日以上いる場所(自宅以外)を自動で付けます
- それ以外で「1 時間以上いた」か「別の日にも行った」場所だけ、**一度だけ**「ここは?」カードが出ます(自宅/職場/ジム/飲食店・カフェ/買い物/その他、または自由入力で店名)。答えは覚えるので二度と聞きません
- 一度きりの短い立ち寄りは聞きません。近くの店・施設名の候補から AI が「何をしたか」を推定します
- 覚えた場所は設定タブの「覚えている場所」で確認・削除できます。推定し直すボタンもあります
- 「寝ていましたか」は聞きません。睡眠は Health Connect からだけ取ります

### 店・施設名の特定(OpenStreetMap)

位置の住所だけでは「何をしていたか」が分からないので、滞在地点の周りにある店・施設名を OpenStreetMap から引いて候補にします(例: `候補: 大戸屋 渋谷店(飲食店, 20m) / セブン-イレブン(コンビニ, 45m)`)。同じ時間帯の決済通知の店名と候補が一致すれば「決済と一致」として確定扱いになります。

仕組みと費用・プライバシー:

- 無料・キー不要の Overpass API を使う。Google の Places API は請求先の登録が要るので使わない
- 個々の滞在座標は外に送らない。**約 2km 四方のタイル**単位で、その範囲の店・施設を一度だけ取得して DB に保存し、照合はサーバー内で行う。OSM 側に分かるのは「この 2km 四方に行ったことがある」だけ
- タイルは夜の推定ジョブのときに取得する(1 回 2 枚まで、90 日で更新)。公式インスタンスが混んでいるときはミラーに切り替える
- 止めたいときは環境変数 `POI_SOURCE=none`
- 精度の目安: 位置は 15 分ごとのサンプルなので、15 分未満の立ち寄りは拾えないことがある。候補は半径 80〜150m(測位精度に応じて)なので、雑居ビルや駅前では複数候補になる。そのときは決済通知が決め手になる
- 位置の記録は Android の WorkManager で 15 分ごと。深夜は OS の省電力で間隔が延びるが、自宅判定には十分

## 9. 消費(何を買ったか)をどこまで取れるか

結論から言うと、**決済通知には商品名は入りません**。PayPay・カード・Suica などの決済ネットワークが受け取るのは「店名・金額・時刻」だけで、明細は店のレジにしか無いからです。アプリ側でどう設定しても、決済通知から品目は取れません。

取れるものと、設定のしかた:

| ソース | 分かること | 設定 |
|---|---|---|
| 決済アプリの通知(PayPay、楽天カード、Vpass、d払い、au PAY、モバイル Suica、マネーフォワード 等) | 店名・金額・時刻 | 各アプリの通知を ON。アプリ内の「通知を拾うアプリ」リストに既定で入っている |
| 出前・通販の通知(Uber Eats、出前館、Amazon、スターバックス モバイルオーダー) | 注文内容(品目)まで入ることが多い | 各アプリの注文通知を ON。既定リストに追加済み。クーポン等の販促通知は除外される |
| Gmail の通知 | 注文確認メールの冒頭(件名+本文の最初の数行)。Uber Eats・Amazon・楽天市場などは品目が載る | Gmail の通知を ON にし、通知の「プレビュー」を表示する設定に。本文が「ご注文」「レシート」「円」などを含む通知だけ拾う |
| コンビニ公式アプリ(セブン-イレブン、ファミペイ、ローソン) | レジでアプリのバーコードを出すと**アプリ内**に電子レシート(品目)が残る。ただし通知には載らないので自動では拾えない | 品目まで欲しい日は、確認カードの自由入力に書くのが現実的 |
| スマートレシート(東芝テック)、各社の電子レシート | 対応店舗の品目。通知には載らない | 同上 |

つまり自動で品目まで取れるのは「出前・通販」だけで、店頭の買い物は「店名+金額+時刻+場所」から AI が推定し、夜のカードで確認(必要なら自由入力で訂正)するのがこのアプリの前提です。

プライバシーの線引き: 通知の読み取りは、リストのアプリの通知と、決済・注文・レシートらしい文面を含む通知だけが対象です。LINE、メッセージ、Slack、Discord、Instagram などの会話アプリの通知は、文面に「円」が含まれていても読みません(アプリ内に固定のリストがあります)。

## 10. データの保管・バックアップ・削除

無料枠の DB は休眠・仕様変更・終了があり得るので、「手元に戻せる」状態を保ちます。

- **保管期間**: 生データは `RAW_EVENT_RETENTION_DAYS`(既定 90 日)を過ぎると毎晩の `/api/jobs/evening` で消えます。日ごとの集計・カード・傾向は残ります。今すぐ消すなら `POST /api/jobs/purge`
- **バックアップ(月 1 回を目安)**: PowerShell で

```bash
curl -H "X-Api-Token: <APP_TOKEN>" https://wellness-app-xxxx.onrender.com/api/data/export -o wellness-backup-2026-10-14.json
```

  出てきた JSON をパスワード付きの場所(自分の PC の暗号化フォルダ等)に置く。健康・位置・決済の記録そのものなので、クラウドの共有フォルダには置かない
- **復元**: 新しい DB を `DATABASE_URL` に設定してデプロイ後、

```bash
curl -X POST -H "X-Api-Token: <APP_TOKEN>" -H "Content-Type: application/json" --data-binary @wellness-backup-2026-10-14.json "https://wellness-app-xxxx.onrender.com/api/data/import?confirm=replace"
```

- **全部消す**: `curl -X DELETE -H "X-Api-Token: <APP_TOKEN>" "https://wellness-app-xxxx.onrender.com/api/data?confirm=delete-everything"`。覚えた場所・地図キャッシュも消える。消したあとは Neon 側のプロジェクト削除で物理的にも消える

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
| 決済通知に商品名が無い | 仕様。決済ネットワークは品目を受け取らない。「9. 消費をどこまで取れるか」を参照 |
| 同じ場所を何度も聞かれる | 設定タブ「覚えている場所」にその場所があるか。無ければ一度カードで答える。自宅は数晩分の位置があれば自動で付く |
| 店名の候補が出ない | 夜の推定ジョブが OSM タイルを取れていない(Render の Logs に `poi tile`)。混雑時は翌日に再試行する。`POI_SOURCE` が `none` になっていないか |
| 利用統計 0件 | 使用状況へのアクセス。再起動後に 1 回同期 |
| 同期が「失敗: timeout」 | Render の起動待ち。30分後に自動で再実行される |
| カードが出ない | Render の **Logs** で推定の失敗を確認。失敗時は rules にフォールバックするので何かは出るはず |
| Render から「free hours」の警告メール | 750時間に近づいている。デモを一時停止(Suspend)するか、同期間隔を延ばす |
