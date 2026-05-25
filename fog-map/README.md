# 霧の地図 🗺️

歩いた場所だけが現れる探索地図。Googleアカウントでログインし、自分だけの地図を作れます。

## ファイル構成

```
fog-map/
├── app.py               # Flask バックエンド
├── requirements.txt     # 依存パッケージ
├── .env.example         # 環境変数テンプレート
├── templates/
│   ├── index.html       # メインUI
│   └── login.html       # ログイン画面
└── README.md
```

---

## セットアップ手順

### 1. Google OAuth クライアントを取得する

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. プロジェクトを作成 → 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuthクライアントID」
3. アプリの種類: **ウェブアプリケーション**
4. 承認済みリダイレクトURIに以下を追加:
   - ローカル開発用: `http://localhost:5000/login/google/authorized`
   - VPS公開用: `https://あなたのドメイン/login/google/authorized`
5. クライアントID と クライアントシークレット をコピー

### 2. 環境変数を設定する

```bash
cp .env.example .env
```

`.env` をテキストエディタで開き、取得した値を入力:

```
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
SECRET_KEY=（下記コマンドで生成）
```

`SECRET_KEY` の生成:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. パッケージをインストールして起動

```bash
py -m pip install -r requirements.txt   # Windows
# または
pip install -r requirements.txt          # Mac/Linux

py app.py   # Windows
python app.py  # Mac/Linux
```

ブラウザで `http://localhost:5000` を開く

---

## VPS（外部公開）での運用

### HTTPS の設定（必須）

Google OAuth は HTTPS が必須です。Nginx + Let's Encrypt での設定を推奨します。

`.env` から以下の行を**削除**してください（HTTPSなら不要）:

```
OAUTHLIB_INSECURE_TRANSPORT=1
```

### gunicorn で起動

```bash
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### Nginx 設定例 (`/etc/nginx/sites-available/fogmap`)

```nginx
server {
    listen 80;
    server_name あなたのドメイン;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name あなたのドメイン;

    ssl_certificate     /etc/letsencrypt/live/あなたのドメイン/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/あなたのドメイン/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### systemd で自動起動 (`/etc/systemd/system/fogmap.service`)

```ini
[Unit]
Description=霧の地図
After=network.target

[Service]
WorkingDirectory=/path/to/fog-map
ExecStart=/path/to/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
Restart=always
EnvironmentFile=/path/to/fog-map/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable fogmap
sudo systemctl start fogmap
```

---

## 使い方

| 操作                    | 説明                              |
| ----------------------- | --------------------------------- |
| ログイン                | Googleアカウントで認証            |
| 歩く                    | 移動するごとに半径10mの霧が晴れる |
| 「ピン追加」→地図タップ | ピンを立てて場所を記録            |
| ピンをタップ            | 名前・メモを表示・編集・削除      |
| 「霧の表示」            | 霧のON/OFF切り替え                |
| 「記録」                | 登録した場所の一覧を表示          |
| アバター画像タップ      | ログアウト・記録リスト            |

探索地点は15秒ごとにサーバーへ保存されます。
次回ログイン時に以前探索した範囲が自動で復元されます。

---

## 写真機能について

### 使い方

1. ツールバーの「撮影」ボタンをタップ → 地図がカメラモードになる
2. 地図上の撮影した場所をタップ → カメラシートが開く
3. シャッターボタンで撮影 → メモを入力して「保存」
4. 地図上に写真サムネイルが表示される

### 仕組み

- 写真は `uploads/` フォルダにJPEGで保存される（ユーザーIDプレフィックスで分離）
- Pillowがインストールされている場合、320px サムネイルも自動生成される
- 地図マーカーはサムネイルを使用するため高速表示される
- タップで拡大ビューワーが開き、撮影日時・メモ・地図上の場所へのジャンプが可能

### VPS運用時の注意

- `uploads/` フォルダのバックアップを忘れずに
- ディスク容量に注意（写真1枚あたり数百KB〜数MB）
- Nginxで直接配信する場合は `/uploads/` を `proxy_pass` から除外してください
