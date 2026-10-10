# Wellness app

**記録しない健康ログ。** スマートリング・決済通知・カレンダー・スマホ利用を自動で集め、AI が「今日なにをしたか」を推定し、本人は夜に選択肢を1つ押すだけ。数週間たつと「こういう日は調子がいい」という *傾向* が、事実と数字だけで見えてきます。

> 自分用に毎日使うために作っています(ドッグフーディング)。Singularity Society BootCamp 応募作。

## なぜ作ったか

リングコン(スマートリング)のデータを Gmail に出して Claude で分析する仕組みは作れた。けれど **自分の主観や行動を手で記録するのが面倒で挫折した。** 「何を食べたか」「眠くなったか」を都度打ち込むのは続かない。

既存の AI ヘルスアプリ(Oura Advisor、WHOOP Coach、Wellness Project など)はウェアラブルの統合と AI コーチは備えているが、**主観と行動の入力はやはり手入力**。ここが続かない本当のボトルネックだと考え、「入力コストをほぼゼロにする」ことだけに賭けた。

## コンセプト

| 原則 | 実装 |
|---|---|
| 入力は「推定への選択」だけ | 決済通知の店名・金額から食事を推定し、「12:25 大戸屋 1,150円、定食でしたか?」と聞く |
| デバイスに依存しない | Android の Health Connect から読む。RingConn でも Oura でも Pixel Watch でも同じ |
| 決済 API に依存しない | Android の通知リスナーで PayPay・カード・マネーフォワードの通知を拾う。銀行の認証情報はアプリに持たせない |
| 1日3分 | 朝のひとこと(音声)、夜の確認カード 5枚前後、日中の質問は 0〜1回 |
| 指示しない | 「ラーメンの日は午後の HRV が 12% 低い(7回中6回)」と事実だけ。「どうすれば」はこちらから聞いたときだけ答える |

## 構成

```
android/   Kotlin 収集アプリ。Health Connect・使用状況統計・通知リスナー・位置を 15分ごとに同期
backend/   FastAPI。受信 → 日次タイムライン → Claude で推定カード生成 → 夜の確認 PWA → 週次の「傾向」
docs/      設計メモ、使用イメージ
```

```
RingConn / 時計 ─▶ Health Connect ─┐
PayPay / カード通知 ────────────────┤  Android 収集アプリ ──▶ /api/ingest ──▶ RawEvent (単一イベント表)
アプリ利用統計 ─────────────────────┤                                            │
位置(端末内で逆ジオコーディング) ──┘                                            ▼
Google カレンダー (秘密の iCal URL) ──────────────────────────▶ 日次コンテキスト ──▶ Claude ──▶ タイムライン + 確認カード
                                                                                    │
                                              夜の PWA で選択肢を押す ◀──────────────────┘
                                                        │
                                                        ▼
                                              週次: 事実と相関だけの「傾向」
```

### 推論バックエンド(差し替え可)

- `agent_sdk` : Claude Agent SDK。自分の Claude Code 契約で動かす個人用
- `api` : Anthropic API キー
- `rules` : LLM なしの決定論的フォールバック。オフラインでもデモでも壊れない

LLM 呼び出しが失敗したら自動で `rules` に落ちるので、確認カードは必ず出ます。

## デモを動かす(スマホ不要)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # mac/linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # APP_TOKEN と INFERENCE_BACKEND=rules にする
python scripts/seed_demo.py --days 21 --answer     # 3週間分の合成データ + 推定 + 回答 + 傾向
uvicorn app.main:app --reload
```

`http://localhost:8000/?token=<APP_TOKEN>` を開くと今夜の確認カードが出ます。

`DEMO_MODE=true` で起動すると `backend/demo/snapshot.json`(合成データに対して Claude が実際に生成した3週間分のカードと傾向)を日付をずらして再生します。公開デモはこの方式で、AI 費用ゼロで Claude 品質の出力を見せます。

## 本番(自分用)で動かす。全部無料

1. バックエンドを Render(無料枠)+ Neon(無料 Postgres)へ。リポジトリを Render の Blueprint として接続すると `render.yaml` から2サービス(本番・デモ)が立つ。cron-job.org で毎晩 `/api/jobs/evening` を叩いて休眠中のサーバーを起こす。手順は [docs/setup.md](docs/setup.md)
2. Android アプリをビルド: `cd android && ./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk` を端末へ
3. アプリでサーバー URL とトークンを保存し、4つの権限(Health Connect、使用状況、通知、位置)を一度だけ許可
4. RingConn アプリ側で Health Connect への書き込みを ON
5. 夜 22時にリマインド通知が来るので、2分だけ確認

## 1か月使うとこうなる

- **1週目**: AI がまだ「あなたの普通」を知らない。カードは 8枚くらい。訂正が多い
- **2週目**: 「いつものコンビニ朝食」「水曜のジム」を覚える。カードは 4〜5枚、ほぼ Yes を押すだけ
- **4週目**: 日曜に「午後に眠気を報告した日の昼食は 7回中6回が丼・麺類」のような、根拠付きの事実が 3〜4本出る

詳細は [docs/vision.md](docs/vision.md)。

## 技術メモ

- 全データは `RawEvent(source, kind, start, end, payload)` に正規化。新しいデバイスや決済アプリを足しても推論層は変わらない
- Android の **通知リスナー**と**使用状況統計 API** が、この設計を iPhone では不可能にしている Android 固有の武器
- 位置情報は端末内の Geocoder で住所化してから送る。座標を外部 API に投げない
- 会社 PC・会社データには触れない。カレンダーは個人の Google カレンダーの iCal URL のみ

## 状態

プロトタイプ。自分で毎日使いながら、ブートキャンプ期間中に以下を進める予定:

- [ ] Claude 推定の精度と質問の自然さ(まとめ払いの按分、いつもの習慣の学習)
- [ ] 日中のトリガー質問(食後の心拍変化、深夜利用のあと)を 1日1回まで
- [ ] 朝の音声メモを共有シートから直接投げる
- [ ] 「どうすれば?」と聞いたときの実験提案(N=1 自己実験)
- [ ] iPhone 版の現実的な縮退版(Health Auto Export + ショートカット)

## License

MIT
