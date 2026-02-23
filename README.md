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
生の FASTQ データを渡すだけで、QIIME2 解析パイプラインの**設計・実行・Python 解析・レポート生成**まで自動で行います。

- データ構造を自動で調査（FASTQ / メタデータ / 既存 QZA）
- データに合った QIIME2 コマンドをゼロから組み立てる
- すぐ実行できる `.sh` / `.ps1` スクリプトを書き出す
- QIIME2 の出力を **Python（pandas / scipy / scikit-learn / matplotlib）で高度解析**
- 解析図をすべて **PDF として自動保存**（view.qiime2.org 不要）
- **自律探索モード**: α多様性・β多様性・分類組成・差次解析・機械学習を AI が自動で順番に実行
- 解析終了後に **日本語・英語の TeX / PDF レポートを自動生成**（`build_report_tex` が ANALYSIS_LOG から自動構築）

すべて **あなたのマシン上** で完結。クラウドや有料 API は一切使いません。

---

## 必要なもの

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9 以上 | 3.9 以上 | 3.9 以上 |
| Ollama | `setup.sh` で自動 | `setup.sh` で自動 | `setup.bat` で自動 |
| Docker | Docker Desktop | Docker Engine | Docker Desktop |
| Python 解析パッケージ | `setup.sh` で自動 | `setup.sh` で自動 | 手動 pip |
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

## 使い方

### QIIME2 パイプライン生成

起動すると、AI が情報を確認してパイプラインを自動生成します。

```
AI: こんにちは！以下を教えてください:
    1. データディレクトリのパス
    2. 実験系の説明（領域・プライマー・比較グループ）
    3. 行いたい解析
    4. 図のスタイル（省略可）

あなた > データ: /Users/yourname/microbiome-data/
         実験系: ヒト腸内細菌、16S V3-V4（341F/806R）、MiSeq PE 2×250bp
                 コントロール 5 サンプル vs 処理群 5 サンプル
         解析: 分類組成 + α/β 多様性 + 差次解析
         スタイル: 白背景・青系カラー

[ツール実行: inspect_directory]
  -> ペアエンド FASTQ 10 サンプルを検出、metadata.tsv も確認...

[ツール実行: set_plot_config]
  -> style: seaborn-v0_8-whitegrid, palette: Blues に設定

AI: V3-V4 パイプラインを生成します。
    trim-left-f=17, trunc-f=270 を適用。
    -> manifest.tsv, run_pipeline.sh, setup_classifier.sh, ANALYSIS_README.md
```

### 自律探索モード（推奨）

QIIME2 解析後、AI が自動で 5 フェーズの探索を実行します。ユーザーは確認不要です。

```
あなた > /data/results/ を使って全ての基本解析を自動で探索して

AI: 自律探索モードを開始します。5 フェーズを順番に実行します。

[Phase 1: α多様性] -----
[ツール実行: execute_python | subfolder=alpha_diversity]
  -> Shannon / Simpson / Chao1 指数を計算
  -> Mann-Whitney U / Kruskal-Wallis 検定
  -> ~/seq2pipe_results/20260223/figures/alpha_diversity/ に保存

[Phase 2: β多様性] -----
[ツール実行: execute_python | subfolder=beta_diversity]
  -> Bray-Curtis PCoA + 信頼楕円
  -> PERMANOVA (R²、p 値)
  -> ~/seq2pipe_results/20260223/figures/beta_diversity/ に保存

[Phase 3: 分類組成] -----
[ツール実行: execute_python | subfolder=taxonomy]
  -> 門・属レベルの stacked bar chart + heatmap
  -> ~/seq2pipe_results/20260223/figures/taxonomy/ に保存

[Phase 4: 差次存在量] -----
[ツール実行: execute_python | subfolder=differential_abundance]
  -> 全 ASV に Mann-Whitney U、Benjamini-Hochberg 補正
  -> volcano plot（FDR < 0.05 を赤でハイライト）
  -> ~/seq2pipe_results/20260223/figures/differential_abundance/ に保存

[Phase 5: 機械学習] -----
[ツール実行: execute_python | subfolder=machine_learning]
  -> Random Forest 5-fold CV (AUC, accuracy)
  -> 重要特徴量 top 20 の horizontal bar chart
  -> ~/seq2pipe_results/20260223/figures/machine_learning/ に保存

[ツール実行: build_report_tex]
  -> ANALYSIS_LOG から TeX を自動構築（LLM 不使用）
  -> report_ja.pdf / report_en.pdf を生成
  -> ~/seq2pipe_results/20260223/report/ に保存
```

### Python ダウンストリーム解析（手動）

QIIME2 の結果を受け取ったら、そのまま Python 解析を続けられます。

```
あなた > shannon 多様性をグループ別に violin plot で比較して、
         Mann-Whitney U 検定の p 値も表示して

[ツール実行: execute_python]
  -> QIIME2 出力から shannon_vector.qza を読み込み
  -> violin plot 生成、統計検定実行
  -> ~/seq2pipe_results/20260223/figures/shannon_violin.pdf に保存

AI: Shannon 多様性の violin plot を生成しました。
    Treatment 群で有意に高く、p = 0.023（Mann-Whitney U）

あなた > Bray-Curtis の PCoA を PERMANOVA 結果付きで出して

[ツール実行: execute_python]
  -> PCoA scatter plot + ellipse 生成
  -> ~/seq2pipe_results/20260223/figures/pcoa_bray_curtis.pdf に保存

あなた > 全解析のレポートを日本語と英語で PDF 出力して

[ツール実行: build_report_tex]
  -> ANALYSIS_LOG から TeX を自動構築
  -> report_ja.pdf / report_en.pdf を生成
```

### 図のスタイル変更

いつでも変更できます。以降の図すべてに即時反映されます。

```
あなた > 図を論文向けに 300 DPI の PNG に変えて

[ツール実行: set_plot_config]
  -> dpi: 300, format: png に変更
```

### 生成されるファイル

```
<データディレクトリ>/
├── manifest.tsv              # QIIME2 インポート用マニフェスト
├── setup_classifier.sh       # SILVA 138 分類器のセットアップ
├── run_pipeline.sh           # 解析パイプライン全体
├── results/
│   ├── table.qza             <- OTU/ASV テーブル
│   ├── taxonomy.qza          <- 分類結果
│   ├── core-metrics-results/ <- 多様性解析
│   └── ancombc-results.qza   <- 差次解析（オプション）
└── ANALYSIS_README.md        <- このデータ専用の操作ガイド

~/seq2pipe_results/<タイムスタンプ>/        <- セッションごとに自動作成
├── figures/
│   ├── alpha_diversity/      <- Phase 1: α多様性（Shannon, Simpson, Chao1）
│   │   ├── alpha_boxplot.pdf
│   │   └── alpha_stats.pdf
│   ├── beta_diversity/       <- Phase 2: β多様性（PCoA, PERMANOVA）
│   │   └── pcoa_bray_curtis.pdf
│   ├── taxonomy/             <- Phase 3: 分類組成（bar chart, heatmap）
│   │   ├── taxonomy_barplot.pdf
│   │   └── taxonomy_heatmap.pdf
│   ├── differential_abundance/ <- Phase 4: 差次解析（volcano plot）
│   │   └── volcano_plot.pdf
│   ├── machine_learning/     <- Phase 5: 機械学習（RF, AUC, feature importance）
│   │   └── feature_importance.pdf
│   └── <その他手動解析の図>
└── report/
    ├── report_ja.tex / report_ja.pdf   <- 日本語レポート（自動生成）
    └── report_en.tex / report_en.pdf   <- 英語レポート（自動生成）
```

### 解析結果の確認

| 出力 | 確認方法 |
|---|---|
| Python 生成の図（.pdf / .png） | そのまま開ける（PDF viewer / 画像ビューア） |
| QIIME2 の `.qzv`（インタラクティブ可視化） | [https://view.qiime2.org](https://view.qiime2.org) にドロップ |
| レポート PDF | PDF viewer で開く |

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

### Python ダウンストリーム解析
| フェーズ | 解析 | パッケージ |
|---|---|---|
| Phase 1 (alpha_diversity) | Shannon / Simpson / Chao1 + 統計検定 | pandas, scipy, seaborn |
| Phase 2 (beta_diversity) | Bray-Curtis PCoA + PERMANOVA | pandas, matplotlib, scipy |
| Phase 3 (taxonomy) | 分類組成 stacked bar + heatmap（門・属） | pandas, seaborn |
| Phase 4 (differential_abundance) | 全 ASV 差次解析 + BH 補正 + volcano plot | scipy, statsmodels |
| Phase 5 (machine_learning) | Random Forest 5-fold CV + feature importance | scikit-learn |
| 手動 | co-occurrence ネットワーク | networkx, scipy |
| レポート | ANALYSIS_LOG → TeX → PDF 自動構築 | tectonic（TeX → PDF） |

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
[ qiime2_agent.py ]
  |
  +---> Ollama (localhost:11434)  <-- ローカル LLM
  |       |
  |       v
  |     [ LLM: qwen2.5-coder など ]
  |         |
  |         v（自律探索モード）
  |       Phase 1: alpha_diversity
  |       Phase 2: beta_diversity
  |       Phase 3: taxonomy
  |       Phase 4: differential_abundance
  |       Phase 5: machine_learning
  |
  +---> ツール実行
          |
          +-- inspect_directory  (データ構造の調査)
          +-- read_file          (ファイル内容の確認)
          +-- write_file         (スクリプト・READMEの書き出し)
          +-- edit_file          (生成済みスクリプトの部分修正)
          +-- generate_manifest  (QIIME2 マニフェスト生成)
          +-- run_command        (Docker 経由で QIIME2 実行)
          +-- check_system       (環境確認)
          |
          +-- set_plot_config    (図スタイル・色・解像度・形式の設定)
          +-- execute_python     (pandas/scipy/sklearn/matplotlib で解析実行)
          |     |- PLOT_CONFIG 自動注入（FIGURE_DIR, FIGURE_FORMAT 等）
          |     |- subfolder パラメータでフェーズ別ディレクトリに保存
          |     |- 生成図を PDF で自動保存
          |     `- ANALYSIS_LOG にステップ・図・統計を記録
          +-- build_report_tex   (ANALYSIS_LOG から TeX/PDF を自動構築)
          |     |- Python で TeX を完全生成（LLM 不使用・高速）
          |     |- フェーズ別セクション（α多様性 / β多様性 / ...）
          |     |- tectonic でコンパイル
          |     |- 日本語版（xeCJK + Hiragino フォント）
          |     `- 英語版（標準 LaTeX）
          +-- compile_report     (旧レポート生成：LLM が TeX を書く方式)
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
├── qiime2_agent.py   # AI エージェント本体
├── launch.sh         # macOS / Linux 起動スクリプト
├── launch.ps1        # Windows 起動スクリプト（PowerShell）
├── launch.bat        # Windows 起動スクリプト（ダブルクリック用）
├── setup.sh          # macOS / Linux セットアップ
├── setup.ps1         # Windows セットアップ（PowerShell）
├── setup.bat         # Windows セットアップ（ダブルクリック用）
├── LICENSE           # MIT License
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
Give it your raw FASTQ data, and it automatically handles **pipeline design, execution, Python analysis, and report generation**.

- Inspects your data structure automatically (FASTQ / metadata / existing QZA)
- Builds the right QIIME2 commands from scratch for your dataset
- Writes ready-to-run `.sh` / `.ps1` scripts
- Runs **Python downstream analysis** (pandas / scipy / scikit-learn / matplotlib) on QIIME2 outputs
- **Auto-saves all figures as PDF** — no need for view.qiime2.org
- **Autonomous exploration mode**: AI automatically runs all 5 analysis phases (alpha diversity → beta diversity → taxonomy → differential abundance → machine learning) without user confirmation
- **Auto-generates Japanese and English TeX / PDF reports** (`build_report_tex` programmatically builds TeX from ANALYSIS_LOG — no LLM context needed)

Everything runs **on your machine**. No cloud, no paid API, no internet required during analysis.

---

## Requirements

| | macOS | Linux | Windows |
|---|---|---|---|
| Python | 3.9+ | 3.9+ | 3.9+ |
| Ollama | auto via `setup.sh` | auto via `setup.sh` | auto via `setup.bat` |
| Docker | Docker Desktop | Docker Engine | Docker Desktop |
| Python analysis packages | auto via `setup.sh` | auto via `setup.sh` | manual pip |
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

## Usage

### QIIME2 pipeline generation

```
AI: Hello! To get started, please tell me:
    1. Path to your data directory
    2. Experimental description (region, primers, comparison groups)
    3. Desired analyses
    4. Figure style preferences (optional)

You > Data: /Users/yourname/microbiome-data/
      Experiment: Human gut, 16S V3-V4 (341F/806R), MiSeq PE 2×250bp,
                  control (5) vs treatment (5)
      Analyses: Taxonomic composition + alpha/beta diversity + differential abundance
      Style: white background, blue palette

[Tool: inspect_directory]
  -> 10 paired-end FASTQ samples detected, metadata.tsv found...

[Tool: set_plot_config]
  -> style: seaborn-v0_8-whitegrid, palette: Blues

AI: Generating V3-V4 pipeline.
    Applying trim-left-f=17, trunc-f=270.
    -> manifest.tsv, run_pipeline.sh, setup_classifier.sh, ANALYSIS_README.md
```

### Autonomous exploration mode (recommended)

After QIIME2, the AI automatically runs all 5 analysis phases without prompting.

```
You > Use /data/results/ and run all basic analyses automatically

AI: Starting autonomous exploration mode. Running 5 phases in sequence.

[Phase 1: Alpha diversity] -----
[Tool: execute_python | subfolder=alpha_diversity]
  -> Compute Shannon / Simpson / Chao1
  -> Mann-Whitney U / Kruskal-Wallis test
  -> Saved: ~/seq2pipe_results/20260223/figures/alpha_diversity/

[Phase 2: Beta diversity] -----
[Tool: execute_python | subfolder=beta_diversity]
  -> Bray-Curtis PCoA + confidence ellipses
  -> PERMANOVA (R², p-value)
  -> Saved: ~/seq2pipe_results/20260223/figures/beta_diversity/

[Phase 3: Taxonomy] -----
[Tool: execute_python | subfolder=taxonomy]
  -> Stacked bar chart + heatmap at phylum / genus level
  -> Saved: ~/seq2pipe_results/20260223/figures/taxonomy/

[Phase 4: Differential abundance] -----
[Tool: execute_python | subfolder=differential_abundance]
  -> Mann-Whitney U on all ASVs, Benjamini-Hochberg FDR
  -> Volcano plot (FDR < 0.05 highlighted in red)
  -> Saved: ~/seq2pipe_results/20260223/figures/differential_abundance/

[Phase 5: Machine learning] -----
[Tool: execute_python | subfolder=machine_learning]
  -> Random Forest 5-fold CV (AUC, accuracy)
  -> Top 20 feature importance bar chart
  -> Saved: ~/seq2pipe_results/20260223/figures/machine_learning/

[Tool: build_report_tex]
  -> Build TeX from ANALYSIS_LOG (no LLM — pure Python, fast)
  -> report_ja.pdf / report_en.pdf
  -> Saved: ~/seq2pipe_results/20260223/report/
```

### Python downstream analysis (manual)

```
You > Show Shannon diversity by group as a violin plot
      with Mann-Whitney U p-values

[Tool: execute_python]
  -> Read shannon_vector.qza from QIIME2 output
  -> Generate violin plot + statistical test
  -> Saved: ~/seq2pipe_results/20260223/figures/shannon_violin.pdf

AI: Shannon diversity violin plot saved.
    Treatment group significantly higher, p = 0.023 (Mann-Whitney U)

You > Generate a report in Japanese and English

[Tool: build_report_tex]
  -> Build TeX from ANALYSIS_LOG
  -> report_ja.pdf / report_en.pdf generated
```

### Figure style control

```
You > Switch to publication quality — 300 DPI PNG

[Tool: set_plot_config]
  -> dpi: 300, format: png applied to all subsequent figures
```

### Output file structure

```
<your data directory>/
├── manifest.tsv              # QIIME2 import manifest
├── setup_classifier.sh       # SILVA 138 classifier setup
├── run_pipeline.sh           # Full analysis pipeline
├── results/
│   ├── table.qza             <- OTU/ASV feature table
│   ├── taxonomy.qza          <- Classification results
│   ├── core-metrics-results/ <- Diversity analysis
│   └── ancombc-results.qza   <- Differential abundance (optional)
└── ANALYSIS_README.md        <- Data-specific operation guide

~/seq2pipe_results/<timestamp>/       <- auto-created per session
├── figures/
│   ├── alpha_diversity/      <- Phase 1: Shannon, Simpson, Chao1
│   │   ├── alpha_boxplot.pdf
│   │   └── alpha_stats.pdf
│   ├── beta_diversity/       <- Phase 2: PCoA, PERMANOVA
│   │   └── pcoa_bray_curtis.pdf
│   ├── taxonomy/             <- Phase 3: bar chart, heatmap
│   │   ├── taxonomy_barplot.pdf
│   │   └── taxonomy_heatmap.pdf
│   ├── differential_abundance/ <- Phase 4: volcano plot
│   │   └── volcano_plot.pdf
│   ├── machine_learning/     <- Phase 5: RF, AUC, feature importance
│   │   └── feature_importance.pdf
│   └── <other manual analysis figures>
└── report/
    ├── report_ja.tex / report_ja.pdf   <- Japanese report (auto-generated)
    └── report_en.tex / report_en.pdf   <- English report (auto-generated)
```

### Viewing results

| Output | How to view |
|---|---|
| Python figures (.pdf / .png) | Open directly in any PDF viewer or image viewer |
| QIIME2 `.qzv` (interactive) | Drop into [https://view.qiime2.org](https://view.qiime2.org) |
| Report PDF | Open in any PDF viewer |

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

### Python downstream
| Phase | Analysis | Packages |
|---|---|---|
| Phase 1 (alpha_diversity) | Shannon / Simpson / Chao1 + stats | pandas, scipy, seaborn |
| Phase 2 (beta_diversity) | Bray-Curtis PCoA + PERMANOVA | pandas, matplotlib, scipy |
| Phase 3 (taxonomy) | Stacked bar chart + heatmap (phylum/genus) | pandas, seaborn |
| Phase 4 (differential_abundance) | All-ASV test + BH correction + volcano | scipy, statsmodels |
| Phase 5 (machine_learning) | Random Forest 5-fold CV + feature importance | scikit-learn |
| Manual | Co-occurrence network | networkx, scipy |
| Report | ANALYSIS_LOG → TeX → PDF (pure Python, no LLM) | tectonic (TeX → PDF) |

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
[ qiime2_agent.py ]
  |
  +---> Ollama (localhost:11434)  <-- Local LLM
  |       |
  |       v
  |     [ LLM: qwen2.5-coder etc. ]
  |         |
  |         v  (autonomous exploration mode)
  |       Phase 1: alpha_diversity
  |       Phase 2: beta_diversity
  |       Phase 3: taxonomy
  |       Phase 4: differential_abundance
  |       Phase 5: machine_learning
  |
  +---> Tool execution
          |
          +-- inspect_directory  (scan data structure)
          +-- read_file          (read file contents)
          +-- write_file         (write scripts & README)
          +-- edit_file          (patch generated scripts)
          +-- generate_manifest  (create QIIME2 manifest)
          +-- run_command        (run QIIME2 via Docker)
          +-- check_system       (verify environment)
          |
          +-- set_plot_config    (style / palette / DPI / format)
          +-- execute_python     (pandas/scipy/sklearn/matplotlib analysis)
          |     |- auto-injects PLOT_CONFIG (FIGURE_DIR, FIGURE_FORMAT, etc.)
          |     |- subfolder param → phase-organized directories
          |     |- saves figures as PDF by default
          |     `- logs step / figures / stats to ANALYSIS_LOG
          +-- build_report_tex   (auto-build TeX/PDF from ANALYSIS_LOG)
          |     |- pure Python TeX generation (no LLM, no context flooding)
          |     |- phase-organized sections (alpha / beta / taxonomy / ...)
          |     |- compiled with tectonic
          |     |- Japanese (xeCJK + Hiragino fonts)
          |     `- English (standard LaTeX)
          +-- compile_report     (legacy: LLM writes TeX directly)
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

Docker is only needed to actually run QIIME2 commands. Script generation works without Docker.

</details>

<details>
<summary>Linux: docker permission denied</summary>

```bash
sudo usermod -aG docker $USER
newgrp docker
```

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
├── qiime2_agent.py   # AI agent core
├── launch.sh         # macOS / Linux launcher
├── launch.ps1        # Windows launcher (PowerShell)
├── launch.bat        # Windows launcher (double-click)
├── setup.sh          # macOS / Linux setup
├── setup.ps1         # Windows setup (PowerShell)
├── setup.bat         # Windows setup (double-click)
├── LICENSE           # MIT License
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
- [QIIME2 View (interactive visualization)](https://view.qiime2.org)
- [QIIME2 Forum](https://forum.qiime2.org/)
- [SILVA Database](https://www.arb-silva.de/)
- [Ollama](https://ollama.com/)

---

## License

- This tool: MIT License
- SILVA 138 data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- QIIME2: BSD License
