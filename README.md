```
  ███████╗███████╗ ██████╗  ██████╗
  ██╔════╝██╔════╝██╔═══██╗╚════██╗
  ███████╗█████╗  ██║   ██║    ██╔╝
  ╚════██║██╔══╝  ██║▄▄ ██║   ██╔╝
  ███████║███████╗╚██████╔╝  ██████╗
  ╚══════╝╚══════╝ ╚══▀▀═╝   ╚═════╝
       ██████╗ ██╗██████╗ ███████╗
       ██╔══██╗██║██╔══██╗██╔════╝
       ██████╔╝██║██████╔╝█████╗
       ██╔═══╝ ██║██╔═══╝ ██╔══╝
       ██║     ██║██║     ███████╗
       ╚═╝     ╚═╝╚═╝     ╚══════╝
          sequence  ->  pipeline
```

> **ローカル LLM で QIIME2 マイクロバイオーム解析を自動化 — オフライン・API キー不要・オープンソース**

---

## 日本語 | [English](#english)

---

## これは何？

**seq2pipe** は、あなたの PC で動くローカル AI エージェントです。
生の FASTQ データを渡すだけで、QIIME2 解析パイプラインを **自動で設計・生成** します。

- データ構造を自動で調査（FASTQ / メタデータ / 既存 QZA）
- データに合った QIIME2 コマンドをゼロから組み立てる
- すぐ実行できる `.sh` / `.ps1` スクリプトを書き出す
- 可視化方法まで含む `ANALYSIS_README.md` を自動生成する

すべて **あなたのマシン上** で完結。クラウドや有料 API は一切使いません。

---

## 必要なもの

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9 以上 | 3.9 以上 | 3.9 以上 |
| Ollama | `setup.sh` で自動 | `setup.sh` で自動 | `setup.bat` で自動 |
| Docker | Docker Desktop | Docker Engine | Docker Desktop |
| RAM | 8 GB 以上推奨 | 8 GB 以上推奨 | 8 GB 以上推奨 |
| ディスク | 約 10 GB（LLM + QIIME2） | 約 10 GB | 約 10 GB |

---

## インストール（3 ステップ）

### macOS

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # 初回のみ
./launch.sh     # 起動
```

### Linux（Ubuntu / Debian / Fedora / Arch など）

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # 初回のみ（Docker Engine を自動インストール）
./launch.sh     # 起動
```

> Linux の場合、`setup.sh` 完了後に `newgrp docker` または再ログインが必要な場合があります。

### Windows

```
1. git clone https://github.com/Rhizobium-gits/seq2pipe.git
2. seq2pipe フォルダを開く
3. setup.bat をダブルクリック（初回のみ）
4. launch.bat をダブルクリックして起動
```

PowerShell を使う場合:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\setup.ps1   # 初回のみ
.\launch.ps1  # 起動
```

---

## 使い方

エージェントを起動すると、AI が対話形式でガイドします。

```
AI: こんにちは！解析したいデータのディレクトリパスを教えてください。

あなた > /Users/yourname/microbiome-data/

[ツール実行: inspect_directory]
  -> ディレクトリ内容を自動調査...

AI: ペアエンド FASTQ を 16 サンプル検出しました。
    V1-V3 領域（27F/338R）用のパイプラインを生成します。
    どのような解析を行いたいですか？

あなた > 分類組成と多様性の両方やりたい

AI: 了解です。以下のファイルを生成します...
    -> manifest.tsv
    -> run_pipeline.sh
    -> setup_classifier.sh
    -> ANALYSIS_README.md
```

### 生成されるファイル

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

### 解析結果の可視化

QIIME2 の `.qzv` ファイルは [https://view.qiime2.org](https://view.qiime2.org) にドラッグ＆ドロップするだけで確認できます。

| ファイル | 内容 |
|---|---|
| `taxa-bar-plots.qzv` | 分類組成の積み上げ棒グラフ |
| `emperor.qzv` | PCoA プロット（β 多様性） |
| `shannon-significance.qzv` | α 多様性のグループ比較 |
| `ancombc-results.qzv` | 差次解析結果 |

---

## 使用モデル

| モデル | RAM | 特徴 |
|---|---|---|
| `qwen2.5-coder:7b` | 8 GB 以上 | コード生成に最適（推奨） |
| `qwen2.5-coder:3b` | 4 GB 以上 | 軽量・高速 |
| `llama3.2:3b` | 4 GB 以上 | 汎用・会話能力高め |
| `qwen3:8b` | 16 GB 以上 | 最高品質・推論能力も高い |

別のモデルを使うには:

```bash
# macOS / Linux
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh

# Windows（PowerShell）
$env:QIIME2_AI_MODEL = "qwen2.5-coder:3b"; .\launch.ps1
```

---

## アーキテクチャ

```
あなた
  |
  v
[ launch.sh / launch.bat ]
  |
  v
[ qiime2_agent.py ]  <-- Python（外部依存なし）
  |
  +---> Ollama (localhost:11434)  <-- ローカル LLM
  |       |
  |       v
  |     [ LLM: qwen2.5-coder など ]
  |
  +---> ツール実行
          |
          +-- inspect_directory  (データ構造の調査)
          +-- read_file          (ファイル内容の確認)
          +-- write_file         (スクリプト・READMEの書き出し)
          +-- generate_manifest  (QIIME2 マニフェスト生成)
          +-- run_command        (Docker 経由で QIIME2 実行)
          +-- check_system       (環境確認)
```

---

## トラブルシューティング

<details>
<summary>Ollama に接続できない</summary>

```bash
# macOS / Linux
ollama serve

# Windows（PowerShell）
Start-Process ollama -ArgumentList "serve"
```

</details>

<details>
<summary>Docker が見つからない / 起動していない</summary>

- macOS / Windows: Docker Desktop を起動してください
- Linux: `sudo systemctl start docker`

QIIME2 コマンドを実際に実行しない場合（スクリプト生成のみ）、Docker は不要です。

</details>

<details>
<summary>Linux: docker コマンドが permission denied</summary>

```bash
sudo usermod -aG docker $USER
newgrp docker
```

</details>

<details>
<summary>Linux: Docker サービスが起動していない</summary>

```bash
sudo systemctl start docker
sudo systemctl enable docker   # 自動起動設定
```

</details>

<details>
<summary>モデルが重い / 応答が遅い</summary>

RAM が少ない場合は軽量モデルに切り替えてください:

```bash
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh
```

</details>

<details>
<summary>classify-sklearn でメモリエラー</summary>

Docker Desktop の設定でメモリを 8 GB 以上に増やし、エージェントに次のように伝えてください:

```
「メモリエラーが出た。--p-n-jobs 1 で修正して」
```

</details>

<details>
<summary>Windows: 実行ポリシーエラー</summary>

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

</details>

---

## ファイル構成

```
seq2pipe/
├── qiime2_agent.py   # AI エージェント本体（Python・外部依存なし）
├── launch.sh         # macOS / Linux 起動スクリプト
├── launch.ps1        # Windows 起動スクリプト（PowerShell）
├── launch.bat        # Windows 起動スクリプト（ダブルクリック用）
├── setup.sh          # macOS / Linux セットアップ
├── setup.ps1         # Windows セットアップ（PowerShell）
├── setup.bat         # Windows セットアップ（ダブルクリック用）
└── README.md         # このファイル
```

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

---
---

<a name="english"></a>

# English

```
  ███████╗███████╗ ██████╗  ██████╗
  ██╔════╝██╔════╝██╔═══██╗╚════██╗
  ███████╗█████╗  ██║   ██║    ██╔╝
  ╚════██║██╔══╝  ██║▄▄ ██║   ██╔╝
  ███████║███████╗╚██████╔╝  ██████╗
  ╚══════╝╚══════╝ ╚══▀▀═╝   ╚═════╝
       ██████╗ ██╗██████╗ ███████╗
       ██╔══██╗██║██╔══██╗██╔════╝
       ██████╔╝██║██████╔╝█████╗
       ██╔═══╝ ██║██╔═══╝ ██╔══╝
       ██║     ██║██║     ███████╗
       ╚═╝     ╚═╝╚═╝     ╚══════╝
          sequence  ->  pipeline
```

> **Automate QIIME2 microbiome analysis with a local LLM — offline, no API key, open source**

[日本語](#日本語--english)

---

## What is this?

**seq2pipe** is a local AI agent that runs entirely on your own machine.
Give it your raw FASTQ data, and it **automatically designs and generates** a complete QIIME2 analysis pipeline.

- Inspects your data structure automatically (FASTQ / metadata / existing QZA)
- Builds the right QIIME2 commands from scratch for your dataset
- Writes ready-to-run `.sh` / `.ps1` scripts
- Generates an `ANALYSIS_README.md` with visualization instructions

Everything runs **on your machine**. No cloud, no paid API, no internet required during analysis.

---

## Requirements

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9+ | 3.9+ | 3.9+ |
| Ollama | auto via `setup.sh` | auto via `setup.sh` | auto via `setup.bat` |
| Docker | Docker Desktop | Docker Engine | Docker Desktop |
| RAM | 8 GB+ recommended | 8 GB+ recommended | 8 GB+ recommended |
| Disk | ~10 GB (LLM + QIIME2) | ~10 GB | ~10 GB |

---

## Install (3 steps)

### macOS

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # first time only
./launch.sh     # start
```

### Linux (Ubuntu / Debian / Fedora / Arch etc.)

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # first time only (auto-installs Docker Engine)
./launch.sh     # start
```

> On Linux, you may need to run `newgrp docker` or log out and back in after `setup.sh` completes.

### Windows

```
1. git clone https://github.com/Rhizobium-gits/seq2pipe.git
2. Open the seq2pipe folder
3. Double-click setup.bat (first time only)
4. Double-click launch.bat to start
```

Using PowerShell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\setup.ps1   # first time only
.\launch.ps1  # start
```

---

## Usage

Start the agent and the AI will guide you interactively.

```
AI: Hello! Please tell me the directory path of the data you want to analyze.

You > /Users/yourname/microbiome-data/

[Tool: inspect_directory]
  -> Scanning directory contents...

AI: Detected paired-end FASTQ files from 16 samples.
    Generating a pipeline for the V1-V3 region (27F/338R).
    What kind of analysis would you like to perform?

You > I want both taxonomic composition and diversity analysis

AI: Got it. Generating the following files...
    -> manifest.tsv
    -> run_pipeline.sh
    -> setup_classifier.sh
    -> ANALYSIS_README.md
```

### Generated files

```
<your data directory>/
├── manifest.tsv              # QIIME2 import manifest
├── setup_classifier.sh       # SILVA 138 classifier setup
├── run_pipeline.sh           # Full analysis pipeline
├── results/
│   ├── taxa-bar-plots.qzv    <- Taxonomic composition bar chart
│   ├── core-metrics-results/ <- Diversity analysis
│   └── ancombc-results.qzv   <- Differential abundance (optional)
└── ANALYSIS_README.md        <- Data-specific operation guide
```

### Visualizing results

Drag and drop any `.qzv` file to [https://view.qiime2.org](https://view.qiime2.org) to visualize results in your browser.

| File | Content |
|---|---|
| `taxa-bar-plots.qzv` | Taxonomic composition stacked bar chart |
| `emperor.qzv` | PCoA plot (beta diversity) |
| `shannon-significance.qzv` | Alpha diversity group comparison |
| `ancombc-results.qzv` | Differential abundance results |

---

## Models

| Model | RAM | Description |
|---|---|---|
| `qwen2.5-coder:7b` | 8 GB+ | Best for code generation (recommended) |
| `qwen2.5-coder:3b` | 4 GB+ | Lightweight and fast |
| `llama3.2:3b` | 4 GB+ | General purpose, good conversation |
| `qwen3:8b` | 16 GB+ | Highest quality, strong reasoning |

To use a different model:

```bash
# macOS / Linux
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh

# Windows (PowerShell)
$env:QIIME2_AI_MODEL = "qwen2.5-coder:3b"; .\launch.ps1
```

---

## Architecture

```
You
  |
  v
[ launch.sh / launch.bat ]
  |
  v
[ qiime2_agent.py ]  <-- Python (no external dependencies)
  |
  +---> Ollama (localhost:11434)  <-- Local LLM
  |       |
  |       v
  |     [ LLM: qwen2.5-coder etc. ]
  |
  +---> Tool execution
          |
          +-- inspect_directory  (scan data structure)
          +-- read_file          (read file contents)
          +-- write_file         (write scripts & README)
          +-- generate_manifest  (create QIIME2 manifest)
          +-- run_command        (run QIIME2 via Docker)
          +-- check_system       (verify environment)
```

---

## Troubleshooting

<details>
<summary>Cannot connect to Ollama</summary>

```bash
# macOS / Linux
ollama serve

# Windows (PowerShell)
Start-Process ollama -ArgumentList "serve"
```

</details>

<details>
<summary>Docker not found / not running</summary>

- macOS / Windows: Start Docker Desktop
- Linux: `sudo systemctl start docker`

Docker is only needed to actually run QIIME2 commands. For script generation only, Docker is not required.

</details>

<details>
<summary>Linux: docker permission denied</summary>

```bash
sudo usermod -aG docker $USER
newgrp docker
```

</details>

<details>
<summary>Linux: Docker service not running</summary>

```bash
sudo systemctl start docker
sudo systemctl enable docker   # enable on boot
```

</details>

<details>
<summary>Model is slow / responses take too long</summary>

Switch to a lighter model if RAM is limited:

```bash
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh
```

</details>

<details>
<summary>classify-sklearn memory error</summary>

Increase Docker Desktop memory to 8 GB or more, then tell the agent:

```
"I got a memory error. Please fix it with --p-n-jobs 1"
```

</details>

<details>
<summary>Windows: execution policy error</summary>

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

</details>

---

## File structure

```
seq2pipe/
├── qiime2_agent.py   # AI agent core (Python, no external deps)
├── launch.sh         # macOS / Linux launcher
├── launch.ps1        # Windows launcher (PowerShell)
├── launch.bat        # Windows launcher (double-click)
├── setup.sh          # macOS / Linux setup
├── setup.ps1         # Windows setup (PowerShell)
├── setup.bat         # Windows setup (double-click)
└── README.md         # This file
```

---

## Contributors

| | Name | Role |
|---|---|---|
| [@Rhizobium-gits](https://github.com/Rhizobium-gits) | Rhizobium-gits | Author |
| [@claude-bot](https://github.com/claude-bot) | Claude (Anthropic) | Co-author — design & implementation |

---

## References

- [QIIME2 Official Documentation](https://docs.qiime2.org/)
- [QIIME2 View](https://view.qiime2.org)
- [QIIME2 Forum](https://forum.qiime2.org/)
- [SILVA Database](https://www.arb-silva.de/)
- [Ollama](https://ollama.com/)

---

## License

- This tool: MIT License
- SILVA 138 data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- QIIME2: BSD License
