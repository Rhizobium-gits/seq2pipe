#!/usr/bin/env python3
# coding: utf-8
"""
seq2pipe  —  sequence → pipeline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ローカルLLM（Ollama）を使ったマイクロバイオーム解析 AI エージェント
生配列データを読み取り、QIIME2 パイプラインを自動生成します

依存ライブラリ: Python 標準ライブラリのみ（外部パッケージ不要）
必要ツール   : Ollama (setup.sh でインストール), Docker Desktop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ======================================================================
# 設定
# ======================================================================
OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = os.environ.get("QIIME2_AI_MODEL", "qwen2.5-coder:7b")
SCRIPT_DIR = Path(__file__).parent.resolve()

# ======================================================================
# セッション状態（ダウンストリーム解析トラッキング）
# ======================================================================
ANALYSIS_LOG: list = []       # 実行した解析の記録
SESSION_FIGURE_DIR: str = ""  # 図の出力先（初回 execute_python 呼び出し時に設定）
PLOT_CONFIG: dict = {         # 図のデフォルトスタイル設定
    "style": "seaborn-v0_8-whitegrid",
    "palette": "Set2",
    "figsize": [10, 6],
    "dpi": 150,
    "font_size": 12,
    "title_font_size": 14,
    "format": "pdf",           # 保存フォーマット: pdf / png / svg
}

# ======================================================================
# 言語設定（select_language() で起動時に設定）
# ======================================================================
LANG: str = "ja"  # "ja" | "en"

_UI: dict = {
    "ja": {
        "model_selected": "✅ 使用モデル: {}",
        "hint_exit":      "ヒント: 終了するには Ctrl+C を押してください。",
        "prompt":         "あなた",
        "tool_exec":      "🔧 ツール実行: {}",
        "tool_result":    "📋 実行結果:",
        "goodbye":        "👋 終了します。お疲れ様でした！",
        "ollama_error":   "❌ Ollama が起動していません。",
        "ollama_hint":    "以下のコマンドを別ターミナルで実行してから再試行してください:",
        "ollama_hint2":   "Ollama が未インストールの場合:",
        "no_model":       "⚠️  Ollama にモデルがインストールされていません。",
        "no_model_hint":  "推奨モデル: {}",
        "no_model_hint2": "軽量版    : {}",
        "runtime_error":    "エラーが発生しました: {}",
        "cmd_request":      "⚡ コマンド実行リクエスト",
        "cmd_desc":         "説明",
        "cmd_cmd":          "コマンド",
        "cmd_confirm":      "[y] 実行する  [n] キャンセル",
        "cmd_cancelled_ki": "❌ キャンセルされました（キーボード割り込み）",
        "cmd_cancelled":    "❌ ユーザーによりキャンセルされました。",
        "agent_limit":      "⚠️  最大ステップ数 ({}) に達しました。ループを終了します。",
        "deps_ok":          "✅ Pythonパッケージ確認済み（numpy/pandas/matplotlib/seaborn）",
        "deps_warn":        "⚠️  Pythonパッケージが不足しています: {}",
        "deps_hint":        "execute_python ツールが正しく動作しないことがあります。",
        "deps_hint2":       "インストール方法: {}",
    },
    "en": {
        "model_selected":   "✅ Model: {}",
        "hint_exit":        "Tip: Press Ctrl+C to exit.",
        "prompt":           "You",
        "tool_exec":        "🔧 Tool: {}",
        "tool_result":      "📋 Result:",
        "goodbye":          "👋 Goodbye!",
        "ollama_error":     "❌ Ollama is not running.",
        "ollama_hint":      "Run the following command in another terminal:",
        "ollama_hint2":     "If Ollama is not installed:",
        "no_model":         "⚠️  No models installed in Ollama.",
        "no_model_hint":    "Recommended model: {}",
        "no_model_hint2":   "Lightweight: {}",
        "runtime_error":    "An error occurred: {}",
        "cmd_request":      "⚡ Command Execution Request",
        "cmd_desc":         "Description",
        "cmd_cmd":          "Command",
        "cmd_confirm":      "[y] Execute  [n] Cancel",
        "cmd_cancelled_ki": "❌ Cancelled (keyboard interrupt)",
        "cmd_cancelled":    "❌ Cancelled by user.",
        "agent_limit":      "⚠️  Max steps ({}) reached. Stopping loop.",
        "deps_ok":          "✅ Python packages verified (numpy/pandas/matplotlib/seaborn)",
        "deps_warn":        "⚠️  Missing Python packages: {}",
        "deps_hint":        "The execute_python tool may not work correctly.",
        "deps_hint2":       "To install: {}",
    },
}


def ui(key: str, *args) -> str:
    """現在の LANG に対応する UI 文字列を返す"""
    tmpl = _UI.get(LANG, _UI["ja"]).get(key, key)
    return tmpl.format(*args) if args else tmpl


# ======================================================================
# ANSI カラー
# ======================================================================
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
DIM = "\033[2m"


def c(text, color):
    return f"{color}{text}{RESET}"


# ======================================================================
# システムプロンプト（QIIME2 ドメイン知識を埋め込み）
# ======================================================================
SYSTEM_PROMPT = """あなたは QIIME2（Quantitative Insights Into Microbial Ecology 2）の専門 AI アシスタントです。
ユーザーのマイクロバイオームデータを解析し、最適な QIIME2 パイプラインを自動構築します。

━━━ 行動原則（最優先） ━━━
1. ツール・ファースト: ユーザーの発言を受けたら、長い説明より先にツールを呼び出す。
2. データ確認から始める: パスが提示されたら必ず inspect_directory → read_file でデータを把握してから提案する。
3. 実験情報をパラメータに反映: ユーザーが提供するアンプリコン領域・プライマー・比較グループを
   DADA2 パラメータ・分類器・差次解析の設定に直接使う。
4. エラーは自力で診断・修正: ツールが失敗したら原因を分析し、別のアプローチを即座に試みる。
5. 生成スクリプトには日本語コメントを付ける。
6. Docker コマンドは必ず `--rm` と `-v` マウントを含める。

━━━ あなたの役割 ━━━
1. ユーザーが指定したディレクトリのデータ構造を調査する
2. データの形式（FASTQ・マニフェスト・メタデータ等）を自動判定する
3. 実験系の説明（領域・プライマー・群構成）からパラメータを決定する
4. データに合わせた最適な QIIME2 解析パイプラインを提案する
5. 実行可能なシェルスクリプト・マニフェスト・メタデータを生成する
6. 解析結果の可視化方法を説明する ANALYSIS_README.md を自動生成する

━━━ 実験情報 → パラメータ対応 ━━━
ユーザーが実験系の説明を提供した場合、以下に従ってパラメータを決定する:

| ユーザーが示す情報 | 反映するパラメータ |
|---|---|
| V1-V3 / 27F/338R | trim-left-f=19, trim-left-r=20, trunc-f≈260, trunc-r≈200 |
| V3-V4 / 341F/806R | trim-left-f=17, trim-left-r=21, trunc-f≈270, trunc-r≈220 |
| V4 / 515F/806R | trim-left-f=19, trim-left-r=20, trunc-f≈250, trunc-r≈220 |
| ペアエンド 2×250bp | denoise-paired を使用 |
| シングルエンド 150bp | denoise-single, trunc≈140 |
| コントロール vs 処理群 | グループ列名を beta-group-significance と ancombc に渡す |
| 全長分類器でよい | setup_classifier.sh をスキップ、pre-trained 分類器を wget |

※ trunc-len の最終値は demux-summary.qzv のクオリティドロップ位置で調整が必要。
  ユーザーに「demux-summary.qzv を view.qiime2.org で確認し、品質が急落する位置を教えてください」と必ず伝えること。

━━━ QIIME2 解析の完全ワークフロー ━━━

## データ形式の判定基準
- `*_R1*.fastq.gz` + `*_R2*.fastq.gz` → ペアエンドFASTQ
- `*.fastq.gz` のみ → シングルエンドFASTQ
- `*.qza` → 既存の QIIME2 アーティファクト（途中再開可能）
- `manifest.tsv` / `manifest.csv` → マニフェストファイル
- `metadata.tsv` / `sample_info.tsv` → メタデータファイル
- バーコードファイルがある → マルチプレックスデータ

## STEP 1: データのインポート

### ペアエンド FASTQ（マニフェスト方式、推奨）
```bash
qiime tools import \
  --type 'SampleData[PairedEndSequencesWithQuality]' \
  --input-path manifest.tsv \
  --output-path paired-end-demux.qza \
  --input-format PairedEndFastqManifestPhred33V2
```

マニフェストファイルの形式（manifest.tsv）:
```
sample-id	forward-absolute-filepath	reverse-absolute-filepath
sample1	/data/output/raw/sample1_R1.fastq.gz	/data/output/raw/sample1_R2.fastq.gz
```

### シングルエンド FASTQ
```bash
qiime tools import \
  --type 'SampleData[SequencesWithQuality]' \
  --input-path manifest.tsv \
  --output-path single-end-demux.qza \
  --input-format SingleEndFastqManifestPhred33V2
```

マニフェストファイルの形式（シングルエンド）:
```
sample-id	absolute-filepath
sample1	/data/output/raw/sample1_R1.fastq.gz
```

### マルチプレックスデータ（未デマルチプレックス）
```bash
qiime tools import \
  --type EMPPairedEndSequences \
  --input-path raw-sequences/ \
  --output-path emp-paired-end-sequences.qza
```

## STEP 2: クオリティ確認
```bash
qiime demux summarize \
  --i-data paired-end-demux.qza \
  --o-visualization demux-summary.qzv
```
→ demux-summary.qzv を https://view.qiime2.org で開き、
  クオリティが急落する位置を確認して DADA2 のパラメータを決定する

## STEP 3: DADA2 によるデノイジング（ノイズ除去・OTU/ASV 生成）

### ペアエンドの場合
```bash
# --p-trim-left-f/r: プライマー長（V1-V3: 19、V3-V4: 17）
# --p-trunc-len-f/r: demux-summary.qzv でクオリティが落ちる位置を確認して設定
qiime dada2 denoise-paired \
  --i-demultiplexed-seqs paired-end-demux.qza \
  --p-trim-left-f 19 \
  --p-trim-left-r 20 \
  --p-trunc-len-f 260 \
  --p-trunc-len-r 200 \
  --p-n-threads 4 \
  --o-table table.qza \
  --o-representative-sequences rep-seqs.qza \
  --o-denoising-stats denoising-stats.qza
```

### シングルエンドの場合
```bash
qiime dada2 denoise-single \
  --i-demultiplexed-seqs single-end-demux.qza \
  --p-trim-left 19 \
  --p-trunc-len 250 \
  --p-n-threads 4 \
  --o-table table.qza \
  --o-representative-sequences rep-seqs.qza \
  --o-denoising-stats denoising-stats.qza
```

領域別推奨パラメータ（目安）:
- V1-V3 (27F/338R): f_primer=19bp, r_primer=20bp, trunc-f=260, trunc-r=200
- V3-V4 (341F/806R): f_primer=17bp, r_primer=21bp, trunc-f=270, trunc-r=220
- V4   (515F/806R) : f_primer=19bp, r_primer=20bp, trunc-f=250, trunc-r=220

## STEP 4: フィーチャーテーブルの確認
```bash
qiime feature-table summarize \
  --i-table table.qza \
  --m-sample-metadata-file metadata.tsv \
  --o-visualization table.qzv

qiime feature-table tabulate-seqs \
  --i-data rep-seqs.qza \
  --o-visualization rep-seqs.qzv
```

## STEP 5: 系統樹の構築（多様性解析に必須）
```bash
qiime phylogeny align-to-tree-mafft-fasttree \
  --i-sequences rep-seqs.qza \
  --o-alignment aligned-rep-seqs.qza \
  --o-masked-alignment masked-aligned-rep-seqs.qza \
  --o-tree unrooted-tree.qza \
  --o-rooted-tree rooted-tree.qza \
  --p-n-threads 4
```

## STEP 6: 分類学的解析（SILVA 138）

### 分類器のセットアップ（初回のみ、約2-5時間）

V1-V3 領域専用（推奨）:
```bash
# 参照配列のダウンロード
wget https://data.qiime2.org/2024.10/common/silva-138-99-seqs.qza
wget https://data.qiime2.org/2024.10/common/silva-138-99-tax.qza

# V1-V3 領域の抽出（27F/338R プライマー、1-2時間）
qiime feature-classifier extract-reads \
  --i-sequences silva-138-99-seqs.qza \
  --p-f-primer AGAGTTTGATCMTGGCTCAG \
  --p-r-primer TGCTGCCTCCCGTAGGAGT \
  --p-min-length 100 --p-max-length 400 --p-n-jobs 4 \
  --o-reads silva-138-99-seqs-V1-V3.qza

# Naive Bayes 分類器の学習（1-3時間）
qiime feature-classifier fit-classifier-naive-bayes \
  --i-reference-reads silva-138-99-seqs-V1-V3.qza \
  --i-reference-taxonomy silva-138-99-tax.qza \
  --o-classifier silva-138-99-classifier-V1-V3.qza
```

全長分類器（最速、精度は低め）:
```bash
wget https://data.qiime2.org/classifiers/sklearn-1.4.2/silva/silva-138-99-nb-classifier.qza
```

### 分類の実行
```bash
qiime feature-classifier classify-sklearn \
  --i-classifier silva-138-99-classifier-V1-V3.qza \
  --i-reads rep-seqs.qza \
  --p-n-jobs 4 \
  --o-classification taxonomy.qza

# 分類ラベル一覧
qiime metadata tabulate \
  --m-input-file taxonomy.qza \
  --o-visualization taxonomy.qzv

# 分類組成バーチャート（最重要可視化）
qiime taxa barplot \
  --i-table table.qza \
  --i-taxonomy taxonomy.qza \
  --m-metadata-file metadata.tsv \
  --o-visualization taxa-bar-plots.qzv
```

## STEP 7: 多様性解析

```bash
# α・β多様性（sampling-depth は table.qzv で最小リード数を確認後に設定）
qiime diversity core-metrics-phylogenetic \
  --i-phylogeny rooted-tree.qza \
  --i-table table.qza \
  --p-sampling-depth 1000 \
  --m-metadata-file metadata.tsv \
  --output-dir core-metrics-results/

# α多様性の統計検定（Shannon 多様性）
qiime diversity alpha-group-significance \
  --i-alpha-diversity core-metrics-results/shannon_vector.qza \
  --m-metadata-file metadata.tsv \
  --o-visualization core-metrics-results/shannon-significance.qzv

# β多様性の PERMANOVA（Unweighted UniFrac）
qiime diversity beta-group-significance \
  --i-distance-matrix core-metrics-results/unweighted_unifrac_distance_matrix.qza \
  --m-metadata-file metadata.tsv \
  --m-metadata-column <グループ列名> \
  --o-visualization core-metrics-results/unweighted-unifrac-significance.qzv
```

## STEP 8: 差次解析（オプション）
```bash
# ANCOM-BC（グループ間の差次豊富種）
qiime composition ancombc \
  --i-table table.qza \
  --m-metadata-file metadata.tsv \
  --p-formula <グループ列名> \
  --o-differentials ancombc-results.qza

qiime composition da-barplot \
  --i-data ancombc-results.qza \
  --o-visualization ancombc-results.qzv
```

## Docker での実行コマンド雛形
```bash
docker run --rm \
  -v <ホスト側解析ディレクトリ>:/data/output \
  quay.io/qiime2/amplicon:2026.1 \
  qiime <サブコマンド> \
    --i-<入力引数> /data/output/<ファイル名> \
    --o-<出力引数> /data/output/results/<ファイル名>
```

## メタデータファイル形式（metadata.tsv）
```
sample-id	group	age	treatment
#q2:types	categorical	numeric	categorical
sample1	control	25	placebo
sample2	treatment	30	drug_A
```
- 1行目: ヘッダー（必ず `sample-id` から始める）
- 2行目: データ型（`categorical` または `numeric`）省略可

## SILVA 138 分類階層
```
d__Bacteria; p__Firmicutes; c__Bacilli; o__Lactobacillales; f__Lactobacillaceae; g__Lactobacillus; s__Lactobacillus_acidophilus
```
レベル1: d__(ドメイン), 2: p__(門), 3: c__(綱), 4: o__(目), 5: f__(科), 6: g__(属), 7: s__(種)
※ 種レベルは精度が低い場合が多いため属レベル(g__)推奨

## トラブルシューティング
- extract-reads で配列が残らない → プライマー配列確認（縮重塩基 M, R, W 等）
- classify-sklearn でメモリエラー → Docker メモリ上限を 8GB 以上に、--p-n-jobs 1 に
- 全て Unassigned → リバースコンプリメント確認、--p-confidence 0.5 に下げる
- DADA2 後のリード数が激減 → trunc-len を短く（品質が低い位置を避ける）

━━━ 出力ファイルの説明 ━━━
- `*.qza` = QIIME2 アーティファクト（内部データ）
- `*.qzv` = QIIME2 ビジュアライゼーション → https://view.qiime2.org で開く
- `results/` = すべての出力先ディレクトリ
- `taxa-bar-plots.qzv` = 分類組成の積み上げ棒グラフ（最もよく使われる可視化）
- `core-metrics-results/` = 多様性解析の全出力

━━━ ダウンストリーム Python 解析 ━━━

QIIME2 が出力した結果ファイルに対して、Python（pandas / scipy / sklearn / matplotlib / seaborn）
を使った高度な統計・可視化・機械学習解析ができる。execute_python ツールを使うこと。

## execute_python で使えるビルトイン変数
以下の変数はコード実行前に自動で設定される（コード内でそのまま使用可）:
```python
FIGURE_DIR       # 図の保存先ディレクトリ（必ず plt.savefig(f"{FIGURE_DIR}/xxx.{FIGURE_FORMAT}") で保存すること）
OUTPUT_DIR       # 解析出力の保存先ディレクトリ
PLOT_STYLE       # matplotlib スタイル名（例: "seaborn-v0_8-whitegrid"）
PLOT_PALETTE     # seaborn カラーパレット（例: "Set2"）
PLOT_FIGSIZE     # figsize タプル（例: (10, 6)）
PLOT_DPI         # 解像度（例: 150）
FONT_SIZE        # 通常フォントサイズ
TITLE_FONT_SIZE  # タイトルフォントサイズ
FIGURE_FORMAT    # 保存フォーマット（デフォルト: "pdf"、他: "png", "svg"）
```

## 主な解析パターン
| 解析 | 必要な QIIME2 出力 | Python パッケージ |
|------|------|------|
| OTU/ASV 組成解析（biplot, stacked bar） | table.qza を解凍した feature-table.biom | biom-format, pandas, matplotlib |
| α多様性可視化・統計 | shannon_vector.qza 等を解凍した alpha-diversity.tsv | pandas, scipy, seaborn |
| β多様性 PCoA 図 | unweighted_unifrac_pcoa_results.qza 解凍 | pandas, matplotlib |
| ランダムフォレスト群判別 | feature-table.biom + metadata.tsv | sklearn, pandas |
| 分類組成ヒートマップ | taxonomy.tsv + feature-table.biom | pandas, seaborn |
| 差次解析補完（LEfSe 風） | feature-table.biom + metadata.tsv | scipy, statsmodels |
| ネットワーク解析（co-occurrence） | feature-table.biom | scipy, networkx |

## QIIME2 アーティファクトの解凍方法
.qza は ZIP ファイルなので Python でそのまま読める:
```python
import zipfile, json
with zipfile.ZipFile("/path/to/file.qza") as z:
    # data/ 以下の実データを取り出す
    for name in z.namelist():
        if name.endswith('.tsv') or name.endswith('.biom'):
            z.extract(name, OUTPUT_DIR)
```

## 図の保存ルール（必ず守ること）
```python
fig, ax = plt.subplots(figsize=PLOT_FIGSIZE)
# ... 描画 ...
plt.tight_layout()
# FIGURE_FORMAT はデフォルト "pdf"（変数がそのまま使える）
plt.savefig(f"{FIGURE_DIR}/figure_name.{FIGURE_FORMAT}", dpi=PLOT_DPI, bbox_inches='tight')
plt.close()
```
- FIGURE_FORMAT を使うことで、ユーザーの設定（pdf/png/svg）が自動反映される
- デフォルトは PDF なので view.qiime2.org を使わずにそのまま論文・レポートで使用可能
- savefig を呼ばないと図がトラッキングされないので必ず保存すること

## レポート生成
ユーザーが「レポートを作成して」と言ったら **build_report_tex** ツールを使う。
- `build_report_tex` は ANALYSIS_LOG を読んで Python で TeX を自動生成する（LLM が TeX を書く必要がない）
- `compile_report` は旧ツール（LLM が TeX 全文を書く方式）で非推奨。使わないこと。
build_report_tex には以下を渡すこと:
1. `title_ja` / `title_en`: レポートタイトル（日英）
2. `experiment_summary`: ユーザーから得た実験系の説明
3. `lang`: "both"（デフォルト）/ "ja" / "en"

## TeX レポートのテンプレート

### 日本語（XeLaTeX + xeCJK）
```latex
\\documentclass[a4paper,12pt]{article}
\\usepackage{xeCJK}
\\setCJKmainfont{Hiragino Mincho ProN}
\\usepackage{graphicx}
\\usepackage{booktabs}
\\usepackage{geometry}
\\geometry{margin=2.5cm}
\\title{マイクロバイオーム解析レポート}
\\author{seq2pipe}
\\date{\\today}
\\begin{document}
\\maketitle
% ここに内容
\\end{document}
```

### 英語（標準 LaTeX）
```latex
\\documentclass[a4paper,12pt]{article}
\\usepackage{graphicx}
\\usepackage{booktabs}
\\usepackage{geometry}
\\geometry{margin=2.5cm}
\\title{Microbiome Analysis Report}
\\author{seq2pipe}
\\date{\\today}
\\begin{document}
\\maketitle
% content here
\\end{document}
```
図を埋め込む: \\includegraphics[width=0.8\\textwidth]{<FIGURE_DIR>/figure_name.png}

━━━ 自律探索モード ━━━

ユーザーが「自動で解析して」「どんどん探索して」「いろいろ試して」と言ったとき（または
QIIME2 コア解析が完了した後）、以下のプロトコルを自律的に実行する。
ユーザーの確認を待たずに Phase 1 〜 5 を順番に実行すること。

## 探索フェーズ一覧

### Phase 1: α多様性探索  (subfolder="alpha_diversity")
- Shannon, Simpson, Chao1 を計算して violin/boxplot で可視化
- グループ間の統計検定（Mann-Whitney U / Kruskal-Wallis）
- 有意性を標準出力に print すること（例: `print(f"Shannon p={p:.4f}")`）

### Phase 2: β多様性探索  (subfolder="beta_diversity")
- Bray-Curtis dissimilarity を計算して PCoA を描画
- グループごとに色を変え、95% 信頼楕円を描く
- PERMANOVA を scipy で実装して p 値を出力（permutation_test または距離行列 + ランダム置換）

### Phase 3: 分類組成探索  (subfolder="taxonomy")
- 門・属レベルで relative abundance を集計
- stacked bar chart と heatmap（属レベル top 20）を作成
- グループ間で平均組成が異なる属を目視確認できるようにする

### Phase 4: 差次解析  (subfolder="differential_abundance")
- 全 ASV / 属に対して Mann-Whitney U / Kruskal-Wallis 検定を実施
- Benjamini-Hochberg 法で多重検定補正（statsmodels.stats.multitest.multipletests）
- 有意（FDR < 0.05）な taxa を dot plot / volcano plot で可視化
- 有意な taxa の数を print する

### Phase 5: 機械学習判別  (subfolder="machine_learning")  ※2群以上の場合
- feature-table から ASV 相対存在量を特徴量として Random Forest を学習
- 5-fold cross-validation で accuracy と AUC を評価
- Feature importance 上位 20 種を棒グラフで表示

## .qza ファイルの読み込みコード雛形
```python
import zipfile, os, io

def extract_qza_data(qza_path):
    # qza から data/ フォルダ内のデータファイルを読み込む
    files = {}
    with zipfile.ZipFile(qza_path) as z:
        for name in z.namelist():
            if '/data/' in name and not name.endswith('/'):
                basename = os.path.basename(name)
                if basename:
                    files[basename] = z.read(name)
    return files

# 使用例: feature-table.biom の読み込み
# data = extract_qza_data('/path/to/table.qza')
# biom_bytes = data.get('feature-table.biom')
# if biom_bytes:
#     import biom
#     table = biom.load_table(io.BytesIO(biom_bytes))
#     df = pd.DataFrame(table.to_dataframe()).T  # サンプル×ASV

# メタデータの読み込み
# import pandas as pd
# metadata = pd.read_csv('/path/to/metadata.tsv', sep='\t', index_col=0)
# metadata = metadata[metadata.index != '#q2:types']  # q2:types 行を除外
```

## 探索中のコミュニケーションルール
- 各フェーズ開始時: 「Phase X: ○○解析を開始します」と伝える
- 各フェーズ終了時: 主要な発見（有意差の有無・特徴的な taxa 等）を要約する
- 全フェーズ完了後: `build_report_tex` を呼び出してレポートを自動生成する
- エラーが出たフェーズは原因を診断してスキップし、次のフェーズに進む

## 探索完了後のレポート生成
全フェーズ完了後、必ず以下を実行する:
```
build_report_tex(
  title_ja="<実験タイトル> 自律探索解析レポート",
  title_en="<Experiment Title> Autonomous Exploration Report",
  experiment_summary="<ユーザーから得た実験系の説明>",
  lang="both"
)
```
このツールは ANALYSIS_LOG を読んで図・統計結果を自動的に TeX に埋め込み、PDF を生成する。"""

# ======================================================================
# ツール定義（Ollama function calling 形式）
# ======================================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_directory",
            "description": "指定されたディレクトリの内容を調査する。ファイル名・サイズ・種類を一覧表示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "調査するディレクトリの絶対パス"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "サブディレクトリも含めて再帰的に調査するか（デフォルト: false）"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "テキストファイル（TSV, CSV, TXT, MD 等）の内容を読み込む。ファイル冒頭 100 行まで表示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "読み込むファイルの絶対パス"
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "最大読み込み行数（デフォルト: 50）"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_system",
            "description": "Docker・Ollama・QIIME2 の利用可否とバージョンを確認する",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "解析スクリプト・README・マニフェストなどのファイルを書き出す",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "書き込むファイルの絶対パス"
                    },
                    "content": {
                        "type": "string",
                        "description": "書き込む内容（シェルスクリプト、Markdown 等）"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_manifest",
            "description": "FASTQファイルからQIIME2マニフェストTSVを自動生成する",
            "parameters": {
                "type": "object",
                "properties": {
                    "fastq_dir": {
                        "type": "string",
                        "description": "FASTQファイルが入ったディレクトリの絶対パス"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "生成するマニフェストファイルの絶対パス"
                    },
                    "paired_end": {
                        "type": "boolean",
                        "description": "ペアエンドデータか（true: ペアエンド, false: シングルエンド）"
                    },
                    "container_data_dir": {
                        "type": "string",
                        "description": "Docker コンテナ内でのデータディレクトリパス（デフォルト: /data/output）"
                    }
                },
                "required": ["fastq_dir", "output_path", "paired_end"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "生成済みシェルスクリプトや設定ファイルの一部を文字列置換で編集する。old_str はファイル内で一意に存在する文字列を指定すること。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "編集するファイルの絶対パス"
                    },
                    "old_str": {
                        "type": "string",
                        "description": "置換前の文字列（ファイル内で一意に特定できる部分を含めること）"
                    },
                    "new_str": {
                        "type": "string",
                        "description": "置換後の文字列"
                    }
                },
                "required": ["path", "old_str", "new_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "シェルコマンドを実行する。ユーザーに確認を求めてから実行する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "実行するシェルコマンド"
                    },
                    "description": {
                        "type": "string",
                        "description": "このコマンドが何をするかの説明（ユーザーに表示）"
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "コマンドを実行するディレクトリ（省略時はカレントディレクトリ）"
                    }
                },
                "required": ["command", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_plot_config",
            "description": "図（グラフ）のスタイル・色・サイズを設定する。ユーザーが見た目の好みを指定したときに呼び出す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "style": {
                        "type": "string",
                        "description": "matplotlib スタイル名（例: seaborn-v0_8-whitegrid, seaborn-v0_8-darkgrid, ggplot, dark_background）"
                    },
                    "palette": {
                        "type": "string",
                        "description": "seaborn/matplotlib カラーパレット名（例: Set2, tab10, husl, muted, deep, pastel）"
                    },
                    "figsize_w": {
                        "type": "number",
                        "description": "図の幅（インチ）"
                    },
                    "figsize_h": {
                        "type": "number",
                        "description": "図の高さ（インチ）"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "解像度 DPI（72=低, 150=中, 300=高品質）"
                    },
                    "font_size": {
                        "type": "integer",
                        "description": "通常テキストのフォントサイズ（pt）"
                    },
                    "title_font_size": {
                        "type": "integer",
                        "description": "タイトルのフォントサイズ（pt）"
                    },
                    "fig_format": {
                        "type": "string",
                        "description": "保存フォーマット（pdf / png / svg）。デフォルトは pdf。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Pythonコードを実行してダウンストリーム解析・統計・可視化を行う。QIIME2の出力（.qza/.tsv/.biom）を読み込み、pandas/scipy/sklearn/matplotlib/seabornで処理する。図は必ず FIGURE_DIR に savefig で保存すること。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "実行する Python コード。FIGURE_DIR, OUTPUT_DIR, PLOT_STYLE, PLOT_PALETTE, PLOT_FIGSIZE, PLOT_DPI, FONT_SIZE 変数が自動注入される。"
                    },
                    "description": {
                        "type": "string",
                        "description": "この解析の説明（レポートに記録される）"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "解析結果・図の保存先ディレクトリ（省略時はセッションのデフォルト出力先）"
                    },
                    "subfolder": {
                        "type": "string",
                        "description": "図を保存するサブフォルダ名。解析種別ごとに分ける（例: alpha_diversity, beta_diversity, taxonomy, differential_abundance, machine_learning）。省略時は figures/ 直下。"
                    }
                },
                "required": ["code", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compile_report",
            "description": "解析結果をTeX形式のレポートにまとめてPDFを生成する。日本語版・英語版を選択可能。解析終了時にユーザーに提案する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content_ja": {
                        "type": "string",
                        "description": "日本語レポートの完全なTeX ソース（\\documentclass から \\end{document} まで）。不要なら空文字。"
                    },
                    "content_en": {
                        "type": "string",
                        "description": "英語レポートの完全なTeX ソース（\\documentclass から \\end{document} まで）。不要なら空文字。"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "出力先ディレクトリ（省略時はセッションの出力先）"
                    }
                },
                "required": ["content_ja", "content_en"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_report_tex",
            "description": "ANALYSIS_LOG を読み取り、全解析ステップ・図・統計結果を含む TeX レポートを自動生成して PDF にコンパイルする。探索が完了したとき、またはユーザーがレポートを求めたときに呼び出す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_ja": {
                        "type": "string",
                        "description": "日本語レポートのタイトル（例: ヒト腸内マイクロバイオーム 自律探索解析レポート）"
                    },
                    "title_en": {
                        "type": "string",
                        "description": "英語レポートのタイトル（例: Human Gut Microbiome Autonomous Exploration Report）"
                    },
                    "experiment_summary": {
                        "type": "string",
                        "description": "実験系の概要（実験背景・サンプル数・プライマー・グループ構成など）。ユーザーから得た情報をそのまま記載する。"
                    },
                    "lang": {
                        "type": "string",
                        "description": "生成言語: 'ja'（日本語のみ）/ 'en'（英語のみ）/ 'both'（両方, デフォルト）"
                    }
                },
                "required": ["title_ja", "title_en", "experiment_summary"]
            }
        }
    }
]

# ======================================================================
# ツール実装
# ======================================================================

def tool_inspect_directory(path: str, recursive: bool = False) -> str:
    """ディレクトリ内容を調査"""
    p = Path(path).expanduser()
    if not p.exists():
        return f"エラー: ディレクトリ '{path}' が存在しません。"
    if not p.is_dir():
        return f"エラー: '{path}' はディレクトリではありません。"

    lines = [f"📂 {p} の内容:\n"]
    total_files = 0

    def scan(dirpath: Path, depth: int = 0):
        nonlocal total_files
        indent = "  " * depth
        try:
            entries = sorted(dirpath.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            lines.append(f"{indent}  [権限エラー: アクセス不可]")
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                lines.append(f"{indent}📁 {entry.name}/")
                if recursive and depth < 3:
                    scan(entry, depth + 1)
            else:
                size = entry.stat().st_size
                size_str = f"{size:,} B" if size < 1024 else \
                           f"{size/1024:.1f} KB" if size < 1024**2 else \
                           f"{size/1024**2:.1f} MB" if size < 1024**3 else \
                           f"{size/1024**3:.1f} GB"
                ext = entry.suffix.lower()
                icon = {"": "📄", ".fastq": "🧬", ".gz": "🗜️",
                        ".qza": "🔵", ".qzv": "🟢", ".tsv": "📊",
                        ".csv": "📊", ".md": "📝", ".sh": "⚙️",
                        ".py": "🐍", ".r": "📈", ".pdf": "📕"}.get(ext, "📄")
                lines.append(f"{indent}{icon} {entry.name}  [{size_str}]")
                total_files += 1

    scan(p)
    lines.append(f"\n合計ファイル数: {total_files}")

    # QIIME2 データ判定のヒント
    all_text = "\n".join(lines)
    hints = []
    if "_R1_" in all_text or "_R1." in all_text:
        hints.append("✅ ペアエンドFASTQを検出（_R1_/_R2_ パターン）")
    elif ".fastq" in all_text:
        hints.append("✅ FASTQファイルを検出")
    if ".qza" in all_text:
        hints.append("✅ 既存の QIIME2 アーティファクト (.qza) を検出 — 途中から再開可能")
    if "metadata" in all_text.lower() or "sample_info" in all_text.lower():
        hints.append("✅ メタデータファイルを検出")
    if "manifest" in all_text.lower():
        hints.append("✅ マニフェストファイルを検出")

    if hints:
        lines.append("\n🔍 自動判定ヒント:")
        lines.extend(hints)

    return "\n".join(lines)


def tool_read_file(path: str, max_lines: int = 50) -> str:
    """ファイルの内容を読む"""
    p = Path(path).expanduser()
    if not p.exists():
        return f"エラー: ファイル '{path}' が存在しません。"
    if not p.is_file():
        return f"エラー: '{path}' はファイルではありません。"

    suffix = p.suffix.lower()
    if suffix in [".gz", ".bz2", ".qza", ".qzv"]:
        return f"'{p.name}' はバイナリ/圧縮ファイルのため内容を表示できません。\nファイルサイズ: {p.stat().st_size / 1024**2:.2f} MB"

    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"\n... （{max_lines} 行以降は省略）")
                    break
                lines.append(line.rstrip())
        return f"📄 {p} の内容（最大 {max_lines} 行）:\n\n" + "\n".join(lines)
    except Exception as e:
        return f"読み込みエラー: {e}"


def _get_docker_cmd() -> Optional[str]:
    """クロスプラットフォームで Docker 実行ファイルを検出する"""
    # macOS: Docker Desktop の固定パスを優先
    if sys.platform == "darwin":
        mac_path = "/Applications/Docker.app/Contents/Resources/bin/docker"
        if Path(mac_path).exists():
            return mac_path
    # Windows / Linux: PATH から検索
    return shutil.which("docker") or shutil.which("docker.exe")


def tool_check_system() -> str:
    """システム環境の確認"""
    results = ["[システム確認結果]\n"]

    # Docker
    docker_cmd = _get_docker_cmd()
    if docker_cmd:
        try:
            result = subprocess.run([docker_cmd, "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                results.append(f"OK Docker: {result.stdout.strip()}")
                ping = subprocess.run([docker_cmd, "info"],
                                      capture_output=True, text=True, timeout=10)
                if ping.returncode == 0:
                    results.append("OK Docker デーモン: 起動中")
                else:
                    results.append("!! Docker デーモン: 停止中 → Docker Desktop を起動してください")
            else:
                results.append("!! Docker: インストール済みだが起動していません")
        except Exception:
            results.append("!! Docker: 確認できませんでした")
    else:
        results.append("NG Docker: インストールされていません → Docker Desktop をインストールしてください")

    # Ollama
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            results.append(f"✅ Ollama: 起動中")
            if models:
                results.append(f"   利用可能モデル: {', '.join(models)}")
            else:
                results.append("   ⚠️  モデルが未インストール → 'ollama pull qwen2.5-coder:7b' を実行してください")
    except Exception:
        results.append("❌ Ollama: 起動していません → 'ollama serve' を実行してください")

    # Python
    results.append(f"✅ Python: {sys.version.split()[0]}")

    # ディスク容量
    import shutil as _shutil
    usage = _shutil.disk_usage(Path.home())
    free_gb = usage.free / 1024**3
    results.append(f"💾 ディスク空き容量: {free_gb:.1f} GB {'✅' if free_gb > 30 else '⚠️  (推奨: 30GB 以上)'}")

    return "\n".join(results)


def tool_write_file(path: str, content: str) -> str:
    """ファイルに内容を書き込む"""
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        # シェルスクリプトなら実行権限を付与
        if p.suffix in [".sh", ".bash"]:
            p.chmod(p.stat().st_mode | 0o755)
            return f"✅ '{p}' を作成しました（実行権限付き）"
        return f"✅ '{p}' を作成しました"
    except Exception as e:
        return f"❌ 書き込みエラー: {e}"


def tool_generate_manifest(fastq_dir: str, output_path: str,
                            paired_end: bool = True,
                            container_data_dir: str = "/data/output") -> str:
    """FASTQファイルからマニフェストを自動生成"""
    d = Path(fastq_dir).expanduser()
    if not d.exists():
        return f"エラー: '{fastq_dir}' が存在しません。"

    # FASTQファイルを収集
    fastq_files = sorted(d.glob("*.fastq.gz")) + sorted(d.glob("*.fastq"))

    if not fastq_files:
        return f"エラー: '{fastq_dir}' に FASTQ ファイルが見つかりません。"

    out_path = Path(output_path).expanduser()

    if paired_end:
        # R1/R2 ペアを検出
        r1_files = [f for f in fastq_files
                    if re.search(r'_R1[_.]|_1\.fastq|_R1\.fastq', f.name)]
        r2_files = [f for f in fastq_files
                    if re.search(r'_R2[_.]|_2\.fastq|_R2\.fastq', f.name)]

        if not r1_files:
            return "エラー: _R1_ パターンのファイルが見つかりません。ファイル名を確認してください。"

        # サンプル名を抽出
        lines = ["sample-id\tforward-absolute-filepath\treverse-absolute-filepath"]
        matched = 0
        unmatched = []

        for r1 in r1_files:
            # サンプル名の推定
            sample_name = re.sub(r'_R1[_.].*$|_R1\.fastq.*$', '', r1.name)
            sample_name = re.sub(r'\.fastq.*$', '', sample_name)

            # 空サンプル名は QIIME2 が拒否するためスキップ
            if not sample_name:
                unmatched.append(r1.name)
                continue

            # 対応する R2 を探す（最初の _R1_ / _R1. のみ置換し二重置換バグを防ぐ）
            r2_pattern = re.sub(r'_R1([_.])', r'_R2\1', r1.name, count=1)
            r2_candidates = [f for f in r2_files if f.name == r2_pattern]

            # コンテナ内パス
            container_r1 = f"{container_data_dir}/{r1.name}"

            if r2_candidates:
                container_r2 = f"{container_data_dir}/{r2_candidates[0].name}"
                lines.append(f"{sample_name}\t{container_r1}\t{container_r2}")
                matched += 1
            else:
                unmatched.append(r1.name)

        # ペアが一件もない場合はファイルを書かずにエラーを返す
        if matched == 0:
            return (
                "❌ エラー: ペアが1組も見つかりませんでした。\n"
                "ファイル名が _R1_/_R1. パターンに合致していない可能性があります。\n"
                f"見つかった R1 ファイル: {[f.name for f in r1_files]}"
            )

        content = "\n".join(lines) + "\n"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            f.write(content)

        result = [f"✅ ペアエンドマニフェストを生成: '{out_path}'",
                  f"   ペア数: {matched}"]
        if unmatched:
            result.append(f"   ⚠️  R2が見つからなかったファイル: {', '.join(unmatched)}")
        result.append(f"\n内容プレビュー:\n{content[:500]}")
        return "\n".join(result)

    else:
        # シングルエンド
        lines = ["sample-id\tabsolute-filepath"]
        for f in fastq_files:
            sample_name = re.sub(r'\.fastq.*$', '', f.name)
            container_path = f"{container_data_dir}/{f.name}"
            lines.append(f"{sample_name}\t{container_path}")

        content = "\n".join(lines) + "\n"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            f.write(content)

        return (f"✅ シングルエンドマニフェストを生成: '{out_path}'\n"
                f"   サンプル数: {len(fastq_files)}\n"
                f"\n内容プレビュー:\n{content[:500]}")


def tool_edit_file(path: str, old_str: str, new_str: str) -> str:
    """ファイルの一部を文字列置換で編集する"""
    p = Path(path).expanduser()
    if not p.exists():
        return f"エラー: '{path}' が存在しません。"
    if not p.is_file():
        return f"エラー: '{path}' はファイルではありません。"
    suffix = p.suffix.lower()
    if suffix in [".gz", ".bz2", ".qza", ".qzv"]:
        return f"エラー: バイナリ/圧縮ファイルは編集できません。"
    try:
        with open(p, encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_str)
        if count == 0:
            # 部分一致のヒントを提示
            snippet = old_str[:60].replace('\n', '\\n')
            return (f"エラー: 指定した文字列が '{p.name}' に見つかりません。\n"
                    f"検索文字列（先頭60字）: {snippet}\n"
                    f"read_file でファイル内容を確認してから再試行してください。")
        if count > 1:
            return (f"エラー: 指定した文字列が {count} 箇所で見つかりました。"
                    f"より一意に特定できる文字列に変更してください。")
        new_content = content.replace(old_str, new_str, 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
        old_lines = old_str.count('\n') + 1
        new_lines = new_str.count('\n') + 1
        return f"✅ '{p.name}' を編集しました（{old_lines} 行 → {new_lines} 行）"
    except Exception as e:
        return f"❌ 編集エラー: {e}"


def tool_run_command(command: str, description: str, working_dir: str = None) -> str:
    """シェルコマンドを実行（ユーザー確認付き）"""
    # working_dir を事前検証（ユーザーに確認を求める前にエラーを返す）
    if working_dir:
        cwd = Path(working_dir).expanduser()
        if not cwd.exists():
            return f"❌ ワーキングディレクトリが存在しません: {working_dir}"
        if not cwd.is_dir():
            return f"❌ ワーキングディレクトリはディレクトリではありません: {working_dir}"
    else:
        cwd = None

    print(f"\n{c(ui('cmd_request'), YELLOW)}")
    print(f"   {ui('cmd_desc')}: {description}")
    print(f"   {ui('cmd_cmd')}:\n   {c(command, CYAN)}")
    print(f"\n{c(ui('cmd_confirm'), DIM)}", end=" > ")

    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ui("cmd_cancelled_ki")

    if answer not in ["y", "yes", "はい"]:
        return ui("cmd_cancelled")

    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=3600, cwd=cwd
        )
        output_parts = []
        if proc.stdout:
            output_parts.append(f"STDOUT:\n{proc.stdout[:3000]}")
        if proc.stderr:
            output_parts.append(f"STDERR:\n{proc.stderr[:1000]}")

        if proc.returncode == 0:
            return f"✅ 成功（終了コード 0）\n" + "\n".join(output_parts)
        else:
            return f"⚠️  終了コード {proc.returncode}\n" + "\n".join(output_parts)
    except subprocess.TimeoutExpired:
        return "⏱️  タイムアウト（1時間を超えました）"
    except Exception as e:
        return f"❌ 実行エラー: {e}"


def tool_set_plot_config(style: str = None, palette: str = None,
                          figsize_w: float = None, figsize_h: float = None,
                          dpi: int = None, font_size: int = None,
                          title_font_size: int = None,
                          fig_format: str = None) -> str:
    """プロット設定を変更する"""
    changed = []
    if style is not None:
        PLOT_CONFIG["style"] = style
        changed.append(f"style: {style}")
    if palette is not None:
        PLOT_CONFIG["palette"] = palette
        changed.append(f"palette: {palette}")
    if figsize_w is not None or figsize_h is not None:
        w = figsize_w if figsize_w is not None else PLOT_CONFIG["figsize"][0]
        h = figsize_h if figsize_h is not None else PLOT_CONFIG["figsize"][1]
        PLOT_CONFIG["figsize"] = [w, h]
        changed.append(f"figsize: ({w}, {h})")
    if dpi is not None:
        PLOT_CONFIG["dpi"] = dpi
        changed.append(f"dpi: {dpi}")
    if font_size is not None:
        PLOT_CONFIG["font_size"] = font_size
        changed.append(f"font_size: {font_size}")
    if title_font_size is not None:
        PLOT_CONFIG["title_font_size"] = title_font_size
        changed.append(f"title_font_size: {title_font_size}")
    if fig_format is not None:
        fmt = fig_format.lower().lstrip(".")
        if fmt in ("pdf", "png", "svg"):
            PLOT_CONFIG["format"] = fmt
            changed.append(f"format: {fmt}")
        else:
            changed.append(f"format: 無効な値 '{fig_format}' (pdf/png/svg のいずれかを指定)")
    if changed:
        lines = "\n".join(f"  {item}" for item in changed)
        return f"✅ プロット設定を更新しました:\n{lines}"
    return "変更なし（有効なパラメータが指定されていません）"


def tool_execute_python(code: str, description: str, output_dir: str = "",
                         subfolder: str = "") -> str:
    """Pythonコードを実行してダウンストリーム解析・可視化を行う"""
    global SESSION_FIGURE_DIR

    # 出力ディレクトリの決定
    if not output_dir:
        if not SESSION_FIGURE_DIR:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            SESSION_FIGURE_DIR = str(Path.home() / "seq2pipe_results" / ts)
        output_dir = SESSION_FIGURE_DIR

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # サブフォルダ対応（解析種別ごとに図を整理）
    safe_sub = re.sub(r'[^\w]', '_', subfolder).strip('_') if subfolder else ""
    figures_dir = (out_path / "figures" / safe_sub) if safe_sub else (out_path / "figures")
    figures_dir.mkdir(parents=True, exist_ok=True)

    # プリアンブル: PLOT_CONFIG 変数 + 共通インポートを自動注入
    preamble = f"""import sys, os, warnings
warnings.filterwarnings('ignore')

# --- seq2pipe ビルトイン変数 ---
FIGURE_DIR = {repr(str(figures_dir))}
OUTPUT_DIR = {repr(str(out_path))}
PLOT_STYLE = {repr(PLOT_CONFIG['style'])}
PLOT_PALETTE = {repr(PLOT_CONFIG['palette'])}
PLOT_FIGSIZE = tuple({PLOT_CONFIG['figsize']})
PLOT_DPI = {PLOT_CONFIG['dpi']}
FONT_SIZE = {PLOT_CONFIG['font_size']}
TITLE_FONT_SIZE = {PLOT_CONFIG['title_font_size']}
FIGURE_FORMAT = {repr(PLOT_CONFIG.get('format', 'pdf'))}

# --- 共通インポート ---
try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    try:
        plt.style.use(PLOT_STYLE)
    except Exception:
        pass
    import seaborn as sns
    sns.set_palette(PLOT_PALETTE)
    matplotlib.rcParams['font.size'] = FONT_SIZE
    matplotlib.rcParams['axes.titlesize'] = TITLE_FONT_SIZE
    matplotlib.rcParams['figure.dpi'] = PLOT_DPI
except ImportError as _e:
    print(f"[WARNING] パッケージ不足: {{_e}}")
    print("pip install numpy pandas matplotlib seaborn を実行してください")

# --- ユーザーコード ---
"""

    full_code = preamble + "\n" + code

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False,
                                     encoding='utf-8') as f:
        f.write(full_code)
        tmp_path = f.name

    try:
        # 実行前の図ファイル一覧
        existing_figs = set(figures_dir.glob("*.png")) | \
                        set(figures_dir.glob("*.pdf")) | \
                        set(figures_dir.glob("*.svg"))

        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=300,
            cwd=str(out_path)
        )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        # 新規生成された図を検出
        new_figs = (set(figures_dir.glob("*.png")) |
                    set(figures_dir.glob("*.pdf")) |
                    set(figures_dir.glob("*.svg"))) - existing_figs
        new_figs = sorted(new_figs)

        # ANALYSIS_LOG に記録
        ANALYSIS_LOG.append({
            "step": len(ANALYSIS_LOG) + 1,
            "description": description,
            "subfolder": safe_sub,
            "figures": [str(f) for f in new_figs],
            "output_summary": stdout[:600] if stdout else "",
            "returncode": proc.returncode,
            "timestamp": datetime.datetime.now().isoformat(),
        })

        # 結果テキスト構築
        parts = []
        if proc.returncode == 0:
            parts.append(f"✅ 解析完了: {description}")
        else:
            parts.append(f"⚠️  解析でエラーが発生: {description}")
        if stdout:
            parts.append(f"\n📄 出力:\n{stdout[:2000]}")
        if stderr and proc.returncode != 0:
            parts.append(f"\n[STDERR]\n{stderr[:500]}")
        if new_figs:
            parts.append(f"\n📊 生成された図 ({len(new_figs)} 件):")
            for fig in new_figs:
                parts.append(f"   {fig}")
        else:
            parts.append("\n（図は生成されませんでした。savefig を呼んでいない可能性があります）")

        return "\n".join(parts)

    except subprocess.TimeoutExpired:
        return "⏱️  タイムアウト（5分を超えました）"
    except Exception as e:
        return f"❌ 実行エラー: {e}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# サブフォルダ → セクション名 マッピング
_SECTION_JA = {
    "alpha_diversity":        "α多様性解析",
    "beta_diversity":         "β多様性解析",
    "taxonomy":               "分類組成解析",
    "differential_abundance": "差次存在量解析",
    "machine_learning":       "機械学習判別解析",
}
_SECTION_EN = {
    "alpha_diversity":        "Alpha Diversity Analysis",
    "beta_diversity":         "Beta Diversity Analysis",
    "taxonomy":               "Taxonomic Composition Analysis",
    "differential_abundance": "Differential Abundance Analysis",
    "machine_learning":       "Machine Learning Classification",
}
_SUBFOLDER_ORDER = [
    "alpha_diversity", "beta_diversity", "taxonomy",
    "differential_abundance", "machine_learning", "",
]


def _tex_escape(s: str) -> str:
    """TeX 特殊文字をエスケープ（順序依存に注意）

    処理順序の原則:
    1. \\ をプレースホルダーに退避（後続ループで {} が再エスケープされるのを防ぐ）
    2. { } を ^ ~ より先に処理（^ → \\^{} の {} が再エスケープされるバグを防ぐ）
    3. プレースホルダーを \\textbackslash{} に置換（ステップ2 の {} エスケープを受けない）
    """
    _BS = "\x00BACKSLASH\x00"
    s = s.replace("\\", _BS)
    for ch, rep in [("&", r"\&"), ("%", r"\%"), ("#", r"\#"),
                    ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                    ("$", r"\$"), ("^", r"\^{}"), ("~", r"\~{}")]:
        s = s.replace(ch, rep)
    s = s.replace(_BS, r"\textbackslash{}")
    return s


def _build_tex_content(lang_code: str, title_ja: str, title_en: str,
                        experiment_summary: str,
                        report_dir: Optional[Path] = None) -> str:
    """ANALYSIS_LOG から TeX ソースを組み立てる"""
    from collections import defaultdict

    is_ja = (lang_code == "ja")
    title = title_ja if is_ja else title_en
    section_map = _SECTION_JA if is_ja else _SECTION_EN

    groups: dict = defaultdict(list)
    for entry in ANALYSIS_LOG:
        groups[entry.get("subfolder", "")].append(entry)

    total_figs = sum(len(e.get("figures", [])) for e in ANALYSIS_LOG)

    L = []  # lines

    # ── プリアンブル ──────────────────────────────────────────
    if is_ja:
        L += [
            r"\documentclass[a4paper,12pt]{article}",
            r"\usepackage{xeCJK}",
            r"\setCJKmainfont{Hiragino Mincho ProN}",
        ]
    else:
        L += [r"\documentclass[a4paper,12pt]{article}"]

    L += [
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{geometry}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\geometry{margin=2.5cm}",
        f"\\title{{{_tex_escape(title)}}}",
        r"\author{seq2pipe}",
        r"\date{\today}",
        r"\begin{document}",
        r"\maketitle",
        r"\tableofcontents",
        r"\newpage",
    ]

    # ── 概要セクション ────────────────────────────────────────
    if is_ja:
        L += [
            r"\section{解析概要}",
            r"本レポートは seq2pipe の自律探索モードによって実行された解析の記録です。",
            r"LLM エージェントが実験系の情報をもとに複数の解析手法を自動で選択・実行し、",
            r"統計的有意性を評価しながら結果を整理しました。",
            r"\vspace{1em}",
            r"\begin{tabular}{ll}",
            r"\toprule",
            f"総解析ステップ数 & {len(ANALYSIS_LOG)} \\\\",
            f"生成された図 & {total_figs} 件 \\\\",
            r"\bottomrule",
            r"\end{tabular}",
        ]
        if experiment_summary:
            L += [r"\vspace{1em}", r"\subsection{実験系}", _tex_escape(experiment_summary)]
    else:
        L += [
            r"\section{Overview}",
            r"This report documents the analyses performed by seq2pipe's autonomous exploration mode.",
            r"The LLM agent automatically selected and executed multiple analysis methods",
            r"based on the experimental context, evaluating statistical significance at each step.",
            r"\vspace{1em}",
            r"\begin{tabular}{ll}",
            r"\toprule",
            f"Total analysis steps & {len(ANALYSIS_LOG)} \\\\",
            f"Figures generated & {total_figs} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
        ]
        if experiment_summary:
            L += [r"\vspace{1em}", r"\subsection{Experimental Setup}",
                  _tex_escape(experiment_summary)]

    # ── 解析フェーズごとのセクション ─────────────────────────
    for sf in _SUBFOLDER_ORDER:
        if sf not in groups:
            continue
        entries = groups[sf]
        sec_name = section_map.get(sf, (_tex_escape(sf) if sf else
                                        ("その他の解析" if is_ja else "Other Analyses")))
        L.append(f"\n\\section{{{sec_name}}}")

        for entry in entries:
            desc = _tex_escape(entry.get("description", ""))
            figs = entry.get("figures", [])
            out_summary = entry.get("output_summary", "")
            ok = entry.get("returncode", 0) == 0

            L.append(f"\n\\subsection{{{desc}}}")

            # 統計出力の抜粋
            stat_lines = [line for line in out_summary.split("\n")
                          if any(kw in line.lower() for kw in
                                 ["p =", "p=", "p-value", "pvalue", "accuracy",
                                  "auc", "significant", "有意", "statistic",
                                  "f1", "precision", "recall", "r2", "rmse"])]
            if stat_lines:
                L += [r"\begin{verbatim}"] + stat_lines[:12] + [r"\end{verbatim}"]
            elif not ok:
                L.append(r"\textit{(この解析はエラーにより完了しませんでした)}"
                         if is_ja else
                         r"\textit{(This analysis did not complete due to an error)}")

            # 図の挿入
            for fig_path in figs:
                caption = desc
                # report_dir からの相対パスを使用（tectonic のサンドボックス対策）
                if report_dir is not None:
                    try:
                        fig_include = os.path.relpath(fig_path, report_dir).replace("\\", "/")
                    except ValueError:
                        fig_include = fig_path  # Windowsドライブ跨ぎ等で失敗した場合は絶対パス
                else:
                    fig_include = fig_path
                L += [
                    r"\begin{figure}[htbp]",
                    r"\centering",
                    f"\\includegraphics[width=0.85\\textwidth]{{{fig_include}}}",
                    f"\\caption{{{caption}}}",
                    r"\end{figure}",
                ]

    # ── 解析ログ表 ────────────────────────────────────────────
    log_title = "解析ログ" if is_ja else "Analysis Log"
    L += [
        f"\n\\section{{{log_title}}}",
        r"\begin{longtable}{r p{7cm} r r}",
        r"\toprule",
    ]
    if is_ja:
        L.append(r"Step & 解析 & 図数 & 状態 \\ \midrule \endhead")
    else:
        L.append(r"Step & Analysis & Figs & Status \\ \midrule \endhead")

    for entry in ANALYSIS_LOG:
        step = entry.get("step", "")
        desc = _tex_escape(entry.get("description", ""))
        n_figs = len(entry.get("figures", []))
        # ✓/✗ ではなく ASCII 文字を使う（フォント依存を避けるため）
        ok = r"\textbf{OK}" if entry.get("returncode", 0) == 0 else r"\textbf{NG}"
        L.append(f"{step} & {desc} & {n_figs} & {ok} \\\\")

    L += [r"\bottomrule", r"\end{longtable}", r"\end{document}"]

    return "\n".join(L)


def tool_build_report_tex(title_ja: str, title_en: str,
                            experiment_summary: str = "",
                            lang: str = "both") -> str:
    """ANALYSIS_LOG から TeX を自動生成してコンパイルする"""
    if not ANALYSIS_LOG:
        return "❌ ANALYSIS_LOG が空です。先に execute_python で解析を実行してください。"

    # 出力先
    if SESSION_FIGURE_DIR:
        report_dir = Path(SESSION_FIGURE_DIR) / "report"
    else:
        report_dir = Path.home() / "seq2pipe_results" / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    tectonic_bin = shutil.which("tectonic")
    results = []

    tasks = []
    if lang in ("ja", "both"):
        tasks.append(("report_ja.tex", "ja", "日本語"))
    if lang in ("en", "both"):
        tasks.append(("report_en.tex", "en", "英語"))

    for filename, lc, label in tasks:
        tex_content = _build_tex_content(lc, title_ja, title_en, experiment_summary, report_dir)
        tex_path = report_dir / filename
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        results.append(f"✅ {label} TeX を生成: {tex_path}")

        if tectonic_bin:
            try:
                proc = subprocess.run(
                    [tectonic_bin, str(tex_path)],
                    capture_output=True, text=True,
                    timeout=120, cwd=str(report_dir)
                )
                pdf_path = tex_path.with_suffix(".pdf")
                if proc.returncode == 0 and pdf_path.exists():
                    results.append(f"✅ {label} PDF を生成: {pdf_path}")
                else:
                    results.append(f"⚠️  {label} PDF コンパイル失敗")
                    if proc.stderr:
                        results.append(f"   {proc.stderr[:300]}")
            except subprocess.TimeoutExpired:
                results.append(f"⏱️  {label} コンパイルタイムアウト")
            except Exception as e:
                results.append(f"❌ {label} コンパイルエラー: {e}")
        else:
            results.append("⚠️  tectonic が見つかりません。brew install tectonic でインストールしてください。")

    results.append(f"\n📁 出力先: {report_dir}")
    results.append(f"📊 記録された解析ステップ: {len(ANALYSIS_LOG)}")
    results.append(f"🖼️  総図数: {sum(len(e.get('figures', [])) for e in ANALYSIS_LOG)}")
    return "\n".join(results)


def tool_compile_report(content_ja: str, content_en: str, output_dir: str = "") -> str:
    """TeX レポートをコンパイルして PDF を生成する"""
    if not output_dir:
        if SESSION_FIGURE_DIR:
            output_dir = str(Path(SESSION_FIGURE_DIR) / "report")
        else:
            output_dir = str(Path.home() / "seq2pipe_results" / "report")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    results = []
    tectonic = shutil.which("tectonic")

    tasks = []
    if content_ja and content_ja.strip():
        tasks.append(("report_ja.tex", content_ja, "日本語"))
    if content_en and content_en.strip():
        tasks.append(("report_en.tex", content_en, "英語"))

    if not tasks:
        return "❌ content_ja と content_en の両方が空です。"

    for filename, content, label in tasks:
        tex_path = out_path / filename
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(content)
        results.append(f"✅ {label} TeX ファイルを作成: {tex_path}")

        if tectonic:
            try:
                proc = subprocess.run(
                    [tectonic, str(tex_path)],
                    capture_output=True, text=True,
                    timeout=120, cwd=str(out_path)
                )
                pdf_path = tex_path.with_suffix('.pdf')
                if proc.returncode == 0 and pdf_path.exists():
                    results.append(f"✅ {label} PDF 生成完了: {pdf_path}")
                else:
                    results.append(f"⚠️  {label} PDF コンパイルに問題:")
                    if proc.stderr:
                        results.append(f"   {proc.stderr[:400]}")
            except subprocess.TimeoutExpired:
                results.append(f"⏱️  {label} コンパイルタイムアウト")
            except Exception as e:
                results.append(f"❌ {label} コンパイルエラー: {e}")
        else:
            results.append(f"⚠️  tectonic が見つかりません。brew install tectonic でインストール後、手動でコンパイルしてください。")

    return "\n".join(results)


def dispatch_tool(name: str, args: dict) -> str:
    """ツール名とパラメータからツール関数を呼び出す"""
    try:
        if name == "inspect_directory":
            return tool_inspect_directory(**args)
        elif name == "read_file":
            return tool_read_file(**args)
        elif name == "check_system":
            return tool_check_system()
        elif name == "write_file":
            return tool_write_file(**args)
        elif name == "generate_manifest":
            return tool_generate_manifest(**args)
        elif name == "edit_file":
            return tool_edit_file(**args)
        elif name == "run_command":
            return tool_run_command(**args)
        elif name == "set_plot_config":
            return tool_set_plot_config(**args)
        elif name == "execute_python":
            return tool_execute_python(**args)
        elif name == "compile_report":
            return tool_compile_report(**args)
        elif name == "build_report_tex":
            return tool_build_report_tex(**args)
        else:
            return f"❌ 不明なツール: {name}"
    except TypeError as e:
        return f"❌ ツール引数エラー ({name}): {e}"
    except Exception as e:
        return f"❌ ツール実行エラー ({name}): {e}"


# ======================================================================
# Ollama API
# ======================================================================

def call_ollama(messages: list, model: str, tools: list = None) -> dict:
    """Ollama /api/chat を呼び出す（ストリーミング有効）"""
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        body["temperature"] = 0.3  # ツール引数JSON生成の安定性向上

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    full_content = ""
    tool_calls = []
    thinking_content = ""

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})
                content = msg.get("content", "")

                # thinking（推論ブロック、qwen3等）
                if msg.get("thinking"):
                    thinking_content += msg["thinking"]
                    continue

                # tool_calls が含まれる場合
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])

                # コンテンツをストリーミング表示
                if content:
                    print(content, end="", flush=True)
                    full_content += content

                if chunk.get("done"):
                    break

        if full_content:
            print()  # 改行

        return {
            "content": full_content,
            "tool_calls": tool_calls,
            "thinking": thinking_content
        }

    except urllib.error.HTTPError as e:
        raise ConnectionError(
            f"Ollama HTTP エラー: {e.code} {e.reason}\n"
            f"詳細: {e}"
        )
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Ollama に接続できません（{OLLAMA_URL}）。\n"
            f"'ollama serve' を別ターミナルで実行してください。\n詳細: {e}"
        )
    except TimeoutError as e:
        raise ConnectionError(
            f"Ollama への接続がタイムアウトしました（timeout=300s）。\n詳細: {e}"
        )


def check_python_deps() -> bool:
    """numpy/pandas/matplotlib/seaborn が sys.executable でインポートできるか確認"""
    check_code = "import numpy, pandas, matplotlib, seaborn"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", check_code],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            print(f"   {c(ui('deps_ok'), GREEN)}")
            return True
        else:
            # ImportError の場合 stderr からパッケージ名を抽出
            missing = proc.stderr.strip().split("\n")[-1] if proc.stderr else "不明"
            print(f"   {c(ui('deps_warn', missing), YELLOW)}")
            print(f"   {ui('deps_hint')}")
            install_cmd = f"{sys.executable} -m pip install numpy pandas matplotlib seaborn"
            print(f"   {ui('deps_hint2', c(install_cmd, CYAN))}")
            return False
    except Exception:
        return False


def check_ollama_running() -> bool:
    """Ollama が起動しているか確認"""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


def get_available_models() -> list:
    """利用可能なモデル一覧を取得"""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ======================================================================
# エージェントループ
# ======================================================================

def run_agent_loop(messages: list, model: str, max_steps: int = 30):
    """ツール呼び出しを含むエージェントループを実行"""
    steps = 0
    while True:
        if steps >= max_steps:
            print(f"\n{c(ui('agent_limit', max_steps), YELLOW)}")
            break
        steps += 1

        print(f"\n{c('🤖 AI', CYAN + BOLD)}: ", end="", flush=True)

        response = call_ollama(messages, model, tools=TOOLS)
        assistant_msg = {"role": "assistant", "content": response["content"]}

        # tool_calls があれば実行
        if response["tool_calls"]:
            tool_results = []
            for tc in response["tool_calls"]:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                tool_args = fn.get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {}

                print(f"\n{c(ui('tool_exec', tool_name), MAGENTA)}")
                print(f"{c(json.dumps(tool_args, ensure_ascii=False, indent=2), DIM)}")

                result = dispatch_tool(tool_name, tool_args)

                print(f"\n{c(ui('tool_result'), GREEN)}")
                print(result)

                tool_results.append({
                    "role": "tool",
                    "content": result
                })

            # tool_calls を assistant メッセージに追加（重複チェック不要 — 外側の if で確認済み）
            assistant_msg["tool_calls"] = response["tool_calls"]

            messages.append(assistant_msg)
            messages.extend(tool_results)

            # ツール実行後、続けて AI に応答させる
            continue
        else:
            # ツールなし → 通常の応答で終了
            messages.append(assistant_msg)
            break


# ======================================================================
# バナー・UI
# ======================================================================

# バナー文字列（"2" を正しいシングル斜めで修正済み）
BANNER_LINES = [
    " ███████╗███████╗ ██████╗ ██████╗",
    " ██╔════╝██╔════╝██╔═══██╗╚════██╗",
    " ███████╗█████╗  ██║   ██║  ██╔═╝",
    " ╚════██║██╔══╝  ██║▄▄ ██║ ██╔╝",
    " ███████║███████╗╚██████╔╝██████╗",
    " ╚══════╝╚══════╝ ╚══▀▀═╝ ╚═════╝",
    " ██████╗ ██╗██████╗ ███████╗",
    " ██╔══██╗██║██╔══██╗██╔════╝",
    " ██████╔╝██║██████╔╝█████╗",
    " ██╔═══╝ ██║██╔═══╝ ██╔══╝",
    " ██║     ██║██║     ███████╗",
    " ╚═╝     ╚═╝╚═╝     ╚══════╝",
    "      sequence -> pipeline",
]

# シアン系グラデーション（256色）
_GRAD = [
    "\033[38;5;23m",   # dark teal
    "\033[38;5;30m",
    "\033[38;5;37m",
    "\033[38;5;44m",
    "\033[38;5;51m",   # bright cyan
    "\033[1;36m",      # bold cyan
    "\033[38;5;87m",
    "\033[38;5;123m",  # pale cyan
    "\033[38;5;87m",
    "\033[1;36m",
    "\033[38;5;51m",
    "\033[38;5;44m",
    "\033[38;5;37m",
]


def print_banner():
    """グラデーション＋スパークルアニメーションでバナーを表示"""
    import time
    import random

    n = len(BANNER_LINES)
    is_tty = sys.stdout.isatty()

    if not is_tty:
        for line in BANNER_LINES:
            print(f"{CYAN}{BOLD}{line}{RESET}")
        return

    try:
        # Phase 1: 暗いシアンで一瞬表示
        for line in BANNER_LINES:
            sys.stdout.write(f"\033[38;5;23m{line}\033[0m\n")
        sys.stdout.flush()
        time.sleep(0.04)

        # Phase 2: カーソルを先頭へ戻す
        sys.stdout.write(f"\033[{n}A\r")
        sys.stdout.flush()

        # Phase 3: グラデーションカラーで下スイープ
        for i, line in enumerate(BANNER_LINES):
            color = _GRAD[i % len(_GRAD)]
            sys.stdout.write(f"\033[2K{color}\033[1m{line}\033[0m\n")
            sys.stdout.flush()
            time.sleep(0.03)

        # Phase 4: スパークル（ランダム行が白く光る × 3波）
        for _ in range(3):
            sparks = set(random.sample(range(n), k=min(4, n)))
            sys.stdout.write(f"\033[{n}A\r")
            for i, line in enumerate(BANNER_LINES):
                color = "\033[1;97m" if i in sparks else _GRAD[i % len(_GRAD)]
                sys.stdout.write(f"\033[2K{color}\033[1m{line}\033[0m\n")
            sys.stdout.flush()
            time.sleep(0.09)

        # Phase 5: グラデーション状態に落ち着く
        sys.stdout.write(f"\033[{n}A\r")
        for i, line in enumerate(BANNER_LINES):
            color = _GRAD[i % len(_GRAD)]
            sys.stdout.write(f"\033[2K{color}\033[1m{line}\033[0m\n")
        sys.stdout.flush()
        print()

    except Exception:
        # アニメーション失敗時は静的表示にフォールバック
        for line in BANNER_LINES:
            print(f"{CYAN}{BOLD}{line}{RESET}")

INITIAL_MESSAGE = """こんにちは！私は QIIME2 + Python ダウンストリーム解析を支援するローカル AI エージェントです。

対応している解析:
  [QIIME2] インポート → DADA2 デノイジング → 分類 → 多様性解析 → 差次解析
  [Python] 組成ヒートマップ / PCoA 図 / ランダムフォレスト判別 / ネットワーク解析
  [レポート] 解析終了後に TeX / PDF レポートを日本語・英語で自動生成

始めるために、以下を教えてください:

  1. データディレクトリのパス
     例: /Users/yourname/microbiome-data/

  2. 実験系の説明
     例: ヒト腸内細菌、16S V3-V4 領域（341F/806R）、Illumina MiSeq ペアエンド 2×250bp
         コントロール 5 サンプル vs 処理群 5 サンプル

  3. 行いたい解析
     例: 分類組成の可視化 / α・β 多様性解析 / グループ間の差次解析 / 機械学習判別

  4. 図のスタイル（省略可）
     例: 白背景・色は青系 / ダーク系 / 論文向け高解像度（300 DPI）

一度にまとめて教えてもらうと、より的確なパイプラインを生成できます。
"""

INITIAL_MESSAGE_EN = """Hello! I am a local AI agent specialized in QIIME2 + Python downstream microbiome analysis.

Supported analyses:
  [QIIME2] Import → DADA2 denoising → Taxonomy classification → Diversity analysis → Differential analysis
  [Python] Composition heatmap / PCoA plot / Random forest classification / Network analysis
  [Report] Auto-generate TeX / PDF reports in Japanese or English after analysis

To get started, please provide:

  1. Path to your data directory
     e.g. /Users/yourname/microbiome-data/

  2. Description of your experiment
     e.g. Human gut microbiome, 16S V3-V4 (341F/806R), Illumina MiSeq paired-end 2×250bp
          5 control samples vs 5 treatment samples

  3. Analyses you want to perform
     e.g. Taxonomy composition visualization / Alpha & beta diversity / Differential analysis / ML classification

  4. Figure style (optional)
     e.g. White background, blue palette / Dark theme / High-resolution for publication (300 DPI)

Providing all information at once helps generate a more accurate pipeline.
"""


def select_language() -> str:
    """起動時に操作言語を選択する（JA / EN）。選択結果を返し LANG グローバルを更新する。"""
    global LANG
    print(f"\n{CYAN}{BOLD}  Select language / 言語を選択してください{RESET}")
    print(f"  {BOLD}[1]{RESET} 日本語 (Japanese)")
    print(f"  {BOLD}[2]{RESET} English")
    while True:
        try:
            choice = input(f"\n  {BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{c(ui('goodbye'), CYAN)}")
            sys.exit(0)
        if choice in ("1", "ja", "JA", "japanese", "Japanese"):
            LANG = "ja"
            break
        elif choice in ("2", "en", "EN", "english", "English"):
            LANG = "en"
            break
        else:
            print(f"  {YELLOW}Please enter 1 or 2 / 1 か 2 を入力してください{RESET}")
    print()
    return LANG


def select_model(available_models: list) -> str:
    """使用するモデルを選択"""
    # 環境変数 QIIME2_AI_MODEL が設定されている場合は最優先
    if DEFAULT_MODEL in available_models:
        return DEFAULT_MODEL

    preferred = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "qwen3:8b",
                 "llama3.2:3b", "llama3.1:8b", "mistral:7b", "codellama:7b"]

    for p in preferred:
        if p in available_models:
            return p
        # プレフィックス一致
        for m in available_models:
            if m.startswith(p.split(":")[0]):
                return m

    if available_models:
        return available_models[0]
    return DEFAULT_MODEL


# ======================================================================
# メインエントリポイント
# ======================================================================

def main():
    # Windows 10+ で ANSI エスケープコードを有効化
    if sys.platform == "win32":
        os.system("")

    print_banner()

    # セッションごとにグローバル状態をリセット（同一プロセスで複数回呼ばれた場合の混入防止）
    global ANALYSIS_LOG, SESSION_FIGURE_DIR
    ANALYSIS_LOG = []
    SESSION_FIGURE_DIR = ""

    # 言語選択
    select_language()

    # Python 依存パッケージ確認（失敗しても続行、警告のみ）
    check_python_deps()

    # Ollama 起動確認
    if not check_ollama_running():
        print(f"{c(ui('ollama_error'), RED)}")
        print(f"   {ui('ollama_hint')}")
        print(f"   {c('ollama serve', CYAN)}")
        print(f"\n   {ui('ollama_hint2')}")
        print(f"   {c('./setup.sh', CYAN)}")
        sys.exit(1)

    # モデル選択
    available = get_available_models()
    if not available:
        print(f"{c(ui('no_model'), YELLOW)}")
        print(f"   {ui('no_model_hint', c('ollama pull qwen2.5-coder:7b', CYAN))}")
        print(f"   {ui('no_model_hint2', c('ollama pull llama3.2:3b', CYAN))}")
        sys.exit(1)

    model = select_model(available)
    print(f"{c(ui('model_selected', model), GREEN)}")
    print(f"{c(ui('hint_exit'), DIM)}\n")

    # 言語に応じたシステムプロンプトと初期メッセージを選択
    if LANG == "en":
        # SYSTEM_PROMPT の末尾に追記することで「最後の指示」として機能させる
        # （LLM は後方の指示を優先する傾向があるため、先頭追記より確実）
        lang_suffix = (
            "\n\n━━━ LANGUAGE OVERRIDE (highest priority) ━━━\n"
            "The user has selected English as the interface language.\n"
            "You MUST respond in English for ALL subsequent messages.\n"
            "This includes explanations, shell scripts, Python code comments, and reports.\n"
            "Do NOT use Japanese in any output."
        )
        initial_msg = INITIAL_MESSAGE_EN
    else:
        lang_suffix = ""
        initial_msg = INITIAL_MESSAGE

    # 会話履歴を初期化
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + lang_suffix},
        {"role": "assistant", "content": initial_msg}
    ]

    print(f"{c('🤖 AI', CYAN + BOLD)}: {initial_msg}")

    # メインループ
    while True:
        try:
            user_input = input(f"\n{c(ui('prompt'), BOLD + GREEN)} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{c(ui('goodbye'), CYAN)}")
            break

        if not user_input:
            continue

        if user_input.lower() in ["quit", "exit", "終了", "q"]:
            print(f"\n{c(ui('goodbye'), CYAN)}")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            run_agent_loop(messages, model)
        except ConnectionError as e:
            print(f"\n{c(str(e), RED)}")
            break
        except Exception as e:
            print(f"\n{c(ui('runtime_error', e), RED)}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
