```
  ███████╗███████╗ ██████╗ ██████╗
  ██╔════╝██╔════╝██╔═══██╗╚════██╗
  ███████╗█████╗  ██║   ██║ █████╔╝
  ╚════██║██╔══╝  ██║▄▄ ██║ ╚═══██╗
  ███████║███████╗╚██████╔╝██████╔╝
  ╚══════╝╚══════╝ ╚══▀▀═╝ ╚══════╝
       ██████╗ ██╗██████╗ ███████╗
       ██╔══██╗██║██╔══██╗██╔════╝
       ██████╔╝██║██████╔╝█████╗
       ██╔═══╝ ██║██╔═══╝ ██╔══╝
       ██║     ██║██║     ███████╗
       ╚═╝     ╚═╝╚═╝     ╚══════╝
          sequence  ->  pipeline
```

ローカル LLM（Ollama）を使って、生配列データから QIIME2 解析パイプラインを自動生成する AI エージェントです。
クラウド・API キー不要で、すべてあなたのマシン上で動作します。

---

## 概要

このツールは以下を自動で行います：

1. **データ構造の自動認識** — FASTQ・メタデータ・既存 QZA を調査
2. **解析パイプラインの生成** — データに合わせた QIIME2 コマンド群を生成
3. **スクリプトの書き出し** — すぐ実行できる `.sh` / `.ps1` スクリプトを出力
4. **操作ガイドの生成** — 可視化方法を含む `README.md` をデータに合わせて生成

---

## 必要なもの

| ソフトウェア | 用途 | インストール |
|---|---|---|
| Ollama | ローカル LLM の実行 | `setup.sh` / `setup.bat` で自動 |
| Docker Desktop | QIIME2 の実行環境 | [公式サイト](https://www.docker.com/products/docker-desktop/) |
| Python 3.9 以上 | エージェントスクリプト | 通常インストール済み |

**ディスク容量の目安:**

| 用途 | 容量 |
|---|---|
| LLM モデル（qwen2.5-coder:7b） | 約 4.7 GB |
| QIIME2 Docker イメージ | 約 4 GB |
| SILVA 138 参照ファイル | 約 30 GB |

---

## クイックスタート

### macOS

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # 初回のみ（Ollama + Docker Desktop を確認）
./launch.sh     # 起動
```

### Linux（Ubuntu / Debian / Fedora / Arch など）

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # 初回のみ（Ollama + Docker Engine を自動インストール）
./launch.sh     # 起動
```

> **Linux の注意点:**
> - `setup.sh` が Docker Engine を `curl -fsSL https://get.docker.com | sudo sh` でインストールします
> - インストール後、`newgrp docker` または再ログインが必要です
> - systemd がある場合は `sudo systemctl enable --now docker` で自動起動されます

### Windows

```
1. git clone https://github.com/Rhizobium-gits/seq2pipe.git
2. seq2pipe フォルダを開く
3. setup.bat をダブルクリック（初回のみ）
4. launch.bat をダブルクリックして起動
```

> PowerShell を使う場合：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> .\setup.ps1   # 初回のみ
> .\launch.ps1  # 起動
> ```

---

## ファイル構成

```
seq2pipe/
├── qiime2_agent.py   # AI エージェント本体（Python・外部依存なし）
│
├── launch.sh         # macOS / Linux 起動スクリプト
├── launch.ps1        # Windows 起動スクリプト（PowerShell）
├── launch.bat        # Windows 起動スクリプト（ダブルクリック用）
│
├── setup.sh          # macOS / Linux セットアップ
├── setup.ps1         # Windows セットアップ（PowerShell）
├── setup.bat         # Windows セットアップ（ダブルクリック用）
│
└── README.md         # このファイル
```

---

## エージェントとの対話例

```
AI: こんにちは！解析したいデータのディレクトリパスを教えてください。

あなた > /Users/yourname/microbiome-data/

[ツール実行: inspect_directory]
  -> ディレクトリ内容を自動調査...

AI: ペアエンドFASTQを16サンプル検出しました。
    V1-V3領域（27F/338R）用のパイプラインを生成します。
    どのような解析を行いたいですか？

あなた > 分類組成と多様性の両方やりたい

AI: 了解です。以下のファイルを生成します...
    -> manifest.tsv
    -> run_pipeline.sh
    -> setup_classifier.sh
    -> ANALYSIS_README.md
```

---

## 生成されるファイル

```
<あなたのデータディレクトリ>/
├── manifest.tsv              # QIIME2 インポート用マニフェスト
├── setup_classifier.sh       # SILVA 138 分類器のセットアップ
├── run_pipeline.sh           # 解析パイプライン全体
├── results/
│   ├── taxa-bar-plots.qzv    <- 分類組成バーチャート
│   ├── core-metrics-results/ <- 多様性解析
│   └── ancombc-results.qzv   <- 差次解析（オプション）
└── ANALYSIS_README.md        <- このデータ専用の操作ガイド
```

---

## 解析結果の可視化

QIIME2 の `.qzv` ファイルは **https://view.qiime2.org** をブラウザで開き、ファイルをドラッグ＆ドロップするだけで可視化できます。

| ファイル | 内容 |
|---|---|
| `taxa-bar-plots.qzv` | 分類組成の積み上げ棒グラフ |
| `emperor.qzv` | PCoA プロット（β多様性） |
| `shannon-significance.qzv` | α多様性のグループ比較 |
| `ancombc-results.qzv` | 差次解析結果 |

---

## SILVA 138 分類器のセットアップ（初回のみ、約 30GB・2〜5時間）

```bash
# macOS / Linux: エージェントが生成する setup_classifier.sh を実行
./setup_classifier.sh

# Windows（PowerShell）
.\setup_classifier.ps1
```

---

## トラブルシューティング

### Ollama に接続できない

```bash
# macOS / Linux
ollama serve

# Windows（PowerShell）
Start-Process ollama -ArgumentList "serve"
```

### モデルが重い / 遅い

```bash
# macOS / Linux
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh

# Windows（PowerShell）
$env:QIIME2_AI_MODEL = "qwen2.5-coder:3b"; .\launch.ps1
```

### Windows: 実行ポリシーエラー

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Linux: docker コマンドが permission denied

```bash
# ユーザーを docker グループに追加してから再ログイン
sudo usermod -aG docker $USER
newgrp docker
```

### Linux: Docker サービスが起動していない

```bash
sudo systemctl start docker
# 自動起動設定
sudo systemctl enable docker
```

### classify-sklearn でメモリエラー

Docker Desktop の設定でメモリを 8GB 以上に設定してから `--p-n-jobs 1` で再実行。
エージェントに「メモリエラーが出た。--p-n-jobs 1 で修正して」と伝えるだけで対応します。

---

## 使用モデル一覧

| モデル | RAM | 特徴 |
|---|---|---|
| qwen2.5-coder:7b | 8GB 以上 | コード生成に最適（推奨） |
| qwen2.5-coder:3b | 4GB 以上 | 軽量・高速 |
| llama3.2:3b | 4GB 以上 | 汎用・会話能力高め |
| qwen3:8b | 16GB 以上 | 最高品質・推論能力も高い |

---

## Contributors

| | Name | Role |
|---|---|---|
| [@Rhizobium-gits](https://github.com/Rhizobium-gits) | Rhizobium-gits | Author |
| [@claude-bot](https://github.com/claude-bot) | Claude (Anthropic) | Co-author — design & implementation |

---

## 参考リンク

- [QIIME2 公式ドキュメント](https://docs.qiime2.org/)
- [QIIME2 View（可視化サイト）](https://view.qiime2.org)
- [QIIME2 Forum](https://forum.qiime2.org/)
- [SILVA データベース](https://www.arb-silva.de/)
- [Ollama 公式サイト](https://ollama.com/)

---

## ライセンス

- このツール: MIT License
- SILVA 138 データ: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- QIIME2: BSD License
