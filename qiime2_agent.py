#!/usr/bin/env python3
# coding: utf-8
"""
QIIME2 Local AI Agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ローカルLLM（Ollama）を使ったマイクロバイオーム解析支援ツール

依存ライブラリ: Python 標準ライブラリのみ（外部パッケージ不要）
必要ツール   : Ollama (setup.sh でインストール), Docker Desktop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ======================================================================
# 設定
# ======================================================================
OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = os.environ.get("QIIME2_AI_MODEL", "qwen2.5-coder:7b")
SCRIPT_DIR = Path(__file__).parent.resolve()

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

━━━ あなたの役割 ━━━
1. ユーザーが指定したディレクトリのデータ構造を調査する
2. データの形式（FASTQ・マニフェスト・メタデータ等）を自動判定する
3. データに合わせた最適な QIIME2 解析パイプラインを提案する
4. 実行可能なシェルスクリプトを生成する
5. 解析結果の可視化方法を説明する README.md を自動生成する

━━━ 行動原則 ━━━
- 必ずツールを使ってデータを実際に確認してから計画を立てる
- FASTQファイルの命名パターンを見てペアエンド/シングルエンドを判定する
- 既存の .qza ファイルがあれば途中から再開できることを伝える
- 生成するスクリプトには詳細なコメントを付ける（日本語で）
- Docker コマンドは必ず `--rm` と `-v` マウントを含める

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
- `core-metrics-results/` = 多様性解析の全出力"""

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


def tool_check_system() -> str:
    """システム環境の確認"""
    results = ["🖥️  システム確認結果:\n"]

    # Docker
    docker_path = "/Applications/Docker.app/Contents/Resources/bin/docker"
    if Path(docker_path).exists():
        try:
            result = subprocess.run([docker_path, "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                results.append(f"✅ Docker: {result.stdout.strip()}")
                # Docker デーモン起動確認
                ping = subprocess.run([docker_path, "info"],
                                      capture_output=True, text=True, timeout=10)
                if ping.returncode == 0:
                    results.append("✅ Docker デーモン: 起動中")
                else:
                    results.append("⚠️  Docker デーモン: 停止中 → Docker Desktop を起動してください")
            else:
                results.append("⚠️  Docker: インストール済みだが起動していません")
        except Exception:
            results.append("⚠️  Docker: 確認できませんでした")
    elif shutil.which("docker"):
        try:
            result = subprocess.run(["docker", "--version"],
                                    capture_output=True, text=True, timeout=5)
            results.append(f"✅ Docker: {result.stdout.strip()}")
        except Exception:
            results.append("❌ Docker: 見つかりません")
    else:
        results.append("❌ Docker: インストールされていません → Docker Desktop をインストールしてください")

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

            # 対応する R2 を探す
            r2_pattern = r1.name.replace("_R1_", "_R2_").replace("_R1.", "_R2.")
            r2_candidates = [f for f in r2_files if f.name == r2_pattern]

            # コンテナ内パス
            container_r1 = f"{container_data_dir}/{r1.name}"

            if r2_candidates:
                container_r2 = f"{container_data_dir}/{r2_candidates[0].name}"
                lines.append(f"{sample_name}\t{container_r1}\t{container_r2}")
                matched += 1
            else:
                unmatched.append(r1.name)

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


def tool_run_command(command: str, description: str, working_dir: str = None) -> str:
    """シェルコマンドを実行（ユーザー確認付き）"""
    print(f"\n{c('⚡ コマンド実行リクエスト', YELLOW)}")
    print(f"   説明: {description}")
    print(f"   コマンド:\n   {c(command, CYAN)}")
    print(f"\n{c('[y] 実行する  [n] キャンセル', DIM)}", end=" > ")

    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "❌ キャンセルされました（キーボード割り込み）"

    if answer not in ["y", "yes", "はい"]:
        return "❌ ユーザーによりキャンセルされました。"

    try:
        cwd = Path(working_dir).expanduser() if working_dir else None
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
        elif name == "run_command":
            return tool_run_command(**args)
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

    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Ollama に接続できません（{OLLAMA_URL}）。\n"
            f"'ollama serve' を別ターミナルで実行してください。\n詳細: {e}"
        )


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

def run_agent_loop(messages: list, model: str):
    """ツール呼び出しを含むエージェントループを実行"""
    while True:
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

                print(f"\n{c(f'🔧 ツール実行: {tool_name}', MAGENTA)}")
                print(f"{c(json.dumps(tool_args, ensure_ascii=False, indent=2), DIM)}")

                result = dispatch_tool(tool_name, tool_args)

                print(f"\n{c('📋 実行結果:', GREEN)}")
                print(result)

                tool_results.append({
                    "role": "tool",
                    "content": result
                })

            # tool_calls を assistant メッセージに追加
            if response["tool_calls"]:
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

BANNER = f"""{CYAN}{BOLD}
╔═══════════════════════════════════════════════════════════════╗
║          QIIME2 Local AI Agent  🧬                           ║
║  ローカル LLM でマイクロバイオームデータを自動解析します     ║
╚═══════════════════════════════════════════════════════════════╝{RESET}
"""

INITIAL_MESSAGE = """こんにちは！私は QIIME2 解析を支援するローカル AI エージェントです。

あなたの生データを解析し、以下を自動生成します:
  📜 解析パイプラインスクリプト（run_pipeline.sh）
  🧬 分類器セットアップスクリプト（setup_classifier.sh）
  📊 メタデータ・マニフェストファイル
  📖 操作ガイド（README.md）

まず、**解析したいデータが入っているディレクトリのパス**を教えてください。
（例: `/Users/yourname/microbiome-data/` または `~/experiment01/`）
"""


def select_model(available_models: list) -> str:
    """使用するモデルを選択"""
    preferred = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "llama3.2:3b",
                 "llama3.1:8b", "mistral:7b", "codellama:7b"]

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
    print(BANNER)

    # Ollama 起動確認
    if not check_ollama_running():
        print(f"{c('❌ Ollama が起動していません。', RED)}")
        print(f"   以下のコマンドを別ターミナルで実行してから再試行してください:")
        print(f"   {c('ollama serve', CYAN)}")
        print(f"\n   Ollama が未インストールの場合:")
        print(f"   {c('./setup.sh', CYAN)} を実行してセットアップしてください。")
        sys.exit(1)

    # モデル選択
    available = get_available_models()
    if not available:
        print(f"{c('⚠️  Ollama にモデルがインストールされていません。', YELLOW)}")
        print(f"   推奨モデル: {c('ollama pull qwen2.5-coder:7b', CYAN)}")
        print(f"   軽量版    : {c('ollama pull llama3.2:3b', CYAN)}")
        sys.exit(1)

    model = select_model(available)
    print(f"{c(f'✅ 使用モデル: {model}', GREEN)}")
    print(f"{c('ヒント: 終了するには Ctrl+C を押してください。', DIM)}\n")

    # 会話履歴を初期化
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": INITIAL_MESSAGE}
    ]

    print(f"{c('🤖 AI', CYAN + BOLD)}: {INITIAL_MESSAGE}")

    # メインループ
    while True:
        try:
            user_input = input(f"\n{c('あなた', BOLD + GREEN)} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{c('👋 終了します。お疲れ様でした！', CYAN)}")
            break

        if not user_input:
            continue

        if user_input.lower() in ["quit", "exit", "終了", "q"]:
            print(f"\n{c('👋 終了します。お疲れ様でした！', CYAN)}")
            break

        messages.append({"role": "user", "content": user_input})

        try:
            run_agent_loop(messages, model)
        except ConnectionError as e:
            print(f"\n{c(str(e), RED)}")
            break
        except Exception as e:
            print(f"\n{c(f'エラーが発生しました: {e}', RED)}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
