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
            fig, ax = plt.subplots(figsize=(7, 6))
            ax.scatter(coords[:, 0], coords[:, 1],
                       c=[color] * n, s=100, edgecolors="white", lw=0.8, zorder=3, alpha=0.9)
            for j, sid in enumerate(dm.index):
                ax.annotate(sid, (coords[j, 0], coords[j, 1]),
                            textcoords="offset points", xytext=(6, 4), fontsize=8, color="#444444")
            ax.set_title(f"{label} PCoA", fontsize=14, fontweight="bold", pad=10)
            ax.set_xlabel("PC 1", fontsize=12, labelpad=6)
            ax.set_ylabel("PC 2", fontsize=12, labelpad=6)
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
# メインエントリポイント
# ══════════════════════════════════════════════════════════════════════

def run_comprehensive_analysis(
    export_dir: str,
    figure_dir: str,
    session_dir: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
) -> list:
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
    list[str]
        生成された図ファイルのパス一覧
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

    _log(f"📊 包括的解析完了: {len(saved)} 件の図を生成")
    return saved
