# セットアップ手順(自分用の本番)

## 0. 用意するもの

- Android 9 以降のスマホ。Android 14 以降なら Health Connect は内蔵。13 以前は Play ストアから「ヘルスコネクト」を入れる
- RingConn アプリ → Me → Data Management → Connect to Health Connect → Sync を ON
- Google カレンダーの「iCal 形式の非公開 URL」(設定 → 対象カレンダー → 「カレンダーの統合」)
- Fly.io アカウント(無料枠で足りる)と `flyctl`
- Claude Code の長期トークン: 自分の PC で `claude setup-token` を実行して表示される値

## 1. バックエンドを Fly.io に出す

```bash
cd backend
fly launch --copy-config --no-deploy          # アプリ名を聞かれたら好きな名前に
fly volumes create kizashi_data --size 1 --region nrt
fly secrets set APP_TOKEN="$(openssl rand -hex 24)" \
  CLAUDE_CODE_OAUTH_TOKEN="<claude setup-token の値>" \
  CALENDAR_ICS_URLS="https://calendar.google.com/calendar/ical/.../basic.ics"
fly deploy
```

API キー方式にするなら `INFERENCE_BACKEND=api ANTHROPIC_API_KEY=...` を secrets に入れる。

動作確認: `https://<app>.fly.dev/healthz` が `{"status":"ok"}` を返す。

## 2. Android アプリを入れる

```bash
cd android
./gradlew assembleDebug
```

`app/build/outputs/apk/debug/app-debug.apk` をスマホへ(USB、Drive、何でも)。「提供元不明のアプリ」を一時的に許可してインストール。

アプリを開いて:

1. サーバー URL(`https://<app>.fly.dev`)と APP_TOKEN を入れて「保存して自動同期を開始」
2. 「Health Connect を許可」→ 全項目 ON
3. 「使用状況へのアクセスを許可」→ 設定画面で Kizashi Collector を ON
4. 「通知の読み取りを許可」→ 設定画面で Kizashi Collector を ON
5. 「位置情報と通知を許可」→ 許可。続けて「常に許可」にする
6. 「今すぐ同期」→ ログに「健康 N件 / 利用統計 N件 / 送信 N件」と出れば OK
7. 「サーバー接続テスト」→ event_counts に数字が入っていれば届いている

電池の最適化で止められる機種(Xiaomi、OPPO など)は、設定 → アプリ → Kizashi Collector → バッテリー → 制限なし。

## 3. 夜の確認

22時(アプリで変更可)にリマインド通知。タップすると `https://<app>.fly.dev/?token=...` が開く。Chrome の「ホーム画面に追加」で PWA にしておくと楽。

## 4. 朝のひとこと

PWA の設定タブに「朝のひとこと」欄。キーボードのマイクで話すだけ。Android の「音声でメモ」をショートカットから直接 `/api/notes` に投げる版は今後。

## トラブルシュート

| 症状 | 見るところ |
|---|---|
| 健康 0件 | RingConn 側の Health Connect 同期が ON か。Health Connect アプリ → データとアクセス → RingConn にデータがあるか |
| 決済通知が来ない | 通知の読み取り権限。PayPay/カードアプリの通知が OS で有効か。アプリ内のパッケージ名リスト |
| 利用統計 0件 | 使用状況へのアクセス。再起動後に 1 回同期 |
| カードが出ない | `fly logs` で推定の失敗を確認。失敗時は rules にフォールバックするので何かは出るはず |
