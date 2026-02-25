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
- **2 つの操作モード**: モード 1（自然言語でやりたい解析を指定）・モード 2（AI が自律的に全解析を設計・実行・`--auto` フラグ）
- **ツール呼び出し型コード生成エージェント（vibe-local 方式）**: LLM がまず `read_file` でデータの列名・形式を確認してからコードを生成するため精度が高く、エラーが出ても `NEVER GIVE UP` で自動修正を繰り返す
- QIIME2 の出力を **Python（pandas / scipy / scikit-learn / matplotlib）で高度解析**
- 解析図をすべて **PDF として自動保存**（view.qiime2.org 不要）
- **AI 自律解析（モード 2）**: 5 フェーズ・14 種類の図を全自動で生成（PCA / PCoA / NMDS / レアファクション曲線 / 分類組成 heatmap / サンプル相関行列 など）
- 解析終了後に **日本語・英語の TeX / PDF レポートを自動生成**（`build_report_tex` が ANALYSIS_LOG から自動構築）

すべて **あなたのマシン上** で完結。クラウドや有料 API は一切使いません。

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

## 使い方

### QIIME2 パイプライン生成

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
         スタイル: 白背景・青系カラー

[ツール実行: inspect_directory]
  -> ペアエンド FASTQ 10 サンプルを検出、metadata.tsv も確認...

[ツール実行: set_plot_config]
  -> style: seaborn-v0_8-whitegrid, palette: Blues に設定

AI: V3-V4 パイプラインを生成します。
    trim-left-f=17, trunc-f=270 を適用。
    -> manifest.tsv, run_pipeline.sh, setup_classifier.sh, ANALYSIS_README.md
```

### 自律エージェントモード（モード 2 / --auto）

QIIME2 解析後、AI が自律的に 5 フェーズ・14 種類の図を全自動で生成します。ユーザーの指示は不要です。
**vibe-local 方式**: LLM がまずファイルを `read_file` で読んで列名・形式を把握してからコードを書くため、フォーマットミスによるエラーが極めて少ない。
エラーが出ても `write_file` で修正 → `run_python` で再実行を EXIT CODE: 0 になるまで繰り返します。

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --auto --manifest manifest.tsv

  [虹色バナーアニメーション]

  モード: 自律エージェント（最大 40 ステップ）

  🚀 STEP 1/2: QIIME2 パイプライン実行中
    -> dada2 denoise-paired, classify-sklearn, core-metrics-phylogenetic...
  ✅ パイプライン完了 → ~/seq2pipe_results/20260225_120000/

  🤖 STEP 2/2: 自律エージェント（tool-calling ループ）

  [list_files] エクスポートファイルを一覧
    -> feature_table: 1 件 / taxonomy: 1 件 / alpha: 4 件 / beta: 4 件

  [Phase 0: クオリティ確認]
  [read_file] denoising/stats.tsv を読む（列名確認）
  [write_file] quality_plot.py を生成
  [run_python] EXIT CODE: 0 → denoising_stats.pdf 保存

  [Phase 1: α多様性]
  [read_file] alpha/shannon_vector.tsv を読む（列名確認）
  [write_file] alpha_diversity.py を生成
  [run_python] EXIT CODE: 0 → alpha_diversity.pdf（Shannon/Chao1/Simpson/Faith's PD）

  [Phase 2: β多様性]
  [read_file] beta/bray_curtis_pcoa_results.tsv を読む
  [write_file] beta_diversity.py を生成（PCoA + CLR-PCA + NMDS + レアファクション）
  [run_python] EXIT CODE: 0 → beta_pcoa.pdf / beta_clr_pca.pdf / beta_nmds.pdf / rarefaction.pdf

  [Phase 3: 分類組成]
  [read_file] taxonomy/taxonomy.tsv + feature-table.tsv を読む
  [write_file] taxonomy_plot.py を生成（phylum stacked bar + genus heatmap + CLR bar）
  [run_python] EXIT CODE: 0 → taxonomy_barplot.pdf / taxonomy_heatmap.pdf / taxonomy_clr.pdf

  [Phase 4: サンプル相関]
  [write_file] correlation_plot.py を生成
  [run_python] EXIT CODE: 0 → sample_correlation.pdf

  ✅ 自律解析完了！（5 フェーズ / 14 件の図）
```

### 解析モード（モード 1）- 自然言語でリクエスト

QIIME2 の結果を受け取ったら、やりたい解析を自然言語で指定できます。
LLM がファイルを先に読んでから正確なコードを生成し、エラーが出ると自動修正します。

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --export-dir ~/seq2pipe_results/20260225_120000/exported/

モードを選択してください:
  1. 解析モード        やりたい解析を自然言語で指定
  2. 自律エージェント  AI が自分でファイルを調べて全解析を全自動実行

選択 (1/2) [1]: 1
やりたい解析を入力してください: Shannon 多様性をグループ別に violin plot で比較して、Mann-Whitney U 検定の p 値も表示

[list_files] エクスポートファイルを一覧
[read_file]  alpha/shannon_vector.tsv の先頭を確認（列名: sample-id, shannon_entropy）
[write_file] analysis.py を生成（violin plot + 統計検定）
[run_python] EXIT CODE: 0
  -> ~/seq2pipe_results/20260225_120000/figures/shannon_violin.pdf 保存

✅ 解析完了！
📊 生成された図 (1 件):
   /Users/yourname/seq2pipe_results/20260225_120000/figures/shannon_violin.pdf
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

### Python ダウンストリーム解析（code_agent.py — ツール呼び出し型エージェント）
| フェーズ | 解析手法 | パッケージ |
|---|---|---|
| Phase 0 (quality) | デノイジング統計（入力 / フィルタリング / デノイジング / 非キメラ） | pandas, matplotlib |
| Phase 1 (alpha) | Shannon / Chao1 / Simpson / Faith's PD + Mann-Whitney U + Kruskal-Wallis | pandas, scipy, seaborn |
| Phase 2 (beta) | Bray-Curtis PCoA・UniFrac PCoA + CLR 変換 PCA + NMDS + レアファクション曲線 | pandas, sklearn, scipy |
| Phase 3 (taxonomy) | 門レベル stacked bar + 属レベル heatmap + CLR 変換 phylum bar | pandas, seaborn |
| Phase 4 (correlation) | サンプル間相関行列 + 階層クラスタリング heatmap | pandas, seaborn, scipy |
| モード 1 | ユーザー指示の任意解析（自然言語 → read_file で形式把握 → コード生成 → 自動修正） | 動的インストール対応 |
| レポート | ANALYSIS_LOG → TeX → PDF 自動構築（LLM 不使用、高速） | tectonic（TeX → PDF） |

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
[ launch.sh / launch.bat ]  →  [ cli.py ]  ← エントリーポイント（虹色バナー・モード選択）
                                    |
          ┌─────────────────────────┼──────────────────────────┐
          |                         |                          |
          v                         v                          v
  モード 1: 解析モード      [ pipeline_runner.py ]     モード 2: 自律エージェント
  （自然言語でリクエスト）   QIIME2 パイプライン実行      （--auto フラグ）
                             + 結果エクスポート
          |                         |                          |
          v                         v                          v
  [ code_agent.py ]  ←─────────────┘────────────→  [ code_agent.py ]
    ツール呼び出し型コード生成エージェント
    |
    +---> Ollama (localhost:11434)  <-- ローカル LLM
    |       TOOL FIRST: 先にデータを読んでからコードを書く
    |       NEVER GIVE UP: エラーが出たら write_file で修正 → run_python で再実行
    |
    +-- list_files      (エクスポートディレクトリのファイル一覧)
    +-- read_file       (ファイル内容を LLM に渡す → 列名・形式を把握してから書く)
    +-- write_file      (atomic write: mkstemp+replace で安全な Python スクリプト生成)
    +-- run_python      (QIIME2 conda Python で実行 → exit code 確認)
    `-- install_package (ModuleNotFoundError 検出 → pip install + ユーザー承認確認)

  自動解析タスク（モード 2）: 5 フェーズ・14 種類の図
    Phase 0: クオリティ確認（デノイジング統計）
    Phase 1: α多様性（Shannon / Chao1 / Simpson / Faith's PD + 統計検定）
    Phase 2: β多様性（Bray-Curtis PCoA / UniFrac PCoA / CLR-PCA / NMDS / レアファクション曲線）
    Phase 3: 分類組成（phylum stacked bar / genus heatmap / CLR phylum bar）
    Phase 4: サンプル相関（相関行列 + 階層クラスタリング）

  ─────────────────────────────────────────────────────
  [ qiime2_agent.py ]  QIIME2 パイプライン生成（pipeline_runner.py 内部で使用）
    |
    +---> Ollama (localhost:11434)  <-- ローカル LLM
    +---> 11 ツール
            +-- inspect_directory  (データ構造の調査)
            +-- read_file          (ファイル内容の確認)
            +-- write_file         (スクリプト書き出し)
            +-- edit_file          (部分修正)
            +-- generate_manifest  (QIIME2 マニフェスト生成)
            +-- run_command        (QIIME2 実行: conda env 自動検出 / Docker fallback)
            +-- check_system       (環境確認)
            +-- set_plot_config    (図スタイル設定)
            +-- execute_python     (Python 解析実行)
            +-- build_report_tex   (ANALYSIS_LOG → TeX/PDF 自動生成)
            `-- log_analysis_step  (QIIME2 ステップを ANALYSIS_LOG に記録)
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
<summary>QIIME2 conda 環境が自動検出されない</summary>

`QIIME2_CONDA_BIN` で明示的に指定してください:

```bash
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

自動検出される候補: `~/miniforge3/envs/qiime2/bin`, `~/miniconda3/envs/qiime2/bin`, `~/anaconda3/envs/qiime2/bin`

</details>

<details>
<summary>Docker が見つからない / 起動していない</summary>

QIIME2 conda 環境が検出されている場合、Docker は不要です。
conda 環境がない場合のみ Docker が必要になります。

- macOS / Windows: Docker Desktop を起動してください
- Linux: `sudo systemctl start docker`

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
├── cli.py            # エントリーポイント（虹色バナー・モード選択・CLI 引数）
├── qiime2_agent.py   # QIIME2 パイプライン生成エージェント（11 ツール）
├── pipeline_runner.py # QIIME2 実行ラッパー + 結果エクスポート
├── code_agent.py     # ツール呼び出し型コード生成エージェント（5 ツール、vibe-local 方式）
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
- **Two operation modes**: Mode 1 (specify your analysis in natural language) · Mode 2 (AI autonomously designs and runs all analyses, `--auto` flag)
- **Tool-calling code generation agent (vibe-local style)**: LLM first calls `read_file` to understand column names and data format before writing code — far fewer format errors; if an error occurs, `NEVER GIVE UP` — it rewrites and retries until EXIT CODE: 0
- Runs **Python downstream analysis** (pandas / scipy / scikit-learn / matplotlib) on QIIME2 outputs
- **Auto-saves all figures as PDF** — no need for view.qiime2.org
- **Autonomous analysis (Mode 2)**: Automatically generates 14 figures across 5 phases (PCA / PCoA / NMDS / rarefaction curves / taxonomy heatmap / sample correlation matrix / and more)
- **Auto-generates Japanese and English TeX / PDF reports** (`build_report_tex` programmatically builds TeX from ANALYSIS_LOG — no LLM context needed)

Everything runs **on your machine**. No cloud, no paid API, no internet required during analysis.

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

### Autonomous agent mode (Mode 2 / --auto)

After QIIME2, the AI autonomously generates 14 figures across 5 phases — no user prompts needed.
**Vibe-local style**: The LLM first calls `read_file` to inspect column names and file format before writing code. If an error occurs, it rewrites and retries until EXIT CODE: 0.

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --auto --manifest manifest.tsv

  [Rainbow banner animation]

  Mode: Autonomous agent (max 40 steps)

  🚀 STEP 1/2: Running QIIME2 pipeline
    -> dada2 denoise-paired, classify-sklearn, core-metrics-phylogenetic...
  ✅ Pipeline complete → ~/seq2pipe_results/20260225_120000/

  🤖 STEP 2/2: Autonomous agent (tool-calling loop)

  [list_files] Enumerate exported files
    -> feature_table: 1 / taxonomy: 1 / alpha: 4 / beta: 4

  [Phase 0: Quality check]
  [read_file]  denoising/stats.tsv (verify column names)
  [write_file] quality_plot.py
  [run_python] EXIT CODE: 0 → denoising_stats.pdf

  [Phase 1: Alpha diversity]
  [read_file]  alpha/shannon_vector.tsv (column: sample-id, shannon_entropy)
  [write_file] alpha_diversity.py
  [run_python] EXIT CODE: 0 → alpha_diversity.pdf (Shannon/Chao1/Simpson/Faith's PD)

  [Phase 2: Beta diversity]
  [read_file]  beta/bray_curtis_pcoa_results.tsv
  [write_file] beta_diversity.py (PCoA + CLR-PCA + NMDS + rarefaction curves)
  [run_python] EXIT CODE: 0 → beta_pcoa.pdf / beta_clr_pca.pdf / beta_nmds.pdf / rarefaction.pdf

  [Phase 3: Taxonomy]
  [read_file]  taxonomy/taxonomy.tsv + feature-table.tsv
  [write_file] taxonomy_plot.py (phylum stacked bar + genus heatmap + CLR bar)
  [run_python] EXIT CODE: 0 → taxonomy_barplot.pdf / taxonomy_heatmap.pdf / taxonomy_clr.pdf

  [Phase 4: Sample correlation]
  [write_file] correlation_plot.py
  [run_python] EXIT CODE: 0 → sample_correlation.pdf

  ✅ Autonomous analysis complete! (5 phases / 14 figures)
```

### Analysis mode (Mode 1) — natural language requests

Specify the analysis you want in natural language. The LLM reads the files first to understand the format, then generates accurate code.

```
$ ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py --export-dir ~/seq2pipe_results/20260225_120000/exported/

Select mode:
  1. Analysis mode     Specify what you want in natural language
  2. Autonomous agent  AI automatically runs all analyses

Choice (1/2) [1]: 1
Enter your request: Shannon diversity violin plot by group with Mann-Whitney U p-values

[list_files] List exported files
[read_file]  alpha/shannon_vector.tsv  (columns: sample-id, shannon_entropy)
[write_file] analysis.py (violin plot + statistical test)
[run_python] EXIT CODE: 0
  -> ~/seq2pipe_results/20260225_120000/figures/shannon_violin.pdf

✅ Analysis complete!
📊 Generated figures (1):
   /Users/yourname/seq2pipe_results/20260225_120000/figures/shannon_violin.pdf
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

### Python downstream (code_agent.py — tool-calling agent)
| Phase | Analysis | Packages |
|---|---|---|
| Phase 0 (quality) | Denoising statistics (input / filtered / denoised / non-chimeric) | pandas, matplotlib |
| Phase 1 (alpha) | Shannon / Chao1 / Simpson / Faith's PD + Mann-Whitney U + Kruskal-Wallis | pandas, scipy, seaborn |
| Phase 2 (beta) | Bray-Curtis PCoA · UniFrac PCoA + CLR-PCA + NMDS + rarefaction curves | pandas, sklearn, scipy |
| Phase 3 (taxonomy) | Phylum stacked bar + genus heatmap + CLR-transformed phylum bar | pandas, seaborn |
| Phase 4 (correlation) | Sample correlation matrix + hierarchical clustering heatmap | pandas, seaborn, scipy |
| Mode 1 | Any user-requested analysis (natural language → read_file → codegen → auto-fix) | dynamic install support |
| Report | ANALYSIS_LOG → TeX → PDF (pure Python, no LLM, fast) | tectonic (TeX → PDF) |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `QIIME2_AI_MODEL` | `qwen2.5-coder:7b` | Ollama model to use |
| `SEQ2PIPE_AUTO_YES` | `0` | Set to `1` to skip command confirmation (autonomous mode) |
| `SEQ2PIPE_MAX_STEPS` | `100` | Maximum agent loop steps |
| `SEQ2PIPE_PYTHON_TIMEOUT` | `600` | Timeout in seconds for `execute_python` |
| `QIIME2_CONDA_BIN` | auto-detected | Path to QIIME2 conda env bin directory (manual override) |

```bash
# Example: autonomous mode (no confirmation prompts)
SEQ2PIPE_AUTO_YES=1 ./launch.sh

# Example: manually specify QIIME2 conda env
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

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
[ launch.sh / launch.bat ]  →  [ cli.py ]  ← Entry point (rainbow banner / mode selection)
                                    |
          ┌─────────────────────────┼──────────────────────────┐
          |                         |                          |
          v                         v                          v
  Mode 1: Analysis mode     [ pipeline_runner.py ]     Mode 2: Autonomous agent
  (natural language)         QIIME2 pipeline +           (--auto flag)
                             result export
          |                         |                          |
          v                         v                          v
  [ code_agent.py ]  ←─────────────┘────────────→  [ code_agent.py ]
    Tool-calling code generation agent
    |
    +---> Ollama (localhost:11434)  <-- Local LLM
    |       TOOL FIRST: read files before writing code
    |       NEVER GIVE UP: write_file to fix → run_python again until EXIT CODE: 0
    |
    +-- list_files      (enumerate exported directory)
    +-- read_file       (feed file contents to LLM → understand column names & format)
    +-- write_file      (atomic write via mkstemp+replace — safe script generation)
    +-- run_python      (execute with QIIME2 conda Python → check exit code)
    `-- install_package (detect ModuleNotFoundError → pip install + user approval)

  Autonomous task (Mode 2): 5 phases · 14 figures
    Phase 0: Quality check (denoising statistics)
    Phase 1: Alpha diversity (Shannon / Chao1 / Simpson / Faith's PD + stats)
    Phase 2: Beta diversity (Bray-Curtis PCoA / UniFrac PCoA / CLR-PCA / NMDS / rarefaction)
    Phase 3: Taxonomy (phylum stacked bar / genus heatmap / CLR phylum bar)
    Phase 4: Sample correlation (correlation matrix + hierarchical clustering)

  ─────────────────────────────────────────────────────
  [ qiime2_agent.py ]  QIIME2 pipeline generation (used inside pipeline_runner.py)
    |
    +---> Ollama (localhost:11434)  <-- Local LLM
    +---> 11 tools
            +-- inspect_directory  (scan data structure)
            +-- read_file          (read file contents)
            +-- write_file         (write scripts & README)
            +-- edit_file          (patch generated scripts)
            +-- generate_manifest  (create QIIME2 manifest)
            +-- run_command        (run QIIME2: auto-detects conda env / Docker fallback)
            +-- check_system       (verify environment)
            +-- set_plot_config    (style / palette / DPI / format)
            +-- execute_python     (Python analysis & visualization)
            +-- build_report_tex   (auto-build TeX/PDF from ANALYSIS_LOG)
            `-- log_analysis_step  (register QIIME2 steps in ANALYSIS_LOG)
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
<summary>QIIME2 conda env not detected automatically</summary>

Specify it manually with `QIIME2_CONDA_BIN`:

```bash
QIIME2_CONDA_BIN=/opt/conda/envs/qiime2/bin ./launch.sh
```

Auto-detected paths: `~/miniforge3/envs/qiime2/bin`, `~/miniconda3/envs/qiime2/bin`, `~/anaconda3/envs/qiime2/bin`

</details>

<details>
<summary>Docker not found / not running</summary>

Docker is not required if a QIIME2 conda env is detected.
Docker is only needed as a fallback when no conda env is available.

- macOS / Windows: Start Docker Desktop
- Linux: `sudo systemctl start docker`

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
├── cli.py            # Entry point (rainbow banner / mode selection / CLI args)
├── qiime2_agent.py   # QIIME2 pipeline generation agent (11 tools)
├── pipeline_runner.py # QIIME2 execution wrapper + result export
├── code_agent.py     # Tool-calling code generation agent (5 tools, vibe-local style)
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
