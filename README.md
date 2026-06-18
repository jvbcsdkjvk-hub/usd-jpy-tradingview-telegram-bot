# USD/JPY TradingView Signal Bot

FOREXCOM:USDJPYを5分・1時間・4時間・日足で読み、売買候補を根拠付きで表示するローカルBOTです。注文は出しません。

## 起動

1. `start_bot.bat` をダブルクリックします。
2. 初回だけ専用環境と必要ライブラリを自動準備します。
3. ブラウザにダッシュボードが開き、以後60秒ごとに更新します。

Python 3.11以降がPCに未導入の場合のみ、先にPythonをインストールしてください。日常利用でPythonを手動起動する必要はありません。

## 判定の考え方

- 5分足40%: エントリータイミング
- 1時間足35%: 主方向
- 4時間足15%、日足10%: 大局のバイアス
- EMA 20/75/200、RSI、MACD、ボリンジャーバンド、ATR
- BOS、FVG、オーダーブロック、流動性スイープ、TradingViewの出来高

方向性は常に `LONG + SHORT = 100%` で表示します。LONGまたはSHORTが85%以上の場合だけ価格候補を表示し、それ以外はWAITです。シグナル時は現在価格をエントリー、5分足ATR×1.5を損切り幅、その2倍を利確幅として表示します。

## iPhoneから見る

PCとiPhoneを同じWi-Fiに接続し、画面に表示される「iPhone（同じWi-Fi）」のURLをiPhoneのSafariへ入力します。Windowsファイアウォールの確認が表示された場合は「プライベートネットワーク」を許可してください。外出先のモバイル回線からはアクセスできません。

## 注意事項

TradingViewのチャート用接続は公式の安定APIではないため、TradingView側の仕様変更で取得できなくなる可能性があります。エラー時は画面に時間足ごとの理由を表示します。FXの出来高は取引所全体の実出来高ではなく、データ提供元のティック出来高として扱ってください。

本ツールは分析支援用です。損失の可能性があり、シグナルや参考SL/TPは利益を保証しません。

## PCを切ってTelegram通知を受ける

`.github/workflows/telegram-signal.yml` をGitHub Actionsで動かすと、5分ごとに分析します。LONGまたはSHORTが85%以上になった場合だけTelegramへエントリー・利確・損切りを送り、同方向は30分のクールダウンを設けます。GitHubのRepository secretsへ `TELEGRAM_BOT_TOKEN` と `TELEGRAM_CHAT_ID` の登録が必要です。
