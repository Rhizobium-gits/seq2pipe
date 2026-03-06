#!/usr/bin/env python3
"""
test/example_mode2_auto.py
===========================
モード 2（--auto 完全自律モード）のローカル実行例。

ユーザー介入なしで全パイプラインを実行。

実行コマンド:
    ./launch.sh --fastq-dir ~/input --auto
    ./launch.sh --fastq-dir ~/input --auto --threads 4 --classifier ~/silva.qza

フロー（4 ステップ自動化パイプライン）:
    cli.py main()
      ├─ _detect_dada2_params()              # FASTQ → パラメータ自動推定
      │   ├─ _sample_read_lengths()          #   先頭200リードの長さ取得
      │   ├─ _count_reads()                  #   リード数カウント
      │   └─ _detect_seq_type()              #   16S/ショットガン判定
      │
      ├─ STEP 1: run_pipeline(config)        # QIIME2 パイプライン
      │   └─ 内部で実行されるコマンド:
      │       qiime tools import ...
      │       qiime dada2 denoise-paired ...
      │       qiime phylogeny align-to-tree-mafft-fasttree ...
      │       qiime feature-classifier classify-sklearn ...  (--classifier 指定時)
      │       qiime diversity core-metrics-phylogenetic ...
      │       qiime tools export ...
      │
      ├─ STEP 1.5: run_comprehensive_analysis()  # 決定論的解析（LLM 不使用）
      │   └─ analysis.py が 29 種類の PNG を生成（下記参照）
      │   └─ generate_analysis_summary() → dict（パターン検出）
      │
      ├─ STEP 2: run_coding_agent(           # 適応型自律エージェント
      │     user_prompt="",                  #   空 → 自律モード
      │     analysis_summary=summary)        #   STEP 1.5 のサマリーを渡す
      │   └─ _build_adaptive_task() が以下のような動的プロンプトを生成:
      │       "Outlier investigation: TEST05 has low Shannon..."
      │       "High-variance genus: Prevotella (CV=1.3)..."
      │   └─ LLM がデータ適応型の追加図を自律生成
      │
      └─ STEP 3: generate_html_report()      # HTML レポート自動生成
"""

# =====================================================================
# STEP 1.5: analysis.py が生成する 29 種類の図（決定論的・LLM 不使用）
# =====================================================================
# 以下は analysis.py の run_comprehensive_analysis() が内部で実行する
# コードの抜粋。全て try/except でラップされ、データがなければスキップ。

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.manifold import MDS

EXPORT = Path("~/seq2pipe_results/20260303_120000/exported").expanduser()
FIG_DIR = Path("~/seq2pipe_results/20260303_120000/figures").expanduser()


# ── fig01: DADA2 デノイジング統計 ──
def fig01_dada2_stats():
    stats = pd.read_csv(EXPORT / "dada2_stats" / "stats.tsv",
                        sep="\t", skiprows=1, index_col=0)
    cols = ["input", "filtered", "denoised", "merged", "non-chimeric"]
    available = [c for c in cols if c in stats.columns]
    stats[available].plot(kind="bar", figsize=(10, 5))
    plt.title("DADA2 Denoising Statistics")
    plt.ylabel("Read Count")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig01_dada2_stats.png", dpi=200)
    plt.close()


# ── fig03: α多様性ボックスプロット ──
def fig03_alpha_diversity():
    alpha_dir = EXPORT / "alpha"
    metrics = {}
    for name in ["shannon", "observed_features", "faith_pd"]:
        p = alpha_dir / f"{name}_vector" / "alpha-diversity.tsv"
        if p.exists():
            df = pd.read_csv(p, sep="\t", index_col=0)
            metrics[name] = df.iloc[:, 0]

    fig, axes = plt.subplots(1, len(metrics), figsize=(4 * len(metrics), 5))
    if len(metrics) == 1:
        axes = [axes]
    for ax, (name, vals) in zip(axes, metrics.items()):
        ax.boxplot(vals.dropna().values)
        ax.set_title(name.replace("_", " ").title())
        ax.set_ylabel(name)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig03_alpha_diversity.png", dpi=200)
    plt.close()


# ── fig05: PCoA (Bray-Curtis) + 分散説明率 ──
def fig05_pcoa_braycurtis():
    dm_path = EXPORT / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    dm = pd.read_csv(dm_path, sep="\t", index_col=0)
    dm_vals = dm.values
    n = dm_vals.shape[0]

    # 固有値分解で分散説明率を計算
    H = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * H @ (dm_vals ** 2) @ H
    eigvals = np.linalg.eigvalsh(B)
    eigvals = np.sort(eigvals)[::-1]
    pos_eig = eigvals[eigvals > 0]
    var_exp = pos_eig / pos_eig.sum() * 100

    mds = MDS(n_components=2, dissimilarity="precomputed", random_state=42,
              normalized_stress=False)
    coords = mds.fit_transform(dm_vals)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(coords[:, 0], coords[:, 1], s=80)
    for i, sid in enumerate(dm.index):
        ax.annotate(sid, (coords[i, 0], coords[i, 1]), fontsize=8)
    ax.set_xlabel(f"PC1 ({var_exp[0]:.1f}%)")
    ax.set_ylabel(f"PC2 ({var_exp[1]:.1f}%)")
    ax.set_title("PCoA (Bray-Curtis)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig05_pcoa_braycurtis.png", dpi=200)
    plt.close()


# ── fig24: サンプルデンドログラム (UPGMA) ──
def fig24_dendrogram():
    dm_path = EXPORT / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    dm = pd.read_csv(dm_path, sep="\t", index_col=0)
    from scipy.spatial.distance import squareform
    condensed = squareform(dm.values)
    Z = linkage(condensed, method="average")

    fig, ax = plt.subplots(figsize=(10, 5))
    dendrogram(Z, labels=dm.index.tolist(), ax=ax, leaf_rotation=45)
    ax.set_title("Sample Dendrogram (UPGMA, Bray-Curtis)")
    ax.set_ylabel("Distance")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig24_dendrogram.png", dpi=200)
    plt.close()


# =====================================================================
# STEP 2: 適応型自律エージェントが生成するコードの例
# =====================================================================
# _build_adaptive_task() が STEP 1.5 のサマリーから動的プロンプトを構築し、
# LLM がそれに基づいて以下のようなコードを自律生成する。

def adaptive_01_outlier_investigation():
    """外れ値サンプル（TEST05）の属プロファイルを他と比較"""
    ft = pd.read_csv(EXPORT / "feature_table" / "feature-table.biom.tsv",
                     sep="\t", skiprows=1, index_col=0)
    ft = ft.select_dtypes(include=[np.number])
    tax = pd.read_csv(EXPORT / "taxonomy" / "taxonomy.tsv", sep="\t", index_col=0)

    common = ft.index.intersection(tax.index)
    genera = tax.loc[common, "Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown")
    ft_g = ft.loc[common].copy()
    ft_g["Genus"] = genera.values
    genus_rel = ft_g.groupby("Genus").sum()
    genus_rel = genus_rel.div(genus_rel.sum(axis=0), axis=1) * 100

    outlier = "TEST05"
    others = [c for c in genus_rel.columns if c != outlier]
    top10 = genus_rel.mean(axis=1).sort_values(ascending=False).head(10).index

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(top10))
    width = 0.35
    ax.bar(x - width / 2, genus_rel.loc[top10, outlier],
           width, label=outlier, color="tomato")
    ax.bar(x + width / 2, genus_rel.loc[top10, others].mean(axis=1),
           width, label="Others (mean)", color="steelblue")
    ax.set_xticks(x)
    ax.set_xticklabels(top10, rotation=45, ha="right")
    ax.set_ylabel("Relative Abundance (%)")
    ax.set_title(f"Genus Profile: {outlier} vs Others")
    ax.legend()
    plt.tight_layout()
    plt.savefig(FIG_DIR / "adaptive_01_outlier_TEST05.png", dpi=200)
    plt.close()


def adaptive_02_high_variance_genus():
    """高変動属（Prevotella）のサンプル間分布"""
    ft = pd.read_csv(EXPORT / "feature_table" / "feature-table.biom.tsv",
                     sep="\t", skiprows=1, index_col=0)
    ft = ft.select_dtypes(include=[np.number])
    tax = pd.read_csv(EXPORT / "taxonomy" / "taxonomy.tsv", sep="\t", index_col=0)

    common = ft.index.intersection(tax.index)
    genera = tax.loc[common, "Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown")
    ft_g = ft.loc[common].copy()
    ft_g["Genus"] = genera.values
    genus_rel = ft_g.groupby("Genus").sum()
    genus_rel = genus_rel.div(genus_rel.sum(axis=0), axis=1) * 100

    target = "Prevotella"
    if target in genus_rel.index:
        vals = genus_rel.loc[target]
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(vals.index, vals.values, color="coral")
        ax.axhline(vals.mean(), color="gray", linestyle="--",
                   label=f"Mean: {vals.mean():.1f}%")
        ax.set_ylabel("Relative Abundance (%)")
        ax.set_xlabel("Sample")
        ax.set_title(f"{target} Abundance Across Samples (CV={vals.std()/vals.mean():.2f})")
        ax.legend()
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "adaptive_02_prevotella_variance.png", dpi=200)
        plt.close()


# =====================================================================
# STEP 3: HTML レポート生成（report_generator.py）
# =====================================================================
# generate_html_report() は以下を実行:
#   1. figures/ 内の全 PNG を base64 エンコード
#   2. _ANALYSIS_CATEGORIES に基づいてカテゴリ分け
#   3. 各カテゴリに数式・解説カードを付与
#   4. 自己完結型 HTML ファイルとして出力
#
# 出力例: ~/seq2pipe_results/20260303_120000/report.html
