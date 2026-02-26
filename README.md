```
 ███████╗███████╗ ██████╗ ██████╗
 ██╔════╝██╔════╝██╔═══██╗╚════██╗
 ███████╗█████╗  ██║   ██║  ██╔═╝
 ╚════██║██╔══╝  ██║▄▄ ██║ ██╔╝
 ███████║███████╗╚██████╔╝██████╗
 ╚══════╝╚══════╝ ╚══▀▀═╝ ╚═════╝
 ██████╗ ██╗██████╗ ███████╗
 ██╔══██╗██║██╔══██╗██╔════╝
 ██████╔╝██║██████╔╝█████╗
 ██╔═══╝ ██║██╔═══╝ ██╔══╝
 ██║     ██║██║     ███████╗
 ╚═╝     ╚═╝╚═╝     ╚══════╝
      sequence -> pipeline
```

> **ローカル LLM で QIIME2 マイクロバイオーム解析を自動化 — オフライン・API キー不要・オープンソース**

---

## 日本語 | [English](#english)

---

## これは何？

**seq2pipe** は、あなたの PC で動くローカル AI エージェントです。
生の FASTQ データを渡すだけで、QIIME2 解析パイプラインの**設計・実行・Python 解析・レポート生成**まで自動で行います。

- **起動時に日本語 / 英語を選択**し、以降の AI 応答・レポートを統一
- 起動時に Python 依存パッケージ（numpy / pandas 等）の存在を自動確認
- データ構造を自動で調査（FASTQ / メタデータ / 既存 QZA）
- データに合った QIIME2 コマンドをゼロから組み立てる
- すぐ実行できる `.sh` / `.ps1` スクリプトを書き出す
- **2 つの操作モード**: チャット（自然言語でやりたい解析を指定）・自律エージェント（AI が自律的に全解析を設計・実行）
- **ツール呼び出し型コード生成エージェント（vibe-local 方式）**: LLM がまず `read_file` でデータの列名・形式を確認してからコードを生成するため精度が高く、エラーが出ても `NEVER GIVE UP` で自動修正を繰り返す
- QIIME2 の出力を **Python（pandas / scipy / scikit-learn / matplotlib）で高度解析**
- 解析図をすべて **PNG/PDF として自動保存**（view.qiime2.org 不要）
- **自律解析（chat_agent / InteractiveSession）**: α多様性・β多様性・DADA2 統計などを自動生成
- 解析終了後に **日本語・英語の TeX / PDF レポートを自動生成**

すべて **あなたのマシン上** で完結。クラウドや有料 API は一切使いません。

---

## デモ出力 — 実際の解析結果

ヒト便検体 10 サンプル（TEST01〜TEST10、凍結乾燥便、Illumina MiSeq ペアエンド V3-V4）を seq2pipe で解析した実際の出力です。

### α 多様性 — Shannon / Faith PD / Evenness / Observed Features

![Alpha Diversity](Figure/alpha_diversity.png)

### β 多様性 — Bray-Curtis PCoA

![Bray-Curtis PCoA](Figure/bray_curtis_pcoa.png)

### β 多様性 — UniFrac (unweighted) PCoA

![UniFrac PCoA](Figure/unifrac_pcoa.png)

### β 多様性 — Jaccard 距離ヒートマップ

![Jaccard Heatmap](Figure/jaccard_heatmap.png)

### DADA2 デノイジング統計

![DADA2 Stats](Figure/dada2_stats.png)

### Shannon 多様性（水平バイオリンプロット）

![Shannon Violin](Figure/shannon_violin.png)

> 上記すべての図と考察を含む PDF レポートを自動生成します: [analysis_report.pdf](Figure/analysis_report.pdf)

---

## 必要なもの

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9 以上 | 3.9 以上 | 3.9 以上 |
| Ollama | `setup.sh` で自動 | `setup.sh` で自動 | `setup.bat` で自動 |
| QIIME2 | conda 環境（推奨）または Docker | conda 環境または Docker Engine | Docker Desktop |
| Docker | 任意（QIIME2 conda env があれば不要） | 任意 | Docker Desktop |
| Python 解析パッケージ | QIIME2 conda env に含まれる | QIIME2 conda env に含まれる | 手動 pip |
| RAM | 8 GB 以上推奨 | 8 GB 以上推奨 | 8 GB 以上推奨 |
| ディスク | 約 10 GB（LLM + QIIME2） | 約 10 GB | 約 10 GB |

**Python 解析パッケージ**（`setup.sh` が自動インストール）:
`numpy`, `pandas`, `matplotlib`, `seaborn`, `scipy`, `scikit-learn`, `biom-format`, `networkx`, `statsmodels`

---

## インストール（3 ステップ）

### macOS

```bash
git clone https://github.com/Rhizobium-gits/seq2pipe.git
cd seq2pipe
chmod +x setup.sh launch.sh
./setup.sh      # 初回のみ（Ollama + Python パッケージ + Docker 確認）
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

Windows の Python 解析パッケージは手動でインストールしてください:

```powershell
pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels
```

---

## 起動方法

```bash
./launch.sh     # macOS / Linux
.\launch.bat    # Windows
```

起動すると言語選択（日本語 / English）の後、対話型ターミナルセッションが始まります。

> **ブラウザ GUI が必要な場合（任意）:** `app.py`（Streamlit）を利用できますが、ターミナル CLI が標準の使用方法です。

---

## 使い方

### QIIME2 パイプライン生成（CLI）

起動すると、まず言語を選択してから AI がパイプラインを自動生成します。

```
言語を選択してください / Select language:
  1. 日本語 (ja)
  2. English (en)
> 1

AI: こんにちは！以下を教えてください:
    1. データディレクトリのパス
    2. 実験系の説明（領域・プライマー・比較グループ）
    3. 行いたい解析
    4. 図のスタイル（省略可）

あなた > データ: /Users/yourname/microbiome-data/
         実験系: ヒト腸内細菌、16S V3-V4（341F/806R）、MiSeq PE 2×250bp
                 コントロール 5 サンプル vs 処理群 5 サンプル
         解析: 分類組成 + α/β 多様性 + 差次解析

[ツール実行: inspect_directory]
  -> ペアエンド FASTQ 10 サンプルを検出、metadata.tsv も確認...

AI: V3-V4 パイプラインを生成します。
    -> manifest.tsv, run_pipeline.sh, ANALYSIS_README.md
```

### 自律エージェントモード（モード 2 / --auto）

QIIME2 解析後、AI が自律的に多様性・統計図を全自動で生成します。

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --auto --manifest manifest.tsv

  🚀 STEP 1/2: QIIME2 パイプライン実行中
    -> dada2 denoise-paired, core-metrics-phylogenetic...
  ✅ パイプライン完了

  🤖 STEP 2/2: chat_agent 自律解析

  [Step 1] α 多様性 4 指標（2×2 グリッド）
  [Step 2] Bray-Curtis PCoA
  [Step 3] UniFrac PCoA
  [Step 4] Jaccard ヒートマップ
  [Step 5] DADA2 統計棒グラフ

  ✅ 自律解析完了！PDF レポート生成 → report_ja.pdf
```

### 解析モード（モード 1）- 自然言語でリクエスト

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --export-dir ~/seq2pipe_results/20260225_120000/exported/

やりたい解析を入力: Shannon 多様性をグループ別に violin plot で比較

[read_file]  alpha/shannon_vector.tsv（列名確認）
[write_file] analysis.py を生成
[run_python] EXIT CODE: 0
  -> figures/shannon_violin.png 保存

✅ 解析完了！
```

### 図のスタイル変更

```
あなた > 図を論文向けに 300 DPI の PNG に変えて

[ツール実行: set_plot_config]
  -> dpi: 300, format: png に変更
```

### 生成されるファイル

```
~/seq2pipe_results/<タイムスタンプ>/
├── exported/                 ← QIIME2 エクスポートデータ
│   ├── feature-table.tsv
│   ├── alpha/<指標>/alpha-diversity.tsv
│   ├── beta/<行列>/distance-matrix.tsv
│   └── denoising_stats/stats.tsv
├── figures/
│   ├── alpha_diversity.png   ← α 多様性 4 パネル
│   ├── bray_curtis_pcoa.png  ← Bray-Curtis PCoA
│   ├── unifrac_pcoa.png      ← UniFrac PCoA
│   ├── jaccard_heatmap.png   ← Jaccard ヒートマップ
│   ├── dada2_stats.png       ← DADA2 デノイジング統計
│   └── shannon_violin.png    ← Shannon バイオリン
└── report/
    ├── report_ja.tex         ← 日本語レポート（自動生成）
    └── report_ja.pdf         ← 日本語 PDF（全図入り）
```

---

## 対応解析一覧

### QIIME2 コア解析
| 解析 | コマンド |
|---|---|
| インポート・デマルチプレックス | `qiime tools import` |
| DADA2 デノイジング | `qiime dada2 denoise-paired/single` |
| 分類（SILVA 138） | `qiime feature-classifier classify-sklearn` |
| 分類組成バーチャート | `qiime taxa barplot` |
| α・β 多様性 | `qiime diversity core-metrics-phylogenetic` |
| 差次解析 ANCOM-BC | `qiime composition ancombc` |

### Python ダウンストリーム解析（chat_agent / code_agent — LLM 自動生成）
| 解析手法 | パッケージ |
|---|---|
| α 多様性 4 指標（Shannon / Faith PD / Evenness / Observed Features） | pandas, seaborn |
| Bray-Curtis PCoA（sklearn MDS） | pandas, sklearn |
| UniFrac PCoA（unweighted / weighted） | pandas, sklearn |
| Jaccard 距離ヒートマップ（seaborn clustermap） | pandas, seaborn |
| DADA2 デノイジング統計棒グラフ | pandas, matplotlib |
| Shannon バイオリンプロット | pandas, seaborn |
| 門・属レベル stacked bar（taxonomy あり） | pandas, seaborn |
| 属レベル heatmap（taxonomy あり） | pandas, seaborn |
| サンプル相関行列 | pandas, scipy, seaborn |
| TeX / PDF レポート自動生成 | tectonic |

---

## 環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `QIIME2_AI_MODEL` | `qwen2.5-coder:7b` | 使用する Ollama モデル |
| `SEQ2PIPE_AUTO_YES` | `0` | `1` にするとコマンド確認をスキップ（自律モード） |
| `SEQ2PIPE_MAX_STEPS` | `100` | エージェントループの最大ステップ数 |
| `SEQ2PIPE_PYTHON_TIMEOUT` | `600` | `execute_python` のタイムアウト秒数 |
| `QIIME2_CONDA_BIN` | 自動検出 | QIIME2 conda 環境の bin ディレクトリ（手動指定用） |

```bash
# 例: 自律モードで起動（確認なし）
SEQ2PIPE_AUTO_YES=1 ./launch.sh

# 例: QIIME2 conda env を手動指定
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

---

## 使用モデル

| モデル | RAM | 特徴 |
|---|---|---|
| `qwen2.5-coder:7b` | 8 GB 以上 | コード生成に最適（推奨） |
| `qwen2.5-coder:3b` | 4 GB 以上 | 軽量・高速 |
| `llama3.2:3b` | 4 GB 以上 | 汎用・会話能力高め |
| `qwen3:8b` | 16 GB 以上 | 最高品質・推論能力も高い |

### 小型モデルへの対応（ロバストネス機能）

7B 以下の小型モデルでは Ollama の tool_calls フォーマットに非対応のことがあります。
seq2pipe は以下の多層フォールバック機構でこれを自動的に補います:

1. **`_parse_text_tool_calls`**: テキスト本文に埋め込まれた JSON をツール呼び出しとして解析（5 パターン対応）
2. **Auto-inject `run_python`**: `write_file` で .py ファイルを書いた直後、モデルが `run_python` を呼ぶのを待たずに自動実行
3. **ステップ 6 フォールバック**: ツール呼び出しループが 5 ステップ進まない場合は自動的に 1 ショット生成（`run_code_agent`）に切り替え
4. **繰り返し検出**: 同じ 50 文字チャンクが 4 回連続したら生成を打ち切り（無限ループ回避）

別のモデルを使うには:

```bash
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh
```

---

## アーキテクチャ

```
あなた
  |
  v
[ launch.sh / cli.py ]  (任意: app.py Streamlit GUI)
        |
        v
[ pipeline_runner.py ]  ←─────────────────────→  [ qiime2_agent.py ]
  QIIME2 パイプライン実行                          QIIME2 コマンド生成
  (manifest モンキーパッチ対応)                    (11 ツール)
        |
        v
[ chat_agent.py / InteractiveSession ]
  自律解析セッション管理
  ├── plan_analysis_suite()  解析プランを LLM に生成させる
  ├── run_planned(analyses)  解析リストを順次実行
  └── generate_report()      TeX/PDF レポート生成
        |
        v
[ code_agent.py / run_code_agent() ]
  LLM コード生成 → サブプロセス実行 → エラー時自動修正（最大 3 回）
  ├── _ensure_required_imports()  plt/pd の自動補完
  ├── ModuleNotFoundError 検出 → install_callback でユーザー確認
  └── 実行成功 + 図生成確認 → CodeExecutionResult 返却
        |
        v
  Ollama (localhost:11434)  ← ローカル LLM
```

---

## トラブルシューティング

<details>
<summary>Ollama に接続できない</summary>

```bash
ollama serve
```

</details>

<details>
<summary>QIIME2 conda 環境が自動検出されない</summary>

```bash
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

自動検出される候補: `~/miniforge3/envs/qiime2/bin`, `~/miniconda3/envs/qiime2/bin`, `~/anaconda3/envs/qiime2/bin`

</details>

<details>
<summary>Docker が見つからない / 起動していない</summary>

QIIME2 conda 環境が検出されている場合、Docker は不要です。

- macOS / Windows: Docker Desktop を起動してください
- Linux: `sudo systemctl start docker`

</details>

<details>
<summary>Python 解析パッケージが足りない</summary>

```bash
pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels
```

</details>

<details>
<summary>tectonic（PDF コンパイル）が見つからない</summary>

```bash
# macOS
brew install tectonic

# Linux
curl --proto '=https' --tlsv1.2 -fsSL https://drop.rs/tectonic | sh
```

</details>

<details>
<summary>モデルが重い / 応答が遅い</summary>

```bash
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh
```

</details>

<details>
<summary>Streamlit が起動しない</summary>

```bash
~/miniforge3/envs/qiime2/bin/pip install streamlit
~/miniforge3/envs/qiime2/bin/streamlit run app.py
```

</details>

---

## ファイル構成

```
seq2pipe/
├── cli.py             # ターミナル エントリーポイント（虹色バナー・モード選択）
├── chat_agent.py      # 自律解析セッション管理 + TeX/PDF レポート生成
├── app.py             # Streamlit ブラウザ GUI（任意）
├── qiime2_agent.py    # QIIME2 パイプライン生成エージェント（11 ツール）
├── pipeline_runner.py # QIIME2 実行ラッパー + 結果エクスポート
├── code_agent.py      # LLM コード生成エージェント（vibe-local 方式）
├── _run_pipeline.py   # フルパイプライン実行スクリプト（バッチ用）
├── _run_analysis.py   # 解析のみ実行スクリプト（既存エクスポート用）
├── Figure/            # デモ出力図（実データ解析結果）
│   ├── alpha_diversity.png
│   ├── bray_curtis_pcoa.png
│   ├── unifrac_pcoa.png
│   ├── jaccard_heatmap.png
│   ├── dada2_stats.png
│   ├── shannon_violin.png
│   └── analysis_report.pdf
├── Paper/             # 技術レポート（TeX / PDF）
│   ├── seq2pipe_ja.tex / seq2pipe_ja.pdf
│   └── seq2pipe_en.tex / seq2pipe_en.pdf
├── launch.sh          # macOS / Linux 起動スクリプト
├── launch.ps1         # Windows 起動スクリプト（PowerShell）
├── launch.bat         # Windows 起動スクリプト（ダブルクリック用）
├── setup.sh           # macOS / Linux セットアップ
├── setup.ps1          # Windows セットアップ（PowerShell）
├── setup.bat          # Windows セットアップ（ダブルクリック用）
├── LICENSE            # MIT License
└── README.md          # このファイル
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
- [QIIME2 View（インタラクティブ可視化）](https://view.qiime2.org)
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
 ███████╗███████╗ ██████╗ ██████╗
 ██╔════╝██╔════╝██╔═══██╗╚════██╗
 ███████╗█████╗  ██║   ██║  ██╔═╝
 ╚════██║██╔══╝  ██║▄▄ ██║ ██╔╝
 ███████║███████╗╚██████╔╝██████╗
 ╚══════╝╚══════╝ ╚══▀▀═╝ ╚═════╝
 ██████╗ ██╗██████╗ ███████╗
 ██╔══██╗██║██╔══██╗██╔════╝
 ██████╔╝██║██████╔╝█████╗
 ██╔═══╝ ██║██╔═══╝ ██╔══╝
 ██║     ██║██║     ███████╗
 ╚═╝     ╚═╝╚═╝     ╚══════╝
      sequence -> pipeline
```

> **Automate QIIME2 microbiome analysis with a local LLM — offline, no API key, open source**

[日本語](#日本語--english)

---

## What is this?

**seq2pipe** is a local AI agent that runs entirely on your own machine.
Give it your raw FASTQ data, and it automatically handles **pipeline design, execution, Python analysis, and report generation**.

- **Select Japanese or English at startup** — all AI responses and reports follow your choice
- Automatically checks for required Python packages (numpy / pandas / etc.) at startup
- Inspects your data structure automatically (FASTQ / metadata / existing QZA)
- Builds the right QIIME2 commands from scratch for your dataset
- Writes ready-to-run `.sh` / `.ps1` scripts
- **Two operation modes**: Chat (specify analysis in natural language) · Autonomous agent (AI designs and runs all analyses)
- **Tool-calling code generation agent (vibe-local style)**: LLM first calls `read_file` to understand column names and data format before writing code — far fewer format errors; if an error occurs, `NEVER GIVE UP` — it rewrites and retries until EXIT CODE: 0
- Runs **Python downstream analysis** (pandas / scipy / scikit-learn / matplotlib) on QIIME2 outputs
- **Auto-saves all figures as PNG/PDF** — no need for view.qiime2.org
- **Autonomous analysis (chat_agent / InteractiveSession)**: Auto-generates α/β diversity, DADA2 statistics, and more
- **Auto-generates Japanese and English TeX / PDF reports**

Everything runs **on your machine**. No cloud, no paid API, no internet required during analysis.

---

## Demo Output — Real Analysis Results

Actual output from seq2pipe on 10 human stool samples (TEST01–TEST10, freeze-dried, Illumina MiSeq paired-end V3-V4):

### Alpha Diversity — Shannon / Faith PD / Evenness / Observed Features

![Alpha Diversity](Figure/alpha_diversity.png)

### Beta Diversity — Bray-Curtis PCoA

![Bray-Curtis PCoA](Figure/bray_curtis_pcoa.png)

### Beta Diversity — UniFrac (unweighted) PCoA

![UniFrac PCoA](Figure/unifrac_pcoa.png)

### Beta Diversity — Jaccard Distance Heatmap

![Jaccard Heatmap](Figure/jaccard_heatmap.png)

### DADA2 Denoising Statistics

![DADA2 Stats](Figure/dada2_stats.png)

### Shannon Diversity (Horizontal Violin Plot)

![Shannon Violin](Figure/shannon_violin.png)

> An automatically generated PDF report including all figures and discussion: [analysis_report.pdf](Figure/analysis_report.pdf)

---

## Requirements

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9+ | 3.9+ | 3.9+ |
| Ollama | auto via `setup.sh` | auto via `setup.sh` | auto via `setup.bat` |
| QIIME2 | conda env (recommended) or Docker | conda env or Docker Engine | Docker Desktop |
| Docker | Optional (not needed if QIIME2 conda env exists) | Optional | Docker Desktop |
| Python analysis packages | included in QIIME2 conda env | included in QIIME2 conda env | manual pip |
| RAM | 8 GB+ recommended | 8 GB+ recommended | 8 GB+ recommended |
| Disk | ~10 GB (LLM + QIIME2) | ~10 GB | ~10 GB |

**Python analysis packages** (auto-installed by `setup.sh`):
`numpy`, `pandas`, `matplotlib`, `seaborn`, `scipy`, `scikit-learn`, `biom-format`, `networkx`, `statsmodels`

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

Install Python packages manually on Windows:

```powershell
pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels
```

---

## Launch

```bash
./launch.sh     # macOS / Linux
.\launch.bat    # Windows
```

After launching, select your language (Japanese / English) and an interactive terminal session begins.

> **Optional browser GUI:** `app.py` (Streamlit) is available for those who prefer a browser interface, but the terminal CLI is the standard way to use seq2pipe.

---

## Usage

### Autonomous agent mode (--auto)

After QIIME2, the AI autonomously generates diversity and statistics figures.

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --auto --manifest manifest.tsv

  🚀 STEP 1/2: Running QIIME2 pipeline
    -> dada2 denoise-paired, core-metrics-phylogenetic...
  ✅ Pipeline complete

  🤖 STEP 2/2: chat_agent autonomous analysis

  [Step 1] Alpha diversity 4-panel (2×2 grid)
  [Step 2] Bray-Curtis PCoA
  [Step 3] UniFrac PCoA
  [Step 4] Jaccard heatmap
  [Step 5] DADA2 denoising statistics

  ✅ Analysis complete! PDF report → report_ja.pdf
```

### Analysis mode (Mode 1) — natural language requests

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --export-dir ~/seq2pipe_results/.../exported/

Enter request: Shannon diversity violin plot by group

[read_file]  alpha/shannon_vector.tsv (check column names)
[write_file] analysis.py
[run_python] EXIT CODE: 0 → figures/shannon_violin.png

✅ Analysis complete!
```

### Output file structure

```
~/seq2pipe_results/<timestamp>/
├── exported/                  ← QIIME2 exported data
│   ├── feature-table.tsv
│   ├── alpha/<metric>/alpha-diversity.tsv
│   ├── beta/<matrix>/distance-matrix.tsv
│   └── denoising_stats/stats.tsv
├── figures/
│   ├── alpha_diversity.png    ← Alpha diversity 4-panel
│   ├── bray_curtis_pcoa.png   ← Bray-Curtis PCoA
│   ├── unifrac_pcoa.png       ← UniFrac PCoA
│   ├── jaccard_heatmap.png    ← Jaccard heatmap
│   ├── dada2_stats.png        ← DADA2 denoising statistics
│   └── shannon_violin.png     ← Shannon violin plot
└── report/
    ├── report_ja.tex          ← Japanese report (auto-generated)
    └── report_ja.pdf          ← Japanese PDF (all figures included)
```

---

## Supported analyses

### QIIME2 core
| Analysis | Command |
|---|---|
| Import & demultiplex | `qiime tools import` |
| DADA2 denoising | `qiime dada2 denoise-paired/single` |
| Taxonomic classification (SILVA 138) | `qiime feature-classifier classify-sklearn` |
| Composition bar chart | `qiime taxa barplot` |
| Alpha & beta diversity | `qiime diversity core-metrics-phylogenetic` |
| Differential abundance ANCOM-BC | `qiime composition ancombc` |

### Python downstream (chat_agent / code_agent — LLM auto-generated)
| Analysis | Packages |
|---|---|
| Alpha diversity 4-panel (Shannon / Faith PD / Evenness / Observed Features) | pandas, seaborn |
| Bray-Curtis PCoA (sklearn MDS) | pandas, sklearn |
| UniFrac PCoA (unweighted / weighted) | pandas, sklearn |
| Jaccard distance heatmap (seaborn clustermap) | pandas, seaborn |
| DADA2 denoising statistics bar chart | pandas, matplotlib |
| Shannon violin plot | pandas, seaborn |
| Phylum/genus stacked bar (with taxonomy) | pandas, seaborn |
| Genus-level heatmap (with taxonomy) | pandas, seaborn |
| Sample correlation matrix | pandas, scipy, seaborn |
| TeX / PDF report auto-generation | tectonic |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `QIIME2_AI_MODEL` | `qwen2.5-coder:7b` | Ollama model to use |
| `SEQ2PIPE_AUTO_YES` | `0` | Set to `1` to skip command confirmation (autonomous mode) |
| `SEQ2PIPE_MAX_STEPS` | `100` | Maximum agent loop steps |
| `SEQ2PIPE_PYTHON_TIMEOUT` | `600` | Timeout in seconds for `execute_python` |
| `QIIME2_CONDA_BIN` | auto-detected | Path to QIIME2 conda env bin directory (manual override) |

---

## Models

| Model | RAM | Description |
|---|---|---|
| `qwen2.5-coder:7b` | 8 GB+ | Best for code generation (recommended) |
| `qwen2.5-coder:3b` | 4 GB+ | Lightweight and fast |
| `llama3.2:3b` | 4 GB+ | General purpose, good conversation |
| `qwen3:8b` | 16 GB+ | Highest quality, strong reasoning |

---

## Architecture

```
You
  |
  v
[ launch.sh / cli.py ]  (optional: app.py Streamlit GUI)
        |
        v
[ pipeline_runner.py ]  ←─────────────────────→  [ qiime2_agent.py ]
  QIIME2 pipeline execution                        QIIME2 command generation
  (manifest monkey-patch support)                  (11 tools)
        |
        v
[ chat_agent.py / InteractiveSession ]
  Autonomous analysis session management
  ├── plan_analysis_suite()   LLM generates analysis plan
  ├── run_planned(analyses)   Execute analysis steps in sequence
  └── generate_report()       Build TeX/PDF report
        |
        v
[ code_agent.py / run_code_agent() ]
  LLM code generation → subprocess execution → auto-fix on error (max 3 retries)
  ├── _ensure_required_imports()  auto-inject plt/pd if missing
  ├── ModuleNotFoundError → install_callback for user approval
  └── success + figure check → return CodeExecutionResult
        |
        v
  Ollama (localhost:11434)  ← Local LLM
```

---

## Troubleshooting

<details>
<summary>Cannot connect to Ollama</summary>

```bash
ollama serve
```

</details>

<details>
<summary>QIIME2 conda env not detected automatically</summary>

```bash
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

</details>

<details>
<summary>Docker not found / not running</summary>

Docker is not required if a QIIME2 conda env is detected.

- macOS / Windows: Start Docker Desktop
- Linux: `sudo systemctl start docker`

</details>

<details>
<summary>Python analysis packages missing</summary>

```bash
pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels
```

</details>

<details>
<summary>tectonic (PDF compilation) not found</summary>

```bash
# macOS
brew install tectonic

# Linux
curl --proto '=https' --tlsv1.2 -fsSL https://drop.rs/tectonic | sh
```

</details>

<details>
<summary>Streamlit won't start</summary>

```bash
~/miniforge3/envs/qiime2/bin/pip install streamlit
~/miniforge3/envs/qiime2/bin/streamlit run app.py
```

</details>

---

## File structure

```
seq2pipe/
├── cli.py             # Terminal entry point (rainbow banner / mode selection)
├── chat_agent.py      # Autonomous analysis session + TeX/PDF report
├── app.py             # Streamlit browser GUI (optional)
├── qiime2_agent.py    # QIIME2 pipeline generation agent (11 tools)
├── pipeline_runner.py # QIIME2 execution wrapper + result export
├── code_agent.py      # LLM code generation agent (vibe-local style)
├── _run_pipeline.py   # Full pipeline batch script
├── _run_analysis.py   # Analysis-only batch script (for existing exports)
├── Figure/            # Demo output figures (real data analysis results)
│   ├── alpha_diversity.png
│   ├── bray_curtis_pcoa.png
│   ├── unifrac_pcoa.png
│   ├── jaccard_heatmap.png
│   ├── dada2_stats.png
│   ├── shannon_violin.png
│   └── analysis_report.pdf
├── Paper/             # Technical report (TeX / PDF)
│   ├── seq2pipe_ja.tex / seq2pipe_ja.pdf
│   └── seq2pipe_en.tex / seq2pipe_en.pdf
├── launch.sh          # macOS / Linux launcher
├── launch.ps1         # Windows launcher (PowerShell)
├── launch.bat         # Windows launcher (double-click)
├── setup.sh           # macOS / Linux setup
├── setup.ps1          # Windows setup (PowerShell)
├── setup.bat          # Windows setup (double-click)
├── LICENSE            # MIT License
└── README.md          # This file
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
- [QIIME2 View (interactive visualization)](https://view.qiime2.org)
- [QIIME2 Forum](https://forum.qiime2.org/)
- [SILVA Database](https://www.arb-silva.de/)
- [Ollama](https://ollama.com/)

---

## License

- This tool: MIT License
- SILVA 138 data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- QIIME2: BSD License
