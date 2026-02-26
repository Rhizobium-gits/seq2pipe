#!/usr/bin/env python3
"""
QIIME2 パイプライン完了後の解析専用スクリプト。
taxonomy なし・多様性 + デノイジング統計に特化。
"""
import sys
sys.path.insert(0, '/Users/satoutsubasa/seq2pipe')

from pathlib import Path
from chat_agent import InteractiveSession

EXPORT_DIR = "/Users/satoutsubasa/seq2pipe_results/20260226_183511/exported"
OUTPUT_DIR = "/Users/satoutsubasa/seq2pipe_results/20260226_183511"
FIGURE_DIR = "/Users/satoutsubasa/seq2pipe_results/20260226_183511/figures"

print("=== chat_agent 解析開始 ===", flush=True)
print(f"export_dir: {EXPORT_DIR}", flush=True)

session = InteractiveSession(
    export_dir=EXPORT_DIR,
    output_dir=OUTPUT_DIR,
    figure_dir=FIGURE_DIR,
)

print(f"検出ファイル: {list(session.export_files.keys())}", flush=True)

session.setup(
    description=(
        "ヒト便検体 10 サンプル（TEST01〜TEST10）の 16S rRNA 解析。"
        "凍結乾燥便、MiSeq ペアエンド。"
        "taxonomy 分類ファイルは存在しないため、多様性と統計量のみ解析する。"
    ),
    goals=(
        "各サンプルの Shannon・Faith PD・evenness・observed features を可視化。"
        "Bray-Curtis・UniFrac の PCoA で群間構造を確認。"
        "Jaccard 距離マトリックスのヒートマップ。"
        "DADA2 デノイジング統計（input/filtered/merged/non-chimeric）の棒グラフ。"
    ),
    lang="ja",
)

# taxonomy を含まない解析プランを明示的に指定
analyses = [
    (
        "Plot all four alpha diversity metrics (Shannon, Faith PD, evenness, observed_features) "
        "as separate subplots (2x2 grid) with stripplot overlay. "
        "Read from: "
        "/Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/alpha/shannon_vector/alpha-diversity.tsv, "
        "/Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/alpha/faith_pd_vector/alpha-diversity.tsv, "
        "/Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/alpha/evenness_vector/alpha-diversity.tsv, "
        "/Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/alpha/observed_features_vector/alpha-diversity.tsv"
    ),
    (
        "Plot Bray-Curtis PCoA from distance matrix. "
        "File: /Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/beta/bray_curtis_distance_matrix/distance-matrix.tsv. "
        "Use sklearn MDS (n_components=2, dissimilarity='precomputed'). "
        "Color points by sample name (tab10 palette). "
        "Label each point with sample ID."
    ),
    (
        "Plot UniFrac (unweighted) PCoA from distance matrix. "
        "File: /Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/beta/unweighted_unifrac_distance_matrix/distance-matrix.tsv. "
        "Use sklearn MDS (n_components=2, dissimilarity='precomputed'). "
        "Label each point. Modern seaborn style."
    ),
    (
        "Plot Jaccard distance heatmap. "
        "File: /Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/beta/jaccard_distance_matrix/distance-matrix.tsv. "
        "Use seaborn clustermap with 'viridis' colormap. "
        "Show sample labels on both axes."
    ),
    (
        "Plot DADA2 denoising statistics as grouped bar chart. "
        "File: /Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/denoising_stats/stats.tsv. "
        "Columns: input, filtered, denoised, merged, non-chimeric. "
        "One group per sample, bars for each statistic. "
        "Use tab10 palette, rotated x-axis labels."
    ),
    (
        "Plot Shannon alpha diversity per sample as a horizontal violin plot. "
        "File: /Users/satoutsubasa/seq2pipe_results/20260226_183511/exported/alpha/shannon_vector/alpha-diversity.tsv. "
        "Sort samples by Shannon value. Add mean line. Modern seaborn white style."
    ),
]

print(f"\n解析プラン ({len(analyses)} ステップ) を実行:", flush=True)
for i, a in enumerate(analyses, 1):
    print(f"  {i}. {a[:80]}...", flush=True)

session.run_planned(analyses)

print("\n=== レポート生成 ===", flush=True)
rpt = session.generate_report()
print(f"  TeX : {rpt['tex_path']}", flush=True)
print(f"  PDF : {rpt['pdf_path']}", flush=True)

print("\n" + session.get_summary(), flush=True)
