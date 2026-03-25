#!/usr/bin/env python3
"""
microbiome_knowledge.py
=======================
マイクロバイオーム解析のドメイン知識を体系化したモジュール。

AI 駆動解析モードが「なぜその解析を選ぶのか」を判断するための
学術的根拠・決定木・メソッド選択ロジックを提供する。

参考文献:
  - Aitchison (1986): Compositional data analysis
  - Gloor et al. (2017): Microbiome datasets are compositional
  - Anderson (2001): PERMANOVA
  - McMurdie & Holmes (2014): Waste not, want not (rarefaction debate)
  - Willis (2019): Rarefaction, alpha diversity, and statistics
  - Quinn et al. (2018): Understanding sequencing data as compositions
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


# ─────────────────────────────────────────────────────────────────────────────
# データ特性プロファイル
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DataProfile:
    """データの統計的特性プロファイル"""
    n_samples: int = 0
    n_groups: int = 0
    min_group_size: int = 0
    max_group_size: int = 0
    is_paired: bool = False
    is_longitudinal: bool = False
    n_asvs: int = 0
    sparsity: float = 0.0             # feature table の 0 の割合 (0.0-1.0)
    read_depth_cv: float = 0.0        # リード深度の変動係数
    min_reads: int = 0
    max_reads: int = 0
    evenness_mean: float = 0.0        # Pielou's J (0=1種優占, 1=完全均等)
    dominance_mean: float = 0.0       # Simpson's dominance (1 - Simpson's diversity)
    has_taxonomy: bool = False
    n_genera: int = 0
    alpha_significant: bool = False   # 群間α多様性に有意差があるか
    alpha_p: float = 1.0
    alpha_effect_size: float = 0.0    # Cliff's delta or similar
    beta_significant: bool = False    # PERMANOVA 有意か
    beta_p: float = 1.0
    beta_pseudo_f: float = 0.0
    high_variance_genera: list[str] = field(default_factory=list)
    group_composition_shift: float = 0.0  # 群間の Bray-Curtis centroid 距離


# ─────────────────────────────────────────────────────────────────────────────
# 1. Alpha 多様性メトリクス知識
# ─────────────────────────────────────────────────────────────────────────────

ALPHA_METRICS = {
    "shannon": {
        "full_name": "Shannon entropy (H')",
        "measures": "richness + evenness",
        "formula": "H' = -Σ pᵢ ln(pᵢ)",
        "range": "0 to ln(S)",
        "interpretation": (
            "Combines species richness and evenness. Higher values indicate "
            "more diverse communities. Sensitive to rare species."
        ),
        "when_to_use": "General diversity comparison. Most commonly reported.",
        "limitations": "Sensitive to rare taxa and sequencing depth.",
        "requires_rarefaction": True,
    },
    "observed_features": {
        "full_name": "Observed ASVs (species richness)",
        "measures": "richness only",
        "formula": "S = count of non-zero ASVs",
        "range": "1 to total ASVs",
        "interpretation": "Raw count of unique taxa. Most sensitive to sequencing depth.",
        "when_to_use": "When richness differences are of primary interest.",
        "limitations": "Highly sensitive to sequencing depth. Always pair with rarefaction.",
        "requires_rarefaction": True,
    },
    "faith_pd": {
        "full_name": "Faith's Phylogenetic Diversity",
        "measures": "phylogenetic richness",
        "formula": "PD = sum of branch lengths in minimum spanning tree",
        "range": "0 to total tree length",
        "interpretation": (
            "Incorporates evolutionary relationships. Two closely related species "
            "contribute less than two distantly related species."
        ),
        "when_to_use": "When phylogenetic relationships matter (e.g., functional diversity proxy).",
        "limitations": "Requires a phylogenetic tree. Sensitive to tree quality.",
        "requires_rarefaction": True,
    },
    "chao1": {
        "full_name": "Chao1 estimator",
        "measures": "estimated true richness",
        "formula": "Ŝ = S_obs + f₁²/(2f₂)  where f₁=singletons, f₂=doubletons",
        "range": "S_obs to ∞",
        "interpretation": "Estimates total species richness including unobserved taxa.",
        "when_to_use": "When estimating total richness from incomplete sampling.",
        "limitations": "Assumes rare species follow specific abundance distribution.",
        "requires_rarefaction": False,
    },
    "simpson": {
        "full_name": "Simpson's diversity index (1-D)",
        "measures": "evenness (dominance-weighted)",
        "formula": "1 - D = 1 - Σ pᵢ²",
        "range": "0 to 1",
        "interpretation": (
            "Probability that two randomly chosen individuals belong to different species. "
            "Less sensitive to rare taxa than Shannon."
        ),
        "when_to_use": "When interested in dominant species. More robust to sampling depth.",
        "limitations": "Less sensitive to changes in rare taxa.",
        "requires_rarefaction": False,
    },
    "pielou_e": {
        "full_name": "Pielou's evenness (J')",
        "measures": "evenness only",
        "formula": "J' = H' / ln(S)",
        "range": "0 to 1",
        "interpretation": "How evenly individuals are distributed among species.",
        "when_to_use": "When evenness (not richness) is the question.",
        "limitations": "Depends on both H' and S, both of which are depth-sensitive.",
        "requires_rarefaction": True,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Beta 多様性メトリクス知識
# ─────────────────────────────────────────────────────────────────────────────

BETA_METRICS = {
    "bray_curtis": {
        "full_name": "Bray-Curtis dissimilarity",
        "type": "quantitative, non-phylogenetic",
        "formula": "BC = Σ|xᵢ-yᵢ| / Σ(xᵢ+yᵢ)",
        "range": "0 (identical) to 1 (no shared species)",
        "interpretation": (
            "Quantifies compositional dissimilarity based on abundance. "
            "Sensitive to dominant taxa. The most widely used metric."
        ),
        "when_to_use": "Default choice for most microbiome studies. Abundance-weighted.",
        "ordination": "PCoA (metric MDS) or NMDS",
        "is_compositional": False,
        "handles_absence": True,
    },
    "jaccard": {
        "full_name": "Jaccard distance",
        "type": "qualitative (presence/absence), non-phylogenetic",
        "formula": "J = 1 - |A∩B| / |A∪B|",
        "range": "0 to 1",
        "interpretation": "Based on shared vs unique taxa (ignores abundance).",
        "when_to_use": "When presence/absence matters more than abundance.",
        "ordination": "PCoA",
        "is_compositional": False,
        "handles_absence": True,
    },
    "unweighted_unifrac": {
        "full_name": "Unweighted UniFrac",
        "type": "qualitative, phylogenetic",
        "formula": "UF = Σ(unique branch lengths) / Σ(total branch lengths)",
        "range": "0 to 1",
        "interpretation": (
            "Phylogenetic version of Jaccard. Measures which lineages "
            "are present vs absent, weighted by evolutionary distance."
        ),
        "when_to_use": "When phylogenetic community membership differences are of interest.",
        "ordination": "PCoA",
        "is_compositional": False,
        "handles_absence": True,
    },
    "weighted_unifrac": {
        "full_name": "Weighted UniFrac",
        "type": "quantitative, phylogenetic",
        "formula": "WUF = Σ|pᵢ-qᵢ| × branch_length / Σ branch_length",
        "range": "0 to 1",
        "interpretation": (
            "Phylogenetic version of Bray-Curtis. Considers both "
            "which lineages are present AND their relative abundance."
        ),
        "when_to_use": "When both phylogenetic placement and abundance matter.",
        "ordination": "PCoA",
        "is_compositional": False,
        "handles_absence": True,
    },
    "aitchison": {
        "full_name": "Aitchison distance (Euclidean on CLR)",
        "type": "quantitative, compositional",
        "formula": "d = ||clr(x) - clr(y)||₂",
        "range": "0 to ∞",
        "interpretation": (
            "The only distance metric that respects the compositional nature of "
            "microbiome data (relative abundances sum to 1). Uses CLR transform."
        ),
        "when_to_use": (
            "When compositional bias is a concern. Recommended by "
            "Gloor et al. (2017) for differential abundance."
        ),
        "ordination": "PCA on CLR-transformed data",
        "is_compositional": True,
        "handles_absence": False,  # requires pseudocount for zeros
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 統計検定の決定木
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestRecommendation:
    """統計検定の推奨"""
    test_name: str
    reason: str
    assumptions: list[str]
    alternatives: list[str]
    interpretation_guide: str
    python_snippet: str = ""


def recommend_alpha_test(profile: DataProfile) -> TestRecommendation:
    """データプロファイルに基づいてα多様性の適切な検定を推奨"""

    if profile.n_groups < 2:
        return TestRecommendation(
            test_name="Descriptive statistics only",
            reason="Only 1 group — no comparison possible",
            assumptions=[],
            alternatives=[],
            interpretation_guide="Report mean ± SD, median, range.",
        )

    if profile.n_groups == 2:
        if profile.is_paired:
            if profile.min_group_size >= 20:
                return TestRecommendation(
                    test_name="Wilcoxon signed-rank test",
                    reason=f"2 paired groups, n={profile.min_group_size} (sufficient for Wilcoxon)",
                    assumptions=["Paired observations", "Symmetric difference distribution"],
                    alternatives=["Paired t-test (if normal)", "Permutation test"],
                    interpretation_guide=(
                        "Tests whether the median difference between pairs is zero. "
                        "Report: W statistic, p-value, and matched-pairs effect size (r = Z/√N)."
                    ),
                )
            else:
                return TestRecommendation(
                    test_name="Wilcoxon signed-rank test (exact)",
                    reason=f"2 paired groups, small n={profile.min_group_size} — use exact p-value",
                    assumptions=["Paired observations"],
                    alternatives=["Exact permutation test"],
                    interpretation_guide=(
                        "Small sample: use exact p-value (not asymptotic). "
                        "Report W statistic and exact p-value. Consider bootstrap CI."
                    ),
                )
        else:
            if profile.min_group_size >= 20:
                return TestRecommendation(
                    test_name="Mann-Whitney U test",
                    reason=f"2 independent groups, n_min={profile.min_group_size}",
                    assumptions=["Independent samples", "Same shape distributions (for location test)"],
                    alternatives=["Welch's t-test (if approximately normal)", "Permutation test"],
                    interpretation_guide=(
                        "Tests whether one group tends to have larger values. "
                        "Report: U statistic, p-value, and Cliff's delta effect size. "
                        "Cliff's delta: |d|<0.147 negligible, <0.33 small, <0.474 medium, else large."
                    ),
                )
            else:
                return TestRecommendation(
                    test_name="Mann-Whitney U test (exact)",
                    reason=f"2 independent groups, small n_min={profile.min_group_size}",
                    assumptions=["Independent samples"],
                    alternatives=["Exact permutation test", "Bootstrap confidence interval"],
                    interpretation_guide=(
                        "Small sample: use exact p-value. Report effect size (Cliff's delta). "
                        "NOTE: with n<5 per group, statistical power is very limited — "
                        "non-significant p does NOT mean no effect. Report effect sizes."
                    ),
                )

    # 3+ groups
    if profile.is_paired:
        return TestRecommendation(
            test_name="Friedman test + Nemenyi post-hoc",
            reason=f"{profile.n_groups} paired/repeated groups",
            assumptions=["Repeated measures on same subjects", "Ordinal or continuous data"],
            alternatives=["Repeated measures ANOVA (if normal)", "Aligned rank transform"],
            interpretation_guide=(
                "Friedman tests overall difference across timepoints/conditions. "
                "If significant, Nemenyi post-hoc identifies which pairs differ. "
                "Report: χ² statistic, df, p-value, and pairwise p-values."
            ),
        )
    else:
        return TestRecommendation(
            test_name="Kruskal-Wallis H test + Dunn's post-hoc (Bonferroni)",
            reason=f"{profile.n_groups} independent groups",
            assumptions=["Independent samples", "Similar distribution shapes across groups"],
            alternatives=["One-way ANOVA + Tukey HSD (if normal)", "Permutation ANOVA"],
            interpretation_guide=(
                "Kruskal-Wallis tests overall difference. If p<0.05, run Dunn's test "
                "for pairwise comparisons with Bonferroni correction. "
                "Report: H statistic, df, p-value, and pairwise adjusted p-values. "
                "Effect size: epsilon-squared (ε² = H/(n-1))."
            ),
        )


def recommend_beta_test(profile: DataProfile) -> TestRecommendation:
    """β多様性の群間比較に適切な検定を推奨"""

    if profile.n_groups < 2:
        return TestRecommendation(
            test_name="No group comparison (1 group)",
            reason="Single group — ordination for visualization only",
            assumptions=[],
            alternatives=[],
            interpretation_guide="Use PCoA/NMDS for exploratory visualization.",
        )

    rec = TestRecommendation(
        test_name="PERMANOVA (Anderson, 2001)",
        reason=(
            f"{profile.n_groups} groups, n={profile.n_samples}. "
            "PERMANOVA is the standard method for testing multivariate "
            "community composition differences."
        ),
        assumptions=[
            "Samples are independent (or use strata for nested designs)",
            "Groups have similar multivariate dispersion (homogeneity of variances)",
            "PERMANOVA tests LOCATION (centroid) difference, not dispersion",
        ],
        alternatives=[
            "ANOSIM (less powerful, tests rank dissimilarities)",
            "MRPP (Multi-Response Permutation Procedure)",
            "db-RDA (distance-based Redundancy Analysis, for covariates)",
        ],
        interpretation_guide=(
            "PERMANOVA pseudo-F tests if group centroids differ. "
            "CRITICAL: a significant result can mean (a) centroids differ, OR "
            "(b) dispersions differ. ALWAYS run PERMDISP (betadisper) alongside. "
            "If PERMDISP is also significant, PERMANOVA results are ambiguous. "
            f"With n={profile.n_samples}, use 999 permutations. "
            "Report: pseudo-F, R², p-value, and PERMDISP result."
        ),
    )

    if profile.min_group_size < 5:
        rec.interpretation_guide += (
            f"\nWARNING: min group size = {profile.min_group_size}. "
            "PERMANOVA with very small groups has low power and may give "
            "unreliable p-values. Consider increasing permutations to 9999."
        )

    return rec


# ─────────────────────────────────────────────────────────────────────────────
# 4. 組成データ解析の決定木
# ─────────────────────────────────────────────────────────────────────────────

def recommend_compositional_method(profile: DataProfile) -> dict:
    """組成データ特性に基づいて適切な変換・手法を推奨"""

    result = {
        "transform": "none",
        "reason": "",
        "ordination": "PCoA on Bray-Curtis",
        "differential_method": "",
        "warnings": [],
    }

    # スパース度チェック
    if profile.sparsity > 0.8:
        result["warnings"].append(
            f"High sparsity ({profile.sparsity:.0%} zeros). Many standard methods "
            "assume non-zero data. Consider: (1) filtering low-prevalence ASVs, "
            "(2) using methods robust to zeros (e.g., ANCOM-BC, Bray-Curtis)."
        )

    # リード深度の不均一性
    if profile.read_depth_cv > 0.5:
        result["warnings"].append(
            f"High read depth variability (CV={profile.read_depth_cv:.2f}). "
            "Raw counts are misleading. Use relative abundance or rarefaction. "
            "Compositional methods (CLR) are recommended."
        )
        result["transform"] = "CLR"
        result["reason"] = (
            "CLR transform (centered log-ratio) is recommended because: "
            "(1) read depth varies significantly between samples, "
            "(2) relative abundances are compositional (sum-to-1 constraint), "
            "(3) CLR preserves subcompositional coherence (Aitchison, 1986)."
        )
        result["ordination"] = "PCA on CLR (= Aitchison distance PCoA)"
    else:
        result["transform"] = "relative_abundance"
        result["reason"] = (
            "Read depth is relatively uniform. Relative abundance normalization "
            "is sufficient. CLR is optional but recommended for differential abundance."
        )

    # 差次豊度解析の手法選択
    if profile.n_groups >= 2:
        if profile.min_group_size >= 10:
            result["differential_method"] = "ALDEx2-style (CLR + Welch's t / Wilcoxon per taxon)"
            result["differential_reason"] = (
                "Sufficient sample size for per-taxon testing. ALDEx2 approach: "
                "Monte Carlo sampling from Dirichlet → CLR → test per taxon → BH-FDR. "
                "Properly handles compositionality."
            )
        elif profile.min_group_size >= 3:
            result["differential_method"] = "Mann-Whitney per genus + BH-FDR on relative abundance"
            result["differential_reason"] = (
                "Small sample size limits options. Non-parametric per-taxon test on "
                "relative abundance with FDR correction. Be cautious with interpretation."
            )
        else:
            result["differential_method"] = "Descriptive only (fold-change, no formal testing)"
            result["differential_reason"] = (
                f"n_min={profile.min_group_size} is too small for reliable statistical testing. "
                "Report fold-changes and confidence intervals, not p-values."
            )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. 順序付け（Ordination）手法の選択ガイド
# ─────────────────────────────────────────────────────────────────────────────

ORDINATION_GUIDE = {
    "PCoA": {
        "full_name": "Principal Coordinates Analysis (metric MDS)",
        "input": "Distance matrix",
        "preserves": "Distances (metric)",
        "when_to_use": (
            "Default ordination. Preserves actual distances. Best when the distance "
            "metric is ecologically meaningful (Bray-Curtis, UniFrac)."
        ),
        "limitations": "Can produce negative eigenvalues with non-Euclidean metrics.",
        "variance_explained": True,
        "recommendation_score": lambda p: 10,  # always good
    },
    "NMDS": {
        "full_name": "Non-Metric Multidimensional Scaling",
        "input": "Distance matrix",
        "preserves": "Rank order of distances (non-metric)",
        "when_to_use": (
            "When rank order matters more than exact distances. Often reveals "
            "patterns that PCoA misses. Report stress value (good if <0.2)."
        ),
        "limitations": "Non-deterministic (use multiple random starts). No variance explained.",
        "variance_explained": False,
        "recommendation_score": lambda p: 8,
    },
    "PCA_CLR": {
        "full_name": "PCA on CLR-transformed abundances",
        "input": "Feature table (CLR-transformed)",
        "preserves": "Aitchison distance (compositionally valid)",
        "when_to_use": (
            "When compositional bias is a concern. Mathematically equivalent to "
            "PCoA on Aitchison distance. Allows biplot (loading arrows for taxa)."
        ),
        "limitations": "Requires pseudocount for zeros. Sensitive to pseudocount choice.",
        "variance_explained": True,
        "recommendation_score": lambda p: 9 if p.read_depth_cv > 0.3 else 6,
    },
    "t-SNE": {
        "full_name": "t-distributed Stochastic Neighbor Embedding",
        "input": "Distance matrix",
        "preserves": "Local structure (neighborhoods)",
        "when_to_use": (
            "When local clustering patterns are of interest. Good for visualizing "
            "distinct clusters. perplexity parameter is critical."
        ),
        "limitations": (
            "Does NOT preserve global distances. Different runs give different results. "
            "Do NOT interpret inter-cluster distances. Only use for cluster visualization."
        ),
        "variance_explained": False,
        "recommendation_score": lambda p: 7 if p.n_samples >= 30 else 3,
    },
    "UMAP": {
        "full_name": "Uniform Manifold Approximation and Projection",
        "input": "Distance matrix",
        "preserves": "Local + some global structure",
        "when_to_use": (
            "Similar to t-SNE but better preserves global structure. "
            "Faster for large datasets. Good for both clusters and gradients."
        ),
        "limitations": "Requires umap-learn package. Results depend on hyperparameters.",
        "variance_explained": False,
        "recommendation_score": lambda p: 7 if p.n_samples >= 20 else 3,
    },
}


def recommend_ordinations(profile: DataProfile) -> list[dict]:
    """データプロファイルに基づいて順序付け手法を推奨順で返す"""
    recs = []
    for name, info in ORDINATION_GUIDE.items():
        score = info["recommendation_score"](profile)
        recs.append({
            "method": name,
            "score": score,
            "reason": info["when_to_use"],
            "limitations": info["limitations"],
        })
    return sorted(recs, key=lambda x: -x["score"])


# ─────────────────────────────────────────────────────────────────────────────
# 6. 統計的検出力の推定
# ─────────────────────────────────────────────────────────────────────────────

def estimate_power_context(profile: DataProfile) -> dict:
    """サンプルサイズに基づく検出力の文脈情報"""
    n_per_group = profile.min_group_size

    if n_per_group >= 30:
        power_level = "adequate"
        guidance = (
            "Sample size is adequate for most microbiome analyses. "
            "Standard non-parametric tests have reasonable power. "
            "FDR correction for multiple testing is feasible."
        )
    elif n_per_group >= 10:
        power_level = "moderate"
        guidance = (
            f"n={n_per_group} per group provides moderate power. "
            "Can detect large effects but may miss subtle differences. "
            "Focus on effect sizes rather than p-values alone. "
            "Limit the number of simultaneous tests to preserve power."
        )
    elif n_per_group >= 5:
        power_level = "low"
        guidance = (
            f"n={n_per_group} per group — low statistical power. "
            "Non-parametric tests may not reach significance even with real effects. "
            "ALWAYS report effect sizes (Cliff's delta, Hedges' g). "
            "A non-significant p-value does NOT mean no effect. "
            "Consider this a pilot/exploratory study."
        )
    else:
        power_level = "very_low"
        guidance = (
            f"n={n_per_group} per group — very low power. "
            "Formal hypothesis testing is unreliable. Focus on: "
            "(1) descriptive statistics and visualization, "
            "(2) effect size estimation with confidence intervals, "
            "(3) identifying trends for future studies with adequate power. "
            "Do NOT over-interpret p-values."
        )

    # 大まかな検出可能効果量
    # Mann-Whitney: 約 80% power には n≈16 per group for large effect (d=0.8)
    detectable_effect = "unknown"
    if n_per_group >= 30:
        detectable_effect = "small-to-medium (Cohen's d ≈ 0.5)"
    elif n_per_group >= 16:
        detectable_effect = "large (Cohen's d ≈ 0.8)"
    elif n_per_group >= 10:
        detectable_effect = "very large (Cohen's d ≈ 1.0+)"
    elif n_per_group >= 5:
        detectable_effect = "only extreme effects (Cohen's d ≈ 1.5+)"
    else:
        detectable_effect = "unreliable (insufficient for formal testing)"

    return {
        "power_level": power_level,
        "guidance": guidance,
        "detectable_effect": detectable_effect,
        "n_per_group": n_per_group,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. 解析フロー決定木 — データ特性から解析戦略を生成
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisDecision:
    """1つの解析決定"""
    analysis_key: str
    reason: str
    priority: int         # 1-10
    domain_rationale: str  # 学術的根拠


def build_domain_driven_plan(
    profile: DataProfile,
    research_question: str,
    available_keys: set[str],
) -> list[AnalysisDecision]:
    """
    ドメイン知識に基づいて解析プランを構築。

    これは LLM に依存しない決定論的なプラン。
    LLM プランニングが失敗した場合のフォールバック、
    および LLM プランのバリデーションに使用する。
    """
    decisions: list[AnalysisDecision] = []
    power = estimate_power_context(profile)
    comp = recommend_compositional_method(profile)
    alpha_rec = recommend_alpha_test(profile)
    beta_rec = recommend_beta_test(profile)

    def _add(key: str, reason: str, priority: int, rationale: str):
        if key in available_keys:
            decisions.append(AnalysisDecision(key, reason, priority, rationale))

    # ── Always: Quality checks ──────────────────────────────────────
    _add("dada2_stats", "Quality assessment is always the first step",
         10, "DADA2 statistics reveal data quality issues before any downstream analysis.")
    _add("read_depth", "Sequencing depth determines which analyses are valid",
         10, "Uneven sequencing depth can create spurious diversity differences (McMurdie & Holmes 2014).")

    if profile.read_depth_cv > 0.5:
        _add("rarefaction",
             f"High read depth variability (CV={profile.read_depth_cv:.2f}) — rarefaction curves critical",
             10, "Rarefaction curves show whether samples reached saturation and if depth differences drive diversity differences.")

    # ── Composition overview ────────────────────────────────────────
    _add("phylum_barplot", "Phylum-level overview of community structure",
         9, "Phylum composition provides the broadest view of community structure and is least affected by taxonomic assignment errors.")

    if profile.has_taxonomy:
        _add("genus_barplot", "Genus-level composition is the standard resolution for 16S analysis",
             9, "16S V3-V4 region provides reliable genus-level classification. Species-level is often unreliable.")

        if profile.n_groups >= 2:
            _add("genus_heatmap",
                 "Clustered heatmap reveals sample grouping by taxonomic profile",
                 8, "Hierarchical clustering of samples by genus abundance can independently confirm or refute group separation seen in ordination.")

    # ── Alpha diversity ─────────────────────────────────────────────
    if profile.n_groups >= 2:
        _add("alpha_boxplot",
             f"Group comparison using {alpha_rec.test_name}",
             9, alpha_rec.interpretation_guide)

        if profile.alpha_significant:
            _add("alpha_raincloud",
                 f"Alpha significant (p={profile.alpha_p:.4f}) — raincloud shows full distribution",
                 8, "Raincloud plots combine density, boxplot, and raw data, showing distribution shape that boxplots hide.")

            if profile.n_groups == 2 and "alpha_effectsize" in available_keys:
                _add("alpha_effectsize",
                     "Quantify magnitude of significant alpha difference",
                     8, "Effect size (Cliff's delta) is essential: p-value depends on sample size, effect size does not.")
        else:
            if power["power_level"] in ("low", "very_low"):
                _add("rarefaction",
                     f"Alpha not significant but power is {power['power_level']} — check sampling adequacy",
                     8, f"{power['guidance']}")

    # rarefaction — 重複防止
    already_has_rarefaction = any(d.analysis_key == "rarefaction" for d in decisions)
    if not already_has_rarefaction and not profile.alpha_significant:
        _add("rarefaction", "Check if non-significance is due to insufficient sampling depth",
             7, "If rarefaction curves have not plateaued, observed diversity differences may be artifacts of sequencing depth.")

    # ── Beta diversity ──────────────────────────────────────────────
    ordination_recs = recommend_ordinations(profile)

    if profile.n_groups >= 2:
        _add("pcoa_all",
             f"Primary ordination — {beta_rec.test_name}",
             9, beta_rec.interpretation_guide)

        _add("nmds",
             "NMDS preserves rank order — may reveal patterns PCoA misses",
             7, ORDINATION_GUIDE["NMDS"]["when_to_use"])

        if profile.beta_significant:
            _add("permanova",
                 f"Beta significant (p≈{profile.beta_p:.3f}) — full PERMANOVA with 999 permutations",
                 10, "Preliminary PERMANOVA was significant. Run full version with proper permutation count and report R².")

            _add("beta_dispersion",
                 "CRITICAL: check if PERMANOVA significance is location or dispersion",
                 9, beta_rec.assumptions[1] + ". PERMDISP (betadisper) distinguishes these.")

            _add("sample_dendrogram",
                 "Dendrogram shows hierarchical group structure",
                 6, "UPGMA dendrogram on Bray-Curtis provides an alternative view of sample clustering.")

            if profile.read_depth_cv > 0.3:
                _add("pca_clr",
                     "CLR-PCA for compositionally valid ordination",
                     8, comp["reason"])

        if profile.n_samples >= 20:
            for orec in ordination_recs:
                if orec["method"] == "t-SNE" and orec["score"] >= 5:
                    _add("tsne", "Sufficient samples for t-SNE local structure",
                         5, ORDINATION_GUIDE["t-SNE"]["when_to_use"])
                if orec["method"] == "UMAP" and orec["score"] >= 5:
                    _add("umap_ordination", "UMAP for local+global structure",
                         5, ORDINATION_GUIDE["UMAP"]["when_to_use"])

    # ── Differential abundance ──────────────────────────────────────
    if profile.n_groups >= 2 and profile.high_variance_genera:
        hv = ", ".join(profile.high_variance_genera[:3])

        if profile.n_groups == 2:
            _add("volcano",
                 f"High-variance genera detected ({hv}) — volcano plot with FDR",
                 9, comp.get("differential_reason", "Per-taxon testing with FDR correction."))
            _add("effect_size_forest",
                 "Forest plot quantifies effect sizes for each taxon",
                 8, "Effect sizes (Cliff's delta) are more informative than p-values for differential abundance.")
            _add("ma_plot",
                 "MA plot shows abundance vs fold-change relationship",
                 6, "MA plot reveals if differential abundance is driven by rare or abundant taxa.")

        _add("lefse_style",
             "LEfSe-style analysis ranks biomarker taxa by effect size",
             8, "LDA effect size combines statistical significance with biological relevance (effect magnitude).")

        _add("genus_violin",
             f"Visualize distribution of top differential genera: {hv}",
             7, "Violin plots show the full distribution shape, revealing bimodality or outlier-driven effects.")

        if profile.n_groups >= 3:
            _add("multi_group_differential",
                 "Multi-group comparison with Kruskal-Wallis + Dunn's post-hoc",
                 8, "Pairwise comparisons needed to identify which groups differ for each taxon.")

    # ── Advanced ────────────────────────────────────────────────────
    if profile.n_genera >= 10:
        _add("cooccurrence_network",
             "Explore ecological interactions via genus co-occurrence",
             5, "Co-occurrence networks reveal potential ecological interactions (mutualism, competition). Use Spearman with SparCC-style filtering for compositionality.")

        _add("correlation_clustermap",
             "Genus correlation structure",
             5, "Clustered correlation heatmap identifies modules of co-varying taxa.")

    if profile.n_groups >= 2:
        _add("core_microbiome",
             "Identify core taxa shared across groups",
             6, "Core microbiome (prevalence ≥ 80%) represents the stable community foundation. Compare core between groups.")

        _add("indicator_species",
             "Indicator species analysis identifies group-specific biomarkers",
             6, "IndVal index combines specificity (faithful to one group) and fidelity (present in all samples of that group).")

        if profile.n_groups == 3 and "ternary_plot" in available_keys:
            _add("ternary_plot",
                 "3-group comparison on ternary coordinates",
                 5, "Ternary plot places each taxon based on its relative abundance across 3 groups, revealing group-specific enrichment.")

        _add("upset_shared_taxa",
             "UpSet diagram for shared/unique taxa between groups",
             5, "UpSet plots are superior to Venn diagrams for >2 groups, showing intersection sizes clearly.")

    # ── Publication ─────────────────────────────────────────────────
    _add("composite_main",
         "Publication-ready 4-panel composite figure",
         8, "Composite figure combining key results: composition, diversity, ordination, and differential abundance.")

    _add("statistical_summary_table",
         "Summary table of all statistical tests performed",
         7, "Table 1 of the analysis: test names, statistics, p-values, FDR q-values, effect sizes.")

    # Sort by priority (descending), then by insertion order
    decisions.sort(key=lambda d: -d.priority)
    return decisions
