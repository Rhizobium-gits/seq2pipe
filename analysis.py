#!/usr/bin/env python3
"""
analysis.py
===========
QIIME2 エクスポートデータから包括的な微生物叢解析図を
LLM に依存せず確定的に生成するモジュール。

使い方:
    from analysis import run_comprehensive_analysis
    figs = run_comprehensive_analysis(export_dir, figure_dir)
"""

import warnings
from pathlib import Path
from typing import Callable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import seaborn as sns
    sns.set_theme(style="white", context="paper", font_scale=1.2)
    _HAS_SNS = True
except ImportError:
    _HAS_SNS = False

try:
    from sklearn.manifold import MDS
    _HAS_SKL = True
except ImportError:
    _HAS_SKL = False

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False

try:
    from scipy import stats as sp_stats
    from scipy.cluster import hierarchy as sp_hierarchy
    from scipy.spatial.distance import squareform
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

DPI = 200
PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]


def _save(fig_dir: Path, name: str) -> str:
    path = fig_dir / name
    plt.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close()
    return str(path)


# ══════════════════════════════════════════════════════════════════════
# 個別図の生成関数
# ══════════════════════════════════════════════════════════════════════

def _fig_dada2_stats(fig_dir: Path, export_dir: Path, session_dir: Path) -> Optional[str]:
    """fig01: DADA2 denoising statistics"""
    stats_path = export_dir / "denoising_stats" / "stats.tsv"
    if not stats_path.exists():
        return None
    stats = pd.read_csv(stats_path, sep="\t", index_col=0)
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(stats))
    w = 0.18
    cols = [c for c in ["input", "filtered", "denoised", "merged", "non-chimeric"] if c in stats.columns]
    for i, col in enumerate(cols):
        ax.bar(x + i * w, stats[col], width=w, label=col, color=PALETTE[i % len(PALETTE)], alpha=0.85, edgecolor="white")
    ax.set_xticks(x + w * (len(cols) - 1) / 2)
    ax.set_xticklabels(stats.index, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Read Count", fontsize=12, labelpad=6)
    ax.set_title("DADA2 Denoising Statistics per Sample", fontsize=14, fontweight="bold", pad=10)
    ax.legend(frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig01_dada2_stats.png")


def _fig_sequencing_depth(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig02: Sequencing depth per sample"""
    read_depth = ft.sum(axis=0).sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(read_depth))]
    ax.bar(range(len(read_depth)), read_depth.values, color=colors, edgecolor="white", alpha=0.85)
    ax.set_xticks(range(len(read_depth)))
    ax.set_xticklabels(read_depth.index, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Total Read Count", fontsize=12, labelpad=6)
    ax.set_title("Sequencing Depth per Sample", fontsize=14, fontweight="bold", pad=10)
    ax.axhline(read_depth.mean(), color="#C44E52", lw=1.5, ls="--", label=f"Mean: {read_depth.mean():.0f}")
    ax.legend(frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig02_sequencing_depth.png")


def _fig_alpha_diversity(fig_dir: Path, alpha: pd.DataFrame) -> Optional[str]:
    """fig03: Alpha diversity boxplots (3 metrics)"""
    cols = [c for c in alpha.columns if alpha[c].notna().sum() > 0]
    n = len(cols)
    if n == 0:
        return None
    colors_a = ["#4C72B0", "#55A868", "#DD8452", "#C44E52"]
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
    if n == 1:
        axes = [axes]
    for ax, col, color in zip(axes, cols, colors_a):
        vals = alpha[col].dropna()
        if _HAS_SNS:
            sns.boxplot(y=vals, ax=ax, color=color, width=0.4, linewidth=1.5,
                        flierprops=dict(marker="o", markersize=5, alpha=0.6))
            sns.stripplot(y=vals, ax=ax, color="#333333", size=5, alpha=0.6, jitter=True)
        else:
            ax.boxplot(vals, patch_artist=True, boxprops=dict(facecolor=color, alpha=0.7))
        ax.set_title(col, fontsize=13, fontweight="bold", pad=8)
        ax.set_ylabel(col, fontsize=11, labelpad=6)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle("Alpha Diversity Metrics", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    return _save(fig_dir, "fig03_alpha_diversity.png")


def _fig_shannon_per_sample(fig_dir: Path, alpha: pd.DataFrame) -> Optional[str]:
    """fig04: Shannon per sample strip plot"""
    if "Shannon" not in alpha.columns:
        return None
    samples = alpha.index.tolist()
    x = np.arange(len(samples))
    vals = alpha["Shannon"].values
    fig, ax = plt.subplots(figsize=(11, 5))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(samples))]
    ax.scatter(x, vals, c=colors, s=90, zorder=3, edgecolors="white", lw=0.8)
    ax.plot(x, vals, color="#999999", lw=1, zorder=2)
    for i, (xi, yi, sid) in enumerate(zip(x, vals, samples)):
        ax.annotate(sid, (xi, yi), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7, color="#444444")
    ax.set_xticks(x)
    ax.set_xticklabels(samples, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Shannon Diversity Index", fontsize=12, labelpad=6)
    ax.set_title("Shannon Diversity Index per Sample", fontsize=14, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig04_shannon_per_sample.png")


def _fig_pcoa(fig_dir: Path, export_dir: Path) -> list:
    """fig05-08: Beta diversity PCoA (4 metrics)"""
    if not _HAS_SKL:
        return []
    metrics = [
        ("braycurtis_distance_matrix", "Bray-Curtis", "#4C72B0"),
        ("jaccard_distance_matrix", "Jaccard", "#DD8452"),
        ("unweighted_unifrac_distance_matrix", "Unweighted UniFrac", "#55A868"),
        ("weighted_unifrac_distance_matrix", "Weighted UniFrac", "#C44E52"),
    ]
    saved = []
    for i, (fname, label, color) in enumerate(metrics, start=5):
        dm_path = export_dir / "beta" / fname / "distance-matrix.tsv"
        if not dm_path.exists():
            continue
        try:
            dm = pd.read_csv(dm_path, sep="\t", index_col=0)
            n = len(dm)
            coords = MDS(n_components=2, dissimilarity="precomputed",
                         random_state=42, max_iter=500).fit_transform(dm.values)
            # variance explained via eigendecomposition of centered distance matrix
            A = -0.5 * dm.values ** 2
            row_mean = A.mean(axis=1, keepdims=True)
            col_mean = A.mean(axis=0, keepdims=True)
            grand_mean = A.mean()
            G = A - row_mean - col_mean + grand_mean
            eigvals = np.linalg.eigvalsh(G)
            eigvals = np.sort(eigvals)[::-1]
            eigvals = np.maximum(eigvals, 0)
            total_var = eigvals.sum()
            var_exp = eigvals[:2] / total_var * 100 if total_var > 0 else [0, 0]
            fig, ax = plt.subplots(figsize=(7, 6))
            ax.scatter(coords[:, 0], coords[:, 1],
                       c=[color] * n, s=100, edgecolors="white", lw=0.8, zorder=3, alpha=0.9)
            for j, sid in enumerate(dm.index):
                ax.annotate(sid, (coords[j, 0], coords[j, 1]),
                            textcoords="offset points", xytext=(6, 4), fontsize=8, color="#444444")
            ax.set_title(f"{label} PCoA", fontsize=14, fontweight="bold", pad=10)
            ax.set_xlabel(f"PC 1 ({var_exp[0]:.1f}%)", fontsize=12, labelpad=6)
            ax.set_ylabel(f"PC 2 ({var_exp[1]:.1f}%)", fontsize=12, labelpad=6)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            plt.tight_layout()
            short = fname.split("_distance")[0]
            saved.append(_save(fig_dir, f"fig0{i}_pcoa_{short}.png"))
        except Exception:
            pass
    return saved


def _fig_beta_heatmaps(fig_dir: Path, export_dir: Path) -> Optional[str]:
    """fig09: Beta diversity distance matrix heatmaps (2x2)"""
    metrics = [
        ("braycurtis_distance_matrix", "Bray-Curtis"),
        ("jaccard_distance_matrix", "Jaccard"),
        ("unweighted_unifrac_distance_matrix", "Unweighted UniFrac"),
        ("weighted_unifrac_distance_matrix", "Weighted UniFrac"),
    ]
    dms = []
    for fname, label in metrics:
        p = export_dir / "beta" / fname / "distance-matrix.tsv"
        if p.exists():
            dms.append((label, pd.read_csv(p, sep="\t", index_col=0)))
    if not dms:
        return None
    rows = (len(dms) + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(14, 6 * rows))
    axes = np.array(axes).flatten()
    for idx, (label, dm) in enumerate(dms):
        ax = axes[idx]
        if _HAS_SNS:
            sns.heatmap(dm, ax=ax, cmap="YlOrRd", square=True, linewidths=0.3,
                        linecolor="white", annot=True, fmt=".2f", annot_kws={"size": 7},
                        cbar_kws={"shrink": 0.7})
        else:
            im = ax.imshow(dm.values, cmap="YlOrRd", aspect="auto")
            plt.colorbar(im, ax=ax, shrink=0.7)
            ax.set_xticks(range(len(dm)))
            ax.set_xticklabels(dm.columns, rotation=45, ha="right", fontsize=7)
            ax.set_yticks(range(len(dm)))
            ax.set_yticklabels(dm.index, fontsize=7)
        ax.set_title(label, fontsize=12, fontweight="bold", pad=8)
    for idx in range(len(dms), len(axes)):
        axes[idx].set_visible(False)
    fig.suptitle("Beta Diversity Distance Matrices", fontsize=15, fontweight="bold", y=1.01)
    plt.tight_layout()
    return _save(fig_dir, "fig09_beta_distance_heatmaps.png")


def _fig_top_asv_heatmap(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig10: Top 30 ASV relative abundance heatmap"""
    ft_rel = ft.div(ft.sum(axis=0), axis=1) * 100
    top30 = ft_rel.mean(axis=1).nlargest(30).index
    top_df = ft_rel.loc[top30]
    fig, ax = plt.subplots(figsize=(12, 10))
    if _HAS_SNS:
        sns.heatmap(top_df, ax=ax, cmap="Blues", linewidths=0.2, linecolor="white",
                    xticklabels=True, yticklabels=True,
                    cbar_kws={"label": "Relative Abundance (%)", "shrink": 0.6})
    else:
        im = ax.imshow(top_df.values, cmap="Blues", aspect="auto")
        plt.colorbar(im, ax=ax, label="Relative Abundance (%)", shrink=0.6)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels([f"ASV{i+1}" for i in range(len(top30))], fontsize=8)
    ax.set_title("Top 30 ASVs — Relative Abundance Heatmap", fontsize=14, fontweight="bold", pad=10)
    ax.set_xlabel("Sample", fontsize=12, labelpad=6)
    ax.set_ylabel("ASV", fontsize=12, labelpad=6)
    plt.tight_layout()
    return _save(fig_dir, "fig10_top30_asv_heatmap.png")


def _fig_alpha_correlations(fig_dir: Path, alpha: pd.DataFrame) -> Optional[str]:
    """fig11: Alpha diversity correlations"""
    pairs = [("Shannon", "Observed ASVs"), ("Shannon", "Faith PD")]
    valid = [(cx, cy) for cx, cy in pairs if cx in alpha.columns and cy in alpha.columns]
    if not valid:
        return None
    fig, axes = plt.subplots(1, len(valid), figsize=(6 * len(valid), 5))
    if len(valid) == 1:
        axes = [axes]
    for ax, (cx, cy) in zip(axes, valid):
        x_vals, y_vals = alpha[cx].values, alpha[cy].values
        colors = [PALETTE[j % len(PALETTE)] for j in range(len(alpha))]
        ax.scatter(x_vals, y_vals, c=colors, s=80, edgecolors="white", lw=0.8, zorder=3)
        for j, sid in enumerate(alpha.index):
            ax.annotate(sid, (x_vals[j], y_vals[j]),
                        textcoords="offset points", xytext=(5, 3), fontsize=7, color="#555555")
        m, b = np.polyfit(x_vals, y_vals, 1)
        xline = np.linspace(x_vals.min(), x_vals.max(), 50)
        ax.plot(xline, m * xline + b, color="#C44E52", lw=1.5, ls="--", alpha=0.7)
        ax.set_xlabel(cx, fontsize=12, labelpad=6)
        ax.set_ylabel(cy, fontsize=12, labelpad=6)
        ax.set_title(f"{cx} vs {cy}", fontsize=13, fontweight="bold", pad=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle("Alpha Diversity Correlations", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    return _save(fig_dir, "fig11_alpha_correlations.png")


def _fig_richness_vs_depth(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig12: ASV richness vs sequencing depth"""
    asv_rich = (ft > 0).sum(axis=0)
    depth = ft.sum(axis=0)
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(depth))]
    ax.scatter(depth, asv_rich, c=colors, s=90, edgecolors="white", lw=0.8, zorder=3)
    for sid in depth.index:
        ax.annotate(sid, (depth[sid], asv_rich[sid]),
                    textcoords="offset points", xytext=(6, 3), fontsize=8, color="#444444")
    m, b = np.polyfit(depth.values, asv_rich.values, 1)
    xline = np.linspace(depth.min(), depth.max(), 50)
    ax.plot(xline, m * xline + b, color="#C44E52", lw=1.5, ls="--", alpha=0.8)
    ax.set_xlabel("Sequencing Depth (reads)", fontsize=12, labelpad=6)
    ax.set_ylabel("ASV Richness", fontsize=12, labelpad=6)
    ax.set_title("ASV Richness vs Sequencing Depth", fontsize=14, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig12_richness_vs_depth.png")


def _fig_genus_composition(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame, top_n: int = 15) -> Optional[str]:
    """fig13: Genus-level stacked bar chart"""
    tax["Genus"] = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax["Genus"] = tax["Genus"].replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax.loc[common, "Genus"]
    genus_counts = merged.groupby("Genus").sum()
    genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100
    top = genus_rel.mean(axis=1).sort_values(ascending=False).head(top_n).index.tolist()
    plot_df = genus_rel.loc[top].copy()
    plot_df.loc["Other"] = genus_rel.drop(index=top, errors="ignore").sum(axis=0)
    plot_df = plot_df.T
    colors = list(plt.cm.tab20.colors[:top_n]) + [(0.75, 0.75, 0.75)]
    fig, ax = plt.subplots(figsize=(12, 6))
    plot_df.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8, edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Sample ID", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title(f"Genus-Level Composition (Top {top_n})", fontsize=14, fontweight="bold", pad=10)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(title="Genus", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8, title_fontsize=9, frameon=False)
    ax.set_ylim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig13_genus_composition.png")


def _fig_phylum_composition(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig14: Phylum-level stacked bar chart"""
    tax["Phylum"] = tax["Taxon"].str.extract(r"p__([^;]+)")[0].fillna("Unknown").str.strip()
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Phylum"] = tax.loc[common, "Phylum"]
    phylum_counts = merged.groupby("Phylum").sum()
    phylum_rel = phylum_counts.div(phylum_counts.sum(axis=0), axis=1) * 100
    top = phylum_rel.mean(axis=1).sort_values(ascending=False).head(10).index.tolist()
    plot_df = phylum_rel.loc[top].copy()
    plot_df.loc["Other"] = phylum_rel.drop(index=top, errors="ignore").sum(axis=0)
    plot_df = plot_df.T
    colors = list(plt.cm.Set3.colors[:10]) + [(0.75, 0.75, 0.75)]
    fig, ax = plt.subplots(figsize=(12, 6))
    plot_df.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8, edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Sample ID", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title("Phylum-Level Composition", fontsize=14, fontweight="bold", pad=10)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(title="Phylum", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9, title_fontsize=10, frameon=False)
    ax.set_ylim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig14_phylum_composition.png")


def _fig_genus_heatmap(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig15: Top 20 genera heatmap"""
    if not _HAS_SNS:
        return None
    tax["Genus"] = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax["Genus"] = tax["Genus"].replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax.loc[common, "Genus"]
    genus_counts = merged.groupby("Genus").sum()
    genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100
    top20 = genus_rel.mean(axis=1).sort_values(ascending=False).head(20).index
    hm_df = genus_rel.loc[top20]
    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(hm_df, ax=ax, cmap="YlOrRd", linewidths=0.3, linecolor="white",
                annot=True, fmt=".1f", annot_kws={"size": 7},
                cbar_kws={"label": "Relative Abundance (%)", "shrink": 0.7})
    ax.set_title("Top 20 Genera — Relative Abundance (%)", fontsize=14, fontweight="bold", pad=10)
    ax.set_xlabel("Sample", fontsize=12, labelpad=6)
    ax.set_ylabel("Genus", fontsize=12, labelpad=6)
    plt.tight_layout()
    return _save(fig_dir, "fig15_genus_heatmap.png")


# ══════════════════════════════════════════════════════════════════════
# 拡張解析図 (fig16-fig25)
# ══════════════════════════════════════════════════════════════════════

def _fig_rarefaction(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig16: Rarefaction curves per sample"""
    rng = np.random.default_rng(42)
    counts = ft.values.astype(int)  # ASV x Samples
    n_asv, n_samples = counts.shape
    fig, ax = plt.subplots(figsize=(10, 6))
    for s_idx in range(n_samples):
        col = counts[:, s_idx]
        total = col.sum()
        if total == 0:
            continue
        depths = np.linspace(100, total, 10, dtype=int)
        depths = depths[depths > 0]
        medians = []
        pool = np.repeat(np.arange(n_asv), col)
        for d in depths:
            obs_list = []
            for _ in range(10):
                sub = rng.choice(pool, size=min(d, len(pool)), replace=False)
                obs_list.append(len(np.unique(sub)))
            medians.append(np.median(obs_list))
        color = PALETTE[s_idx % len(PALETTE)]
        ax.plot(depths, medians, marker="o", markersize=3, lw=1.5,
                color=color, alpha=0.8, label=ft.columns[s_idx])
    ax.set_xlabel("Sequencing Depth", fontsize=12, labelpad=6)
    ax.set_ylabel("Observed ASVs", fontsize=12, labelpad=6)
    ax.set_title("Rarefaction Curves", fontsize=14, fontweight="bold", pad=10)
    ax.legend(fontsize=8, frameon=False, bbox_to_anchor=(1.01, 1), loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig16_rarefaction_curves.png")


def _fig_nmds(fig_dir: Path, export_dir: Path) -> Optional[str]:
    """fig17: NMDS ordination (Bray-Curtis)"""
    if not _HAS_SKL:
        return None
    dm_path = export_dir / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    if not dm_path.exists():
        return None
    dm = pd.read_csv(dm_path, sep="\t", index_col=0)
    mds = MDS(n_components=2, dissimilarity="precomputed", metric=False,
              random_state=42, max_iter=1000, normalized_stress="auto")
    coords = mds.fit_transform(dm.values)
    stress = mds.stress_
    fig, ax = plt.subplots(figsize=(8, 7))
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(dm))]
    ax.scatter(coords[:, 0], coords[:, 1], c=colors, s=120,
               edgecolors="white", lw=0.8, zorder=3, alpha=0.9)
    for j, sid in enumerate(dm.index):
        ax.annotate(sid, (coords[j, 0], coords[j, 1]),
                    textcoords="offset points", xytext=(6, 4), fontsize=8, color="#444444")
    ax.set_title(f"NMDS (Bray-Curtis)  stress={stress:.3f}",
                 fontsize=14, fontweight="bold", pad=10)
    ax.set_xlabel("NMDS1", fontsize=12, labelpad=6)
    ax.set_ylabel("NMDS2", fontsize=12, labelpad=6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig17_nmds_braycurtis.png")


def _fig_rank_abundance(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig18: Rank-abundance curves"""
    fig, ax = plt.subplots(figsize=(10, 6))
    for s_idx, sid in enumerate(ft.columns):
        abundances = ft[sid].values.copy()
        abundances = abundances[abundances > 0]
        abundances = np.sort(abundances)[::-1]
        rel = abundances / abundances.sum() * 100
        color = PALETTE[s_idx % len(PALETTE)]
        ax.semilogy(np.arange(1, len(rel) + 1), rel, lw=1.5,
                     color=color, alpha=0.7, label=sid)
    ax.set_xlabel("Species Rank", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%, log)", fontsize=12, labelpad=6)
    ax.set_title("Rank-Abundance Curves", fontsize=14, fontweight="bold", pad=10)
    ax.legend(fontsize=8, frameon=False, bbox_to_anchor=(1.01, 1), loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig18_rank_abundance.png")


def _fig_taxonomic_alluvial(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig19: Taxonomic alluvial plot (Phylum -> Class -> Order)"""
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    levels = [("Phylum", r"p__([^;]+)"), ("Class", r"c__([^;]+)"), ("Order", r"o__([^;]+)")]
    tax_levels = {}
    for lvl_name, pattern in levels:
        tax_levels[lvl_name] = tax["Taxon"].str.extract(pattern)[0].fillna("Unknown").str.strip()
        tax_levels[lvl_name] = tax_levels[lvl_name].replace("", "Unknown")

    common = ft.index.intersection(tax.index)
    total_reads = ft.loc[common].sum(axis=1)

    df = pd.DataFrame({k: v.loc[common] for k, v in tax_levels.items()})
    df["reads"] = total_reads.values

    top_phyla = df.groupby("Phylum")["reads"].sum().nlargest(8).index.tolist()
    df.loc[~df["Phylum"].isin(top_phyla), "Phylum"] = "Other"

    cmap = plt.cm.tab20
    phylum_colors = {p: cmap(i / max(len(top_phyla), 1)) for i, p in enumerate(top_phyla)}
    phylum_colors["Other"] = (0.75, 0.75, 0.75, 1.0)

    fig, ax = plt.subplots(figsize=(14, 8))
    n_levels = len(levels)
    x_positions = np.linspace(0, 1, n_levels)
    strip_width = 0.12

    level_names = [l[0] for l in levels]
    node_data = {}
    for li, lvl in enumerate(level_names):
        groups = df.groupby(lvl)["reads"].sum().sort_values(ascending=False)
        total = groups.sum()
        y_offset = 0
        nd = {}
        for name, val in groups.items():
            h = val / total
            nd[name] = (y_offset, y_offset + h)
            y_offset += h + 0.005
        node_data[lvl] = nd

    for li, lvl in enumerate(level_names):
        x = x_positions[li]
        for name, (y0, y1) in node_data[lvl].items():
            color = phylum_colors.get(name, (0.6, 0.6, 0.6, 0.8))
            ax.barh(y=(y0 + y1) / 2, width=strip_width, height=y1 - y0,
                    left=x - strip_width / 2, color=color, edgecolor="white", lw=0.5)
            if y1 - y0 > 0.02:
                label = name if len(name) < 18 else name[:15] + "..."
                ax.text(x, (y0 + y1) / 2, label, ha="center", va="center",
                        fontsize=6, fontweight="bold", color="white")

    for li in range(n_levels - 1):
        lvl_from, lvl_to = level_names[li], level_names[li + 1]
        x0, x1 = x_positions[li] + strip_width / 2, x_positions[li + 1] - strip_width / 2
        flows = df.groupby([lvl_from, lvl_to])["reads"].sum()
        total = df["reads"].sum()

        from_offsets = {k: v[0] for k, v in node_data[lvl_from].items()}
        to_offsets = {k: v[0] for k, v in node_data[lvl_to].items()}

        for (src, dst), val in flows.items():
            h = val / total
            y0_src = from_offsets.get(src, 0)
            y0_dst = to_offsets.get(dst, 0)
            from_offsets[src] = y0_src + h
            to_offsets[dst] = y0_dst + h

            verts = [
                (x0, y0_src), (x0 + (x1 - x0) / 3, y0_src),
                (x1 - (x1 - x0) / 3, y0_dst), (x1, y0_dst),
                (x1, y0_dst + h), (x1 - (x1 - x0) / 3, y0_dst + h),
                (x0 + (x1 - x0) / 3, y0_src + h), (x0, y0_src + h),
                (x0, y0_src),
            ]
            codes = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.LINETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.CLOSEPOLY]
            color = phylum_colors.get(src, (0.6, 0.6, 0.6, 0.5))
            patch = PathPatch(MplPath(verts, codes), facecolor=(*color[:3], 0.3),
                              edgecolor="none")
            ax.add_patch(patch)

    ax.set_xlim(-0.15, 1.15)
    ax.set_ylim(-0.02, max(sum(y1 - y0 + 0.005 for y0, y1 in nd.values())
                           for nd in node_data.values()) + 0.02)
    for li, lvl in enumerate(level_names):
        ax.text(x_positions[li], -0.03, lvl, ha="center", va="top",
                fontsize=13, fontweight="bold")
    ax.set_title("Taxonomic Flow (Phylum > Class > Order)",
                 fontsize=14, fontweight="bold", pad=10)
    ax.axis("off")
    plt.tight_layout()
    return _save(fig_dir, "fig19_taxonomic_alluvial.png")


def _fig_cooccurrence_network(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig20: Co-occurrence network of top genera (Spearman)"""
    if not _HAS_NX or not _HAS_SCIPY:
        return None
    tax_g = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax_g = tax_g.replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax_g.loc[common]
    genus_counts = merged.groupby("Genus").sum()
    genus_counts = genus_counts.drop("Unknown", errors="ignore")
    top = genus_counts.sum(axis=1).nlargest(30).index
    genus_sub = genus_counts.loc[top].T

    G = nx.Graph()
    mean_abd = genus_sub.mean()
    for g in top:
        G.add_node(g, size=mean_abd[g])

    for i, g1 in enumerate(top):
        for g2 in top[i + 1:]:
            r, p = sp_stats.spearmanr(genus_sub[g1], genus_sub[g2])
            if abs(r) > 0.6 and p < 0.05:
                G.add_edge(g1, g2, weight=r)

    if G.number_of_edges() == 0:
        for i, g1 in enumerate(top):
            for g2 in top[i + 1:]:
                r, _ = sp_stats.spearmanr(genus_sub[g1], genus_sub[g2])
                if abs(r) > 0.4:
                    G.add_edge(g1, g2, weight=r)

    if G.number_of_edges() == 0:
        return None

    fig, ax = plt.subplots(figsize=(10, 10))
    pos = nx.spring_layout(G, seed=42, k=2.0)
    sizes = [max(G.nodes[n].get("size", 1), 0.1) for n in G.nodes()]
    max_s = max(sizes) if sizes else 1
    node_sizes = [s / max_s * 800 + 100 for s in sizes]

    edges = G.edges(data=True)
    edge_colors = ["#C44E52" if e[2]["weight"] < 0 else "#55A868" for e in edges]
    edge_widths = [abs(e[2]["weight"]) * 3 for e in edges]

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=edge_colors,
                           width=edge_widths, alpha=0.5)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=node_sizes,
                           node_color="#4C72B0", alpha=0.8, edgecolors="white", linewidths=0.8)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=7, font_color="#333333")
    ax.set_title("Genus Co-occurrence Network (Spearman)",
                 fontsize=14, fontweight="bold", pad=10)
    ax.axis("off")
    plt.tight_layout()
    return _save(fig_dir, "fig20_cooccurrence_network.png")


def _fig_family_composition(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig21: Family-level stacked bar chart (top 15)"""
    tax["Family"] = tax["Taxon"].str.extract(r"f__([^;]+)")[0].fillna("Unknown").str.strip()
    tax["Family"] = tax["Family"].replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Family"] = tax.loc[common, "Family"]
    family_counts = merged.groupby("Family").sum()
    family_rel = family_counts.div(family_counts.sum(axis=0), axis=1) * 100
    top = family_rel.mean(axis=1).sort_values(ascending=False).head(15).index.tolist()
    plot_df = family_rel.loc[top].copy()
    plot_df.loc["Other"] = family_rel.drop(index=top, errors="ignore").sum(axis=0)
    plot_df = plot_df.T
    colors = list(plt.cm.tab20.colors[:15]) + [(0.75, 0.75, 0.75)]
    fig, ax = plt.subplots(figsize=(12, 6))
    plot_df.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8,
                 edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Sample ID", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title("Family-Level Composition (Top 15)", fontsize=14, fontweight="bold", pad=10)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(title="Family", bbox_to_anchor=(1.01, 1), loc="upper left",
              fontsize=8, title_fontsize=9, frameon=False)
    ax.set_ylim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig21_family_composition.png")


def _fig_core_microbiome(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig22: Core microbiome (prevalence vs mean abundance)"""
    tax_g = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax_g = tax_g.replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax_g.loc[common]
    genus_counts = merged.groupby("Genus").sum()
    genus_counts = genus_counts.drop("Unknown", errors="ignore")
    genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100

    n_samples = genus_rel.shape[1]
    prevalence = (genus_rel > 0).sum(axis=1) / n_samples
    mean_abd = genus_rel.mean(axis=1)

    fig, ax = plt.subplots(figsize=(10, 7))
    is_core = prevalence >= 0.8
    ax.scatter(prevalence[~is_core], mean_abd[~is_core],
               c="#8C8C8C", s=40, alpha=0.5, edgecolors="white", lw=0.5, label="Non-core")
    ax.scatter(prevalence[is_core], mean_abd[is_core],
               c="#C44E52", s=80, alpha=0.8, edgecolors="white", lw=0.8, label="Core (prevalence >= 80%)", zorder=3)
    for g in prevalence[is_core].index:
        if mean_abd[g] > mean_abd.quantile(0.8):
            ax.annotate(g, (prevalence[g], mean_abd[g]),
                        textcoords="offset points", xytext=(5, 3), fontsize=7, color="#333333")
    ax.axvline(0.8, color="#C44E52", ls="--", lw=1, alpha=0.5)
    ax.set_xlabel("Prevalence (fraction of samples)", fontsize=12, labelpad=6)
    ax.set_ylabel("Mean Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title("Core Microbiome Analysis", fontsize=14, fontweight="bold", pad=10)
    ax.legend(frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig22_core_microbiome.png")


def _fig_volcano(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig23: Differential abundance volcano plot (Mann-Whitney U)"""
    if not _HAS_SCIPY:
        return None
    tax_g = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax_g = tax_g.replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax_g.loc[common]
    genus_counts = merged.groupby("Genus").sum()
    genus_counts = genus_counts.drop("Unknown", errors="ignore")
    genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100

    samples = genus_rel.columns.tolist()
    n = len(samples)
    if n < 4:
        return None
    mid = n // 2
    grp1 = samples[:mid]
    grp2 = samples[mid:]

    results = []
    for genus in genus_rel.index:
        v1 = genus_rel.loc[genus, grp1].values
        v2 = genus_rel.loc[genus, grp2].values
        mean1, mean2 = v1.mean(), v2.mean()
        pseudo = 0.001
        log2fc = np.log2((mean2 + pseudo) / (mean1 + pseudo))
        try:
            _, pval = sp_stats.mannwhitneyu(v1, v2, alternative="two-sided")
        except ValueError:
            pval = 1.0
        results.append((genus, log2fc, pval))

    res_df = pd.DataFrame(results, columns=["Genus", "log2FC", "pvalue"])
    # Benjamini-Hochberg FDR correction
    n_tests = len(res_df)
    ranked = res_df["pvalue"].rank()
    res_df["fdr"] = res_df["pvalue"] * n_tests / ranked
    res_df["fdr"] = res_df["fdr"].clip(upper=1.0)
    # ensure monotonicity
    res_df = res_df.sort_values("pvalue")
    res_df["fdr"] = res_df["fdr"].cummin()
    res_df = res_df.sort_index()
    res_df["neg_log10p"] = -np.log10(res_df["pvalue"].clip(lower=1e-10))

    fig, ax = plt.subplots(figsize=(10, 7))
    sig = (res_df["fdr"] < 0.05) & (res_df["log2FC"].abs() > 1)
    ax.scatter(res_df.loc[~sig, "log2FC"], res_df.loc[~sig, "neg_log10p"],
               c="#8C8C8C", s=30, alpha=0.5, edgecolors="none")
    up = sig & (res_df["log2FC"] > 0)
    down = sig & (res_df["log2FC"] < 0)
    ax.scatter(res_df.loc[up, "log2FC"], res_df.loc[up, "neg_log10p"],
               c="#C44E52", s=60, alpha=0.8, edgecolors="white", lw=0.5, label="Up")
    ax.scatter(res_df.loc[down, "log2FC"], res_df.loc[down, "neg_log10p"],
               c="#4C72B0", s=60, alpha=0.8, edgecolors="white", lw=0.5, label="Down")
    for _, row in res_df[sig].iterrows():
        ax.annotate(row["Genus"], (row["log2FC"], row["neg_log10p"]),
                    textcoords="offset points", xytext=(5, 3), fontsize=7, color="#333333")
    ax.axhline(-np.log10(0.05), color="#999999", ls="--", lw=0.8, alpha=0.5)
    ax.axvline(-1, color="#999999", ls="--", lw=0.8, alpha=0.5)
    ax.axvline(1, color="#999999", ls="--", lw=0.8, alpha=0.5)
    ax.set_xlabel("log2 Fold Change", fontsize=12, labelpad=6)
    ax.set_ylabel("-log10(p-value)", fontsize=12, labelpad=6)
    grp1_label = f"Group1 ({grp1[0]}..{grp1[-1]})"
    grp2_label = f"Group2 ({grp2[0]}..{grp2[-1]})"
    ax.set_title(f"Differential Abundance (BH-corrected): {grp1_label} vs {grp2_label}",
                 fontsize=13, fontweight="bold", pad=10)
    ax.legend(frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig23_differential_abundance.png")


def _fig_sample_dendrogram(fig_dir: Path, export_dir: Path) -> Optional[str]:
    """fig24: Sample dendrogram (Bray-Curtis UPGMA)"""
    if not _HAS_SCIPY:
        return None
    dm_path = export_dir / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    if not dm_path.exists():
        return None
    dm = pd.read_csv(dm_path, sep="\t", index_col=0)
    condensed = squareform(dm.values)
    linkage = sp_hierarchy.linkage(condensed, method="average")

    fig, ax = plt.subplots(figsize=(10, 6))
    sp_hierarchy.dendrogram(linkage, labels=dm.index.tolist(), ax=ax,
                            leaf_rotation=45, leaf_font_size=10,
                            color_threshold=0, above_threshold_color="#4C72B0")
    ax.set_ylabel("Bray-Curtis Distance", fontsize=12, labelpad=6)
    ax.set_title("Sample Dendrogram (UPGMA, Bray-Curtis)",
                 fontsize=14, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig24_sample_dendrogram.png")


def _fig_genus_correlation(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig25: Genus Spearman correlation clustermap"""
    if not _HAS_SNS or not _HAS_SCIPY:
        return None
    tax_g = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
    tax_g = tax_g.replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Genus"] = tax_g.loc[common]
    genus_counts = merged.groupby("Genus").sum()
    genus_counts = genus_counts.drop("Unknown", errors="ignore")
    top20 = genus_counts.sum(axis=1).nlargest(20).index
    genus_sub = genus_counts.loc[top20].T

    n = len(top20)
    corr_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                corr_matrix[i, j] = 1.0
            elif i < j:
                r, _ = sp_stats.spearmanr(genus_sub.iloc[:, i], genus_sub.iloc[:, j])
                corr_matrix[i, j] = r
                corr_matrix[j, i] = r

    corr_df = pd.DataFrame(corr_matrix, index=top20, columns=top20)

    g = sns.clustermap(corr_df, cmap="RdBu_r", center=0, linewidths=0.3,
                       linecolor="white", figsize=(12, 10),
                       annot=True, fmt=".2f", annot_kws={"size": 6},
                       cbar_kws={"label": "Spearman r", "shrink": 0.6},
                       dendrogram_ratio=0.12)
    g.fig.suptitle("Genus Spearman Correlation (Top 20)",
                   fontsize=14, fontweight="bold", y=1.01)
    path = fig_dir / "fig25_genus_correlation.png"
    g.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close()
    return str(path)


def _fig_class_composition(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig26: Class-level stacked bar chart (top 15)"""
    tax["Class"] = tax["Taxon"].str.extract(r"c__([^;]+)")[0].fillna("Unknown").str.strip()
    tax["Class"] = tax["Class"].replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Class"] = tax.loc[common, "Class"]
    class_counts = merged.groupby("Class").sum()
    class_rel = class_counts.div(class_counts.sum(axis=0), axis=1) * 100
    top = class_rel.mean(axis=1).sort_values(ascending=False).head(15).index.tolist()
    plot_df = class_rel.loc[top].copy()
    plot_df.loc["Other"] = class_rel.drop(index=top, errors="ignore").sum(axis=0)
    plot_df = plot_df.T
    colors = list(plt.cm.tab20.colors[:15]) + [(0.75, 0.75, 0.75)]
    fig, ax = plt.subplots(figsize=(12, 6))
    plot_df.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8,
                 edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Sample ID", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title("Class-Level Composition (Top 15)", fontsize=14, fontweight="bold", pad=10)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(title="Class", bbox_to_anchor=(1.01, 1), loc="upper left",
              fontsize=8, title_fontsize=9, frameon=False)
    ax.set_ylim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig26_class_composition.png")


def _fig_order_composition(fig_dir: Path, ft: pd.DataFrame, tax: pd.DataFrame) -> Optional[str]:
    """fig27: Order-level stacked bar chart (top 15)"""
    tax["Order"] = tax["Taxon"].str.extract(r"o__([^;]+)")[0].fillna("Unknown").str.strip()
    tax["Order"] = tax["Order"].replace("", "Unknown")
    common = ft.index.intersection(tax.index)
    merged = ft.loc[common].copy()
    merged["Order"] = tax.loc[common, "Order"]
    order_counts = merged.groupby("Order").sum()
    order_rel = order_counts.div(order_counts.sum(axis=0), axis=1) * 100
    top = order_rel.mean(axis=1).sort_values(ascending=False).head(15).index.tolist()
    plot_df = order_rel.loc[top].copy()
    plot_df.loc["Other"] = order_rel.drop(index=top, errors="ignore").sum(axis=0)
    plot_df = plot_df.T
    colors = list(plt.cm.tab20.colors[:15]) + [(0.75, 0.75, 0.75)]
    fig, ax = plt.subplots(figsize=(12, 6))
    plot_df.plot(kind="bar", stacked=True, ax=ax, color=colors, width=0.8,
                 edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Sample ID", fontsize=12, labelpad=6)
    ax.set_ylabel("Relative Abundance (%)", fontsize=12, labelpad=6)
    ax.set_title("Order-Level Composition (Top 15)", fontsize=14, fontweight="bold", pad=10)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(title="Order", bbox_to_anchor=(1.01, 1), loc="upper left",
              fontsize=8, title_fontsize=9, frameon=False)
    ax.set_ylim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig27_order_composition.png")


def _fig_simpson_pielou(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig28: Simpson diversity + Pielou evenness (computed from feature table)"""
    ft_rel = ft.div(ft.sum(axis=0), axis=1)
    simpson = 1 - (ft_rel ** 2).sum(axis=0)
    richness = (ft > 0).sum(axis=0)
    shannon = -(ft_rel * np.log(ft_rel + 1e-10)).sum(axis=0)
    pielou = shannon / np.log(richness.clip(lower=2))

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    colors_s = [PALETTE[i % len(PALETTE)] for i in range(len(simpson))]

    ax = axes[0]
    ax.bar(range(len(simpson)), simpson.values, color=colors_s, edgecolor="white", alpha=0.85)
    ax.set_xticks(range(len(simpson)))
    ax.set_xticklabels(simpson.index, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Simpson Diversity (1 - D)", fontsize=11, labelpad=6)
    ax.set_title("Simpson Diversity Index", fontsize=13, fontweight="bold", pad=8)
    ax.axhline(simpson.mean(), color="#C44E52", lw=1.5, ls="--", alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax = axes[1]
    ax.bar(range(len(pielou)), pielou.values, color=colors_s, edgecolor="white", alpha=0.85)
    ax.set_xticks(range(len(pielou)))
    ax.set_xticklabels(pielou.index, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Pielou's Evenness (J')", fontsize=11, labelpad=6)
    ax.set_title("Pielou's Evenness Index", fontsize=13, fontweight="bold", pad=8)
    ax.axhline(pielou.mean(), color="#C44E52", lw=1.5, ls="--", alpha=0.7)
    ax.set_ylim(0, 1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle("Diversity & Evenness Metrics", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    return _save(fig_dir, "fig28_simpson_pielou.png")


def _fig_asv_overlap(fig_dir: Path, ft: pd.DataFrame) -> Optional[str]:
    """fig29: ASV overlap UpSet-style horizontal bar chart"""
    presence = (ft > 0).astype(int)
    n_samples = presence.shape[1]
    samples = presence.columns.tolist()

    # compute intersection sizes for all non-empty subsets (top combinations)
    from itertools import combinations
    combo_sizes = {}
    for size in range(1, min(n_samples, 4) + 1):
        for combo in combinations(range(n_samples), size):
            mask = presence.iloc[:, list(combo)].all(axis=1)
            # exclusive to this combination
            others = [j for j in range(n_samples) if j not in combo]
            if others:
                mask = mask & ~presence.iloc[:, others].any(axis=1)
            count = mask.sum()
            if count > 0:
                combo_sizes[combo] = count

    # also add: shared by ALL samples, shared by >= 80%
    shared_all = presence.all(axis=1).sum()
    shared_80 = (presence.sum(axis=1) >= n_samples * 0.8).sum()

    # top 15 intersections by size
    sorted_combos = sorted(combo_sizes.items(), key=lambda x: -x[1])[:15]

    if not sorted_combos:
        return None

    fig, ax = plt.subplots(figsize=(10, 8))
    labels = []
    sizes = []
    for combo, size in reversed(sorted_combos):
        label = " & ".join(samples[j] for j in combo)
        if len(label) > 30:
            label = f"{len(combo)} samples"
        labels.append(label)
        sizes.append(size)

    colors_bar = [PALETTE[i % len(PALETTE)] for i in range(len(sizes))]
    ax.barh(range(len(sizes)), sizes, color=colors_bar, edgecolor="white", alpha=0.85)
    ax.set_yticks(range(len(sizes)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Number of ASVs", fontsize=12, labelpad=6)
    ax.set_title(f"ASV Sharing Patterns (shared by all: {shared_all}, by >=80%: {shared_80})",
                 fontsize=13, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _save(fig_dir, "fig29_asv_overlap.png")


# ══════════════════════════════════════════════════════════════════════
# 解析サマリー生成
# ══════════════════════════════════════════════════════════════════════

def generate_analysis_summary(
    export_dir: str,
    ft: Optional[pd.DataFrame],
    tax: Optional[pd.DataFrame],
    alpha: Optional[pd.DataFrame],
) -> dict:
    """基本解析結果の構造化サマリーを生成（LLM エージェントへの入力用）"""
    summary: dict = {}

    if ft is not None:
        summary["n_samples"] = ft.shape[1]
        summary["n_asvs"] = ft.shape[0]
        summary["sample_ids"] = ft.columns.tolist()
        depths = ft.sum(axis=0)
        summary["sequencing_depth"] = {
            "min": int(depths.min()), "max": int(depths.max()),
            "mean": int(depths.mean()),
        }
    else:
        return summary

    if tax is not None and "Taxon" in tax.columns:
        common = ft.index.intersection(tax.index)
        ft_c = ft.loc[common]
        # Phylum
        phyla = tax["Taxon"].str.extract(r"p__([^;]+)")[0].fillna("Unknown").str.strip()
        phyla = phyla.replace("", "Unknown")
        merged_p = ft_c.copy()
        merged_p["Phylum"] = phyla.loc[common]
        phylum_rel = merged_p.groupby("Phylum").sum().div(
            merged_p.groupby("Phylum").sum().sum(axis=0), axis=1) * 100
        top_phyla = phylum_rel.mean(axis=1).sort_values(ascending=False).head(5)
        summary["top_phyla"] = [(n, round(v, 1)) for n, v in top_phyla.items()]

        # Genus
        genera = tax["Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
        genera = genera.replace("", "Unknown")
        merged_g = ft_c.copy()
        merged_g["Genus"] = genera.loc[common]
        genus_counts = merged_g.groupby("Genus").sum()
        genus_counts = genus_counts.drop("Unknown", errors="ignore")
        genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100

        top_genera = genus_rel.mean(axis=1).sort_values(ascending=False).head(10)
        summary["top_genera"] = [(n, round(v, 1)) for n, v in top_genera.items()]

        # core genera
        n_s = genus_rel.shape[1]
        prevalence = (genus_rel > 0).sum(axis=1) / n_s
        summary["core_genera"] = prevalence[prevalence >= 0.8].index.tolist()

        # dominant genus per sample
        dom = {}
        for sid in genus_rel.columns:
            dom[sid] = genus_rel[sid].idxmax()
        summary["dominant_genus_per_sample"] = dom

        # high variance genera
        cv = genus_rel.std(axis=1) / (genus_rel.mean(axis=1) + 0.001)
        top_cv = cv[cv > 1.0].sort_values(ascending=False).head(5)
        summary["high_variance_genera"] = [(n, round(v, 2)) for n, v in top_cv.items()]

    if alpha is not None:
        alpha_summary = {}
        for col in alpha.columns:
            vals = alpha[col].dropna()
            if len(vals) > 0:
                alpha_summary[col] = {
                    "mean": round(float(vals.mean()), 3),
                    "std": round(float(vals.std()), 3),
                    "min_sample": str(vals.idxmin()),
                    "max_sample": str(vals.idxmax()),
                }
        summary["alpha_summary"] = alpha_summary

    # outlier detection via beta diversity
    export = Path(export_dir)
    dm_path = export / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    if dm_path.exists():
        dm = pd.read_csv(dm_path, sep="\t", index_col=0)
        centroid_dist = dm.mean(axis=1)
        mean_d = centroid_dist.mean()
        std_d = centroid_dist.std()
        outliers = centroid_dist[centroid_dist > mean_d + 2 * std_d].index.tolist()
        summary["outlier_samples"] = outliers

    # interesting patterns (auto-detected)
    patterns = []
    if alpha is not None and "Shannon" in alpha.columns:
        s = alpha["Shannon"].dropna()
        if len(s) > 0:
            low_sample = s.idxmin()
            if s[low_sample] < s.mean() - 1.5 * s.std():
                patterns.append(
                    f"Sample {low_sample} has unusually low Shannon diversity "
                    f"({s[low_sample]:.2f}, mean={s.mean():.2f})")

    if "high_variance_genera" in summary and summary["high_variance_genera"]:
        for g, cv_val in summary["high_variance_genera"][:3]:
            patterns.append(f"Genus {g} shows high inter-sample variance (CV={cv_val})")

    if "top_phyla" in summary:
        top_p = summary["top_phyla"][0]
        if top_p[1] > 40:
            patterns.append(f"{top_p[0]} dominates across samples ({top_p[1]}% mean relative abundance)")

    if "outlier_samples" in summary and summary["outlier_samples"]:
        for s in summary["outlier_samples"]:
            patterns.append(f"Sample {s} is an outlier in Bray-Curtis beta diversity")

    summary["interesting_patterns"] = patterns
    return summary


# ══════════════════════════════════════════════════════════════════════
# メインエントリポイント
# ══════════════════════════════════════════════════════════════════════

def run_comprehensive_analysis(
    export_dir: str,
    figure_dir: str,
    session_dir: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
) -> tuple:
    """
    QIIME2 エクスポートデータから包括的な解析図を生成する。

    Parameters
    ----------
    export_dir : str
        QIIME2 エクスポートディレクトリ (exported/)
    figure_dir : str
        図の保存先ディレクトリ
    session_dir : str, optional
        セッションディレクトリ（denoising-stats.qza 等の検索用）
    log_callback : callable, optional
        ログ出力コールバック

    Returns
    -------
    tuple[list[str], dict]
        (生成された図ファイルのパス一覧, 解析サマリー辞書)
    """
    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg, flush=True)

    export = Path(export_dir)
    fig_dir = Path(figure_dir)
    sess_dir = Path(session_dir) if session_dir else export.parent
    fig_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []

    # ── Feature table 読み込み ─────────────────────────────────────────
    ft_path = export / "feature-table.tsv"
    ft = None
    if ft_path.exists():
        try:
            ft = pd.read_csv(ft_path, sep="\t", index_col=0, skiprows=1)
        except Exception as e:
            _log(f"  ⚠️  feature-table 読み込み失敗: {e}")

    # ── Alpha diversity 読み込み ───────────────────────────────────────
    alpha_data = {}
    alpha_dir = export / "alpha"
    _metric_map = {
        "shannon_vector": "Shannon",
        "faith_pd_vector": "Faith PD",
        "observed_features_vector": "Observed ASVs",
    }
    if alpha_dir.exists():
        for metric_dir in sorted(alpha_dir.iterdir()):
            tsvs = list(metric_dir.glob("*.tsv"))
            if tsvs:
                try:
                    df = pd.read_csv(tsvs[0], sep="\t", index_col=0)
                    if len(df.columns) >= 1:
                        col_name = _metric_map.get(metric_dir.name, metric_dir.name)
                        alpha_data[col_name] = df.iloc[:, 0]
                except Exception:
                    pass
    alpha = pd.DataFrame(alpha_data) if alpha_data else None

    # ── Taxonomy 読み込み ──────────────────────────────────────────────
    tax_path = export / "taxonomy" / "taxonomy.tsv"
    tax = None
    if tax_path.exists():
        try:
            tax = pd.read_csv(tax_path, sep="\t", index_col=0)
        except Exception:
            pass

    # ── 図の生成 ──────────────────────────────────────────────────────
    _log("📊 包括的解析: 図を生成中...")

    # fig01: DADA2 stats
    try:
        r = _fig_dada2_stats(fig_dir, export, sess_dir)
        if r:
            saved.append(r)
            _log(f"  ✅ {Path(r).name}")
    except Exception as e:
        _log(f"  ⚠️  fig01 (DADA2 stats): {e}")

    # fig02: Sequencing depth
    if ft is not None:
        try:
            r = _fig_sequencing_depth(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig02 (sequencing depth): {e}")

    # fig03: Alpha diversity boxplots
    if alpha is not None:
        try:
            r = _fig_alpha_diversity(fig_dir, alpha)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig03 (alpha diversity): {e}")

    # fig04: Shannon per sample
    if alpha is not None:
        try:
            r = _fig_shannon_per_sample(fig_dir, alpha)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig04 (Shannon per sample): {e}")

    # fig05-08: PCoA
    try:
        pcoa_figs = _fig_pcoa(fig_dir, export)
        saved.extend(pcoa_figs)
        for f in pcoa_figs:
            _log(f"  ✅ {Path(f).name}")
    except Exception as e:
        _log(f"  ⚠️  fig05-08 (PCoA): {e}")

    # fig09: Beta heatmaps
    try:
        r = _fig_beta_heatmaps(fig_dir, export)
        if r:
            saved.append(r)
            _log(f"  ✅ {Path(r).name}")
    except Exception as e:
        _log(f"  ⚠️  fig09 (beta heatmaps): {e}")

    # fig10: Top ASV heatmap
    if ft is not None:
        try:
            r = _fig_top_asv_heatmap(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig10 (ASV heatmap): {e}")

    # fig11: Alpha correlations
    if alpha is not None:
        try:
            r = _fig_alpha_correlations(fig_dir, alpha)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig11 (alpha correlations): {e}")

    # fig12: Richness vs depth
    if ft is not None:
        try:
            r = _fig_richness_vs_depth(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig12 (richness vs depth): {e}")

    # fig13-15: Taxonomy (genus/phylum) — only if taxonomy available
    if ft is not None and tax is not None:
        _log("  🔬 Taxonomy 図を生成中...")
        try:
            r = _fig_genus_composition(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig13 (genus composition): {e}")

        try:
            r = _fig_phylum_composition(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig14 (phylum composition): {e}")

        try:
            r = _fig_genus_heatmap(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig15 (genus heatmap): {e}")
    elif tax is None:
        _log("  ℹ️  Taxonomy データなし — fig13-15 をスキップ")

    # ── 拡張解析 (fig16-fig25) ─────────────────────────────────────────
    _log("  🔬 拡張解析図を生成中...")

    # fig16: Rarefaction curves
    if ft is not None:
        try:
            r = _fig_rarefaction(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig16 (rarefaction): {e}")

    # fig17: NMDS
    try:
        r = _fig_nmds(fig_dir, export)
        if r:
            saved.append(r)
            _log(f"  ✅ {Path(r).name}")
    except Exception as e:
        _log(f"  ⚠️  fig17 (NMDS): {e}")

    # fig18: Rank abundance
    if ft is not None:
        try:
            r = _fig_rank_abundance(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig18 (rank abundance): {e}")

    # fig19: Taxonomic alluvial
    if ft is not None and tax is not None:
        try:
            r = _fig_taxonomic_alluvial(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig19 (alluvial): {e}")

    # fig20: Co-occurrence network
    if ft is not None and tax is not None:
        try:
            r = _fig_cooccurrence_network(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig20 (co-occurrence): {e}")

    # fig21: Family composition
    if ft is not None and tax is not None:
        try:
            r = _fig_family_composition(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig21 (family composition): {e}")

    # fig22: Core microbiome
    if ft is not None and tax is not None:
        try:
            r = _fig_core_microbiome(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig22 (core microbiome): {e}")

    # fig23: Volcano plot
    if ft is not None and tax is not None:
        try:
            r = _fig_volcano(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig23 (volcano): {e}")

    # fig24: Sample dendrogram
    try:
        r = _fig_sample_dendrogram(fig_dir, export)
        if r:
            saved.append(r)
            _log(f"  ✅ {Path(r).name}")
    except Exception as e:
        _log(f"  ⚠️  fig24 (dendrogram): {e}")

    # fig25: Genus correlation clustermap
    if ft is not None and tax is not None:
        try:
            r = _fig_genus_correlation(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig25 (genus correlation): {e}")

    # fig26: Class composition
    if ft is not None and tax is not None:
        try:
            r = _fig_class_composition(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig26 (class composition): {e}")

    # fig27: Order composition
    if ft is not None and tax is not None:
        try:
            r = _fig_order_composition(fig_dir, ft, tax.copy())
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig27 (order composition): {e}")

    # fig28: Simpson + Pielou
    if ft is not None:
        try:
            r = _fig_simpson_pielou(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig28 (Simpson/Pielou): {e}")

    # fig29: ASV overlap
    if ft is not None:
        try:
            r = _fig_asv_overlap(fig_dir, ft)
            if r:
                saved.append(r)
                _log(f"  ✅ {Path(r).name}")
        except Exception as e:
            _log(f"  ⚠️  fig29 (ASV overlap): {e}")

    _log(f"📊 包括的解析完了: {len(saved)} 件の図を生成")

    # ── 解析サマリー生成（LLM エージェントへの入力用）────────────────────
    summary = {}
    try:
        summary = generate_analysis_summary(str(export), ft, tax, alpha)
        _log(f"📋 解析サマリー: {len(summary.get('interesting_patterns', []))} 個のパターンを検出")
    except Exception as e:
        _log(f"  ⚠️  解析サマリー生成失敗: {e}")

    return saved, summary
