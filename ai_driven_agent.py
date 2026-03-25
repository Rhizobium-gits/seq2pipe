#!/usr/bin/env python3
"""
ai_driven_agent.py
==================
AI 駆動解析モード（--ai-driven / モード 5）。

AI（LLM）が自らデータを偵察し、実験デザインと研究目的に基づいて
解析プランを立案。各ステップの結果を見て次の解析を動的に決定する。

Phase 1: データ偵察 — 実際にデータを読み込み、群間統計検定を実行
Phase 2: AI プランニング — 統計結果をもとに解析プランを立案
Phase 3: 適応的実行ループ — 各ステップの統計的発見に基づいてリプラン
"""

from __future__ import annotations

import json
import re
import csv
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

import sys
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import (
    _run_code, _extract_code, _detect_missing_module, pip_install,
)
from manual_auto_agent import (
    ExperimentalDesign, parse_metadata, ANALYSIS_REGISTRY, AnalysisSpec,
    _select_stat_test, _expand_prompt, _build_step_prompt, AnalysisStep,
)
from microbiome_knowledge import (
    DataProfile, ALPHA_METRICS, BETA_METRICS,
    recommend_alpha_test, recommend_beta_test,
    recommend_compositional_method, recommend_ordinations,
    estimate_power_context, build_domain_driven_plan,
)
from experiment_knowledge import (
    ExperimentContext, build_experiment_context,
)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: データ偵察 — 実データを読み込み統計解析まで実行
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DataRecon:
    """データ偵察の結果（基本統計 + 群間検定結果）"""
    # 基本情報
    n_samples: int = 0
    n_asvs: int = 0
    total_reads: int = 0
    min_reads: int = 0
    max_reads: int = 0
    median_reads: int = 0
    sample_ids: list[str] = field(default_factory=list)
    has_taxonomy: bool = False
    n_genera: int = 0
    top_phyla: list[tuple[str, float]] = field(default_factory=list)   # (name, rel_abundance%)
    top_genera: list[tuple[str, float]] = field(default_factory=list)
    alpha_metrics: list[str] = field(default_factory=list)
    beta_metrics: list[str] = field(default_factory=list)
    has_denoising: bool = False
    denoising_pass_rate: float = 0.0
    chimera_rate: float = 0.0
    merge_rate: float = 0.0
    sparsity: float = 0.0
    evenness_mean: float = 0.0
    dominance_mean: float = 0.0
    singleton_fraction: float = 0.0    # 1サンプルにしか出現しないASVの割合
    goods_coverage_mean: float = 0.0   # Good's coverage 平均
    fb_ratio: float = 0.0             # Firmicutes/Bacteroidetes 比
    proteobacteria_fraction: float = 0.0
    unclassified_fraction: float = 0.0

    # 群間統計検定結果
    alpha_group_tests: list[dict] = field(default_factory=list)
    # e.g. [{"metric": "shannon", "test": "Mann-Whitney", "p": 0.003, "group_means": {"ctrl": 4.2, "abx": 2.5}}]
    beta_group_tests: list[dict] = field(default_factory=list)
    # e.g. [{"metric": "bray_curtis", "test": "PERMANOVA-approx", "pseudo_F": 3.5, "p": 0.01}]
    dominant_genus_per_group: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # e.g. {"ctrl": [("Lactobacillus", 25.3), ...], "abx": [("Enterococcus", 40.1), ...]}
    group_read_depth: dict[str, float] = field(default_factory=dict)
    # e.g. {"ctrl": 27000, "abx": 25000}
    outlier_samples: list[str] = field(default_factory=list)
    high_variance_genera: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Samples: {self.n_samples}",
            f"ASVs: {self.n_asvs}",
            f"Total reads: {self.total_reads:,}",
            f"Reads/sample: min={self.min_reads:,}, median={self.median_reads:,}, max={self.max_reads:,}",
        ]
        if self.group_read_depth:
            grd = ", ".join(f"{g}={int(v):,}" for g, v in self.group_read_depth.items())
            lines.append(f"Mean reads per group: {grd}")
        if self.sparsity > 0:
            lines.append(f"Feature table sparsity: {self.sparsity:.0%} zeros")
        if self.evenness_mean > 0:
            lines.append(f"Mean evenness (Pielou's J): {self.evenness_mean:.3f} (0=dominated, 1=even)")
        if self.dominance_mean > 0:
            lines.append(f"Mean dominance (Simpson's D): {self.dominance_mean:.3f} (high=few dominant taxa)")
        if self.outlier_samples:
            lines.append(f"Potential outlier samples (read depth): {', '.join(self.outlier_samples)}")

        if self.has_taxonomy:
            lines.append(f"Genera detected: {self.n_genera}")
            if self.top_phyla:
                phyla_str = ", ".join(f"{n} ({a:.1f}%)" for n, a in self.top_phyla[:5])
                lines.append(f"Top phyla (relative abundance): {phyla_str}")
            if self.top_genera:
                gen_str = ", ".join(f"{n} ({a:.1f}%)" for n, a in self.top_genera[:8])
                lines.append(f"Top genera (relative abundance): {gen_str}")
            if self.dominant_genus_per_group:
                for grp, taxa in self.dominant_genus_per_group.items():
                    top3 = ", ".join(f"{n} ({a:.1f}%)" for n, a in taxa[:3])
                    lines.append(f"  Group '{grp}' dominants: {top3}")
            if self.high_variance_genera:
                lines.append(f"High-variance genera (across groups): {', '.join(self.high_variance_genera[:5])}")

        if self.alpha_group_tests:
            lines.append("Alpha diversity group tests:")
            for t in self.alpha_group_tests:
                p_str = f"p={t['p']:.4f}" if t['p'] is not None else "p=N/A"
                sig = " ***" if t.get('p') and t['p'] < 0.001 else (" **" if t.get('p') and t['p'] < 0.01 else (" *" if t.get('p') and t['p'] < 0.05 else ""))
                means = ""
                if t.get("group_means"):
                    means = " | " + ", ".join(f"{g}={v:.2f}" for g, v in t["group_means"].items())
                lines.append(f"  {t['metric']}: {t['test']} {p_str}{sig}{means}")

        if self.beta_group_tests:
            lines.append("Beta diversity group tests:")
            for t in self.beta_group_tests:
                p_str = f"p≈{t['p']:.3f}" if t['p'] is not None else "p=N/A"
                f_str = f"pseudo-F={t.get('pseudo_F', 0):.2f}" if t.get('pseudo_F') else ""
                sig = " ***" if t.get('p') and t['p'] < 0.001 else (" **" if t.get('p') and t['p'] < 0.01 else (" *" if t.get('p') and t['p'] < 0.05 else ""))
                lines.append(f"  {t['metric']}: {f_str} {p_str}{sig}")

        if self.alpha_metrics:
            lines.append(f"Available alpha metrics: {', '.join(self.alpha_metrics)}")
        if self.beta_metrics:
            lines.append(f"Available beta metrics: {', '.join(self.beta_metrics)}")
        if self.has_denoising:
            lines.append(f"Denoising pass rate: {self.denoising_pass_rate:.1%}")
        return "\n".join(lines)

    def to_profile(self, design: ExperimentalDesign) -> DataProfile:
        """DataRecon + ExperimentalDesign から DataProfile を構築"""
        import statistics as _st

        reads = [self.min_reads, self.max_reads] if self.min_reads else []
        read_cv = 0.0
        if reads and self.median_reads > 0:
            all_reads = list(self.group_read_depth.values()) if self.group_read_depth else reads
            if len(all_reads) >= 2:
                mean_r = _st.mean(all_reads)
                std_r = _st.stdev(all_reads) if len(all_reads) > 1 else 0
                read_cv = std_r / mean_r if mean_r > 0 else 0

        alpha_sig = any(t.get("p", 1) < 0.05 for t in self.alpha_group_tests)
        alpha_p = min((t.get("p", 1) for t in self.alpha_group_tests), default=1.0)
        beta_sig = any(t.get("p", 1) < 0.05 for t in self.beta_group_tests)
        beta_p = min((t.get("p", 1) for t in self.beta_group_tests), default=1.0)
        beta_f = max((t.get("pseudo_F", 0) for t in self.beta_group_tests), default=0.0)

        group_sizes = list(design.group_sizes.values()) if design.group_sizes else [self.n_samples]

        return DataProfile(
            n_samples=self.n_samples,
            n_groups=design.n_groups,
            min_group_size=min(group_sizes) if group_sizes else 0,
            max_group_size=max(group_sizes) if group_sizes else 0,
            is_paired=design.is_paired,
            is_longitudinal=design.is_longitudinal,
            n_asvs=self.n_asvs,
            read_depth_cv=read_cv,
            min_reads=self.min_reads,
            max_reads=self.max_reads,
            has_taxonomy=self.has_taxonomy,
            n_genera=self.n_genera,
            alpha_significant=alpha_sig,
            alpha_p=alpha_p,
            beta_significant=beta_sig,
            beta_p=beta_p,
            beta_pseudo_f=beta_f,
            sparsity=self.sparsity,
            evenness_mean=self.evenness_mean,
            dominance_mean=self.dominance_mean,
            singleton_fraction=self.singleton_fraction,
            goods_coverage_mean=self.goods_coverage_mean,
            fb_ratio=self.fb_ratio,
            proteobacteria_fraction=self.proteobacteria_fraction,
            unclassified_fraction=self.unclassified_fraction,
            chimera_rate=self.chimera_rate,
            merge_rate=self.merge_rate,
            denoising_pass_rate=self.denoising_pass_rate,
            high_variance_genera=self.high_variance_genera,
        )


def _safe_read_tsv(path: str, skip_comment: bool = False) -> tuple[list[str], list[list[str]]]:
    """TSV を安全に読み込む。(header, rows) を返す。"""
    rows = []
    header = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if skip_comment and line.startswith("# "):
                continue
            if not header:
                header = line.split("\t")
                continue
            if line.startswith("#q2:"):
                continue
            rows.append(line.split("\t"))
    return header, rows


def run_data_recon(
    export_files: dict[str, list[str]],
    design: ExperimentalDesign,
    metadata_path: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
) -> DataRecon:
    """データを実際に読み込み、基本統計＋群間統計検定を実行"""
    import statistics

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    recon = DataRecon()

    # メタデータのグループマッピング読み込み
    group_map: dict[str, str] = {}  # sample_id -> group
    if metadata_path and design.primary_group:
        try:
            with open(metadata_path) as f:
                reader = csv.reader(f, delimiter="\t")
                mheader = next(reader)
                id_idx = 0
                grp_idx = None
                for i, col in enumerate(mheader):
                    if col == design.primary_group:
                        grp_idx = i
                        break
                if grp_idx is not None:
                    for row in reader:
                        if row and not row[0].startswith("#q2:"):
                            group_map[row[id_idx]] = row[grp_idx] if grp_idx < len(row) else ""
        except Exception:
            pass

    # ── Feature table 解析 ─────────────────────────────────────────
    ft_paths = export_files.get("feature_table", [])
    sample_reads: dict[str, int] = {}
    ft_matrix: dict[str, dict[str, float]] = {}  # asv_id -> {sample: count}

    if ft_paths:
        try:
            _log("  📊 Feature table を解析中...")
            header, rows = _safe_read_tsv(ft_paths[0], skip_comment=True)
            sample_ids = header[1:]
            recon.sample_ids = sample_ids
            recon.n_samples = len(sample_ids)
            sample_reads = {s: 0 for s in sample_ids}

            for row in rows:
                if len(row) < 2:
                    continue
                asv_id = row[0]
                ft_matrix[asv_id] = {}
                for j, sid in enumerate(sample_ids):
                    if j + 1 < len(row):
                        try:
                            val = float(row[j + 1])
                            sample_reads[sid] += int(val)
                            ft_matrix[asv_id][sid] = val
                        except (ValueError, IndexError):
                            pass

            recon.n_asvs = len(ft_matrix)
            reads_list = list(sample_reads.values())
            if reads_list:
                recon.total_reads = sum(reads_list)
                recon.min_reads = min(reads_list)
                recon.max_reads = max(reads_list)
                recon.median_reads = int(statistics.median(reads_list))

            # スパース度（feature table 内の 0 の割合）
            total_cells = len(ft_matrix) * len(sample_ids)
            zero_cells = 0
            for asv_counts in ft_matrix.values():
                for sid in sample_ids:
                    if asv_counts.get(sid, 0) == 0:
                        zero_cells += 1
            recon.sparsity = zero_cells / total_cells if total_cells > 0 else 0.0
            if recon.sparsity > 0.7:
                _log(f"    ⚠️ High sparsity: {recon.sparsity:.0%} zeros in feature table")

            # サンプルごとのイーブンネス（Shannon / ln(S)）
            import math as _math
            evenness_vals = []
            for sid in sample_ids:
                counts = [ft_matrix[asv].get(sid, 0) for asv in ft_matrix]
                total_c = sum(counts)
                if total_c == 0:
                    continue
                nonzero = [c for c in counts if c > 0]
                s = len(nonzero)
                if s <= 1:
                    evenness_vals.append(0.0)
                    continue
                h = -sum((c / total_c) * _math.log(c / total_c) for c in nonzero)
                j = h / _math.log(s)
                evenness_vals.append(j)
            if evenness_vals:
                recon.evenness_mean = statistics.mean(evenness_vals)
                # dominance = 1 - Simpson
                dom_vals = []
                for sid in sample_ids:
                    counts = [ft_matrix[asv].get(sid, 0) for asv in ft_matrix]
                    total_c = sum(counts)
                    if total_c <= 1:
                        continue
                    simpson = sum((c / total_c) ** 2 for c in counts if c > 0)
                    dom_vals.append(simpson)
                if dom_vals:
                    recon.dominance_mean = statistics.mean(dom_vals)

            # シングルトン比率（1サンプルにしか出現しないASV）
            n_singletons = 0
            for asv_id, asv_counts in ft_matrix.items():
                n_present = sum(1 for v in asv_counts.values() if v > 0)
                if n_present == 1:
                    n_singletons += 1
            recon.singleton_fraction = n_singletons / len(ft_matrix) if ft_matrix else 0

            # Good's coverage per sample: C = 1 - (n_singletons_in_sample / total_reads_in_sample)
            coverage_vals = []
            for sid in sample_ids:
                counts = [ft_matrix[asv].get(sid, 0) for asv in ft_matrix]
                total_c = sum(counts)
                if total_c > 0:
                    n_sing = sum(1 for c in counts if c == 1)
                    coverage_vals.append(1 - n_sing / total_c)
            if coverage_vals:
                recon.goods_coverage_mean = statistics.mean(coverage_vals)

            # 群別平均リード数
            if group_map:
                from collections import defaultdict
                grp_reads: dict[str, list[int]] = defaultdict(list)
                for sid, cnt in sample_reads.items():
                    g = group_map.get(sid, "")
                    if g:
                        grp_reads[g].append(cnt)
                recon.group_read_depth = {
                    g: statistics.mean(vals) for g, vals in grp_reads.items() if vals
                }

            # 外れ値検出 (IQR)
            if len(reads_list) >= 4:
                sorted_r = sorted(reads_list)
                q1 = sorted_r[len(sorted_r) // 4]
                q3 = sorted_r[3 * len(sorted_r) // 4]
                iqr = q3 - q1
                low_thresh = q1 - 1.5 * iqr
                recon.outlier_samples = [
                    sid for sid, cnt in sample_reads.items()
                    if cnt < low_thresh
                ]

            _log(f"    {recon.n_samples} samples, {recon.n_asvs} ASVs, "
                 f"{recon.total_reads:,} total reads")
            if recon.outlier_samples:
                _log(f"    ⚠️ 外れ値候補: {recon.outlier_samples}")
        except Exception as e:
            _log(f"    ⚠️ Feature table 解析失敗: {e}")

    # ── Taxonomy 解析（群別優占属を計算）──────────────────────────
    tax_paths = export_files.get("taxonomy", [])
    asv_genus: dict[str, str] = {}
    asv_phylum: dict[str, str] = {}
    if tax_paths:
        try:
            _log("  🧬 Taxonomy を解析中...")
            recon.has_taxonomy = True
            with open(tax_paths[0]) as f:
                f.readline()  # skip header
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 2:
                        continue
                    asv_id = parts[0]
                    taxon = parts[1]
                    m_p = re.search(r"p__([^;]+)", taxon)
                    m_g = re.search(r"g__([^;]+)", taxon)
                    if m_p:
                        p = m_p.group(1).strip()
                        if p and p != "__":
                            asv_phylum[asv_id] = p
                    if m_g:
                        g = m_g.group(1).strip()
                        if g and g != "__":
                            asv_genus[asv_id] = g

            recon.n_genera = len(set(asv_genus.values()))

            # 全体の相対豊度（属レベル）
            if ft_matrix and asv_genus:
                from collections import defaultdict
                genus_total: dict[str, float] = defaultdict(float)
                phylum_total: dict[str, float] = defaultdict(float)
                grand_total = 0.0

                for asv_id, sample_counts in ft_matrix.items():
                    total = sum(sample_counts.values())
                    grand_total += total
                    g = asv_genus.get(asv_id, "Unknown")
                    genus_total[g] += total
                    p = asv_phylum.get(asv_id, "Unknown")
                    phylum_total[p] += total

                if grand_total > 0:
                    recon.top_phyla = [
                        (name, count / grand_total * 100)
                        for name, count in sorted(phylum_total.items(), key=lambda x: -x[1])[:10]
                    ]
                    recon.top_genera = [
                        (name, count / grand_total * 100)
                        for name, count in sorted(genus_total.items(), key=lambda x: -x[1])[:15]
                    ]

                    # F/B 比・Proteobacteria 比率
                    firm = phylum_total.get("Firmicutes", 0)
                    bact = phylum_total.get("Bacteroidetes", 0) + phylum_total.get("Bacteroidota", 0)
                    recon.fb_ratio = firm / bact if bact > 0 else 0.0
                    proteo = phylum_total.get("Proteobacteria", 0) + phylum_total.get("Pseudomonadota", 0)
                    recon.proteobacteria_fraction = proteo / grand_total if grand_total > 0 else 0.0

                    # 未分類比率
                    unclass = genus_total.get("Unknown", 0) + genus_total.get("", 0) + genus_total.get("__", 0)
                    recon.unclassified_fraction = unclass / grand_total if grand_total > 0 else 0.0

                # 群別優占属
                if group_map:
                    grp_genus_abd: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
                    grp_total_reads: dict[str, float] = defaultdict(float)
                    for asv_id, sample_counts in ft_matrix.items():
                        g = asv_genus.get(asv_id, "Unknown")
                        for sid, cnt in sample_counts.items():
                            grp = group_map.get(sid, "")
                            if grp:
                                grp_genus_abd[grp][g] += cnt
                                grp_total_reads[grp] += cnt

                    for grp in grp_genus_abd:
                        if grp_total_reads[grp] > 0:
                            ranked = sorted(
                                grp_genus_abd[grp].items(), key=lambda x: -x[1]
                            )
                            recon.dominant_genus_per_group[grp] = [
                                (name, count / grp_total_reads[grp] * 100)
                                for name, count in ranked[:5]
                            ]

                    # 群間で最も差がある属を検出
                    groups = list(grp_genus_abd.keys())
                    if len(groups) >= 2:
                        all_genera = set()
                        for g in groups:
                            all_genera.update(grp_genus_abd[g].keys())
                        genus_var = {}
                        for gen in all_genera:
                            vals = []
                            for g in groups:
                                tot = grp_total_reads[g] if grp_total_reads[g] > 0 else 1
                                vals.append(grp_genus_abd[g].get(gen, 0) / tot * 100)
                            if len(vals) >= 2:
                                genus_var[gen] = max(vals) - min(vals)
                        recon.high_variance_genera = [
                            g for g, v in sorted(genus_var.items(), key=lambda x: -x[1])[:10]
                            if v > 1.0  # >1% difference
                        ]

            _log(f"    {recon.n_genera} genera")
            if recon.high_variance_genera:
                _log(f"    🔍 群間差が大きい属: {', '.join(recon.high_variance_genera[:5])}")
        except Exception as e:
            _log(f"    ⚠️ Taxonomy 解析失敗: {e}")

    # ── Alpha diversity 群間検定 ──────────────────────────────────
    alpha_paths = export_files.get("alpha", [])
    for ap in alpha_paths:
        metric_name = Path(ap).parent.name or Path(ap).stem
        recon.alpha_metrics.append(metric_name)

        if group_map and len(set(group_map.values())) >= 2:
            try:
                header, rows = _safe_read_tsv(ap)
                if len(header) >= 2:
                    val_col = 1
                    groups_vals: dict[str, list[float]] = {}
                    for row in rows:
                        if len(row) < 2:
                            continue
                        sid = row[0]
                        grp = group_map.get(sid, "")
                        if not grp:
                            continue
                        try:
                            v = float(row[val_col])
                            groups_vals.setdefault(grp, []).append(v)
                        except (ValueError, IndexError):
                            pass

                    if len(groups_vals) >= 2:
                        from scipy.stats import mannwhitneyu, kruskal
                        group_names = sorted(groups_vals.keys())
                        group_means = {g: statistics.mean(groups_vals[g]) for g in group_names if groups_vals[g]}

                        if len(group_names) == 2:
                            g1, g2 = group_names
                            if groups_vals[g1] and groups_vals[g2]:
                                stat, p = mannwhitneyu(groups_vals[g1], groups_vals[g2], alternative='two-sided')
                                recon.alpha_group_tests.append({
                                    "metric": metric_name, "test": "Mann-Whitney U",
                                    "statistic": float(stat), "p": float(p),
                                    "group_means": group_means,
                                })
                        else:
                            all_groups = [groups_vals[g] for g in group_names if groups_vals[g]]
                            if len(all_groups) >= 2:
                                stat, p = kruskal(*all_groups)
                                recon.alpha_group_tests.append({
                                    "metric": metric_name, "test": "Kruskal-Wallis",
                                    "statistic": float(stat), "p": float(p),
                                    "group_means": group_means,
                                })
            except Exception:
                pass

    if recon.alpha_group_tests:
        _log("  📐 Alpha diversity 群間検定:")
        for t in recon.alpha_group_tests:
            sig = "***" if t['p'] < 0.001 else ("**" if t['p'] < 0.01 else ("*" if t['p'] < 0.05 else "ns"))
            _log(f"    {t['metric']}: p={t['p']:.4f} ({sig})")

    # ── Beta diversity 擬似 PERMANOVA ─────────────────────────────
    beta_paths = export_files.get("beta", [])
    for bp in beta_paths:
        metric_name = Path(bp).parent.name or Path(bp).stem
        recon.beta_metrics.append(metric_name)

        if group_map and len(set(group_map.values())) >= 2:
            try:
                header, rows = _safe_read_tsv(bp)
                sample_order = header[1:]
                n = len(sample_order)
                if n < 4:
                    continue

                # 距離行列を構築
                dm = {}
                for row in rows:
                    if len(row) < n + 1:
                        continue
                    sid_i = row[0]
                    for j, sid_j in enumerate(sample_order):
                        try:
                            dm[(sid_i, sid_j)] = float(row[j + 1])
                        except (ValueError, IndexError):
                            pass

                # 擬似 PERMANOVA: SS_between / SS_within の F 比を計算
                # 999回 permutation で p-value を推定
                import random
                groups_list = [group_map.get(s, "") for s in sample_order]
                valid = [i for i, g in enumerate(groups_list) if g]
                if len(valid) < 4:
                    continue

                valid_samples = [sample_order[i] for i in valid]
                valid_groups = [groups_list[i] for i in valid]
                unique_groups = sorted(set(valid_groups))
                if len(unique_groups) < 2:
                    continue

                def _pseudo_f(groups_perm):
                    k = len(set(groups_perm))
                    N = len(groups_perm)
                    if k < 2 or N < k + 1:
                        return 0.0
                    ss_within = 0.0
                    ss_total = 0.0
                    for i in range(len(valid_samples)):
                        for j in range(i + 1, len(valid_samples)):
                            d = dm.get((valid_samples[i], valid_samples[j]), 0)
                            d2 = d * d
                            ss_total += d2
                            if groups_perm[i] == groups_perm[j]:
                                ss_within += d2
                    ss_between = ss_total - ss_within
                    denom = ss_within / (N - k) if (N - k) > 0 else 1e-10
                    numer = ss_between / (k - 1) if (k - 1) > 0 else 0
                    return numer / denom if denom > 0 else 0.0

                observed_f = _pseudo_f(valid_groups)

                # 99 permutations (fast approximation)
                n_perm = 99
                count_ge = 0
                rng = random.Random(42)
                for _ in range(n_perm):
                    perm = valid_groups[:]
                    rng.shuffle(perm)
                    if _pseudo_f(perm) >= observed_f:
                        count_ge += 1
                p_value = (count_ge + 1) / (n_perm + 1)

                recon.beta_group_tests.append({
                    "metric": metric_name, "test": "PERMANOVA (99 perm)",
                    "pseudo_F": float(observed_f), "p": float(p_value),
                })
            except Exception:
                pass

    if recon.beta_group_tests:
        _log("  📐 Beta diversity 群間検定 (PERMANOVA):")
        for t in recon.beta_group_tests:
            sig = "***" if t['p'] < 0.001 else ("**" if t['p'] < 0.01 else ("*" if t['p'] < 0.05 else "ns"))
            _log(f"    {t['metric']}: pseudo-F={t['pseudo_F']:.2f}, p≈{t['p']:.3f} ({sig})")

    # ── Denoising stats ───────────────────────────────────────────
    den_paths = export_files.get("denoising", [])
    if den_paths:
        try:
            recon.has_denoising = True
            header, rows = _safe_read_tsv(den_paths[0])
            input_idx = next((i for i, h in enumerate(header) if "input" in h.lower()), None)
            nonchim_idx = next((i for i, h in enumerate(header)
                                if "non-chimeric" in h.lower() or "nonchimeric" in h.lower()), None)
            merged_idx = next((i for i, h in enumerate(header) if "merged" in h.lower()), None)
            filtered_idx = next((i for i, h in enumerate(header) if "filtered" in h.lower()), None)

            if input_idx is not None and nonchim_idx is not None:
                total_in = sum(int(r[input_idx]) for r in rows if len(r) > max(input_idx, nonchim_idx))
                total_out = sum(int(r[nonchim_idx]) for r in rows if len(r) > max(input_idx, nonchim_idx))
                if total_in > 0:
                    recon.denoising_pass_rate = total_out / total_in

                # キメラ率 = (merged - non_chimeric) / merged
                if merged_idx is not None:
                    total_merged = sum(int(r[merged_idx]) for r in rows if len(r) > merged_idx)
                    if total_merged > 0:
                        recon.chimera_rate = (total_merged - total_out) / total_merged

                # マージ率 = merged / filtered
                if merged_idx is not None and filtered_idx is not None:
                    total_filtered = sum(int(r[filtered_idx]) for r in rows if len(r) > filtered_idx)
                    if total_filtered > 0:
                        recon.merge_rate = total_merged / total_filtered

            _log(f"  🔬 Denoising: pass={recon.denoising_pass_rate:.1%}, "
                 f"chimera={recon.chimera_rate:.1%}, merge={recon.merge_rate:.1%}")
        except Exception:
            pass

    return recon


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: AI プランニング — 統計結果に基づくプラン立案
# ─────────────────────────────────────────────────────────────────────────────

def _build_registry_menu(
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
) -> str:
    """レジストリから選択可能な解析のメニューを構築"""
    available_cats = set(export_files.keys())
    lines = []
    for spec in ANALYSIS_REGISTRY:
        missing = [r for r in spec.requires if r not in available_cats and r != "metadata"]
        if missing:
            continue
        if spec.min_groups > 0 and design.n_groups < spec.min_groups:
            continue
        if design.n_groups > spec.max_groups:
            continue
        if spec.needs_timepoint and not design.is_longitudinal:
            continue
        if spec.needs_paired and not design.is_paired:
            continue
        lines.append(f'  - key="{spec.key}", phase="{spec.phase}", title="{spec.title}"')
    return "\n".join(lines)


def _build_planning_prompt(
    research_question: str,
    design: ExperimentalDesign,
    recon: DataRecon,
    registry_menu: str,
    profile: DataProfile,
    experiment_ctx: Optional[ExperimentContext] = None,
) -> str:
    """統計結果 + ドメイン知識 + 実験系知識を含むプランニングプロンプト"""
    stat_test = _select_stat_test(design)
    alpha_rec = recommend_alpha_test(profile)
    beta_rec = recommend_beta_test(profile)
    comp_rec = recommend_compositional_method(profile)
    power_ctx = estimate_power_context(profile)
    ord_recs = recommend_ordinations(profile)
    ord_text = "\n".join(
        f"  {i+1}. {r['method']} (score={r['score']}/10): {r['reason'][:80]}"
        for i, r in enumerate(ord_recs[:4])
    )

    return f"""You are an expert microbiome bioinformatician planning an analysis strategy.

## RESEARCH QUESTION
{research_question}

## EXPERIMENTAL DESIGN
{design.summary()}

## DATA RECONNAISSANCE — ACTUAL STATISTICAL RESULTS
{recon.summary()}

## DOMAIN KNOWLEDGE — METHOD RECOMMENDATIONS FOR THIS DATA

### Statistical Power Assessment
{power_ctx['guidance']}
Detectable effect size: {power_ctx['detectable_effect']}

### Recommended Alpha Diversity Test
{alpha_rec.test_name}: {alpha_rec.reason}
Interpretation: {alpha_rec.interpretation_guide[:200]}

### Recommended Beta Diversity Test
{beta_rec.test_name}: {beta_rec.reason}
CRITICAL: {beta_rec.assumptions[1] if len(beta_rec.assumptions) > 1 else 'Check dispersion'}

### Compositional Data Recommendation
Transform: {comp_rec['transform']} — {comp_rec['reason'][:150]}
Differential method: {comp_rec.get('differential_method', 'N/A')}
{chr(10).join(f"WARNING: {w[:120]}" for w in comp_rec.get('warnings', []))}

### Ordination Method Ranking (for this dataset)
{ord_text}

{"## EXPERIMENT-SPECIFIC KNOWLEDGE (from literature)" + chr(10) + experiment_ctx.summary() if experiment_ctx and experiment_ctx.experiment_types else ""}

## AVAILABLE ANALYSES (select from this menu)
{registry_menu}

## YOUR TASK
You have ACTUAL STATISTICAL TEST RESULTS, DOMAIN-SPECIFIC METHOD RECOMMENDATIONS,
and EXPERIMENT-SPECIFIC LITERATURE KNOWLEDGE above.
Use ALL of these to make informed decisions:

1. If alpha diversity shows significant group differences (p<0.05), prioritize:
   - Effect size plots to quantify the magnitude
   - Rarefaction curves to check if differences are due to sampling
   - Alpha trajectory if longitudinal data exists

2. If beta diversity shows significant separation (PERMANOVA p<0.05), prioritize:
   - Multiple ordination methods (PCoA, NMDS, t-SNE) to visualize separation
   - Beta dispersion to check if significance is due to location or spread
   - PERMANOVA detailed analysis

3. If specific genera show high variance between groups, prioritize:
   - Volcano plot / LEfSe to identify differentially abundant taxa
   - Genus-level violin plots for top differential genera
   - Indicator species analysis

4. If NO significant differences found, focus on:
   - Exploratory visualizations (composition, ordination)
   - Higher taxonomic levels (phylum/family instead of genus)
   - Consider if experimental design has enough statistical power

5. Always include quality checks first, and publication composites last.

Return a JSON array. Each element:
{{"key": "<analysis_key>", "reason": "<specific reason based on the DATA you see above>", "priority": <1-10>}}

IMPORTANT:
- Select 12-20 analyses (be selective based on what the DATA tells you)
- Your reasons must reference ACTUAL statistical values from the reconnaissance
- Example good reason: "Shannon p=0.003 indicates significant diversity difference; boxplot will visualize this"
- Example bad reason: "Standard analysis" (too generic, doesn't reference data)

Return ONLY the JSON array."""


def _parse_plan_json(content: str) -> list[dict]:
    """LLM の出力から JSON 配列を抽出"""
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return []


def ai_plan_analysis(
    research_question: str,
    design: ExperimentalDesign,
    recon: DataRecon,
    export_files: dict[str, list[str]],
    model: str,
    profile: Optional[DataProfile] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    experiment_ctx: Optional[ExperimentContext] = None,
) -> list[dict]:
    """LLM に統計結果 + ドメイン知識 + 実験系知識ベースのプランを立案させる"""
    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    if profile is None:
        profile = recon.to_profile(design)

    registry_menu = _build_registry_menu(design, export_files)
    prompt = _build_planning_prompt(
        research_question, design, recon, registry_menu, profile, experiment_ctx,
    )

    _log("  🧠 AI が統計結果 + ドメイン知識をもとにプランを立案中...")
    messages = [
        {
            "role": "system",
            "content": "You are a microbiome bioinformatics expert. Return ONLY a JSON array.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _agent.call_ollama(messages, model)
        plan_items = _parse_plan_json(response.get("content", ""))
        if plan_items:
            _log(f"  ✅ AI が {len(plan_items)} ステップのプランを立案")
            return plan_items
    except Exception as e:
        _log(f"  ⚠️ AI プランニング失敗: {e}")

    # ドメイン知識ベースのフォールバック
    _log("  🧬 フォールバック → microbiome_knowledge ドメイン知識に基づくプラン構築")
    available_keys = {s.key for s in ANALYSIS_REGISTRY}
    avail_cats = set(export_files.keys())
    # filter available_keys by data availability
    filtered_keys = set()
    for spec in ANALYSIS_REGISTRY:
        missing = [r for r in spec.requires if r not in avail_cats and r != "metadata"]
        if missing:
            continue
        if spec.min_groups > 0 and design.n_groups < spec.min_groups:
            continue
        if design.n_groups > spec.max_groups:
            continue
        if spec.needs_timepoint and not design.is_longitudinal:
            continue
        filtered_keys.add(spec.key)

    domain_decisions = build_domain_driven_plan(profile, research_question, filtered_keys)
    return [
        {"key": d.analysis_key, "reason": d.reason, "priority": d.priority,
         "domain_rationale": d.domain_rationale}
        for d in domain_decisions
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: 適応的リプランニング — 実際の統計結果で次を決める
# ─────────────────────────────────────────────────────────────────────────────

def _build_replan_prompt(
    research_question: str,
    design: ExperimentalDesign,
    completed_steps: list[dict],
    remaining_keys: list[str],
    registry_menu: str,
    recon: DataRecon,
) -> str:
    """発見に基づく調査計画を含むリプランプロンプト"""
    completed_text = ""
    for s in completed_steps[-6:]:
        status = "SUCCESS" if s["success"] else "FAILED"
        completed_text += f'\n  [{status}] {s["title"]}'
        if s.get("stdout_excerpt"):
            completed_text += f'\n    Statistical output: {s["stdout_excerpt"]}'
        if s.get("figures"):
            completed_text += f'\n    Figures: {len(s["figures"])} generated'

    remaining_text = "\n".join(f"  - {k}" for k in remaining_keys[:10])

    comparisons_text = ""
    if design.comparisons:
        comparisons_text = "\n## AVAILABLE COMPARISONS\n"
        for c in design.comparisons[:10]:
            comparisons_text += f"  - {c.summary_line()}\n"

    return f"""You are an investigative microbiome bioinformatician.
You don't just run analyses — you INVESTIGATE discoveries.

## RESEARCH QUESTION
{research_question}

## EXPERIMENTAL DESIGN
{design.summary()}

## INITIAL DATA RECONNAISSANCE
{recon.summary()}

## COMPLETED ANALYSES AND THEIR OUTPUTS
{completed_text}

## REMAINING PLANNED ANALYSES
{remaining_text}
{comparisons_text}
## ALL AVAILABLE ANALYSES (can add from menu)
{registry_menu}

## YOUR TASK — Think like a scientist investigating data

### 1. SKIP analyses no longer needed
Based on what you've learned from completed analyses.

### 2. ADD from menu
Existing analyses that should be added given findings.

### 3. INVESTIGATE — Custom follow-up investigations
This is the most important part. Based on discoveries, propose CUSTOM analyses
that are NOT in the menu. Think about:

- **Co-occurrence patterns**: If taxa A and B are strongly correlated, does this
  pattern hold within each treatment group? Does the correlation break down after treatment?
- **Differential taxa follow-up**: If Genus X is enriched in group A, what are its
  ecological partners? Do its co-occurring taxa also shift?
- **Cluster investigation**: If PCoA shows clear clusters, which taxa drive the separation?
  Compute taxa contributions to PC1/PC2.
- **Temporal patterns**: If a taxon changes over time in one group, does the same taxon
  change in the other group? At what rate?
- **Cross-comparison**: If effect is significant at timepoint X, is it also significant
  at timepoint Y? Is the effect growing or shrinking?
- **Ecological interpretation**: If diversity drops, is it driven by loss of rare taxa
  or expansion of dominant taxa? Decompose the change.

### 4. REORDER remaining analyses

Return JSON:
{{
  "skip": ["key1"],
  "add": [{{"key": "x", "reason": "reason from findings", "priority": 8}}],
  "investigate": [
    {{
      "title": "Short descriptive title",
      "hypothesis": "What you expect to find and why",
      "method": "Specific analysis method (e.g., Spearman correlation of taxon A vs B per group)",
      "code_instructions": "Detailed instructions for generating the Python code: what to read, compute, and plot",
      "priority": 9
    }}
  ],
  "reorder": [],
  "reasoning": "Chain of reasoning: what you discovered → what it implies → what to investigate next"
}}

Return ONLY JSON."""


def _parse_replan_json(content: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 結果データクラス + 実行エンジン
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AIDrivenStepResult:
    key: str
    title: str
    reason: str
    success: bool
    figures: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    code: str = ""


@dataclass
class AIDrivenResult:
    recon: DataRecon = field(default_factory=DataRecon)
    initial_plan: list[dict] = field(default_factory=list)
    results: list[AIDrivenStepResult] = field(default_factory=list)
    all_figures: list[str] = field(default_factory=list)
    replan_history: list[dict] = field(default_factory=list)
    investigations: list[dict] = field(default_factory=list)  # 発見駆動の追加調査
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_by_ai: int = 0
    added_by_ai: int = 0
    investigated_by_ai: int = 0


def _extract_stats_from_stdout(stdout: str) -> str:
    """stdout から統計的に重要な行を抽出（p-value, F-stat, R², etc.）"""
    if not stdout:
        return ""
    important_lines = []
    patterns = [
        r"p[\s_]*val", r"p\s*[=<>]", r"statistic", r"F[\s_]*stat",
        r"pseudo[\s_]*F", r"R[²2\s]", r"effect", r"significant",
        r"mann.*whitney", r"kruskal", r"wilcoxon", r"permanova",
        r"anosim", r"log2.*fold", r"FDR", r"q[\s_]*val",
        r"mean|median|std", r"enriched|depleted|differential",
    ]
    combined = re.compile("|".join(patterns), re.IGNORECASE)
    for line in stdout.split("\n"):
        line = line.strip()
        if line and combined.search(line):
            important_lines.append(line)
    # 最大10行、500文字に制限
    result = "\n".join(important_lines[:10])
    return result[:500]


def run_ai_driven(
    research_question: str,
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
    replan_interval: int = 4,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> AIDrivenResult:
    """AI 駆動解析モードのメイン実行エンジン。"""
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    result = AIDrivenResult()

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: データ偵察（実際の統計検定を実行）
    # ═══════════════════════════════════════════════════════════════════
    _log(f"\n{'═' * 56}")
    _log(f"  🔍 Phase 1: Data Reconnaissance + Statistical Testing")
    _log(f"{'═' * 56}")

    recon = run_data_recon(export_files, design, metadata_path, log_callback)
    result.recon = recon
    _log(f"\n{recon.summary()}\n")

    # DataProfile 構築
    profile = recon.to_profile(design)
    power_ctx = estimate_power_context(profile)
    _log(f"  📊 Statistical power: {power_ctx['power_level']} (n_min={power_ctx['n_per_group']})")
    _log(f"     {power_ctx['guidance'][:120]}")

    comp_rec = recommend_compositional_method(profile)
    if comp_rec["warnings"]:
        for w in comp_rec["warnings"]:
            _log(f"  ⚠️ {w[:120]}")
    _log(f"  🧬 Recommended transform: {comp_rec['transform']}")

    # 実験コンテキスト構築
    exp_ctx = build_experiment_context(research_question, research_question)
    if exp_ctx.experiment_types:
        _log(f"\n  🧪 Experiment type detected: {', '.join(et.name for et in exp_ctx.experiment_types)}")
        _log(f"  📚 Literature-based hypotheses: {len(exp_ctx.all_hypotheses)}")
        _log(f"  🔍 Key taxa to monitor: {', '.join(list(exp_ctx.taxa_to_watch.keys())[:6])}")
        for h in exp_ctx.all_hypotheses[:3]:
            _log(f"    [{h.expected_direction}] {h.hypothesis[:80]}")
        if exp_ctx.warnings:
            for w in exp_ctx.warnings[:2]:
                _log(f"  ⚠️ {w[:100]}")

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: AI プランニング（統計結果 + ドメイン知識 + 実験系知識）
    # ═══════════════════════════════════════════════════════════════════
    _log(f"\n{'═' * 56}")
    _log(f"  🧠 Phase 2: AI Planning (stats + domain + experiment knowledge)")
    _log(f"{'═' * 56}")

    plan_items = ai_plan_analysis(
        research_question, design, recon, export_files, model, profile,
        log_callback, exp_ctx,
    )
    result.initial_plan = plan_items

    spec_map: dict[str, AnalysisSpec] = {s.key: s for s in ANALYSIS_REGISTRY}
    plan_queue: list[dict] = [item for item in plan_items if item.get("key", "") in spec_map]

    _log(f"\n  📋 AI Analysis Plan ({len(plan_queue)} steps):")
    for i, item in enumerate(plan_queue, 1):
        reason = item.get("reason", "")[:80]
        _log(f"    {i:2d}. {item['key']}  — {reason}")
    _log("")

    # ═══════════════════════════════════════════════════════════════════
    # Phase 3: 適応的実行ループ
    # ═══════════════════════════════════════════════════════════════════
    _log(f"{'═' * 56}")
    _log(f"  🔄 Phase 3: Adaptive Execution Loop")
    _log(f"{'═' * 56}\n")

    completed_info: list[dict] = []
    registry_menu = _build_registry_menu(design, export_files)
    step_counter = 0

    while plan_queue:
        item = plan_queue.pop(0)
        key = item["key"]
        reason = item.get("reason", "")
        is_investigation = key.startswith("investigate_")
        investigation_data = item.get("_investigation", {})

        # レジストリ解析 or カスタム調査かで分岐
        if is_investigation:
            spec = None
            step_title = investigation_data.get("title", "Follow-up Investigation")
            step_counter += 1

            _log(f"{'─' * 48}")
            _log(f"  🔬 Step {step_counter}: INVESTIGATION — {step_title}")
            _log(f"  💡 Hypothesis: {investigation_data.get('hypothesis', '')[:120]}")
            _log(f"  🧪 Method: {investigation_data.get('method', '')[:120]}")
            _log(f"{'─' * 48}")

            # カスタム調査用のプロンプト構築
            prior_summaries = [
                f"{c['title']}: {'OK' if c['success'] else 'FAILED'}"
                + (f" | {c.get('stdout_excerpt', '')[:120]}" if c.get("stdout_excerpt") else "")
                for c in completed_info[-4:]
            ]

            files_text = ""
            for cat, paths in export_files.items():
                for p in paths:
                    files_text += f"  [{cat}] {p}\n"
            if metadata_path:
                files_text += f"  [metadata] {metadata_path}\n"

            meta_read = ""
            if metadata_path and design.primary_group:
                meta_read = (
                    f"meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')\n"
                    f"id_col = meta.columns[0]\nmeta = meta.set_index(id_col)\n"
                    f"group_col = '{design.primary_group}'\n"
                )

            prompt = f"""You are an investigative microbiome bioinformatician.
A previous analysis revealed something interesting. Now you need to investigate further.

## RESEARCH QUESTION
{research_question}

## EXPERIMENTAL DESIGN
{design.summary()}

## INVESTIGATION TASK
Title: {investigation_data.get('title', '')}
Hypothesis: {investigation_data.get('hypothesis', '')}
Method: {investigation_data.get('method', '')}
Detailed instructions: {investigation_data.get('code_instructions', '')}

## PREVIOUS FINDINGS
{chr(10).join(f'  - {s}' for s in prior_summaries)}

## AVAILABLE FILES
{files_text}

## HOW TO READ METADATA
{meta_read}

## FILE FORMATS
feature-table.tsv: skiprows=1, index_col=0 (row=ASV, col=sample)
taxonomy.tsv: index_col=0, cols: Taxon, Confidence. Genus: str.extract(r'g__([^;]+)')[0]
alpha TSV: index_col=0, 1 numeric col
beta TSV: square distance matrix, index_col=0

## CODE REQUIREMENTS
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt; import pandas as pd
FIGURE_DIR = r'{figure_dir}'; DPI = 150
import os; os.makedirs(FIGURE_DIR, exist_ok=True)
Save as: os.path.join(FIGURE_DIR, 'ai{step_counter:02d}_investigation_*.png')
PNG only. No plt.show(). Print key statistical results to stdout.

## IMPORTANT
- Print any p-values, correlations, or key findings to stdout
- This is an INVESTIGATION — include interpretation in print statements
- Example: print(f"Spearman r={{r:.3f}}, p={{p:.4f}} — {{interpretation}}")

Output ONLY Python code in ```python ... ```."""

            _log("  LLM にカスタム調査コードを依頼中...")
            messages = [
                {"role": "system", "content": "You are a microbiome analysis expert. Generate only Python code in ```python ... ```."},
                {"role": "user", "content": prompt},
            ]

        else:
            spec = spec_map.get(key)
            if not spec:
                continue
            step_title = spec.title
            step_counter += 1

            _log(f"{'─' * 48}")
            _log(f"  📊 Step {step_counter}: {step_title}")
            _log(f"  💡 Reason: {reason[:100]}")
            _log(f"{'─' * 48}")

            for pkg in spec.extra_packages:
                try:
                    __import__(pkg.replace("-", "_").split("[")[0])
                except ImportError:
                    approved = install_callback(pkg) if install_callback else True
                    if approved:
                        pip_install(pkg, log_callback)

            expanded = _expand_prompt(spec, design, metadata_path, research_question)
            analysis_step = AnalysisStep(
                step_num=step_counter, spec=spec, code_prompt=expanded,
                figure_prefix=f"ai{step_counter:02d}_{spec.key}",
            )

            prior_summaries = [
                f"{c['title']}: {'OK' if c['success'] else 'FAILED'}"
                + (f" | {c.get('stdout_excerpt', '')[:120]}" if c.get("stdout_excerpt") else "")
                for c in completed_info[-4:]
            ]
            prompt = _build_step_prompt(
                step=analysis_step, design=design, export_files=export_files,
                figure_dir=figure_dir, metadata_path=metadata_path,
                research_question=research_question, prior_results=prior_summaries,
            )

            _log("  LLM にコード生成を依頼中...")
            messages = [
                {"role": "system", "content": "You are a microbiome analysis expert. Generate only Python code in ```python ... ```."},
                {"role": "user", "content": prompt},
            ]

        try:
            response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"  ❌ Ollama エラー: {e}")
            result.results.append(AIDrivenStepResult(key=key, title=step_title, reason=reason, success=False, stderr=str(e)))
            result.failed_steps += 1
            completed_info.append({"key": key, "title": step_title, "success": False, "stdout_excerpt": "", "figures": []})
            continue

        code = _extract_code(response.get("content", ""))
        if not code:
            _log("  ⚠️ コード生成なし。スキップ。")
            result.results.append(AIDrivenStepResult(key=key, title=step_title, reason=reason, success=False, stderr="No code"))
            result.failed_steps += 1
            completed_info.append({"key": key, "title": step_title, "success": False, "stdout_excerpt": "", "figures": []})
            continue

        _log(f"  コード生成完了 ({len(code.splitlines())} 行)")

        last_code = code
        step_success = False
        new_figs: list[str] = []
        last_stdout = ""
        last_stderr = ""

        for attempt in range(max_retries):
            _log(f"  実行中... (試行 {attempt + 1}/{max_retries})")
            success, stdout, stderr, figs = _run_code(last_code, output_dir, figure_dir, log_callback)
            last_stdout = stdout
            last_stderr = stderr
            if success:
                step_success = True
                new_figs = figs
                break
            missing_pkg = _detect_missing_module(stderr)
            if missing_pkg:
                approved = install_callback(missing_pkg) if install_callback else True
                if approved and pip_install(missing_pkg, log_callback):
                    continue
            if attempt < max_retries - 1:
                _log("  LLM にコード修正を依頼中...")
                fix_msgs = messages + [
                    {"role": "assistant", "content": f"```python\n{last_code}\n```"},
                    {"role": "user", "content": f"Error:\n```\n{stderr[:1500]}\n```\nFix. Return complete script in ```python...```."},
                ]
                try:
                    fix_resp = _agent.call_ollama(fix_msgs, model)
                    fixed = _extract_code(fix_resp.get("content", ""))
                    if fixed:
                        last_code = fixed
                except Exception:
                    pass

        step_result = AIDrivenStepResult(
            key=key, title=step_title, reason=reason,
            success=step_success, figures=new_figs,
            stdout=last_stdout, stderr=last_stderr, code=last_code,
        )
        result.results.append(step_result)

        # stdout から統計結果を抽出
        stats_excerpt = _extract_stats_from_stdout(last_stdout)

        if step_success:
            result.completed_steps += 1
            result.all_figures.extend(new_figs)
            fig_names = [Path(f).name for f in new_figs]
            _log(f"  ✅ 成功 — 図: {fig_names}" if new_figs else "  ✅ 成功")
            if stats_excerpt:
                _log(f"  📈 統計結果: {stats_excerpt[:150]}")
        else:
            result.failed_steps += 1
            _log(f"  ❌ 失敗: {last_stderr[:200]}")

        completed_info.append({
            "key": key, "title": step_title, "success": step_success,
            "stdout_excerpt": stats_excerpt,
            "figures": [Path(f).name for f in new_figs],
        })

        # ── 適応的リプランニング ──────────────────────────────────
        if plan_queue and step_counter % replan_interval == 0:
            _log(f"\n  🔄 Adaptive Replanning (after step {step_counter})...")
            remaining_keys = [it["key"] for it in plan_queue]

            replan_prompt = _build_replan_prompt(
                research_question, design, completed_info,
                remaining_keys, registry_menu, recon,
            )
            replan_msgs = [
                {"role": "system", "content": "You are a microbiome bioinformatics expert. Return ONLY JSON."},
                {"role": "user", "content": replan_prompt},
            ]
            try:
                replan_resp = _agent.call_ollama(replan_msgs, model)
                replan_data = _parse_replan_json(replan_resp.get("content", ""))

                if replan_data:
                    result.replan_history.append(replan_data)
                    reasoning = replan_data.get("reasoning", "")
                    if reasoning:
                        _log(f"    🧠 AI reasoning: {reasoning[:150]}")

                    skip_keys = set(replan_data.get("skip", []))
                    if skip_keys:
                        before = len(plan_queue)
                        plan_queue = [it for it in plan_queue if it["key"] not in skip_keys]
                        skipped = before - len(plan_queue)
                        if skipped:
                            result.skipped_by_ai += skipped
                            _log(f"    ⏭ AI スキップ: {skip_keys}")

                    for add_item in replan_data.get("add", []):
                        add_key = add_item.get("key", "")
                        already_done = {c["key"] for c in completed_info}
                        already_queued = {it["key"] for it in plan_queue}
                        if add_key in spec_map and add_key not in already_done and add_key not in already_queued:
                            plan_queue.append(add_item)
                            result.added_by_ai += 1
                            _log(f"    ➕ AI 追加: {add_key} — {add_item.get('reason', '')[:80]}")

                    reorder = replan_data.get("reorder", [])
                    if reorder:
                        key_to_item = {it["key"]: it for it in plan_queue}
                        new_queue = []
                        for rk in reorder:
                            if rk in key_to_item:
                                new_queue.append(key_to_item.pop(rk))
                        new_queue.extend(key_to_item.values())
                        plan_queue = new_queue

                    # ── 発見駆動の追加調査（investigate）────────
                    for inv in replan_data.get("investigate", []):
                        inv_title = inv.get("title", "Follow-up investigation")
                        inv_hyp = inv.get("hypothesis", "")
                        inv_method = inv.get("method", "")
                        inv_code = inv.get("code_instructions", "")
                        inv_priority = inv.get("priority", 7)

                        if inv_title and inv_code:
                            # カスタム調査をキューに追加（特殊な key = "investigate_N"）
                            inv_key = f"investigate_{result.investigated_by_ai + 1}"
                            plan_queue.append({
                                "key": inv_key,
                                "reason": f"Discovery: {inv_hyp[:100]}",
                                "priority": inv_priority,
                                "_investigation": inv,  # 生データを保持
                            })
                            result.investigated_by_ai += 1
                            result.investigations.append(inv)
                            _log(f"    🔬 AI 調査追加: {inv_title}")
                            _log(f"       仮説: {inv_hyp[:100]}")
                            _log(f"       手法: {inv_method[:100]}")

                    _log(f"    📋 残りプラン: {len(plan_queue)} ステップ")
            except Exception as e:
                _log(f"    ⚠️ リプランニング失敗（続行）: {e}")

    _log(f"\n{'═' * 56}")
    _log(f"  🏁 AI-Driven Analysis Complete")
    _log(f"  ✅ Completed: {result.completed_steps}")
    _log(f"  ❌ Failed:    {result.failed_steps}")
    _log(f"  ⏭  Skipped by AI: {result.skipped_by_ai}")
    _log(f"  ➕ Added by AI:   {result.added_by_ai}")
    _log(f"  🔬 Investigations: {result.investigated_by_ai}")
    _log(f"  🔄 Replanning events: {len(result.replan_history)}")
    _log(f"  📊 Total figures: {len(result.all_figures)}")
    _log(f"{'═' * 56}\n")

    return result
