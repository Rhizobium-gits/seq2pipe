#!/usr/bin/env python3
"""
eval_mediator.py
================
解析ステップの結果を **実データから** 多軸スコアで定量評価し、
次元圧縮した状態ベクトルを LLM に渡して次の解析を判断させる仲介サーバー。

v2: stdout テキストマッチではなく、実際のファイル（TSV/距離行列/図）を
直接読み込んで定量評価する DataInspector 層を追加。

アーキテクチャ:
  ┌─────────────────────────────────────────────────┐
  │  DataInspector — 実データを直接読み込んで定量化   │
  │    feature-table.tsv → 豊度分布, スパース度      │
  │    alpha/*.tsv       → 群間検定 (U検定/KW)       │
  │    beta/*.tsv        → PERMANOVA, 分散均一性     │
  │    taxonomy.tsv      → 組成シフト, 特徴的菌属    │
  │    figures/*.png     → ファイルサイズ (生成確認)  │
  └───────────────┬─────────────────────────────────┘
                  ↓
  ┌─────────────────────────────────────────────────┐
  │  EvalMediator.evaluate()                         │
  │    DataInspector の定量値 + stdout 補助情報       │
  │    → 8 軸スコア (0.0–1.0)                        │
  │    → KnowledgeState に蓄積                       │
  └───────────────┬─────────────────────────────────┘
                  ↓
  ┌─────────────────────────────────────────────────┐
  │  KnowledgeState                                  │
  │    スコア行列 (n_steps × 8) → SVD 3主成分圧縮   │
  │    + 実データスナップショット (数値テーブル)      │
  └───────────────┬─────────────────────────────────┘
                  ↓
  ┌─────────────────────────────────────────────────┐
  │  build_decision_prompt()                         │
  │    圧縮スコア + 実データスナップショット          │
  │    → LLM が数値を見て次ステップを判断            │
  └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics as _stats
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════════════════════════
# 評価軸定義
# ═══════════════════════════════════════════════════════════════════════════════

EVAL_AXES = [
    "statistical_significance",
    "biological_relevance",
    "data_quality",
    "novelty",
    "actionability",
    "confidence",
    "reproducibility",
    "effect_magnitude",
]

DEFAULT_WEIGHTS = {
    "statistical_significance": 0.20,
    "biological_relevance":     0.18,
    "data_quality":             0.10,
    "novelty":                  0.12,
    "actionability":            0.15,
    "confidence":               0.08,
    "reproducibility":          0.07,
    "effect_magnitude":         0.10,
}


@dataclass
class StepScore:
    """1 ステップの多軸評価スコア"""
    step_key: str
    step_title: str
    axis_scores: dict[str, float] = field(default_factory=dict)
    composite_score: float = 0.0
    key_findings: list[str] = field(default_factory=list)
    suggested_followups: list[str] = field(default_factory=list)
    raw_evidence: dict[str, str] = field(default_factory=dict)
    data_snapshot: dict = field(default_factory=dict)  # 実データから抽出した数値

    def summary_line(self) -> str:
        top_axes = sorted(self.axis_scores.items(), key=lambda x: -x[1])[:3]
        axes_str = ", ".join(f"{a}={v:.2f}" for a, v in top_axes)
        return f"[{self.composite_score:.2f}] {self.step_title}: {axes_str}"


# ═══════════════════════════════════════════════════════════════════════════════
# 自前ノンパラメトリック検定（scipy 不要）
# ═══════════════════════════════════════════════════════════════════════════════

def _rank_data(values: list[float]) -> list[float]:
    """タイ補正付きランク変換"""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def _normal_cdf_approx(z: float) -> float:
    """標準正規分布 CDF の近似（Abramowitz & Stegun）"""
    if z < -8:
        return 0.0
    if z > 8:
        return 1.0
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1
    if z < 0:
        sign = -1
        z = -z
    t = 1.0 / (1.0 + p * z)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z / 2)
    return 0.5 * (1.0 + sign * y)


def _mann_whitney_u(x: list[float], y: list[float]) -> tuple[float, float]:
    """Mann-Whitney U 検定（正規近似、scipy 不要）"""
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0, 1.0
    combined = x + y
    ranks = _rank_data(combined)
    r1 = sum(ranks[:nx])
    u1 = r1 - nx * (nx + 1) / 2
    u2 = nx * ny - u1
    U = min(u1, u2)
    # 正規近似
    mu = nx * ny / 2
    n = nx + ny
    # タイ補正
    from collections import Counter
    tied_groups = Counter(combined)
    tie_correction = sum(t ** 3 - t for t in tied_groups.values() if t > 1)
    sigma = math.sqrt(nx * ny / 12 * ((n + 1) - tie_correction / (n * (n - 1))))
    if sigma == 0:
        return U, 1.0
    z = (U - mu) / sigma
    p = 2 * _normal_cdf_approx(-abs(z))  # two-sided
    return U, max(p, 1e-10)


def _kruskal_wallis(groups: list[list[float]]) -> tuple[float, float]:
    """Kruskal-Wallis H 検定（chi-squared 近似、scipy 不要）"""
    k = len(groups)
    if k < 2:
        return 0.0, 1.0
    all_vals = []
    group_ids = []
    for i, g in enumerate(groups):
        all_vals.extend(g)
        group_ids.extend([i] * len(g))
    N = len(all_vals)
    if N < 3:
        return 0.0, 1.0

    ranks = _rank_data(all_vals)

    # 群ごとのランク合計
    group_rank_sums = [0.0] * k
    group_ns = [len(g) for g in groups]
    idx = 0
    for i, g in enumerate(groups):
        for _ in g:
            group_rank_sums[i] += ranks[idx]
            idx += 1

    # H 統計量
    H = 12.0 / (N * (N + 1)) * sum(
        group_rank_sums[i] ** 2 / group_ns[i]
        for i in range(k) if group_ns[i] > 0
    ) - 3 * (N + 1)

    # タイ補正
    from collections import Counter
    tied = Counter(all_vals)
    tie_sum = sum(t ** 3 - t for t in tied.values() if t > 1)
    if tie_sum > 0:
        H /= (1 - tie_sum / (N ** 3 - N))

    # p 値: chi-squared 分布 (df=k-1) の近似
    df = k - 1
    p = _chi2_survival(H, df)
    return H, p


def _chi2_survival(x: float, df: int) -> float:
    """chi-squared 分布の生存関数 P(X > x) の近似（Wilson-Hilferty）"""
    if x <= 0 or df <= 0:
        return 1.0
    # Wilson-Hilferty 変換: chi2 → 正規近似
    z = ((x / df) ** (1.0 / 3) - (1 - 2.0 / (9 * df))) / math.sqrt(2.0 / (9 * df))
    return 1.0 - _normal_cdf_approx(z)


# ═══════════════════════════════════════════════════════════════════════════════
# DataInspector — 実データを直接読み込んで定量評価する層
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_read_tsv(path: str, skip_comment: bool = False) -> tuple[list[str], list[list[str]]]:
    """TSV を安全に読み込む。先頭タブ（index列名なし）も正しく処理"""
    rows = []
    header = []
    try:
        with open(path) as f:
            for line in f:
                # 末尾の改行・スペースのみ除去（先頭タブは保持）
                line = line.rstrip()
                if not line:
                    continue
                if skip_comment and line.lstrip().startswith("# "):
                    continue
                if not header:
                    header = line.split("\t")
                    continue
                if line.lstrip().startswith("#q2:"):
                    continue
                rows.append(line.split("\t"))
    except Exception:
        pass
    return header, rows


@dataclass
class DataSnapshot:
    """実データから抽出した定量的スナップショット"""
    # Feature table
    n_samples: int = 0
    n_asvs: int = 0
    total_reads: int = 0
    reads_per_sample: dict[str, int] = field(default_factory=dict)
    sparsity: float = 0.0
    sample_evenness: dict[str, float] = field(default_factory=dict)  # sample → Pielou's J

    # Alpha diversity (実測値)
    alpha_values: dict[str, dict[str, float]] = field(default_factory=dict)
    # metric → {sample: value}
    alpha_group_tests: list[dict] = field(default_factory=list)
    # [{"metric": "shannon", "test": "Mann-Whitney", "U": 2.0, "p": 0.003, "effect_size": 0.85, "group_means": {...}}]

    # Beta diversity (実測値)
    beta_group_separation: dict[str, float] = field(default_factory=dict)
    # metric → pseudo-F
    beta_pvalues: dict[str, float] = field(default_factory=dict)
    beta_within_vs_between: dict[str, dict] = field(default_factory=dict)
    # metric → {"within_mean": 0.3, "between_mean": 0.6, "ratio": 2.0}

    # Taxonomy (実測値)
    phylum_abundances: dict[str, float] = field(default_factory=dict)   # phylum → relative %
    genus_abundances: dict[str, float] = field(default_factory=dict)    # genus → relative %
    group_differential_genera: list[dict] = field(default_factory=list)
    # [{"genus": "X", "group_a_mean": 10.2, "group_b_mean": 1.3, "fold_change": 7.8, "direction": "enriched_in_a"}]
    composition_shift: float = 0.0  # 群間の Bray-Curtis 組成変化量

    # 生成された図
    figure_paths: list[str] = field(default_factory=list)
    figure_sizes_kb: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """シリアライズ可能な dict"""
        return {
            "n_samples": self.n_samples,
            "n_asvs": self.n_asvs,
            "sparsity": round(self.sparsity, 3),
            "alpha_tests": self.alpha_group_tests,
            "beta_F": {k: round(v, 2) for k, v in self.beta_group_separation.items()},
            "beta_p": {k: round(v, 4) for k, v in self.beta_pvalues.items()},
            "beta_separation_ratio": {
                k: round(v.get("ratio", 0), 2)
                for k, v in self.beta_within_vs_between.items()
            },
            "top_phyla": dict(sorted(self.phylum_abundances.items(), key=lambda x: -x[1])[:5]),
            "differential_genera": self.group_differential_genera[:5],
            "composition_shift": round(self.composition_shift, 3),
            "n_figures": len(self.figure_paths),
        }

    def text_for_llm(self) -> str:
        """LLM に渡すための構造化テキスト"""
        lines = ["### ACTUAL DATA (read from files, not stdout)"]

        if self.alpha_group_tests:
            lines.append("\nAlpha diversity (computed from raw values):")
            for t in self.alpha_group_tests:
                means = t.get("group_means", {})
                means_str = ", ".join(f"{g}={v:.3f}" for g, v in means.items())
                lines.append(
                    f"  {t['metric']}: {t['test']} U={t.get('U', '?')}, "
                    f"p={t['p']:.4g}, effect_size={t.get('effect_size', 0):.2f} "
                    f"| means: {means_str}"
                )

        if self.beta_pvalues:
            lines.append("\nBeta diversity (computed from distance matrices):")
            for metric in self.beta_pvalues:
                F = self.beta_group_separation.get(metric, 0)
                p = self.beta_pvalues[metric]
                ratio_info = self.beta_within_vs_between.get(metric, {})
                lines.append(
                    f"  {metric}: pseudo-F={F:.2f}, p={p:.4g}, "
                    f"between/within={ratio_info.get('ratio', 0):.2f} "
                    f"(within_mean={ratio_info.get('within_mean', 0):.3f}, "
                    f"between_mean={ratio_info.get('between_mean', 0):.3f})"
                )

        if self.group_differential_genera:
            lines.append("\nDifferential genera (computed from feature table):")
            for g in self.group_differential_genera[:8]:
                lines.append(
                    f"  {g['genus']}: {g['direction']} "
                    f"(fold_change={g['fold_change']:.1f}x, "
                    f"means: {g.get('group_a_mean', 0):.1f}% vs {g.get('group_b_mean', 0):.1f}%)"
                )

        if self.composition_shift > 0:
            lines.append(f"\nOverall composition shift (Bray-Curtis): {self.composition_shift:.3f}")

        if not self.alpha_group_tests and not self.beta_pvalues and not self.group_differential_genera:
            lines.append("  (no group-level data available for this step)")

        return "\n".join(lines)


class DataInspector:
    """
    実データファイルを直接読み込んで定量評価する。
    stdout のテキストマッチではなく、TSV/距離行列を Python でパースして
    統計検定を自前で実行する。
    """

    def __init__(
        self,
        export_files: dict[str, list[str]],
        metadata_path: str = "",
        group_column: str = "",
    ):
        self.export_files = export_files
        self.metadata_path = metadata_path
        self.group_column = group_column

        # メタデータからグループマッピングを構築
        self.group_map: dict[str, str] = {}
        self._load_group_map()

        # Feature table キャッシュ（何度も読まなくて良いように）
        self._ft_matrix: Optional[dict[str, dict[str, float]]] = None
        self._sample_reads: Optional[dict[str, int]] = None
        self._taxonomy: Optional[dict[str, str]] = None  # asv → genus
        self._phylum: Optional[dict[str, str]] = None

    def _load_group_map(self):
        if not self.metadata_path or not self.group_column:
            return
        try:
            header, rows = _safe_read_tsv(self.metadata_path)
            grp_idx = None
            for i, col in enumerate(header):
                if col == self.group_column:
                    grp_idx = i
                    break
            if grp_idx is not None:
                for row in rows:
                    if row and len(row) > grp_idx:
                        self.group_map[row[0]] = row[grp_idx]
        except Exception:
            pass

    def _ensure_feature_table(self):
        """Feature table を遅延読み込み"""
        if self._ft_matrix is not None:
            return
        self._ft_matrix = {}
        self._sample_reads = {}

        ft_paths = self.export_files.get("feature_table", [])
        if not ft_paths:
            return
        header, rows = _safe_read_tsv(ft_paths[0], skip_comment=True)
        if not header:
            return
        sample_ids = header[1:]
        self._sample_reads = {s: 0 for s in sample_ids}
        for row in rows:
            if len(row) < 2:
                continue
            asv_id = row[0]
            self._ft_matrix[asv_id] = {}
            for j, sid in enumerate(sample_ids):
                if j + 1 < len(row):
                    try:
                        val = float(row[j + 1])
                        self._sample_reads[sid] = self._sample_reads.get(sid, 0) + int(val)
                        self._ft_matrix[asv_id][sid] = val
                    except (ValueError, IndexError):
                        pass

    def _ensure_taxonomy(self):
        """Taxonomy を遅延読み込み"""
        if self._taxonomy is not None:
            return
        self._taxonomy = {}
        self._phylum = {}
        tax_paths = self.export_files.get("taxonomy", [])
        if not tax_paths:
            return
        try:
            with open(tax_paths[0]) as f:
                f.readline()  # skip header
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 2:
                        continue
                    asv_id = parts[0]
                    taxon = parts[1]
                    m_g = re.search(r"g__([^;]+)", taxon)
                    m_p = re.search(r"p__([^;]+)", taxon)
                    if m_g:
                        g = m_g.group(1).strip()
                        if g and g != "__":
                            self._taxonomy[asv_id] = g
                    if m_p:
                        p = m_p.group(1).strip()
                        if p and p != "__":
                            self._phylum[asv_id] = p
        except Exception:
            pass

    def inspect(self, step_key: str, figure_paths: list[str]) -> DataSnapshot:
        """
        ステップの種類に応じて実データを読み込み、定量スナップショットを返す。
        これが stdout テキストマッチとの決定的な違い。
        """
        snap = DataSnapshot()
        snap.figure_paths = figure_paths
        for fp in figure_paths:
            try:
                snap.figure_sizes_kb.append(os.path.getsize(fp) / 1024)
            except OSError:
                pass

        # ステップカテゴリに応じてデータ読み込み
        if "alpha" in step_key:
            self._inspect_alpha(snap)
        if "beta" in step_key or "pcoa" in step_key or "nmds" in step_key or "permanova" in step_key:
            self._inspect_beta(snap)
        if "taxonomy" in step_key or "differential" in step_key or "volcano" in step_key or "lefse" in step_key:
            self._inspect_taxonomy(snap)
        if "qc" in step_key or "denoising" in step_key or "rarefaction" in step_key:
            self._inspect_quality(snap)

        # 常に基本情報は取る
        self._inspect_basic(snap)

        return snap

    def _inspect_basic(self, snap: DataSnapshot):
        self._ensure_feature_table()
        if self._ft_matrix:
            snap.n_asvs = len(self._ft_matrix)
        if self._sample_reads:
            snap.n_samples = len(self._sample_reads)
            snap.reads_per_sample = dict(self._sample_reads)
            snap.total_reads = sum(self._sample_reads.values())
            # スパース度
            if self._ft_matrix and snap.n_samples > 0:
                total_cells = len(self._ft_matrix) * snap.n_samples
                zero_cells = 0
                sample_ids = list(self._sample_reads.keys())
                for asv_counts in self._ft_matrix.values():
                    for sid in sample_ids:
                        if asv_counts.get(sid, 0) == 0:
                            zero_cells += 1
                snap.sparsity = zero_cells / total_cells if total_cells > 0 else 0

    def _inspect_alpha(self, snap: DataSnapshot):
        """Alpha diversity TSV を直接読み込んで群間検定を実行"""
        alpha_paths = self.export_files.get("alpha", [])
        if not alpha_paths or not self.group_map:
            return

        groups = sorted(set(self.group_map.values()))
        if len(groups) < 2:
            return

        for ap in alpha_paths:
            metric_name = Path(ap).parent.name or Path(ap).stem
            header, rows = _safe_read_tsv(ap)

            # QIIME2 alpha TSV: ヘッダが "\tmetric_name" (index列名が空) の場合がある
            # → header = ['', 'shannon_entropy'] or header = ['shannon_entropy'] (1列に見える)
            # どちらの場合でも、rows の各行は [sample_id, value] になる

            # サンプルごとの値を読み込み
            sample_vals: dict[str, float] = {}
            for row in rows:
                if len(row) >= 2:
                    try:
                        sample_vals[row[0]] = float(row[1])
                    except (ValueError, IndexError):
                        pass
                elif len(row) == 1 and len(header) >= 1:
                    # ヘッダ行が index 列を含んでいた場合 (header=[sample_id, val])
                    pass

            if not sample_vals:
                continue

            snap.alpha_values[metric_name] = sample_vals

            # 群別に分ける
            group_vals: dict[str, list[float]] = {g: [] for g in groups}
            for sid, val in sample_vals.items():
                g = self.group_map.get(sid, "")
                if g in group_vals:
                    group_vals[g].append(val)

            # 全群にデータがあるか
            if not all(group_vals[g] for g in groups):
                continue

            group_means = {g: _stats.mean(vals) for g, vals in group_vals.items()}

            if len(groups) == 2:
                g1, g2 = groups
                v1, v2 = group_vals[g1], group_vals[g2]
                stat, p = _mann_whitney_u(v1, v2)

                # Cliff's delta
                n1, n2 = len(v1), len(v2)
                dominance = sum(
                    (1 if a > b else -1 if a < b else 0)
                    for a in v1 for b in v2
                )
                cliffs_d = abs(dominance / (n1 * n2)) if n1 * n2 > 0 else 0

                snap.alpha_group_tests.append({
                    "metric": metric_name,
                    "test": "Mann-Whitney U",
                    "U": float(stat),
                    "p": float(p),
                    "effect_size": cliffs_d,
                    "group_means": group_means,
                    "group_medians": {
                        g: _stats.median(vals) for g, vals in group_vals.items()
                    },
                    "group_n": {g: len(vals) for g, vals in group_vals.items()},
                })
            else:
                all_groups = [group_vals[g] for g in groups]
                stat, p = _kruskal_wallis(all_groups)
                N = sum(len(v) for v in all_groups)
                k = len(groups)
                eta_sq = (stat - k + 1) / (N - k) if (N - k) > 0 else 0
                snap.alpha_group_tests.append({
                    "metric": metric_name,
                    "test": "Kruskal-Wallis",
                    "H": float(stat),
                    "p": float(p),
                    "effect_size": max(0, eta_sq),
                    "group_means": group_means,
                    "group_n": {g: len(vals) for g, vals in group_vals.items()},
                })

    def _inspect_beta(self, snap: DataSnapshot):
        """距離行列 TSV を直接読み込んで群間分離度を計算"""
        beta_paths = self.export_files.get("beta", [])
        if not beta_paths or not self.group_map:
            return

        groups = sorted(set(self.group_map.values()))
        if len(groups) < 2:
            return

        for bp in beta_paths:
            metric_name = Path(bp).parent.name or Path(bp).stem
            header, rows = _safe_read_tsv(bp)
            sample_order = header[1:]
            n = len(sample_order)
            if n < 4:
                continue

            # 距離行列を構築
            dm: dict[tuple[str, str], float] = {}
            for row in rows:
                if len(row) < n + 1:
                    continue
                sid_i = row[0]
                for j, sid_j in enumerate(sample_order):
                    try:
                        dm[(sid_i, sid_j)] = float(row[j + 1])
                    except (ValueError, IndexError):
                        pass

            # 群内距離 vs 群間距離
            valid_samples = [s for s in sample_order if s in self.group_map]
            within_dists = []
            between_dists = []
            for i, si in enumerate(valid_samples):
                for j, sj in enumerate(valid_samples):
                    if i >= j:
                        continue
                    d = dm.get((si, sj), dm.get((sj, si), None))
                    if d is None:
                        continue
                    gi = self.group_map[si]
                    gj = self.group_map[sj]
                    if gi == gj:
                        within_dists.append(d)
                    else:
                        between_dists.append(d)

            if within_dists and between_dists:
                within_mean = _stats.mean(within_dists)
                between_mean = _stats.mean(between_dists)
                ratio = between_mean / within_mean if within_mean > 0 else 0
                snap.beta_within_vs_between[metric_name] = {
                    "within_mean": within_mean,
                    "between_mean": between_mean,
                    "ratio": ratio,
                    "within_std": _stats.stdev(within_dists) if len(within_dists) > 1 else 0,
                    "between_std": _stats.stdev(between_dists) if len(between_dists) > 1 else 0,
                }

            # 擬似 PERMANOVA
            import random
            valid_groups = [self.group_map[s] for s in valid_samples]
            unique_groups = sorted(set(valid_groups))
            if len(unique_groups) < 2 or len(valid_samples) < 4:
                continue

            def _pseudo_f(groups_perm):
                k = len(set(groups_perm))
                N = len(groups_perm)
                if k < 2 or N < k + 1:
                    return 0.0
                ss_within = 0.0
                ss_total = 0.0
                for ii in range(len(valid_samples)):
                    for jj in range(ii + 1, len(valid_samples)):
                        d = dm.get((valid_samples[ii], valid_samples[jj]),
                                   dm.get((valid_samples[jj], valid_samples[ii]), 0))
                        d2 = d * d
                        ss_total += d2
                        if groups_perm[ii] == groups_perm[jj]:
                            ss_within += d2
                ss_between = ss_total - ss_within
                denom = ss_within / (N - k) if (N - k) > 0 else 1e-10
                numer = ss_between / (k - 1) if (k - 1) > 0 else 0
                return numer / denom if denom > 0 else 0.0

            observed_f = _pseudo_f(valid_groups)
            snap.beta_group_separation[metric_name] = observed_f

            # 199 permutations
            n_perm = 199
            count_ge = 0
            rng = random.Random(42)
            for _ in range(n_perm):
                perm = valid_groups[:]
                rng.shuffle(perm)
                if _pseudo_f(perm) >= observed_f:
                    count_ge += 1
            p_value = (count_ge + 1) / (n_perm + 1)
            snap.beta_pvalues[metric_name] = p_value

    def _inspect_taxonomy(self, snap: DataSnapshot):
        """Taxonomy + Feature table から群間組成差を直接計算"""
        self._ensure_feature_table()
        self._ensure_taxonomy()
        if not self._ft_matrix or not self._taxonomy:
            return

        sample_ids = list(self._sample_reads.keys()) if self._sample_reads else []
        if not sample_ids:
            return

        # 全体の属レベル相対豊度
        genus_total: dict[str, float] = {}
        phylum_total: dict[str, float] = {}
        grand_total = 0.0
        for asv_id, sample_counts in self._ft_matrix.items():
            total = sum(sample_counts.values())
            grand_total += total
            g = self._taxonomy.get(asv_id, "Unknown")
            genus_total[g] = genus_total.get(g, 0) + total
            p = self._phylum.get(asv_id, "Unknown") if self._phylum else "Unknown"
            phylum_total[p] = phylum_total.get(p, 0) + total

        if grand_total > 0:
            snap.phylum_abundances = {
                name: round(count / grand_total * 100, 2)
                for name, count in sorted(phylum_total.items(), key=lambda x: -x[1])[:10]
            }
            snap.genus_abundances = {
                name: round(count / grand_total * 100, 2)
                for name, count in sorted(genus_total.items(), key=lambda x: -x[1])[:15]
            }

        # 群別の属レベル相対豊度 → 差分計算
        if not self.group_map:
            return

        groups = sorted(set(self.group_map.values()))
        if len(groups) < 2:
            return

        from collections import defaultdict
        grp_genus_abd: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        grp_total: dict[str, float] = defaultdict(float)

        for asv_id, sample_counts in self._ft_matrix.items():
            g = self._taxonomy.get(asv_id, "Unknown")
            for sid, cnt in sample_counts.items():
                grp = self.group_map.get(sid, "")
                if grp:
                    grp_genus_abd[grp][g] += cnt
                    grp_total[grp] += cnt

        # 群間で最も差が大きい属を特定
        all_genera = set()
        for grp in groups:
            all_genera.update(grp_genus_abd[grp].keys())

        diffs = []
        for genus in all_genera:
            if genus in ("Unknown", "", "__"):
                continue
            rel_abds = {}
            for grp in groups:
                tot = grp_total[grp] if grp_total[grp] > 0 else 1
                rel_abds[grp] = grp_genus_abd[grp].get(genus, 0) / tot * 100

            max_abd = max(rel_abds.values())
            min_abd = min(rel_abds.values())
            if max_abd < 0.1:  # 全群で 0.1% 未満は無視
                continue

            fold = max_abd / min_abd if min_abd > 0.01 else max_abd / 0.01
            max_grp = max(rel_abds, key=rel_abds.get)
            min_grp = min(rel_abds, key=rel_abds.get)

            diffs.append({
                "genus": genus,
                "group_a": max_grp,
                "group_a_mean": round(rel_abds[max_grp], 2),
                "group_b": min_grp,
                "group_b_mean": round(rel_abds[min_grp], 2),
                "fold_change": round(fold, 1),
                "abs_diff": round(max_abd - min_abd, 2),
                "direction": f"enriched_in_{max_grp}",
            })

        diffs.sort(key=lambda x: -x["abs_diff"])
        snap.group_differential_genera = diffs[:10]

        # 群間の組成シフト（全属の Bray-Curtis 風距離）
        if len(groups) == 2:
            g1, g2 = groups
            all_g = list(all_genera)
            v1 = [grp_genus_abd[g1].get(g, 0) / (grp_total[g1] or 1) for g in all_g]
            v2 = [grp_genus_abd[g2].get(g, 0) / (grp_total[g2] or 1) for g in all_g]
            num = sum(abs(a - b) for a, b in zip(v1, v2))
            den = sum(a + b for a, b in zip(v1, v2))
            snap.composition_shift = num / den if den > 0 else 0

    def _inspect_quality(self, snap: DataSnapshot):
        """Denoising stats を直接読み込む"""
        den_paths = self.export_files.get("denoising", [])
        if not den_paths:
            return
        # 基本的な読み込みは inspect_basic でカバーされるので
        # ここでは evenness を計算
        self._ensure_feature_table()
        if not self._ft_matrix or not self._sample_reads:
            return
        sample_ids = list(self._sample_reads.keys())
        for sid in sample_ids:
            counts = [self._ft_matrix[asv].get(sid, 0) for asv in self._ft_matrix]
            total_c = sum(counts)
            if total_c == 0:
                continue
            nonzero = [c for c in counts if c > 0]
            s = len(nonzero)
            if s <= 1:
                snap.sample_evenness[sid] = 0.0
                continue
            h = -sum((c / total_c) * math.log(c / total_c) for c in nonzero)
            j = h / math.log(s)
            snap.sample_evenness[sid] = j


# ═══════════════════════════════════════════════════════════════════════════════
# スコアリングエンジン — DataSnapshot から定量スコアを計算
# ═══════════════════════════════════════════════════════════════════════════════

def _score_from_data(
    snap: DataSnapshot,
    step_key: str,
    stdout: str,
    stderr: str,
    success: bool,
    n_samples: int,
    min_group_size: int,
    prior_scores: list[StepScore],
) -> tuple[dict[str, float], dict[str, str], list[str], list[str]]:
    """
    DataSnapshot の実測値からスコアを計算。
    stdout は補助情報としてのみ使用。
    """
    axis_scores = {}
    evidence = {}
    findings = []
    followups = []

    # ── 1. statistical_significance ──
    # 実データの検定結果から直接計算
    p_values = []
    for t in snap.alpha_group_tests:
        p_values.append(t["p"])
    for metric, p in snap.beta_pvalues.items():
        p_values.append(p)

    if p_values:
        min_p = min(p_values)
        # p → score: log scale, p=0.001→0.9, p=0.01→0.7, p=0.05→0.5
        sig_score = min(1.0, max(0.0, -math.log10(max(min_p, 1e-10)) / 4.0))
        n_sig = sum(1 for p in p_values if p < 0.05)
        evidence["statistical_significance"] = (
            f"min_p={min_p:.4g} ({n_sig}/{len(p_values)} sig) [from raw data]"
        )
        if min_p < 0.05:
            findings.append(f"Significant result: p={min_p:.4g} (from direct computation)")
    elif success:
        sig_score = 0.3
        evidence["statistical_significance"] = "no group tests computed (data may lack groups)"
    else:
        sig_score = 0.0
        evidence["statistical_significance"] = "step failed"
    axis_scores["statistical_significance"] = sig_score

    # ── 2. biological_relevance ──
    bio_score = 0.2
    if snap.group_differential_genera:
        # 大きな fold change = 生物学的に意味がある
        max_fc = max(g["fold_change"] for g in snap.group_differential_genera)
        max_diff = max(g["abs_diff"] for g in snap.group_differential_genera)
        bio_score = min(1.0, max_fc / 10.0 + max_diff / 20.0)

        top_genus = snap.group_differential_genera[0]
        findings.append(
            f"{top_genus['genus']}: {top_genus['fold_change']}x enriched in "
            f"{top_genus['group_a']} ({top_genus['group_a_mean']}% vs {top_genus['group_b_mean']}%)"
        )
        evidence["biological_relevance"] = (
            f"max_fold_change={max_fc:.1f}x, max_abs_diff={max_diff:.1f}% [from feature table]"
        )

        # 既知の重要菌属にヒットしているか
        important_genera = {
            "Faecalibacterium", "Lactobacillus", "Bacteroides",
            "Enterococcus", "Escherichia", "Akkermansia",
            "Clostridioides", "Roseburia", "Bifidobacterium",
        }
        hits = [g["genus"] for g in snap.group_differential_genera if g["genus"] in important_genera]
        if hits:
            bio_score = min(1.0, bio_score + 0.15)
            findings.append(f"Key taxa differential: {', '.join(hits)}")
    elif snap.composition_shift > 0:
        bio_score = min(1.0, snap.composition_shift * 2)
        evidence["biological_relevance"] = f"composition_shift={snap.composition_shift:.3f} [Bray-Curtis]"
    else:
        evidence["biological_relevance"] = "no differential data available"

    # 特定ステップにボーナス
    bio_keys = {"taxonomy_barplot", "differential_volcano", "lefse", "indicator_species"}
    if step_key in bio_keys:
        bio_score = min(1.0, bio_score + 0.15)
    axis_scores["biological_relevance"] = bio_score

    # ── 3. data_quality ──
    if not success:
        qual_score = 0.1
        evidence["data_quality"] = "execution failed"
    else:
        qual_score = 0.7
        issues = []
        if snap.sparsity > 0.9:
            qual_score -= 0.2
            issues.append(f"very_sparse={snap.sparsity:.0%}")
        elif snap.sparsity > 0.7:
            qual_score -= 0.1
            issues.append(f"sparse={snap.sparsity:.0%}")

        if snap.reads_per_sample:
            reads = list(snap.reads_per_sample.values())
            if reads:
                cv = _stats.stdev(reads) / _stats.mean(reads) if len(reads) > 1 and _stats.mean(reads) > 0 else 0
                if cv > 0.5:
                    qual_score -= 0.1
                    issues.append(f"read_depth_CV={cv:.2f}")

        if snap.sample_evenness:
            mean_j = _stats.mean(snap.sample_evenness.values())
            if mean_j < 0.3:
                qual_score -= 0.1
                issues.append(f"low_evenness={mean_j:.2f}")

        evidence["data_quality"] = "; ".join(issues) if issues else "no quality issues [from data]"
    axis_scores["data_quality"] = max(0.1, min(1.0, qual_score))

    # ── 4. novelty ──
    novel_score = 0.3
    if prior_scores and snap.alpha_group_tests:
        # 前のステップと一貫しない結果 = 新規性が高い
        prev_sigs = [
            s.axis_scores.get("statistical_significance", 0) > 0.5
            for s in prior_scores
        ]
        current_sig = sig_score > 0.5
        if prev_sigs and (all(prev_sigs) != current_sig):
            novel_score = 0.7
            findings.append("Inconsistent with prior results — unexpected pattern")

    if snap.group_differential_genera:
        # 非常に大きな fold change は予想外の可能性
        max_fc = max(g["fold_change"] for g in snap.group_differential_genera)
        if max_fc > 20:
            novel_score = max(novel_score, 0.8)
            findings.append(f"Extreme fold change: {max_fc:.0f}x — potential novel finding")

    evidence["novelty"] = f"score={novel_score:.2f} [data-derived]"
    axis_scores["novelty"] = novel_score

    # ── 5. actionability ──
    action_score = 0.3
    if sig_score > 0.5:
        action_score += 0.2
        followups.append("Significant result → add effect size quantification")
    if snap.group_differential_genera and len(snap.group_differential_genera) >= 3:
        action_score += 0.2
        followups.append(f"{len(snap.group_differential_genera)} differential genera → add functional prediction")
    if snap.beta_within_vs_between:
        for m, info in snap.beta_within_vs_between.items():
            if info.get("ratio", 0) > 1.5:
                action_score += 0.15
                followups.append(f"{m}: clear separation (ratio={info['ratio']:.1f}) → add ordination")
                break

    if snap.figure_paths:
        action_score += 0.05 * min(len(snap.figure_paths), 3)

    evidence["actionability"] = f"triggers: sig={sig_score>.5}, diff_genera={len(snap.group_differential_genera)}"
    axis_scores["actionability"] = min(1.0, action_score)

    # ── 6. confidence ──
    if min_group_size >= 20:
        conf_score = 0.9
    elif min_group_size >= 10:
        conf_score = 0.7
    elif min_group_size >= 5:
        conf_score = 0.5
    else:
        conf_score = 0.3
    evidence["confidence"] = f"min_group_size={min_group_size} [from metadata]"
    axis_scores["confidence"] = conf_score

    # ── 7. reproducibility ──
    repro_score = 0.5
    # 同カテゴリのステップ間で p 値の方向性が一致しているか
    cats = {
        "alpha": ["alpha_boxplot", "alpha_rarefaction", "alpha_effect_size"],
        "beta": ["beta_pcoa", "beta_nmds", "permanova_detail", "beta_dispersion"],
        "taxonomy": ["taxonomy_barplot", "differential_volcano", "lefse"],
    }
    my_cat = None
    for cat, keys in cats.items():
        if step_key in keys:
            my_cat = cat
            break
    if my_cat:
        same_cat = [s for s in prior_scores if any(s.step_key in keys for c, keys in cats.items() if c == my_cat)]
        if same_cat:
            prev_sigs = [s.axis_scores.get("statistical_significance", 0) > 0.5 for s in same_cat]
            current_sig = sig_score > 0.5
            if all(s == current_sig for s in prev_sigs):
                repro_score = 0.8
                evidence["reproducibility"] = f"consistent with {len(same_cat)} prior {my_cat} analyses"
            else:
                repro_score = 0.3
                evidence["reproducibility"] = f"inconsistent with prior {my_cat} analyses"
        else:
            evidence["reproducibility"] = f"first {my_cat or 'unknown'} analysis"
    else:
        evidence["reproducibility"] = "category unknown"
    axis_scores["reproducibility"] = repro_score

    # ── 8. effect_magnitude ──
    effect_sizes = []
    for t in snap.alpha_group_tests:
        effect_sizes.append(t.get("effect_size", 0))
    for m, info in snap.beta_within_vs_between.items():
        # ratio を効果量の代理として使用
        effect_sizes.append(min(1.0, info.get("ratio", 0) / 3.0))
    if snap.group_differential_genera:
        max_fc = max(g["fold_change"] for g in snap.group_differential_genera)
        effect_sizes.append(min(1.0, max_fc / 10.0))

    if effect_sizes:
        effect_score = max(effect_sizes)
        evidence["effect_magnitude"] = (
            f"max_effect={max(effect_sizes):.2f} [from data: "
            f"alpha_effects={len(snap.alpha_group_tests)}, "
            f"beta_ratios={len(snap.beta_within_vs_between)}, "
            f"fc={len(snap.group_differential_genera)} genera]"
        )
    else:
        effect_score = 0.2
        evidence["effect_magnitude"] = "no effect sizes computed"
    axis_scores["effect_magnitude"] = min(1.0, effect_score)

    return axis_scores, evidence, findings, followups


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeState — 蓄積・圧縮
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KnowledgeState:
    """蓄積された知識の圧縮表現"""
    step_scores: list[StepScore] = field(default_factory=list)
    all_findings: list[str] = field(default_factory=list)
    data_snapshots: list[DataSnapshot] = field(default_factory=list)

    principal_components: list[dict] = field(default_factory=list)
    mean_composite: float = 0.0
    discovery_momentum: float = 0.0
    coverage_map: dict[str, float] = field(default_factory=dict)
    strongest_findings: list[str] = field(default_factory=list)
    weakest_areas: list[str] = field(default_factory=list)
    suggested_directions: list[str] = field(default_factory=list)

    def add_score(self, score: StepScore, snapshot: DataSnapshot):
        self.step_scores.append(score)
        self.all_findings.extend(score.key_findings)
        self.data_snapshots.append(snapshot)
        self._recompute()

    def _recompute(self):
        if not self.step_scores:
            return
        n = len(self.step_scores)
        composites = [s.composite_score for s in self.step_scores]
        self.mean_composite = sum(composites) / n
        if n >= 3:
            recent = composites[-3:]
            older = composites[:-3] if n > 3 else [composites[0]]
            self.discovery_momentum = (sum(recent) / len(recent)) - (sum(older) / len(older))
        else:
            self.discovery_momentum = 0.0

        cat_map = {
            "quality": ["qc_summary", "denoising_stats", "rarefaction"],
            "alpha": ["alpha_boxplot", "alpha_rarefaction", "alpha_effect_size", "alpha_trajectory"],
            "beta": ["beta_pcoa", "beta_nmds", "beta_tsne", "permanova_detail", "beta_dispersion", "beta_heatmap"],
            "taxonomy": ["taxonomy_barplot", "taxonomy_heatmap", "differential_volcano", "lefse", "indicator_species"],
            "advanced": ["network_analysis", "picrust2", "core_microbiome", "guild_analysis", "ml_classifier"],
            "composite": ["publication_composite", "summary_report"],
        }
        for cat, keys in cat_map.items():
            done = [s for s in self.step_scores if s.step_key in keys]
            self.coverage_map[cat] = sum(s.composite_score for s in done) / len(done) if done else 0.0

        self._compress_svd()

        sorted_scores = sorted(self.step_scores, key=lambda s: -s.composite_score)
        self.strongest_findings = []
        for s in sorted_scores[:3]:
            if s.key_findings:
                self.strongest_findings.append(f"{s.step_title} [{s.composite_score:.2f}]: {s.key_findings[0]}")

        self.weakest_areas = [cat for cat, cov in self.coverage_map.items() if cov < 0.3 and cat != "composite"]
        self.suggested_directions = self._compute_directions()

    def _compress_svd(self):
        n = len(self.step_scores)
        if n < 2:
            self.principal_components = []
            return
        m = len(EVAL_AXES)
        matrix = [[s.axis_scores.get(axis, 0.0) for axis in EVAL_AXES] for s in self.step_scores]
        means = [sum(matrix[i][j] for i in range(n)) / n for j in range(m)]
        centered = [[matrix[i][j] - means[j] for j in range(m)] for i in range(n)]

        cov = [[0.0] * m for _ in range(m)]
        for row in centered:
            for i in range(m):
                for j in range(m):
                    cov[i][j] += row[i] * row[j]
        for i in range(m):
            for j in range(m):
                cov[i][j] /= max(n - 1, 1)

        eigenvectors, eigenvalues = [], []
        residual_cov = [row[:] for row in cov]
        for _ in range(min(3, m, n)):
            v = [1.0 / math.sqrt(m)] * m
            for _ in range(50):
                new_v = [sum(residual_cov[i][j] * v[j] for j in range(m)) for i in range(m)]
                norm = math.sqrt(sum(x * x for x in new_v))
                if norm < 1e-10:
                    break
                v = [x / norm for x in new_v]
            Av = [sum(residual_cov[i][j] * v[j] for j in range(m)) for i in range(m)]
            eigenval = sum(v[i] * Av[i] for i in range(m))
            eigenvectors.append(v)
            eigenvalues.append(max(eigenval, 0))
            for i in range(m):
                for j in range(m):
                    residual_cov[i][j] -= eigenval * v[i] * v[j]

        total_var = sum(eigenvalues) if eigenvalues else 1
        self.principal_components = []
        for idx, (eigvec, eigval) in enumerate(zip(eigenvectors, eigenvalues)):
            contributions = sorted(
                [(EVAL_AXES[j], eigvec[j]) for j in range(m)], key=lambda x: -abs(x[1])
            )
            top_axis = contributions[0][0] if contributions else "unknown"
            if "significance" in top_axis:
                label = "statistical_certainty"
            elif "biological" in top_axis or "novelty" in top_axis:
                label = "biological_discovery"
            else:
                label = "data_robustness"

            self.principal_components.append({
                "label": label,
                "variance_explained": eigval / total_var if total_var > 0 else 0,
                "top_contributors": [{"axis": a, "loading": round(l, 3)} for a, l in contributions[:3]],
            })

    def _compute_directions(self) -> list[str]:
        directions = []
        sig_high = [s for s in self.step_scores if s.axis_scores.get("statistical_significance", 0) > 0.7]
        if sig_high:
            directions.append(f"DEEPEN: {len(sig_high)} steps show strong significance")
        novel = [s for s in self.step_scores if s.axis_scores.get("novelty", 0) > 0.6]
        if novel:
            directions.append(f"FOLLOW_UP: {len(novel)} novel findings need validation")
        for area in self.weakest_areas:
            directions.append(f"EXPLORE: '{area}' under-explored (coverage={self.coverage_map.get(area, 0):.2f})")
        if self.discovery_momentum > 0.1:
            directions.append("MOMENTUM: discovery rate increasing — continue")
        elif self.discovery_momentum < -0.1:
            directions.append("PIVOT: discovery rate declining — try new angles")
        return directions

    def compressed_summary(self) -> str:
        lines = [
            f"=== KNOWLEDGE STATE (n={len(self.step_scores)} steps, DATA-DRIVEN) ===",
            f"Mean composite score: {self.mean_composite:.3f}",
            f"Discovery momentum: {self.discovery_momentum:+.3f}",
        ]
        if self.coverage_map:
            cov_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(self.coverage_map.items()))
            lines.append(f"Coverage: {cov_str}")
        if self.principal_components:
            lines.append("\nPrincipal Components:")
            for pc in self.principal_components:
                contribs = ", ".join(f"{c['axis']}({c['loading']:+.2f})" for c in pc['top_contributors'][:2])
                lines.append(f"  {pc['label']}: {pc['variance_explained']*100:.0f}% [{contribs}]")
        if self.strongest_findings:
            lines.append("\nStrongest findings:")
            for f in self.strongest_findings:
                lines.append(f"  * {f}")
        if self.weakest_areas:
            lines.append(f"\nWeak areas: {', '.join(self.weakest_areas)}")
        if self.suggested_directions:
            lines.append("\nDirections:")
            for d in self.suggested_directions:
                lines.append(f"  -> {d}")
        return "\n".join(lines)

    def score_matrix_text(self) -> str:
        if not self.step_scores:
            return "(no scores yet)"
        header = "Step".ljust(30) + " ".join(a[:6].ljust(7) for a in EVAL_AXES) + " TOTAL"
        lines = [header, "-" * len(header)]
        for s in self.step_scores:
            row = s.step_key[:29].ljust(30)
            for axis in EVAL_AXES:
                row += f"{s.axis_scores.get(axis, 0):.2f}".ljust(8)
            row += f"{s.composite_score:.3f}"
            lines.append(row)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# EvalMediator — 仲介サーバー本体
# ═══════════════════════════════════════════════════════════════════════════════

class EvalMediator:
    """
    解析結果の多軸評価 → 圧縮 → LLM 判断プロンプト生成を行う仲介サーバー。

    stdout テキストマッチではなく、DataInspector が実ファイルを読み込んで
    統計検定を自前で実行し、その数値からスコアを算出する。
    """

    def __init__(
        self,
        export_files: dict[str, list[str]],
        metadata_path: str = "",
        group_column: str = "",
        n_samples: int = 0,
        min_group_size: int = 0,
        weights: Optional[dict[str, float]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.n_samples = n_samples
        self.min_group_size = min_group_size
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.state = KnowledgeState()
        self._log_cb = log_callback

        # DataInspector: 実データ読み込み層
        self.inspector = DataInspector(export_files, metadata_path, group_column)

    def _log(self, msg: str):
        if self._log_cb:
            self._log_cb(msg)

    def evaluate(
        self,
        step_key: str,
        step_title: str,
        stdout: str,
        stderr: str,
        success: bool,
        figure_paths: list[str] = None,
    ) -> StepScore:
        """
        1 ステップの結果を評価。
        DataInspector で実データを読み込み → 定量スコア計算。
        """
        if figure_paths is None:
            figure_paths = []

        # ★ ここが核心: 実データからスナップショットを取得
        snapshot = self.inspector.inspect(step_key, figure_paths)

        # DataSnapshot からスコアを計算
        axis_scores, evidence, findings, followups = _score_from_data(
            snapshot, step_key, stdout, stderr, success,
            self.n_samples, self.min_group_size,
            self.state.step_scores,
        )

        composite = sum(axis_scores[a] * self.weights.get(a, 0) for a in EVAL_AXES)

        score = StepScore(
            step_key=step_key,
            step_title=step_title,
            axis_scores=axis_scores,
            composite_score=composite,
            key_findings=findings,
            suggested_followups=followups,
            raw_evidence=evidence,
            data_snapshot=snapshot.to_dict(),
        )

        self.state.add_score(score, snapshot)

        self._log(f"  [EVAL] {score.summary_line()}")
        if findings:
            self._log(f"     Finding: {findings[0][:100]}")
        if followups:
            self._log(f"     Suggest: {followups[0][:80]}")

        return score

    def build_decision_prompt(
        self,
        remaining_keys: list[str],
        registry_menu: str,
        research_question: str = "",
    ) -> str:
        """圧縮スコア + 実データスナップショットを含む判断プロンプト"""
        compressed = self.state.compressed_summary()

        # 直近ステップの実データスナップショット
        recent_data = ""
        for s, snap in zip(
            self.state.step_scores[-3:],
            self.state.data_snapshots[-3:],
        ):
            recent_data += f"\n--- {s.step_key} [{s.composite_score:.2f}] ---"
            recent_data += f"\n{snap.text_for_llm()}"
            for axis, val in sorted(s.axis_scores.items(), key=lambda x: -x[1])[:4]:
                bar = "#" * int(val * 10) + "." * (10 - int(val * 10))
                recent_data += f"\n  {axis:30s} [{bar}] {val:.2f}  {s.raw_evidence.get(axis, '')}"
            if s.key_findings:
                recent_data += f"\n  KEY: {s.key_findings[0][:150]}"

        remaining_text = "\n".join(f"  - {k}" for k in remaining_keys[:15])

        return f"""You are an adaptive analysis decision engine.
You receive QUANTITATIVE SCORES computed from ACTUAL DATA FILES (not stdout text).

## RESEARCH QUESTION
{research_question}

## COMPRESSED KNOWLEDGE STATE
{compressed}

## RECENT EVALUATIONS (scores from raw data inspection)
{recent_data}

## REMAINING PLANNED STEPS
{remaining_text}

## AVAILABLE ANALYSES
{registry_menu}

## DECISION RULES (score-based, data-driven)

1. **composite > 0.7**: Strong finding from data → DEEPEN (add mechanistic follow-ups)
2. **composite 0.4-0.7**: Moderate → VALIDATE (add complementary methods)
3. **composite < 0.4**: Weak in data → SKIP related follow-ups
4. **beta separation ratio > 2.0**: Clear community separation → prioritize ordination + PERMANOVA
5. **alpha effect_size > 0.5**: Large diversity difference → add rarefaction + effect size plot
6. **differential genera fold_change > 5x**: Major taxon shift → add functional prediction
7. **MOMENTUM positive**: Keep current direction
8. **MOMENTUM negative**: Pivot to unexplored categories
9. **COVERAGE gap < 0.3**: Fill that gap

Return JSON:
{{
  "skip": ["key1"],
  "add": [{{"key": "x", "reason": "data-driven reason", "priority": 8}}],
  "investigate": [
    {{
      "title": "Title",
      "hypothesis": "Based on fold_change=X of genus Y...",
      "method": "Specific method",
      "code_instructions": "Detailed instructions",
      "priority": 9,
      "trigger_data": {{"metric": "value that triggered this"}}
    }}
  ],
  "reorder": [],
  "reasoning": "Data says: beta ratio=X, alpha p=Y, therefore..."
}}

Return ONLY JSON."""

    def adjust_weights_for_experiment(self, experiment_type: str):
        adjustments = {
            "antibiotic_treatment": {
                "biological_relevance": 0.22, "effect_magnitude": 0.15,
                "statistical_significance": 0.18,
            },
            "diet_intervention": {
                "effect_magnitude": 0.15, "reproducibility": 0.12, "novelty": 0.08,
            },
            "longitudinal": {
                "reproducibility": 0.15, "confidence": 0.12, "novelty": 0.10,
            },
            "case_control": {
                "statistical_significance": 0.25, "confidence": 0.12,
                "biological_relevance": 0.15,
            },
        }
        if experiment_type in adjustments:
            self.weights.update(adjustments[experiment_type])
            total = sum(self.weights.values())
            if total > 0:
                self.weights = {k: v / total for k, v in self.weights.items()}
            self._log(f"  Weights adjusted for '{experiment_type}'")

    def decide(self, remaining_keys: list[str]) -> "Decision":
        """
        Python 判断木で次ステップを確定的に決定。
        LLM に聞かずにデータから決まることは全てここで決める。
        """
        return DecisionEngine(self.state, self.inspector).decide(remaining_keys)

    def get_state_snapshot(self) -> dict:
        return {
            "n_steps": len(self.state.step_scores),
            "mean_composite": self.state.mean_composite,
            "discovery_momentum": self.state.discovery_momentum,
            "coverage": self.state.coverage_map,
            "principal_components": self.state.principal_components,
            "strongest_findings": self.state.strongest_findings,
            "weakest_areas": self.state.weakest_areas,
            "suggested_directions": self.state.suggested_directions,
            "scores": [
                {
                    "key": s.step_key,
                    "composite": s.composite_score,
                    "axes": s.axis_scores,
                    "findings": s.key_findings[:2],
                    "data": s.data_snapshot,
                }
                for s in self.state.step_scores
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DecisionEngine — 文献ベースの確定的判断木
# ═══════════════════════════════════════════════════════════════════════════════
#
# LLM に聞かずに、データの数値から次に何をすべきかを Python の if 文で決定。
# 根拠は全て査読論文の標準的プラクティスに基づく:
#   - Anderson (2001): PERMANOVA → beta dispersion check は必須
#   - Willis (2019): rarefaction の是非は read depth CV で判断
#   - Gloor et al. (2017): 組成データ → CLR 変換の判断
#   - Fernandes et al. (2014): 差次解析 → ALDEx2 の適用条件
#   - McMurdie & Holmes (2014): rarefaction vs 正規化の判断

@dataclass
class Decision:
    """判断木の出力"""
    skip: list[str] = field(default_factory=list)        # 不要になったステップ
    add: list[dict] = field(default_factory=list)         # 追加すべきステップ
    reorder: list[str] = field(default_factory=list)      # 優先度変更
    investigate: list[dict] = field(default_factory=list)  # カスタム調査
    reasoning: list[str] = field(default_factory=list)     # 判断根拠（人間可読）

    def merge_with_llm(self, llm_decision: dict) -> dict:
        """Python 判断と LLM 判断をマージ。Python 側が優先。"""
        result = {
            "skip": list(set(self.skip + llm_decision.get("skip", []))),
            "add": self.add + [
                a for a in llm_decision.get("add", [])
                if a.get("key") not in {x.get("key") for x in self.add}
            ],
            "reorder": self.reorder or llm_decision.get("reorder", []),
            "investigate": self.investigate + llm_decision.get("investigate", []),
            "reasoning": (
                "Python decision tree: " + "; ".join(self.reasoning)
                + " | LLM: " + llm_decision.get("reasoning", "")
            ),
        }
        # Python が skip したものを LLM が add していたら Python が勝つ
        skip_set = set(result["skip"])
        result["add"] = [a for a in result["add"] if a.get("key") not in skip_set]
        return result


class DecisionEngine:
    """
    文献ベースの確定的判断木。
    DataInspector の実測値と KnowledgeState のスコアから
    次ステップを if 文で決定する。
    """

    def __init__(self, state: KnowledgeState, inspector: DataInspector):
        self.state = state
        self.inspector = inspector
        # 最新の DataSnapshot を取得
        self._latest_snap = state.data_snapshots[-1] if state.data_snapshots else DataSnapshot()
        # 全スナップショットを統合した累積知識
        self._all_snaps = state.data_snapshots

    def decide(self, remaining_keys: list[str]) -> Decision:
        d = Decision()
        remaining_set = set(remaining_keys)
        completed_keys = {s.step_key for s in self.state.step_scores}

        # ── 各判断木を実行 ──
        self._decide_alpha(d, remaining_set, completed_keys)
        self._decide_beta(d, remaining_set, completed_keys)
        self._decide_taxonomy(d, remaining_set, completed_keys)
        self._decide_quality(d, remaining_set, completed_keys)
        self._decide_advanced(d, remaining_set, completed_keys)
        self._decide_coverage_gaps(d, remaining_set, completed_keys)
        self._decide_reorder(d, remaining_set)

        return d

    # ── Alpha diversity 判断木 ────────────────────────────────────

    def _decide_alpha(self, d: Decision, remaining: set, done: set):
        """
        Willis (2019): alpha diversity の解釈は effect size + rarefaction が鍵
        """
        # 累積された alpha 検定結果を集める
        alpha_tests = []
        for snap in self._all_snaps:
            alpha_tests.extend(snap.alpha_group_tests)

        if not alpha_tests:
            return

        min_p = min(t["p"] for t in alpha_tests)
        max_effect = max(t.get("effect_size", 0) for t in alpha_tests)
        best_metric = min(alpha_tests, key=lambda t: t["p"])

        if min_p < 0.05:
            # === 有意な alpha diversity 差がある ===
            d.reasoning.append(
                f"alpha {best_metric['metric']} p={min_p:.4g} < 0.05"
            )

            if max_effect > 0.5:
                # 大きな効果量 → 深掘り
                d.reasoning.append(f"large effect (Cliff's d={max_effect:.2f} > 0.5)")

                if "alpha_effect_size" not in done and "alpha_effect_size" not in remaining:
                    d.add.append({
                        "key": "alpha_effect_size",
                        "reason": f"alpha p={min_p:.4g} with large effect (d={max_effect:.2f}) — quantify magnitude",
                        "priority": 3,
                    })

                if "alpha_rarefaction" not in done and "alpha_rarefaction" not in remaining:
                    d.add.append({
                        "key": "alpha_rarefaction",
                        "reason": "confirm diversity difference isn't driven by uneven sampling depth",
                        "priority": 4,
                    })
            else:
                # 小さな効果量 → rarefaction で確認（sampling artifact かも）
                d.reasoning.append(f"small effect (d={max_effect:.2f} <= 0.5) — may be sampling artifact")

                if "alpha_rarefaction" not in done and "alpha_rarefaction" not in remaining:
                    d.add.append({
                        "key": "alpha_rarefaction",
                        "reason": f"alpha significant (p={min_p:.4g}) but effect small (d={max_effect:.2f}) — check rarefaction",
                        "priority": 3,
                    })

                # 効果量が小さいなら effect_size_plot は優先度低い
                if "alpha_effect_size" in remaining:
                    d.reorder.append("alpha_effect_size")  # 後回し
        else:
            # === alpha 有意でない ===
            d.reasoning.append(f"alpha NOT significant (p={min_p:.4g})")

            # alpha 関連のフォローアップは不要
            for key in ["alpha_effect_size", "alpha_trajectory"]:
                if key in remaining:
                    d.skip.append(key)
                    d.reasoning.append(f"skip {key}: alpha not significant")

            # ただし rarefaction はデータ品質チェックとして残す

    # ── Beta diversity 判断木 ─────────────────────────────────────

    def _decide_beta(self, d: Decision, remaining: set, done: set):
        """
        Anderson (2001): PERMANOVA が有意 → betadisper で分散の均一性を必ず確認
        Legendre & Anderson (1999): pseudo-F の大きさで分離の強さを判断
        """
        beta_p = {}
        beta_F = {}
        beta_ratio = {}
        for snap in self._all_snaps:
            beta_p.update(snap.beta_pvalues)
            beta_F.update(snap.beta_group_separation)
            for m, info in snap.beta_within_vs_between.items():
                beta_ratio[m] = info.get("ratio", 0)

        if not beta_p:
            return

        min_p = min(beta_p.values())
        max_F = max(beta_F.values()) if beta_F else 0
        max_ratio = max(beta_ratio.values()) if beta_ratio else 0
        best_metric = min(beta_p, key=beta_p.get)

        if min_p < 0.05:
            # === 有意な群間分離 ===
            d.reasoning.append(f"beta {best_metric} PERMANOVA p={min_p:.4g}, F={beta_F.get(best_metric, 0):.1f}")

            # Anderson (2001): PERMANOVA 有意 → 必ず dispersion check
            if "beta_dispersion" not in done and "beta_dispersion" not in remaining:
                d.add.append({
                    "key": "beta_dispersion",
                    "reason": f"PERMANOVA significant (p={min_p:.4g}) — MUST check if due to location or dispersion (Anderson 2001)",
                    "priority": 2,  # 高優先度
                })

            if max_ratio > 2.0:
                # 明確な分離 → 複数の ordination で可視化
                d.reasoning.append(f"clear separation (between/within={max_ratio:.1f})")

                if "beta_nmds" not in done and "beta_nmds" not in remaining:
                    d.add.append({
                        "key": "beta_nmds",
                        "reason": f"clear group separation (ratio={max_ratio:.1f}) — NMDS for nonlinear visualization",
                        "priority": 5,
                    })

                # PERMANOVA detail 追加
                if "permanova_detail" not in done and "permanova_detail" not in remaining:
                    d.add.append({
                        "key": "permanova_detail",
                        "reason": f"significant separation — full pairwise PERMANOVA needed",
                        "priority": 4,
                    })
            elif max_ratio > 1.3:
                d.reasoning.append(f"moderate separation (ratio={max_ratio:.1f})")
                # PERMANOVA detail は追加するが ordination は予定通りで OK
                if "permanova_detail" not in done and "permanova_detail" not in remaining:
                    d.add.append({
                        "key": "permanova_detail",
                        "reason": f"moderate separation (ratio={max_ratio:.1f}) — pairwise tests needed",
                        "priority": 5,
                    })
            else:
                # ratio 低い = PERMANOVA 有意だが分離が弱い → dispersion が原因かも
                d.reasoning.append(f"weak separation despite significant PERMANOVA (ratio={max_ratio:.1f})")
                # beta_dispersion の優先度を上げる
        else:
            # === beta 有意でない ===
            d.reasoning.append(f"beta NOT significant (p={min_p:.4g})")

            # beta 関連のフォローアップを削減
            for key in ["permanova_detail", "beta_dispersion", "beta_nmds", "beta_tsne", "beta_heatmap"]:
                if key in remaining:
                    d.skip.append(key)
                    d.reasoning.append(f"skip {key}: beta not significant")

    # ── Taxonomy / Differential 判断木 ───────────────────────────

    def _decide_taxonomy(self, d: Decision, remaining: set, done: set):
        """
        Gloor et al. (2017): 組成データの性質を考慮した差次解析
        Fernandes et al. (2014): ALDEx2 の適用判断
        Lin & Peddada (2020): ANCOM-BC の適用判断
        """
        diff_genera = []
        for snap in self._all_snaps:
            diff_genera.extend(snap.group_differential_genera)

        if not diff_genera:
            return

        max_fc = max(g["fold_change"] for g in diff_genera)
        max_diff = max(g["abs_diff"] for g in diff_genera)
        n_significant = sum(1 for g in diff_genera if g["fold_change"] > 2)
        top_genus = max(diff_genera, key=lambda g: g["abs_diff"])

        # 低豊度バイアスチェック
        low_abundance_bias = any(
            g["fold_change"] > 50 and max(g["group_a_mean"], g["group_b_mean"]) < 1.0
            for g in diff_genera
        )
        if low_abundance_bias:
            d.reasoning.append(
                "WARNING: extreme fold change in low-abundance taxa — likely artifact"
            )
            d.investigate.append({
                "title": "Low-abundance bias check",
                "hypothesis": "Extreme fold changes in rare taxa may be compositional artifacts",
                "method": "Filter taxa < 0.1% relative abundance, recompute fold changes",
                "code_instructions": (
                    "Read feature-table.tsv, compute relative abundance per sample, "
                    "filter ASVs with mean relative abundance < 0.001, "
                    "recompute group-level fold changes. "
                    "Print filtered vs unfiltered top differential genera. "
                    "Plot scatter of abundance vs fold change."
                ),
                "priority": 3,
            })

        if max_fc > 5:
            # 大きな fold change → 差次解析を正式実行
            d.reasoning.append(f"large fold change: {top_genus['genus']} {max_fc:.0f}x")

            if "differential_volcano" not in done and "differential_volcano" not in remaining:
                d.add.append({
                    "key": "differential_volcano",
                    "reason": f"{top_genus['genus']} shows {max_fc:.0f}x change — formal differential test needed",
                    "priority": 2,
                })

            if "lefse" not in done and "lefse" not in remaining:
                d.add.append({
                    "key": "lefse",
                    "reason": f"{n_significant} genera with >2x fold change — LEfSe for effect size ranking",
                    "priority": 4,
                })

        if n_significant >= 5:
            # 多くの属が変化 → 機能予測で生物学的解釈
            d.reasoning.append(f"{n_significant} genera with >2x change — functional shift likely")

            if "picrust2" not in done and "picrust2" not in remaining:
                d.add.append({
                    "key": "picrust2",
                    "reason": f"{n_significant} differential genera — predict functional consequences",
                    "priority": 6,
                })

            if "indicator_species" not in done and "indicator_species" not in remaining:
                d.add.append({
                    "key": "indicator_species",
                    "reason": f"multiple differential taxa — identify group-specific indicators",
                    "priority": 5,
                })

        if max_diff > 10:
            # 10% 以上の絶対差 → 組成変化が大きい → ネットワーク解析も有用
            d.reasoning.append(f"major composition shift (max_diff={max_diff:.1f}%)")
            if "network_analysis" not in done and "network_analysis" not in remaining:
                d.add.append({
                    "key": "network_analysis",
                    "reason": f"{max_diff:.0f}% composition shift — co-occurrence patterns may reveal mechanisms",
                    "priority": 7,
                })

        if max_fc <= 2 and max_diff < 3:
            # 弱い差次 → 差次解析系は低優先度に
            d.reasoning.append(f"weak differential signal (max_fc={max_fc:.1f}, max_diff={max_diff:.1f}%)")
            for key in ["differential_volcano", "lefse", "indicator_species"]:
                if key in remaining:
                    d.reorder.append(key)  # 後回し

    # ── Data quality 判断木 ──────────────────────────────────────

    def _decide_quality(self, d: Decision, remaining: set, done: set):
        """
        McMurdie & Holmes (2014): read depth 不均一 → rarefaction の判断
        Willis (2019): coverage に基づく rarefaction の是非
        """
        if not self.inspector._sample_reads:
            self.inspector._ensure_feature_table()

        if not self.inspector._sample_reads:
            return

        reads = list(self.inspector._sample_reads.values())
        if len(reads) < 2:
            return

        mean_reads = _stats.mean(reads)
        min_reads = min(reads)
        max_reads = max(reads)
        cv = _stats.stdev(reads) / mean_reads if mean_reads > 0 else 0

        if cv > 0.5:
            # read depth が非常に不均一 → rarefaction 重要
            d.reasoning.append(
                f"read depth highly uneven: CV={cv:.2f} (min={min_reads}, max={max_reads})"
            )
            if "alpha_rarefaction" not in done and "alpha_rarefaction" not in remaining:
                d.add.append({
                    "key": "alpha_rarefaction",
                    "reason": f"read depth CV={cv:.2f} — rarefaction curves essential (McMurdie & Holmes 2014)",
                    "priority": 2,
                })

        # スパース度チェック
        sparsity = 0
        for snap in self._all_snaps:
            if snap.sparsity > 0:
                sparsity = max(sparsity, snap.sparsity)

        if sparsity > 0.9:
            d.reasoning.append(f"very sparse feature table ({sparsity:.0%} zeros)")
            d.investigate.append({
                "title": "Sparsity-aware analysis",
                "hypothesis": f"Feature table is {sparsity:.0%} sparse — standard methods may be unreliable",
                "method": "Filter low-prevalence ASVs (present in < 10% of samples), recompute diversity",
                "code_instructions": (
                    "Read feature-table.tsv. Count how many samples each ASV appears in. "
                    "Filter ASVs present in < 10% of samples. Print before/after ASV counts. "
                    "Recompute Shannon diversity on filtered table. "
                    "Compare with unfiltered Shannon values. Plot correlation."
                ),
                "priority": 3,
            })

    # ── Advanced analysis 判断木 ─────────────────────────────────

    def _decide_advanced(self, d: Decision, remaining: set, done: set):
        """
        データの性質から高度な解析の要否を判断。
        """
        # 全情報を統合
        alpha_sig = any(
            t["p"] < 0.05
            for snap in self._all_snaps
            for t in snap.alpha_group_tests
        )
        beta_sig = any(
            p < 0.05
            for snap in self._all_snaps
            for p in snap.beta_pvalues.values()
        )
        has_differential = any(
            g["fold_change"] > 2
            for snap in self._all_snaps
            for g in snap.group_differential_genera
        )

        if not alpha_sig and not beta_sig and not has_differential:
            # 何も有意でない → 探索的可視化に集中、高度な解析はスキップ
            d.reasoning.append("no significant signals — focus on exploratory visualization")
            for key in ["network_analysis", "ml_classifier", "picrust2"]:
                if key in remaining:
                    d.skip.append(key)
                    d.reasoning.append(f"skip {key}: no significant patterns to follow up")

        # 少なくとも alpha OR beta が有意で差次菌属もある → ML 分類器が有用
        if (alpha_sig or beta_sig) and has_differential:
            n_samples = self.inspector._sample_reads and len(self.inspector._sample_reads) or 0
            if n_samples >= 30:  # ML には最低 30 サンプル
                if "ml_classifier" not in done and "ml_classifier" not in remaining:
                    d.add.append({
                        "key": "ml_classifier",
                        "reason": "significant patterns + sufficient samples — ML can identify predictive taxa",
                        "priority": 8,
                    })
            else:
                d.reasoning.append(f"ML skipped: n={n_samples} < 30 (overfitting risk)")

    # ── Coverage gap 判断木 ──────────────────────────────────────

    def _decide_coverage_gaps(self, d: Decision, remaining: set, done: set):
        """未カバーのカテゴリを補完"""
        coverage = self.state.coverage_map

        # quality カテゴリが未実行 → QC を最優先で追加
        if coverage.get("quality", 0) == 0:
            if "qc_summary" not in done and "qc_summary" not in remaining:
                d.add.append({
                    "key": "qc_summary",
                    "reason": "quality assessment not yet done — should be first",
                    "priority": 1,
                })

        # compositeが未実行で他のカテゴリが十分 → 最後にまとめ図
        done_categories = sum(1 for v in coverage.values() if v > 0.3)
        if done_categories >= 3 and coverage.get("composite", 0) == 0:
            if "publication_composite" not in done and "publication_composite" not in remaining:
                d.add.append({
                    "key": "publication_composite",
                    "reason": f"{done_categories} categories analyzed — generate publication figure",
                    "priority": 10,  # 最後
                })

    # ── 優先度ベースのリオーダー ─────────────────────────────────

    def _decide_reorder(self, d: Decision, remaining: set):
        """追加したステップを含めて優先度順にソート"""
        if not d.add:
            return
        # add したものの priority でソート
        added_keys = [a["key"] for a in sorted(d.add, key=lambda x: x.get("priority", 5))]
        # skip されたものを除外
        skip_set = set(d.skip)
        # remaining から skip を除いた上で、add の高優先度を先頭に
        remaining_filtered = [k for k in remaining if k not in skip_set]
        d.reorder = added_keys + [k for k in remaining_filtered if k not in set(added_keys)]
