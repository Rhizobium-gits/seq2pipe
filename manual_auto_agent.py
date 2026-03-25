#!/usr/bin/env python3
"""
manual_auto_agent.py
====================
研究目的駆動の自律解析モード（manual-auto）。

ユーザーが研究の問い・仮説とメタデータを指定すると、
実験デザインを解析し、研究目的に最適化された包括的な解析プランを
自動作成・実行する。

使い方:
    python cli.py --manual-auto --fastq-dir ~/data \\
        --metadata metadata.tsv \\
        --research-question "抗生物質投与群とコントロール群の腸内細菌叢の違い"
"""

from __future__ import annotations

import re
import csv
import glob
import datetime
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

import sys
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import (
    run_code_agent, CodeExecutionResult, _run_code, _extract_code,
    _detect_missing_module, pip_install,
)


# ─────────────────────────────────────────────────────────────────────────────
# 実験デザイン解析
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Comparison:
    """1つの比較（どのサンプルとどのサンプルを比べるか）"""
    name: str                          # e.g. "antibiotic vs control at day7"
    type: str                          # "between_group" | "within_time" | "interaction" | "pairwise"
    factor: str                        # 比較する因子 (e.g. "treatment")
    group_a: str = ""
    group_b: str = ""
    filter_conditions: dict = field(default_factory=dict)  # e.g. {"timepoint": "day7"}
    sample_ids_a: list[str] = field(default_factory=list)
    sample_ids_b: list[str] = field(default_factory=list)
    n_a: int = 0
    n_b: int = 0
    statistical_test: str = ""
    rationale: str = ""

    def summary_line(self) -> str:
        filt = ""
        if self.filter_conditions:
            filt = " | " + ", ".join(f"{k}={v}" for k, v in self.filter_conditions.items())
        return f"[{self.type}] {self.name} (n={self.n_a} vs {self.n_b}){filt}"


@dataclass
class ExperimentalDesign:
    """メタデータから決定論的に抽出した実験デザイン情報"""
    sample_ids: list[str] = field(default_factory=list)
    n_samples: int = 0
    columns: list[str] = field(default_factory=list)
    group_columns: list[str] = field(default_factory=list)
    continuous_columns: list[str] = field(default_factory=list)
    timepoint_column: Optional[str] = None
    subject_column: Optional[str] = None
    primary_group: str = ""
    group_values: dict[str, list[str]] = field(default_factory=dict)
    group_sizes: dict[str, int] = field(default_factory=dict)
    is_paired: bool = False
    is_longitudinal: bool = False
    n_groups: int = 0
    has_unbalanced_design: bool = False

    # 多因子デザイン
    factors: list[str] = field(default_factory=list)           # 全因子列 (group_columns + primary)
    factor_levels: dict[str, list[str]] = field(default_factory=dict)  # 因子 → 水準一覧
    cross_table: dict[str, int] = field(default_factory=dict)  # "treatment=abx|timepoint=day7" → n
    comparisons: list[Comparison] = field(default_factory=list) # 自動生成された比較プラン
    timepoints_sorted: list[str] = field(default_factory=list)  # 時間順にソート済み
    baseline_timepoint: Optional[str] = None                    # 最初のタイムポイント

    def summary(self) -> str:
        lines = [
            f"Samples: {self.n_samples}",
            f"Columns: {', '.join(self.columns)}",
        ]
        if self.primary_group:
            sizes = ", ".join(f"{k}={v}" for k, v in self.group_sizes.items())
            lines.append(f"Primary grouping: '{self.primary_group}' ({self.n_groups} groups: {sizes})")
        if self.is_longitudinal:
            lines.append(f"Longitudinal: timepoint column = '{self.timepoint_column}'")
            if self.timepoints_sorted:
                lines.append(f"  Timepoints (sorted): {' → '.join(self.timepoints_sorted)}")
            if self.baseline_timepoint:
                lines.append(f"  Baseline: {self.baseline_timepoint}")
        if self.is_paired:
            lines.append(f"Paired design: subject column = '{self.subject_column}'")
        if self.group_columns:
            lines.append(f"Other categorical columns: {', '.join(self.group_columns)}")
        if self.continuous_columns:
            lines.append(f"Continuous columns: {', '.join(self.continuous_columns)}")
        if self.has_unbalanced_design:
            lines.append("Unbalanced design detected")

        # 多因子クロステーブル
        if self.cross_table and len(self.factors) >= 2:
            lines.append(f"\nCross-design ({' × '.join(self.factors)}):")
            for combo, n in sorted(self.cross_table.items()):
                lines.append(f"  {combo}: n={n}")

        # 比較プラン
        if self.comparisons:
            lines.append(f"\nAuto-generated comparisons ({len(self.comparisons)}):")
            for c in self.comparisons:
                lines.append(f"  {c.summary_line()}")

        return "\n".join(lines)


_TIMEPOINT_PATTERNS = re.compile(
    r"(timepoint|time_point|time|day|week|month|visit|stage|period|dpi|hpi)",
    re.IGNORECASE,
)
_SUBJECT_PATTERNS = re.compile(
    r"(subject|patient|donor|individual|mouse|animal|rat|pig|cow|host|participant|person|id_subject)",
    re.IGNORECASE,
)
_GROUP_PRIORITY = [
    "treatment", "group", "condition", "genotype", "diet", "gravity",
    "status", "phenotype", "disease", "sex", "gender", "tissue",
    "sample_type", "sample-type", "body_site", "body-site", "site",
    "location", "habitat", "environment", "source",
]


def parse_metadata(metadata_path: str) -> ExperimentalDesign:
    """メタデータ TSV を解析して ExperimentalDesign を返す。"""
    path = Path(metadata_path)
    if not path.exists():
        return ExperimentalDesign()

    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        # #q2:types 行をスキップ
        for row in reader:
            if row and row[0].startswith("#q2:"):
                continue
            if row:
                rows.append(dict(zip(header, row)))

    if not rows:
        return ExperimentalDesign()

    id_col = header[0]
    sample_ids = [r.get(id_col, "") for r in rows if r.get(id_col)]
    non_id_cols = [c for c in header if c != id_col]

    # カラムの分類
    group_cols: list[str] = []
    continuous_cols: list[str] = []
    timepoint_col: Optional[str] = None
    subject_col: Optional[str] = None

    for col in non_id_cols:
        vals = [r.get(col, "") for r in rows if r.get(col, "") not in ("", "NA", "nan", "NaN")]
        if not vals:
            continue

        # 数値判定
        try:
            _ = [float(v) for v in vals]
            is_numeric = True
        except (ValueError, TypeError):
            is_numeric = False

        n_unique = len(set(vals))

        # タイムポイント検出（最初のマッチのみ）
        if not timepoint_col and _TIMEPOINT_PATTERNS.search(col):
            timepoint_col = col
            continue

        # 被験者列検出（最初のマッチのみ）
        if not subject_col and _SUBJECT_PATTERNS.search(col):
            subject_col = col
            continue

        # カテゴリ列 vs 連続列
        if is_numeric and n_unique > 10:
            continuous_cols.append(col)
        elif n_unique <= 20:
            group_cols.append(col)
        elif not is_numeric:
            group_cols.append(col)
        else:
            continuous_cols.append(col)

    # プライマリグループの選択
    primary_group = ""
    for prio in _GROUP_PRIORITY:
        for col in group_cols:
            if prio in col.lower():
                primary_group = col
                break
        if primary_group:
            break
    if not primary_group and group_cols:
        primary_group = group_cols[0]

    # グループサイズ計算
    group_values: dict[str, list[str]] = {}
    group_sizes: dict[str, int] = {}
    if primary_group:
        vals = [r.get(primary_group, "") for r in rows if r.get(primary_group)]
        unique_vals = sorted(set(vals))
        group_values[primary_group] = unique_vals
        group_sizes = {v: vals.count(v) for v in unique_vals}

    # ペアデザイン判定
    is_paired = False
    if subject_col and primary_group:
        subjects = [r.get(subject_col, "") for r in rows if r.get(subject_col)]
        is_paired = len(set(subjects)) < len(sample_ids)

    n_groups = len(group_sizes)
    max_size = max(group_sizes.values()) if group_sizes else 0
    min_size = min(group_sizes.values()) if group_sizes else 0
    unbalanced = (max_size / min_size > 2.0) if min_size > 0 else False

    # 他のグループ列についても値を記録
    for col in group_cols:
        if col != primary_group:
            vals = [r.get(col, "") for r in rows if r.get(col)]
            group_values[col] = sorted(set(vals))

    # ── 多因子デザイン解析 ─────────────────────────────────────────
    # 全因子（primary + 他のカテゴリ列 + timepoint）
    factors: list[str] = []
    factor_levels: dict[str, list[str]] = {}

    if primary_group:
        factors.append(primary_group)
        factor_levels[primary_group] = sorted(set(
            r.get(primary_group, "") for r in rows if r.get(primary_group)
        ))
    if timepoint_col:
        factors.append(timepoint_col)
        tp_vals = [r.get(timepoint_col, "") for r in rows if r.get(timepoint_col)]
        # 数値ソートを試みる（day0, day7 → 0, 7）
        try:
            tp_nums = [(float(re.sub(r"[^\d.]", "", v) or "0"), v) for v in set(tp_vals)]
            factor_levels[timepoint_col] = [v for _, v in sorted(tp_nums)]
        except (ValueError, TypeError):
            factor_levels[timepoint_col] = sorted(set(tp_vals))
    for col in group_cols:
        if col != primary_group:
            factors.append(col)
            factor_levels[col] = sorted(set(
                r.get(col, "") for r in rows if r.get(col)
            ))

    # クロステーブル（因子の組み合わせごとのサンプル数）
    cross_table: dict[str, int] = {}
    cross_factors = [f for f in [primary_group, timepoint_col] if f]
    if len(cross_factors) >= 2:
        for r in rows:
            combo_parts = []
            for f in cross_factors:
                v = r.get(f, "")
                if v:
                    combo_parts.append(f"{f}={v}")
            if len(combo_parts) == len(cross_factors):
                key = " | ".join(combo_parts)
                cross_table[key] = cross_table.get(key, 0) + 1

    # タイムポイントのソートとベースライン検出
    timepoints_sorted: list[str] = factor_levels.get(timepoint_col, []) if timepoint_col else []
    baseline_tp: Optional[str] = timepoints_sorted[0] if timepoints_sorted else None

    # ── 比較プラン自動生成 ────────────────────────────────────────
    comparisons: list[Comparison] = []

    # サンプルをグループ化する関数
    def _get_samples(conditions: dict[str, str]) -> list[str]:
        result = []
        for r in rows:
            match = all(r.get(k) == v for k, v in conditions.items())
            if match:
                result.append(r.get(id_col, ""))
        return [s for s in result if s]

    primary_levels = factor_levels.get(primary_group, []) if primary_group else []

    # (A) 全体の群間比較（primary group のペアワイズ）
    if len(primary_levels) >= 2:
        from itertools import combinations as _comb
        for ga, gb in _comb(primary_levels, 2):
            sids_a = _get_samples({primary_group: ga})
            sids_b = _get_samples({primary_group: gb})
            comparisons.append(Comparison(
                name=f"{ga} vs {gb} (overall)",
                type="between_group",
                factor=primary_group,
                group_a=ga, group_b=gb,
                sample_ids_a=sids_a, sample_ids_b=sids_b,
                n_a=len(sids_a), n_b=len(sids_b),
                rationale=f"Overall comparison between {primary_group} levels.",
            ))

    # (B) タイムポイント内の群間比較（同一時点で群を比較）
    if timepoint_col and primary_group and len(primary_levels) >= 2 and len(timepoints_sorted) >= 2:
        for tp in timepoints_sorted:
            for ga, gb in _comb(primary_levels, 2):
                sids_a = _get_samples({primary_group: ga, timepoint_col: tp})
                sids_b = _get_samples({primary_group: gb, timepoint_col: tp})
                if sids_a and sids_b:
                    comparisons.append(Comparison(
                        name=f"{ga} vs {gb} at {timepoint_col}={tp}",
                        type="between_group",
                        factor=primary_group,
                        group_a=ga, group_b=gb,
                        filter_conditions={timepoint_col: tp},
                        sample_ids_a=sids_a, sample_ids_b=sids_b,
                        n_a=len(sids_a), n_b=len(sids_b),
                        rationale=f"Group comparison within timepoint {tp}.",
                    ))

    # (C) 群内の時系列比較（同一群で時間変化を追跡）
    if timepoint_col and primary_group and len(timepoints_sorted) >= 2:
        for grp in primary_levels:
            # ベースライン vs 各後続タイムポイント
            if baseline_tp:
                for tp in timepoints_sorted[1:]:
                    sids_base = _get_samples({primary_group: grp, timepoint_col: baseline_tp})
                    sids_post = _get_samples({primary_group: grp, timepoint_col: tp})
                    if sids_base and sids_post:
                        comparisons.append(Comparison(
                            name=f"{grp}: {baseline_tp} → {tp}",
                            type="within_time",
                            factor=timepoint_col,
                            group_a=baseline_tp, group_b=tp,
                            filter_conditions={primary_group: grp},
                            sample_ids_a=sids_base, sample_ids_b=sids_post,
                            n_a=len(sids_base), n_b=len(sids_post),
                            rationale=f"Temporal change in {grp} group from baseline ({baseline_tp}) to {tp}.",
                        ))

    # (D) 交互作用検出候補（treatment効果がtimepointで異なるか）
    if timepoint_col and primary_group and len(primary_levels) >= 2 and len(timepoints_sorted) >= 2:
        comparisons.append(Comparison(
            name=f"{primary_group} × {timepoint_col} interaction",
            type="interaction",
            factor=f"{primary_group} × {timepoint_col}",
            rationale=(
                f"Test whether the effect of {primary_group} differs across {timepoint_col}. "
                "Requires two-way PERMANOVA or interaction plot."
            ),
        ))

    # (E) 他のカテゴリ列との比較（secondary factors）
    for sec_col in group_cols:
        if sec_col == primary_group:
            continue
        sec_levels = factor_levels.get(sec_col, [])
        if 2 <= len(sec_levels) <= 5:
            for ga, gb in _comb(sec_levels, 2):
                sids_a = _get_samples({sec_col: ga})
                sids_b = _get_samples({sec_col: gb})
                if sids_a and sids_b:
                    comparisons.append(Comparison(
                        name=f"{ga} vs {gb} (by {sec_col})",
                        type="between_group",
                        factor=sec_col,
                        group_a=ga, group_b=gb,
                        sample_ids_a=sids_a, sample_ids_b=sids_b,
                        n_a=len(sids_a), n_b=len(sids_b),
                        rationale=f"Secondary factor comparison on {sec_col}.",
                    ))

    design = ExperimentalDesign(
        sample_ids=sample_ids,
        n_samples=len(sample_ids),
        columns=non_id_cols,
        group_columns=[c for c in group_cols if c != primary_group],
        continuous_columns=continuous_cols,
        timepoint_column=timepoint_col,
        subject_column=subject_col,
        primary_group=primary_group,
        group_values=group_values,
        group_sizes=group_sizes,
        is_paired=is_paired,
        is_longitudinal=timepoint_col is not None,
        n_groups=n_groups,
        has_unbalanced_design=unbalanced,
        factors=factors,
        factor_levels=factor_levels,
        cross_table=cross_table,
        comparisons=comparisons,
        timepoints_sorted=timepoints_sorted,
        baseline_timepoint=baseline_tp,
    )
    return design


# ─────────────────────────────────────────────────────────────────────────────
# 解析レジストリ — 全可視化・統計手法
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisSpec:
    """解析仕様"""
    key: str
    phase: str                    # quality / composition / alpha / beta / differential / advanced / publication
    title: str                    # 人間可読タイトル
    description: str              # LLM に渡す解析説明
    requires: list[str]           # 必要データカテゴリ: feature_table, taxonomy, alpha, beta, denoising, metadata
    min_groups: int = 0           # 最小グループ数 (0=制約なし)
    max_groups: int = 999         # 最大グループ数
    needs_timepoint: bool = False # 縦断データが必要
    needs_paired: bool = False    # ペアデザインが必要
    extra_packages: list[str] = field(default_factory=list)  # 追加 pip パッケージ


# フェーズ順に定義
ANALYSIS_REGISTRY: list[AnalysisSpec] = [
    # ── Phase 1: Data Quality ──────────────────────────────────────────
    AnalysisSpec(
        key="dada2_stats",
        phase="quality",
        title="DADA2 Denoising Statistics",
        description=(
            "Stacked/grouped bar chart showing: input → filtered → denoised → merged → non-chimeric reads per sample. "
            "Add percentage labels. Sort samples by group if metadata available."
        ),
        requires=["denoising"],
    ),
    AnalysisSpec(
        key="read_depth",
        phase="quality",
        title="Sequencing Depth per Sample",
        description=(
            "Bar chart of total reads per sample from feature table, colored by group. "
            "Add horizontal line at median. Flag samples below 1000 reads."
        ),
        requires=["feature_table"],
    ),
    AnalysisSpec(
        key="asv_frequency",
        phase="quality",
        title="ASV Frequency Distribution",
        description=(
            "Histogram of ASV total counts (log10 scale). "
            "Annotate: total ASVs, singletons, doubletons."
        ),
        requires=["feature_table"],
    ),

    # ── Phase 2: Taxonomic Composition ─────────────────────────────────
    AnalysisSpec(
        key="phylum_barplot",
        phase="composition",
        title="Phylum-Level Composition (Stacked Bar)",
        description=(
            "Stacked bar chart of relative abundance at phylum level. "
            "Top 10 phyla + 'Other'. Samples sorted by {primary_group}. "
            "Use tab20 palette. Add group separator lines if grouped."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="genus_barplot",
        phase="composition",
        title="Genus-Level Composition (Stacked Bar)",
        description=(
            "Stacked bar chart of relative abundance at genus level. "
            "Top 15 genera + 'Other'. Samples sorted by {primary_group}."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="family_barplot",
        phase="composition",
        title="Family-Level Composition (Stacked Bar)",
        description=(
            "Stacked bar chart at family level. Top 12 families + 'Other'. "
            "Samples sorted by {primary_group}."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="genus_heatmap",
        phase="composition",
        title="Genus Abundance Heatmap (Clustermap)",
        description=(
            "Seaborn clustermap of top 25 genera × samples. "
            "Z-score normalization per genus (row). "
            "Add column color bar for {primary_group}. "
            "Use 'RdYlBu_r' colormap."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="genus_violin",
        phase="composition",
        title="Top Genera Distribution (Violin + Strip)",
        description=(
            "Violin + strip plot for top 10 genera, grouped by {primary_group}. "
            "Each genus as a facet (2×5 subplots). "
            "Add {stat_test} p-value annotation."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="genus_boxplot_grouped",
        phase="composition",
        title="Group-wise Genus Abundance Comparison",
        description=(
            "For each of the top 8 genera: boxplot comparing {group_labels}. "
            "Add individual data points (jitter). Annotate p-values from "
            "{stat_test} with multiple testing correction (Benjamini-Hochberg FDR)."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="core_microbiome",
        phase="composition",
        title="Core Microbiome (Prevalence vs Abundance)",
        description=(
            "Scatter plot: x=prevalence (fraction of samples), y=mean relative abundance. "
            "Highlight core genera (prevalence ≥ 80%) in red. "
            "Create separate panels per group if metadata available."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="indicator_species",
        phase="composition",
        title="Indicator Species Analysis",
        description=(
            "For each group in {primary_group}, identify genera with highest specificity and fidelity. "
            "Compute IndVal index (specificity × fidelity) per genus per group. "
            "Plot: horizontal bar chart of top 5 indicator genera per group. "
            "Color bars by group. Add IndVal value annotation."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),

    # ── Phase 3: Alpha Diversity ───────────────────────────────────────
    AnalysisSpec(
        key="alpha_boxplot",
        phase="alpha",
        title="Alpha Diversity Comparison (Multi-Metric)",
        description=(
            "Read ALL alpha diversity files. Create a multi-panel figure (1 row per metric). "
            "Boxplot + jitter for each group in {primary_group}. "
            "Run {stat_test} for each metric. Annotate with p-value and effect size. "
            "Metrics: Shannon, Observed Features, Chao1, Faith's PD (if available)."
        ),
        requires=["alpha"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="alpha_raincloud",
        phase="alpha",
        title="Alpha Diversity Raincloud Plots",
        description=(
            "Raincloud plot (half-violin + strip + boxplot) for Shannon index by {primary_group}. "
            "Use the ptitprince or manual implementation: "
            "  - Half violin (kde) on top, boxplot in middle, raw data points at bottom. "
            "Add mean ± SD annotation per group."
        ),
        requires=["alpha"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="rarefaction",
        phase="alpha",
        title="Rarefaction Curves",
        description=(
            "Subsample feature table at 10-15 evenly spaced depths. "
            "10 iterations per depth. Plot mean observed ASVs vs depth. "
            "Color lines by {primary_group}. Add group mean ± SEM as thick line + ribbon."
        ),
        requires=["feature_table"],
    ),
    AnalysisSpec(
        key="alpha_trajectory",
        phase="alpha",
        title="Alpha Diversity Trajectory (Longitudinal)",
        description=(
            "Line plot: x={timepoint_col}, y=Shannon index. "
            "Color by {primary_group}. Add group mean ± SEM. "
            "Connect individual subjects with thin lines (spaghetti). "
            "Thick group-mean line overlay."
        ),
        requires=["alpha"],
        needs_timepoint=True,
        min_groups=1,
    ),
    AnalysisSpec(
        key="alpha_effectsize",
        phase="alpha",
        title="Alpha Diversity Effect Sizes",
        description=(
            "Forest plot of effect sizes (Cliff's delta or Cohen's d) for all alpha metrics. "
            "x-axis = effect size, y-axis = metric. "
            "Add 95% CI whiskers. Color by magnitude (small/medium/large)."
        ),
        requires=["alpha"],
        min_groups=2,
        max_groups=2,
    ),

    # ── Phase 4: Beta Diversity ────────────────────────────────────────
    AnalysisSpec(
        key="pcoa_all",
        phase="beta",
        title="PCoA Ordination (All Metrics)",
        description=(
            "Multi-panel PCoA: Bray-Curtis, Jaccard, Unweighted UniFrac, Weighted UniFrac "
            "(use only available files). Color points by {primary_group}. "
            "Add 95% confidence ellipses per group (matplotlib Ellipse). "
            "Show % variance explained on axes. 2×2 subplot layout."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="nmds",
        phase="beta",
        title="NMDS Ordination",
        description=(
            "NMDS on Bray-Curtis distance matrix. Color by {primary_group}. "
            "Show stress value in title. Add convex hulls per group. "
            "Use sklearn MDS(metric=False, n_init=4, max_iter=1000)."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="tsne",
        phase="beta",
        title="t-SNE Visualization",
        description=(
            "t-SNE on Bray-Curtis distance matrix. Color by {primary_group}. "
            "perplexity = min(30, n_samples - 1). random_state=42. "
            "Use sklearn TSNE(metric='precomputed')."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="umap_ordination",
        phase="beta",
        title="UMAP Ordination",
        description=(
            "UMAP on Bray-Curtis distance matrix. Color by {primary_group}. "
            "n_neighbors = min(15, n_samples - 1). min_dist = 0.1. "
            "import umap; reducer = umap.UMAP(metric='precomputed'). "
            "If umap not installed, pip install umap-learn first."
        ),
        requires=["beta"],
        min_groups=2,
        extra_packages=["umap-learn"],
    ),
    AnalysisSpec(
        key="pca_clr",
        phase="beta",
        title="PCA on CLR-Transformed Abundances",
        description=(
            "CLR (center log-ratio) transform feature table. "
            "PCA biplot: samples as points colored by {primary_group}, "
            "top 10 contributing taxa as arrows (loading vectors). "
            "Show % variance on axes."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="permanova",
        phase="beta",
        title="PERMANOVA / ANOSIM Statistical Tests",
        description=(
            "For each distance matrix: run PERMANOVA (permutational MANOVA) and ANOSIM. "
            "Implement PERMANOVA: for 999 permutations, permute group labels, "
            "compute pseudo-F = (SS_between / (k-1)) / (SS_within / (N-k)). "
            "p-value = fraction of permuted F >= observed F. "
            "Save results as a formatted table figure (matplotlib table) AND print as text. "
            "Include: metric, pseudo-F, R-statistic, p-value, n_permutations."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="beta_dispersion",
        phase="beta",
        title="Beta Dispersion (Homogeneity of Variances)",
        description=(
            "For each group, compute distance-to-centroid from Bray-Curtis matrix. "
            "Boxplot comparing dispersions per group. "
            "Run Levene's test or permutation test for homogeneity. "
            "Important for interpreting PERMANOVA results."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="sample_dendrogram",
        phase="beta",
        title="Hierarchical Clustering Dendrogram",
        description=(
            "UPGMA dendrogram from Bray-Curtis distance matrix. "
            "Color leaves by {primary_group}. "
            "scipy.cluster.hierarchy: linkage + dendrogram. "
            "Add color bar below."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="beta_trajectory",
        phase="beta",
        title="Beta Diversity Trajectory (Longitudinal)",
        description=(
            "For each subject: plot PCoA coordinates across timepoints as connected lines. "
            "Color by {primary_group}. Add arrows showing direction of change. "
            "Spaghetti plot overlay with group centroid trajectory."
        ),
        requires=["beta"],
        needs_timepoint=True,
        min_groups=1,
    ),

    # ── Phase 5: Differential Abundance ────────────────────────────────
    AnalysisSpec(
        key="volcano",
        phase="differential",
        title="Volcano Plot (Differential Abundance)",
        description=(
            "For each genus: {stat_test} between {group_labels}. "
            "x = log2(fold-change + pseudocount), y = -log10(p-value). "
            "Apply Benjamini-Hochberg FDR correction. "
            "Color: red = up (log2FC>1, q<0.05), blue = down (log2FC<-1, q<0.05), gray = NS. "
            "Label top 10 significant genera. Add dashed threshold lines."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
        max_groups=2,
    ),
    AnalysisSpec(
        key="ma_plot",
        phase="differential",
        title="MA Plot (Mean-Difference)",
        description=(
            "x = log2(mean abundance across both groups), y = log2(fold-change). "
            "Color significant genera (FDR < 0.05). Label outliers. "
            "Add LOESS smoothing line."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
        max_groups=2,
    ),
    AnalysisSpec(
        key="effect_size_forest",
        phase="differential",
        title="Effect Size Forest Plot",
        description=(
            "Forest plot: horizontal bars showing Cliff's delta (or Hedges' g) per genus. "
            "95% CI whiskers. Sorted by effect size. Top 20 genera. "
            "Color by direction (positive=up in group2, negative=down)."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
        max_groups=2,
    ),
    AnalysisSpec(
        key="multi_group_differential",
        phase="differential",
        title="Multi-Group Differential Abundance (Kruskal-Wallis)",
        description=(
            "Kruskal-Wallis test for each genus across {n_groups} groups. "
            "Apply BH-FDR correction. Heatmap of mean relative abundance (z-scored) "
            "for all significant genera (FDR < 0.05). "
            "Annotate with asterisks. Add Dunn's post-hoc pairwise comparisons."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=3,
    ),
    AnalysisSpec(
        key="lefse_style",
        phase="differential",
        title="LEfSe-Style Differential Analysis",
        description=(
            "1. Kruskal-Wallis test per taxon across groups (p<0.05). "
            "2. Pairwise Wilcoxon for surviving taxa. "
            "3. Compute LDA effect size = log10(1 + fold_change × -log10(p)). "
            "Plot horizontal bar chart sorted by LDA effect size. "
            "Color by enriched group. Only show taxa with effect_size > 2."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),

    # ── Phase 6: Advanced / Network / Special ──────────────────────────
    AnalysisSpec(
        key="cooccurrence_network",
        phase="advanced",
        title="Co-Occurrence Network",
        description=(
            "Spearman correlation for top 30 genera across all samples. "
            "Edge if |r| > 0.6 AND p < 0.05. Node size = mean abundance. "
            "Green edges = positive correlation, red = negative. "
            "Use networkx spring_layout. Label nodes with genus names."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="correlation_clustermap",
        phase="advanced",
        title="Genus-Genus Correlation Heatmap",
        description=(
            "Pairwise Spearman correlation for top 20 genera. "
            "sns.clustermap with cmap='RdBu_r', center=0, annot=True (fmt='.2f'). "
            "Hierarchical clustering on both axes."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="ternary_plot",
        phase="advanced",
        title="Ternary Plot (3-Group Composition)",
        description=(
            "For the top 20 genera: compute mean relative abundance in each of 3 groups. "
            "Plot as ternary diagram using matplotlib (manual triangle coordinates). "
            "Each axis = one group. Point size = overall mean abundance. "
            "Label top genera."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=3,
        max_groups=3,
    ),
    AnalysisSpec(
        key="upset_shared_taxa",
        phase="advanced",
        title="UpSet Diagram (Shared/Unique Taxa)",
        description=(
            "For each group: set of genera with prevalence > 50%. "
            "Draw UpSet plot (intersection matrix + bar chart) showing shared and unique genera. "
            "Implement manually with matplotlib (horizontal bars for set sizes, "
            "vertical bars for intersection sizes, dot matrix for memberships)."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="taxonomy_alluvial",
        phase="advanced",
        title="Taxonomy Alluvial / Sankey Diagram",
        description=(
            "Flow diagram: Phylum → Class → Order → Family → Genus for top 8 taxa. "
            "Width of flow = relative abundance. "
            "Use matplotlib PathPatch with cubic Bezier curves. "
            "Vertical bars at each taxonomic level, colored flows connecting them."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="rank_abundance",
        phase="advanced",
        title="Rank-Abundance Curves (by Group)",
        description=(
            "For each sample: sort ASV abundances descending, plot rank vs relative abundance (log scale). "
            "Color by {primary_group}. Add group mean ± SEM as thick line."
        ),
        requires=["feature_table"],
    ),
    AnalysisSpec(
        key="venn_diagram",
        phase="advanced",
        title="Venn Diagram of Shared ASVs",
        description=(
            "For 2-3 groups: set of ASVs present in ≥50% of samples per group. "
            "Draw Venn diagram with matplotlib_venn (or manual circles). "
            "Annotate: total ASVs per group, shared count, unique count."
        ),
        requires=["feature_table"],
        min_groups=2,
        max_groups=3,
        extra_packages=["matplotlib-venn"],
    ),
    AnalysisSpec(
        key="sample_similarity_heatmap",
        phase="advanced",
        title="Sample-Sample Similarity Heatmap",
        description=(
            "Heatmap of Bray-Curtis similarity (1 - distance). "
            "Hierarchical clustering on both axes. "
            "Add group color bars on sides. Annotate diagonal blocks."
        ),
        requires=["beta"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="diversity_correlation",
        phase="advanced",
        title="Diversity vs Metadata Correlation",
        description=(
            "Scatter plots: Shannon index vs each continuous metadata column. "
            "Add Spearman correlation coefficient and p-value. "
            "LOESS trendline. Color by {primary_group}."
        ),
        requires=["alpha"],
    ),
    AnalysisSpec(
        key="taxa_prevalence_heatmap",
        phase="advanced",
        title="Taxa Prevalence Heatmap Across Groups",
        description=(
            "Binary heatmap: rows = top 30 genera, columns = groups. "
            "Cell value = prevalence within group (0-100%). "
            "Color gradient from white (0%) to dark red (100%). "
            "Annotate cells with percentage."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),

    # ── Phase 7: Publication Composite ─────────────────────────────────
    AnalysisSpec(
        key="composite_main",
        phase="publication",
        title="Main Figure Composite (4-Panel)",
        description=(
            "Multi-panel publication figure (2×2) combining: "
            "A) Genus stacked bar by group, B) Shannon diversity boxplot, "
            "C) PCoA Bray-Curtis with ellipses, D) Volcano plot or LEfSe bar. "
            "Use plt.subplot_mosaic or gridspec. Add panel labels (A, B, C, D). "
            "figsize=(14, 12), dpi=300."
        ),
        requires=["feature_table", "taxonomy"],
        min_groups=2,
    ),
    AnalysisSpec(
        key="composite_supplementary",
        phase="publication",
        title="Supplementary Figure Composite",
        description=(
            "Multi-panel supplementary figure (2×3): "
            "A) Rarefaction curves, B) DADA2 stats, C) NMDS, "
            "D) Top genera violin, E) Correlation clustermap, F) Core microbiome. "
            "figsize=(18, 12), dpi=300."
        ),
        requires=["feature_table", "taxonomy"],
    ),
    AnalysisSpec(
        key="statistical_summary_table",
        phase="publication",
        title="Statistical Results Summary Table",
        description=(
            "Create a formatted table figure showing ALL statistical tests performed: "
            "Test name, metric, test statistic, p-value, FDR-corrected q-value, effect size, interpretation. "
            "Use matplotlib table with alternating row colors. Save as high-res PNG. "
            "This is the 'Table 1' of the analysis."
        ),
        requires=["feature_table"],
        min_groups=2,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 解析プラン構築
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisStep:
    """プラン内の1ステップ"""
    step_num: int
    spec: AnalysisSpec
    code_prompt: str
    skip_reason: Optional[str] = None
    figure_prefix: str = ""


@dataclass
class AnalysisPlan:
    """解析プラン全体"""
    research_question: str
    design: ExperimentalDesign
    steps: list[AnalysisStep] = field(default_factory=list)
    skipped: list[AnalysisStep] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Research Question: {self.research_question}",
            f"Total steps: {len(self.steps)} (skipped: {len(self.skipped)})",
            "",
        ]
        phase_order = ["quality", "composition", "alpha", "beta", "differential", "advanced", "publication"]
        phase_names = {
            "quality": "Data Quality",
            "composition": "Taxonomic Composition",
            "alpha": "Alpha Diversity",
            "beta": "Beta Diversity",
            "differential": "Differential Abundance",
            "advanced": "Advanced Analysis",
            "publication": "Publication Figures",
        }
        for phase in phase_order:
            phase_steps = [s for s in self.steps if s.spec.phase == phase]
            if phase_steps:
                lines.append(f"── {phase_names.get(phase, phase)} ({len(phase_steps)} steps) ──")
                for s in phase_steps:
                    lines.append(f"  {s.step_num:2d}. {s.spec.title}")
        return "\n".join(lines)


def _select_stat_test(design: ExperimentalDesign) -> str:
    """実験デザインに基づいて適切な統計検定を選択"""
    if design.n_groups == 2:
        if design.is_paired:
            return "Wilcoxon signed-rank test"
        return "Mann-Whitney U test"
    elif design.n_groups >= 3:
        if design.is_paired:
            return "Friedman test + Nemenyi post-hoc"
        return "Kruskal-Wallis test + Dunn's post-hoc (Bonferroni)"
    return "descriptive statistics only"


def _expand_prompt(spec: AnalysisSpec, design: ExperimentalDesign,
                   metadata_path: str, research_question: str) -> str:
    """AnalysisSpec の description をデザイン情報で展開"""
    group_labels = ", ".join(f"'{v}'" for v in list(design.group_sizes.keys())[:5])
    stat_test = _select_stat_test(design)

    text = spec.description
    text = text.replace("{primary_group}", design.primary_group or "group")
    text = text.replace("{group_labels}", group_labels or "groups")
    text = text.replace("{n_groups}", str(design.n_groups))
    text = text.replace("{stat_test}", stat_test)
    text = text.replace("{timepoint_col}", design.timepoint_column or "timepoint")

    return text


def build_analysis_plan(
    research_question: str,
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
    metadata_path: str = "",
    model: str = "",
) -> AnalysisPlan:
    """
    研究目的とデザインに基づいて解析プランを構築。

    Pass 1: 決定論的スキャフォールド（レジストリから条件一致するものを選択）
    Pass 2: LLM による研究目的固有のステップ追加（オプション）
    """
    plan = AnalysisPlan(research_question=research_question, design=design)
    available_cats = set(export_files.keys())

    step_num = 0
    for spec in ANALYSIS_REGISTRY:
        # データ要件チェック
        missing = [r for r in spec.requires if r not in available_cats and r != "metadata"]
        if missing:
            plan.skipped.append(AnalysisStep(
                step_num=0, spec=spec, code_prompt="",
                skip_reason=f"Missing data: {', '.join(missing)}",
            ))
            continue

        # グループ数チェック
        if spec.min_groups > 0 and design.n_groups < spec.min_groups:
            plan.skipped.append(AnalysisStep(
                step_num=0, spec=spec, code_prompt="",
                skip_reason=f"Need ≥{spec.min_groups} groups, have {design.n_groups}",
            ))
            continue
        if design.n_groups > spec.max_groups:
            plan.skipped.append(AnalysisStep(
                step_num=0, spec=spec, code_prompt="",
                skip_reason=f"Need ≤{spec.max_groups} groups, have {design.n_groups}",
            ))
            continue

        # 縦断/ペア要件チェック
        if spec.needs_timepoint and not design.is_longitudinal:
            plan.skipped.append(AnalysisStep(
                step_num=0, spec=spec, code_prompt="",
                skip_reason="No timepoint column in metadata",
            ))
            continue
        if spec.needs_paired and not design.is_paired:
            plan.skipped.append(AnalysisStep(
                step_num=0, spec=spec, code_prompt="",
                skip_reason="Not a paired design",
            ))
            continue

        # プロンプト展開
        step_num += 1
        expanded = _expand_prompt(spec, design, metadata_path, research_question)

        plan.steps.append(AnalysisStep(
            step_num=step_num,
            spec=spec,
            code_prompt=expanded,
            figure_prefix=f"step{step_num:02d}_{spec.key}",
        ))

    return plan


# ─────────────────────────────────────────────────────────────────────────────
# ステップ実行用プロンプト構築
# ─────────────────────────────────────────────────────────────────────────────

def _build_step_prompt(
    step: AnalysisStep,
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
    figure_dir: str,
    metadata_path: str,
    research_question: str,
    prior_results: list[str],
    dpi: int = 150,
) -> str:
    """1ステップ分の完全なコード生成プロンプト"""
    stat_test = _select_stat_test(design)
    group_labels = list(design.group_sizes.keys())

    lines = [
        "You are an expert microbiome bioinformatics analyst.",
        "Write a COMPLETE, self-contained Python script for the following analysis.",
        "",
        f"## RESEARCH QUESTION",
        f"{research_question}",
        "",
        f"## EXPERIMENTAL DESIGN",
        design.summary(),
        "",
        f"## CURRENT TASK (Step {step.step_num})",
        f"### {step.spec.title}",
        step.code_prompt,
        "",
        f"## Statistical test to use: {stat_test}",
    ]

    if group_labels:
        lines.append(f"## Group labels (in metadata column '{design.primary_group}'): {group_labels}")

    # 比較プラン（多因子デザインの場合）
    if design.comparisons:
        lines.append("")
        lines.append("## PLANNED COMPARISONS (use these exact groups/filters)")
        for c in design.comparisons:
            if c.type == "interaction":
                lines.append(f"  - INTERACTION: {c.name} — {c.rationale}")
            elif c.filter_conditions:
                filt = ", ".join(f"{k}='{v}'" for k, v in c.filter_conditions.items())
                lines.append(
                    f"  - {c.name}: filter metadata where {filt}, "
                    f"then compare '{c.group_a}' (n={c.n_a}) vs '{c.group_b}' (n={c.n_b})"
                )
            else:
                lines.append(f"  - {c.name}: '{c.group_a}' (n={c.n_a}) vs '{c.group_b}' (n={c.n_b})")
        lines.append("  Use these comparisons where appropriate for this analysis step.")

    if prior_results:
        lines.append("")
        lines.append("## PREVIOUS FINDINGS (for context)")
        for r in prior_results[-4:]:
            lines.append(f"  - {r}")

    lines += [
        "",
        "## AVAILABLE FILES — use ONLY these exact paths",
    ]
    for cat, paths in export_files.items():
        for p in paths:
            lines.append(f"  [{cat}] {p}")
    if metadata_path:
        lines.append(f"  [metadata] {metadata_path}")

    # メタデータの読み方の具体的な指示
    if metadata_path and design.primary_group:
        lines += [
            "",
            "## HOW TO READ METADATA",
            f"  meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')",
            f"  id_col = meta.columns[0]  # '{design.columns[0] if design.columns else 'sample-id'}'",
            f"  meta = meta.set_index(id_col)",
            f"  group_col = '{design.primary_group}'",
            f"  groups = meta[group_col].unique()  # {group_labels}",
        ]

    lines += [
        "",
        "## FILE FORMATS",
        "",
        "### feature-table.tsv (QIIME2 biom export)",
        "  Line 1: '# Constructed from biom file' ← SKIP",
        "  Line 2: '#OTU ID\\t<sample1>\\t<sample2>...' ← header",
        "  Read: ft = pd.read_csv(path, sep='\\t', skiprows=1, index_col=0)",
        "",
        "### taxonomy.tsv",
        "  Columns: Feature ID (index) | Taxon | Confidence",
        "  Phylum: tax['Taxon'].str.extract(r'p__([^;]+)')[0].fillna('Unknown').str.strip()",
        "  Genus:  tax['Taxon'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()",
        "",
        "### alpha TSV: sample-id (index) | metric_value. Get name: col = alpha.columns[0]",
        "### beta TSV: square distance matrix. Read: dm = pd.read_csv(path, sep='\\t', index_col=0)",
        "### denoising-stats.tsv: index=sample-id, cols: input|filtered|denoised|merged|non-chimeric",
        "",
        "## CODE REQUIREMENTS",
        "1. First 4 lines MUST be:",
        "   import matplotlib",
        "   matplotlib.use('Agg')",
        "   import matplotlib.pyplot as plt",
        "   import pandas as pd",
        "2. Then:",
        f"   FIGURE_DIR = r'{figure_dir}'",
        f"   DPI = {dpi}",
        "   import os; os.makedirs(FIGURE_DIR, exist_ok=True)",
        f"3. Save ALL figures with prefix '{step.figure_prefix}_': e.g.",
        f"   plt.savefig(os.path.join(FIGURE_DIR, '{step.figure_prefix}_main.png'), dpi=DPI, bbox_inches='tight')",
        "   plt.close()",
        "4. PNG format ONLY (never .pdf, .svg, .jpg)",
        "5. All labels and titles in English",
        "6. Use try/except around independent sections",
        "7. No plt.show()",
        "",
        "## FIGURE STYLE",
        "import seaborn as sns",
        "sns.set_theme(style='white', context='paper', font_scale=1.3)",
        "PALETTE = sns.color_palette('tab10')",
        "# Remove top/right spines: ax.spines[['top','right']].set_visible(False)",
        "",
        "## COMMON MISTAKES — avoid these",
        "- str.extract() returns DataFrame: use [0] → tax['Taxon'].str.extract(r'g__([^;]+)')[0]",
        "- DO NOT import biom — use pd.read_csv on .tsv files",
        "- DO NOT hardcode data values — read from files",
        "- Align sample IDs between feature table and metadata: common = ft.columns.intersection(meta.index)",
        "",
        "## OUTPUT ONLY the Python code in ```python ... ```.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 実行エンジン
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """1ステップの実行結果"""
    step: AnalysisStep
    success: bool
    figures: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    code: str = ""
    summary: str = ""


@dataclass
class ManualAutoResult:
    """manual-auto 全体の結果"""
    plan: AnalysisPlan
    results: list[StepResult] = field(default_factory=list)
    all_figures: list[str] = field(default_factory=list)
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0


def run_manual_auto(
    research_question: str,
    design: ExperimentalDesign,
    plan: AnalysisPlan,
    export_files: dict[str, list[str]],
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> ManualAutoResult:
    """
    manual-auto モードの実行エンジン。

    各ステップについて:
    1. コード生成プロンプトを構築
    2. LLM にコード生成を依頼
    3. 実行・リトライ
    4. 結果を記録し次ステップへ
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    result = ManualAutoResult(plan=plan, skipped_steps=len(plan.skipped))
    prior_results: list[str] = []

    total = len(plan.steps)
    _log(f"\n{'═' * 56}")
    _log(f"  🔬 Manual-Auto Analysis: {total} steps planned")
    _log(f"  📋 Research: {research_question[:80]}")
    _log(f"{'═' * 56}\n")

    for i, step in enumerate(plan.steps):
        _log(f"\n{'─' * 48}")
        _log(f"  📊 Step {step.step_num}/{total}: {step.spec.title}")
        _log(f"  Phase: {step.spec.phase}")
        _log(f"{'─' * 48}")

        # 追加パッケージの事前インストール
        for pkg in step.spec.extra_packages:
            _log(f"  📦 追加パッケージ確認: {pkg}")
            try:
                __import__(pkg.replace("-", "_").split("[")[0])
            except ImportError:
                approved = install_callback(pkg) if install_callback else True
                if approved:
                    pip_install(pkg, log_callback)

        # プロンプト構築
        prompt = _build_step_prompt(
            step=step,
            design=design,
            export_files=export_files,
            figure_dir=figure_dir,
            metadata_path=metadata_path,
            research_question=research_question,
            prior_results=prior_results,
        )

        # LLM にコード生成を依頼
        _log("  LLM にコード生成を依頼中...")
        system_msg = {
            "role": "system",
            "content": (
                "You are a microbiome analysis expert. "
                "Generate only Python code without explanation. "
                "Wrap code in ```python ... ```."
            ),
        }
        messages = [system_msg, {"role": "user", "content": prompt}]

        try:
            response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"  ❌ Ollama エラー: {e}")
            result.results.append(StepResult(step=step, success=False, stderr=str(e)))
            result.failed_steps += 1
            continue

        code = _extract_code(response.get("content", ""))
        if not code:
            _log("  ⚠️ コードが生成されませんでした。スキップします。")
            result.results.append(StepResult(step=step, success=False, stderr="No code generated"))
            result.failed_steps += 1
            continue

        _log(f"  コード生成完了 ({len(code.splitlines())} 行)")

        # 実行 + リトライ
        last_code = code
        step_success = False
        new_figs: list[str] = []
        last_stdout = ""
        last_stderr = ""

        for attempt in range(max_retries):
            _log(f"  実行中... (試行 {attempt + 1}/{max_retries})")
            success, stdout, stderr, figs = _run_code(
                last_code, output_dir, figure_dir, log_callback
            )
            last_stdout = stdout
            last_stderr = stderr

            if success and figs:
                step_success = True
                new_figs = figs
                break

            if success and not figs:
                # 実行成功だが図なし — コードは動いた（統計テーブルのみの場合など）
                step_success = True
                break

            # エラー処理
            missing_pkg = _detect_missing_module(stderr)
            if missing_pkg:
                _log(f"  📦 未インストール: {missing_pkg}")
                approved = install_callback(missing_pkg) if install_callback else True
                if approved and pip_install(missing_pkg, log_callback):
                    continue

            if attempt < max_retries - 1:
                _log("  LLM にコード修正を依頼中...")
                fix_msgs = messages + [
                    {"role": "assistant", "content": f"```python\n{last_code}\n```"},
                    {
                        "role": "user",
                        "content": (
                            f"Error:\n```\n{stderr[:1500]}\n```\n"
                            "Fix the code. Return the COMPLETE corrected script in ```python...```."
                        ),
                    },
                ]
                try:
                    fix_resp = _agent.call_ollama(fix_msgs, model)
                    fixed = _extract_code(fix_resp.get("content", ""))
                    if fixed:
                        last_code = fixed
                        _log(f"  修正コード受信 ({len(last_code.splitlines())} 行)")
                except Exception:
                    pass

        # 結果記録
        step_result = StepResult(
            step=step,
            success=step_success,
            figures=new_figs,
            stdout=last_stdout,
            stderr=last_stderr,
            code=last_code,
        )

        if step_success:
            result.completed_steps += 1
            result.all_figures.extend(new_figs)
            fig_names = [Path(f).name for f in new_figs]
            _log(f"  ✅ 成功 — 図: {fig_names}" if new_figs else "  ✅ 成功（テーブル/テキスト出力）")
            summary_text = f"{step.spec.title}: {len(new_figs)} figures generated"
            if last_stdout and len(last_stdout.strip()) < 500:
                summary_text += f" | Output: {last_stdout.strip()[:200]}"
            step_result.summary = summary_text
            prior_results.append(summary_text)
        else:
            result.failed_steps += 1
            _log(f"  ❌ 失敗: {last_stderr[:200]}")
            prior_results.append(f"{step.spec.title}: FAILED")

        result.results.append(step_result)

    # 最終サマリー
    _log(f"\n{'═' * 56}")
    _log(f"  🏁 Manual-Auto Analysis Complete")
    _log(f"  ✅ Completed: {result.completed_steps}/{total}")
    _log(f"  ❌ Failed:    {result.failed_steps}/{total}")
    _log(f"  ⏭  Skipped:   {result.skipped_steps}")
    _log(f"  📊 Total figures: {len(result.all_figures)}")
    _log(f"{'═' * 56}\n")

    return result
