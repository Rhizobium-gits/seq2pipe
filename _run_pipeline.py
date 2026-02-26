#!/usr/bin/env python3
"""
フルパイプライン + 解析 実行スクリプト
stdout は呼び出し元シェルにそのまま渡す（_Tee 不使用）。
"""
import sys, os
sys.path.insert(0, '/Users/satoutsubasa/seq2pipe')

import datetime
import shutil
from pathlib import Path
import qiime2_agent as _agent
from chat_agent import InteractiveSession

# ── マニフェストのモンキーパッチ ──────────────────────────────────────────
# qiime2_agent の自動生成（サンプルID が TEST01_SpRn_L001 になる）を避け、
# 正しいサンプルID（TEST01 等）と実ホストパスを持つ事前作成マニフェストを使う。
_CUSTOM_MANIFEST = "/Users/satoutsubasa/input/manifest.tsv"

def _patched_generate_manifest(fastq_dir, output_path, **kwargs):
    shutil.copy(_CUSTOM_MANIFEST, output_path)
    return f"✅ カスタムマニフェストを使用: {_CUSTOM_MANIFEST}"

_agent.tool_generate_manifest = _patched_generate_manifest

# ── 出力ディレクトリ ────────────────────────────────────────────────────────
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_dir = Path.home() / "seq2pipe_results" / ts
output_dir.mkdir(parents=True, exist_ok=True)
fig_dir = output_dir / "figures"
fig_dir.mkdir(exist_ok=True)

print(f"=== seq2pipe 開始 {ts} ===", flush=True)
print(f"出力先: {output_dir}", flush=True)

# ── グローバル注入 ──────────────────────────────────────────────────────────
_agent.SESSION_OUTPUT_DIR = str(output_dir)
_agent.SESSION_FIGURE_DIR = str(fig_dir)
_agent.AUTO_YES = True

# ── STEP 1: QIIME2 パイプライン ─────────────────────────────────────────────
print("\n" + "="*55, flush=True)
print("STEP 1/3: QIIME2 パイプライン (DADA2 + taxonomy + diversity)", flush=True)
print("="*55, flush=True)

result_text = _agent.tool_run_qiime2_pipeline(
    fastq_dir="/Users/satoutsubasa/input",
    paired_end=True,
    trim_left_f=0,
    trim_left_r=0,
    trunc_len_f=250,
    trunc_len_r=200,
    metadata_path="/Users/satoutsubasa/input/sample-metadata.tsv",
    n_threads=4,
    sampling_depth=3000,
)

lines = result_text.splitlines() if result_text else []
pipeline_ok = result_text and not any(l.startswith("❌") for l in lines[:5])

print(f"\nパイプライン結果 (先頭 5 行):", flush=True)
for l in lines[:5]:
    print(f"  {l}", flush=True)

export_dir = output_dir / "exported"
if not export_dir.exists():
    # qiime2_agent が使う出力ディレクトリを探す
    # SESSION_OUTPUT_DIR 内の exported/ を検索
    candidates = list(output_dir.glob("*/exported")) + list(output_dir.glob("exported"))
    if candidates:
        export_dir = candidates[0]

print(f"\nexport_dir: {export_dir}", flush=True)
print(f"exists: {export_dir.exists()}", flush=True)

if not export_dir.exists() or not pipeline_ok:
    print("❌ パイプライン失敗。終了します。", flush=True)
    sys.exit(1)

# ── STEP 2: 自律解析 ────────────────────────────────────────────────────────
print("\n" + "="*55, flush=True)
print("STEP 2/3: 多様性・菌叢構成解析 (chat_agent 自律モード)", flush=True)
print("="*55, flush=True)

session = InteractiveSession(
    export_dir=str(export_dir),
    output_dir=str(output_dir),
    figure_dir=str(fig_dir),
)

session.setup(
    description=(
        "ヒト便検体 10 サンプル（TEST01〜TEST10）の 16S rRNA アンプリコン解析。"
        "凍結乾燥便、Illumina MiSeq ペアエンド、V3-V4 領域。"
    ),
    goals=(
        "α 多様性（Shannon, Faith PD, observed features）の各サンプル分布を可視化。"
        "β 多様性（Bray-Curtis, UniFrac）による群間構造の PCoA。"
        "門・属レベルの菌叢構成比率の積み上げ棒グラフ。"
        "優占菌（トップ 10 属・門）の相対存在量。"
        "デノイジング統計による品質確認。"
    ),
    lang="ja",
)

analyses = session.plan_analysis_suite()
print(f"\n解析プラン ({len(analyses)} ステップ):", flush=True)
for i, a in enumerate(analyses, 1):
    print(f"  {i}. {a}", flush=True)

print("\n全解析を自動実行中...", flush=True)
session.run_planned(analyses)

# ── STEP 3: レポート生成 ────────────────────────────────────────────────────
print("\n" + "="*55, flush=True)
print("STEP 3/3: TeX/PDF レポート生成", flush=True)
print("="*55, flush=True)

rpt = session.generate_report()
print(f"  TeX : {rpt['tex_path']}", flush=True)
print(f"  PDF : {rpt['pdf_path']}", flush=True)
print(f"  Dir : {rpt['report_dir']}", flush=True)

print("\n" + session.get_summary(), flush=True)
print(f"\n✅ 完了！ 出力先: {output_dir}", flush=True)
