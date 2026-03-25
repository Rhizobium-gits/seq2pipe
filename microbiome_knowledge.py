#!/usr/bin/env python3
"""
microbiome_knowledge.py
=======================
マイクロバイオーム解析の包括的ドメイン知識モジュール。

AI 駆動解析モードが「なぜその解析を選ぶのか」を判断するための
学術的根拠・決定木・メソッド選択ロジック・生態学的解釈規則を提供する。

カバー領域:
  1. データ品質・前処理の判断基準
  2. 分類学的解析の知識
  3. α多様性メトリクス（Hill numbers 統一フレームワーク）
  4. β多様性メトリクス（回転分割 vs 入れ子構造）
  5. 統計検定の決定木（検出力・仮定・効果量）
  6. 組成データ解析（CLR, ALR, Aitchison）
  7. 順序付け手法の選択ガイド
  8. 差次豊度解析手法の比較（ALDEx2, ANCOM-BC, DESeq2 等）
  9. ネットワーク・相互作用解析
  10. 機械学習手法の適用判断
  11. 生態学的解釈（ディスバイオシス, コアマイクロバイオーム, 機能ギルド）
  12. 研究デザインの評価（バッチ効果, 交絡因子, ケージ効果）
  13. 多重検定補正の選択
  14. 統計的検出力の推定
  15. 解析フロー決定木

参考文献:
  Aitchison (1986) — Compositional data analysis
  Anderson (2001) — PERMANOVA
  Baselga (2010) — Beta diversity partitioning (turnover vs nestedness)
  Callahan et al. (2016) — DADA2
  Chao & Jost (2012) — Coverage-based rarefaction
  Fernandes et al. (2014) — ALDEx2
  Gloor et al. (2017) — Microbiome datasets are compositional
  Hill (1973) — Diversity and evenness: a unifying notation
  Kurtz et al. (2015) — SPIEC-EASI
  Lin & Peddada (2020) — ANCOM-BC
  Love et al. (2014) — DESeq2
  Lozupone & Knight (2005) — UniFrac
  McMurdie & Holmes (2014) — Waste not, want not
  Niku et al. (2019) — GLLVM for multivariate abundance
  Quinn et al. (2018) — Sequencing data as compositions
  Willis (2019) — Rarefaction, alpha diversity, and statistics
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


# ═══════════════════════════════════════════════════════════════════════════════
# データ特性プロファイル（全判断の入力となる統合データ構造）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DataProfile:
    """データの統計的特性プロファイル — 全判断はこのプロファイルから導出される"""
    # サンプル・デザイン
    n_samples: int = 0
    n_groups: int = 0
    min_group_size: int = 0
    max_group_size: int = 0
    is_paired: bool = False
    is_longitudinal: bool = False

    # Feature table 特性
    n_asvs: int = 0
    sparsity: float = 0.0             # 0 の割合 (0.0–1.0)
    read_depth_cv: float = 0.0        # リード深度の変動係数
    min_reads: int = 0
    max_reads: int = 0
    singleton_fraction: float = 0.0   # シングルトン ASV の割合
    goods_coverage_mean: float = 0.0  # Good's coverage 平均

    # 多様性指標
    evenness_mean: float = 0.0        # Pielou's J (0=1種優占, 1=完全均等)
    dominance_mean: float = 0.0       # Simpson's dominance (Σpᵢ²)

    # 分類学
    has_taxonomy: bool = False
    n_genera: int = 0
    unclassified_fraction: float = 0.0  # 分類不能 ASV の割合
    fb_ratio: float = 0.0             # Firmicutes/Bacteroidetes 比
    proteobacteria_fraction: float = 0.0

    # 群間比較結果
    alpha_significant: bool = False
    alpha_p: float = 1.0
    alpha_effect_size: float = 0.0    # Cliff's delta
    beta_significant: bool = False
    beta_p: float = 1.0
    beta_pseudo_f: float = 0.0
    high_variance_genera: list[str] = field(default_factory=list)
    group_composition_shift: float = 0.0

    # データ品質
    chimera_rate: float = 0.0         # キメラ除去率
    merge_rate: float = 0.0           # リードマージ成功率
    denoising_pass_rate: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 1. データ品質・前処理の判断基準
# ═══════════════════════════════════════════════════════════════════════════════

QUALITY_THRESHOLDS = {
    "min_reads_per_sample": {
        "critical": 1000,
        "warning": 5000,
        "good": 10000,
        "interpretation": {
            "critical": "Samples below 1,000 reads should be excluded — insufficient for reliable diversity estimates.",
            "warning": "5,000–10,000 reads: marginal. Rarefaction to common depth will lose many samples.",
            "good": ">10,000 reads: adequate for most 16S analyses.",
        },
    },
    "denoising_pass_rate": {
        "poor": 0.3,
        "acceptable": 0.5,
        "good": 0.7,
        "interpretation": {
            "poor": "<30% pass rate: severe quality issue. Check primer trimming, quality filtering, and read merging.",
            "acceptable": "30–70%: typical for many datasets. Check if losses are at filtering or merging step.",
            "good": ">70%: good quality data.",
        },
    },
    "chimera_rate": {
        "normal": 0.15,
        "high": 0.30,
        "interpretation": {
            "normal": "<15% chimeras: typical for amplicon data.",
            "high": ">30%: unusually high. May indicate PCR issues or contamination.",
        },
    },
    "read_depth_cv": {
        "uniform": 0.3,
        "variable": 0.5,
        "highly_variable": 1.0,
        "interpretation": {
            "uniform": "CV<0.3: uniform sequencing depth. Raw counts are relatively comparable.",
            "variable": "CV 0.3–0.5: moderate variation. Use relative abundance or rarefaction.",
            "highly_variable": "CV>0.5: highly variable. Compositional methods (CLR) recommended. Rarefaction will lose many reads.",
        },
    },
    "sparsity": {
        "low": 0.5,
        "moderate": 0.7,
        "high": 0.85,
        "interpretation": {
            "low": "<50% zeros: relatively dense. Most methods work well.",
            "moderate": "50–70%: typical for genus-level data. Watch for zero-inflation in statistical models.",
            "high": ">85%: highly sparse. Many ASVs present in few samples. Filter low-prevalence features before testing.",
        },
    },
    "goods_coverage": {
        "insufficient": 0.90,
        "adequate": 0.95,
        "good": 0.99,
        "interpretation": {
            "insufficient": "<90%: many species unsampled. Observed richness is unreliable.",
            "adequate": "95–99%: most common species captured. Rare biosphere partially missed.",
            "good": ">99%: excellent coverage. Observed richness is a good estimate.",
        },
    },
}


def assess_data_quality(profile: DataProfile) -> list[dict]:
    """データ品質を多次元で評価し、問題点と推奨事項を返す"""
    issues = []

    # リード深度
    if profile.min_reads < QUALITY_THRESHOLDS["min_reads_per_sample"]["critical"]:
        issues.append({
            "category": "read_depth",
            "severity": "critical",
            "finding": f"Minimum reads per sample = {profile.min_reads:,}",
            "interpretation": QUALITY_THRESHOLDS["min_reads_per_sample"]["interpretation"]["critical"],
            "action": "Exclude samples below 1,000 reads before any analysis.",
        })
    elif profile.min_reads < QUALITY_THRESHOLDS["min_reads_per_sample"]["warning"]:
        issues.append({
            "category": "read_depth",
            "severity": "warning",
            "finding": f"Minimum reads per sample = {profile.min_reads:,}",
            "interpretation": QUALITY_THRESHOLDS["min_reads_per_sample"]["interpretation"]["warning"],
            "action": "Consider rarefaction to common depth. Report excluded samples.",
        })

    # リード深度の不均一性
    if profile.read_depth_cv > QUALITY_THRESHOLDS["read_depth_cv"]["highly_variable"]:
        issues.append({
            "category": "depth_uniformity",
            "severity": "warning",
            "finding": f"Read depth CV = {profile.read_depth_cv:.2f}",
            "interpretation": QUALITY_THRESHOLDS["read_depth_cv"]["interpretation"]["highly_variable"],
            "action": "Use CLR transform or rarefaction. Report depth range.",
        })

    # スパース度
    if profile.sparsity > QUALITY_THRESHOLDS["sparsity"]["high"]:
        issues.append({
            "category": "sparsity",
            "severity": "warning",
            "finding": f"Feature table sparsity = {profile.sparsity:.0%}",
            "interpretation": QUALITY_THRESHOLDS["sparsity"]["interpretation"]["high"],
            "action": "Filter ASVs with prevalence < 5–10% before statistical testing.",
        })

    # デノイジング
    if profile.denoising_pass_rate > 0 and profile.denoising_pass_rate < QUALITY_THRESHOLDS["denoising_pass_rate"]["poor"]:
        issues.append({
            "category": "denoising",
            "severity": "critical",
            "finding": f"Denoising pass rate = {profile.denoising_pass_rate:.0%}",
            "interpretation": QUALITY_THRESHOLDS["denoising_pass_rate"]["interpretation"]["poor"],
            "action": "Check DADA2 parameters: trunc_len may be too aggressive, or quality is very low.",
        })

    # 均等度（多様性の偏り）
    if profile.dominance_mean > 0.5:
        issues.append({
            "category": "dominance",
            "severity": "info",
            "finding": f"Mean Simpson's dominance = {profile.dominance_mean:.3f}",
            "interpretation": "Community is dominated by few taxa. Shannon diversity may not capture the full picture.",
            "action": "Include Simpson's diversity alongside Shannon. Check for pathobiont dominance.",
        })

    # シングルトン
    if profile.singleton_fraction > 0.5:
        issues.append({
            "category": "singletons",
            "severity": "warning",
            "finding": f"Singleton ASVs = {profile.singleton_fraction:.0%}",
            "interpretation": "Over half of ASVs appear in only one sample. May inflate richness estimates.",
            "action": "Filter singletons for diversity analysis. Keep for differential abundance (rare taxa may be real).",
        })

    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 分類学的解析の知識
# ═══════════════════════════════════════════════════════════════════════════════

TAXONOMY_KNOWLEDGE = {
    "marker_regions": {
        "V3-V4": {
            "resolution": "genus (reliable), species (limited)",
            "amplicon_length": "~460 bp",
            "taxonomic_coverage": "Broad bacterial coverage. Standard for human/animal microbiome.",
            "limitations": "Poor resolution for some genera (Clostridium sensu lato).",
        },
        "V4": {
            "resolution": "genus (reliable), species (very limited)",
            "amplicon_length": "~253 bp",
            "taxonomic_coverage": "Earth Microbiome Project standard. Good cross-study comparability.",
            "limitations": "Shorter region = less taxonomic resolution than V3-V4.",
        },
        "V1-V2": {
            "resolution": "genus-species (better for some taxa)",
            "amplicon_length": "~330 bp",
            "taxonomic_coverage": "Better resolution for Staphylococcus, Streptococcus.",
            "limitations": "Less commonly used. Database coverage may vary.",
        },
        "ITS": {
            "resolution": "species (for fungi)",
            "amplicon_length": "variable (200–600 bp)",
            "taxonomic_coverage": "Fungal community profiling (ITS1 or ITS2).",
            "limitations": "Variable length complicates alignment-based methods.",
        },
    },
    "confidence_thresholds": {
        "high": 0.9,
        "moderate": 0.7,
        "low": 0.5,
        "interpretation": (
            "QIIME2 Naive Bayes classifier confidence. >0.9: reliable. "
            "0.7–0.9: genus-level usually ok, species questionable. "
            "<0.7: treat with caution, report as 'unclassified' at that level."
        ),
    },
    "biological_markers": {
        "fb_ratio": {
            "name": "Firmicutes/Bacteroidetes ratio",
            "significance": (
                "Historically linked to obesity and metabolic health in humans. "
                "F/B > 2 sometimes associated with obesity, but this is oversimplified "
                "and dataset-dependent. Do NOT over-interpret."
            ),
            "when_to_report": "Human/mouse gut studies focused on metabolic phenotypes.",
        },
        "proteobacteria_bloom": {
            "name": "Proteobacteria expansion",
            "significance": (
                "Elevated Proteobacteria (>15–20% in gut) is a potential marker of "
                "dysbiosis and inflammation (Shin et al. 2015). Includes many facultative "
                "anaerobes that thrive in oxidative stress."
            ),
            "when_to_report": "When Proteobacteria relative abundance is notably high.",
        },
        "scfa_producers": {
            "name": "Short-chain fatty acid producer guilds",
            "key_genera": ["Faecalibacterium", "Roseburia", "Coprococcus", "Eubacterium", "Butyricicoccus"],
            "significance": "SCFA producers (butyrate, propionate, acetate) are associated with gut health and anti-inflammatory effects.",
        },
        "pathobionts": {
            "name": "Potential pathobionts",
            "key_genera": ["Escherichia", "Klebsiella", "Enterococcus", "Clostridium", "Clostridioides"],
            "significance": "Normally present at low abundance but can bloom during dysbiosis or antibiotic treatment.",
        },
    },
    "unclassified_interpretation": {
        "threshold_warning": 0.20,
        "interpretation": (
            "If >20% of reads are unclassified at genus level, consider: "
            "(1) database choice (SILVA vs Greengenes2 vs GTDB), "
            "(2) classification method, (3) non-target amplification. "
            "Unclassified taxa are real organisms — do not discard them from diversity analyses."
        ),
    },
}


def assess_taxonomy(profile: DataProfile) -> list[dict]:
    """分類学的特性を評価"""
    findings = []

    if profile.unclassified_fraction > TAXONOMY_KNOWLEDGE["unclassified_interpretation"]["threshold_warning"]:
        findings.append({
            "category": "taxonomy",
            "finding": f"Unclassified fraction = {profile.unclassified_fraction:.0%}",
            "interpretation": TAXONOMY_KNOWLEDGE["unclassified_interpretation"]["interpretation"],
            "action": "Consider alternative classifier or database.",
        })

    if profile.proteobacteria_fraction > 0.15:
        findings.append({
            "category": "biology",
            "finding": f"Proteobacteria = {profile.proteobacteria_fraction:.0%}",
            "interpretation": TAXONOMY_KNOWLEDGE["biological_markers"]["proteobacteria_bloom"]["significance"],
            "action": "Investigate Proteobacteria at genus level. Check for Enterobacteriaceae bloom.",
        })

    if profile.fb_ratio > 0:
        findings.append({
            "category": "biology",
            "finding": f"Firmicutes/Bacteroidetes ratio = {profile.fb_ratio:.1f}",
            "interpretation": TAXONOMY_KNOWLEDGE["biological_markers"]["fb_ratio"]["significance"],
            "action": "Report F/B ratio but do not over-interpret. Compare within-study, not across studies.",
        })

    return findings


# ═══════════════════════════════════════════════════════════════════════════════
# 3. α多様性 — Hill numbers 統一フレームワーク
# ═══════════════════════════════════════════════════════════════════════════════

ALPHA_METRICS = {
    "observed_features": {
        "hill_order": 0,
        "full_name": "Observed ASVs (Hill q=0, species richness)",
        "measures": "richness only",
        "formula": "⁰D = S (count of species with abundance > 0)",
        "sensitivity": "Equally weights all species regardless of abundance. Most sensitive to rare taxa and sequencing depth.",
        "requires_rarefaction": True,
    },
    "shannon": {
        "hill_order": 1,
        "full_name": "Shannon entropy H' (related to Hill q=1)",
        "measures": "richness + evenness",
        "formula": "H' = -Σ pᵢ ln(pᵢ);  ¹D = exp(H')",
        "sensitivity": "Weighs species by relative abundance. Moderately sensitive to rare taxa.",
        "requires_rarefaction": True,
    },
    "simpson": {
        "hill_order": 2,
        "full_name": "Simpson's index 1-D (related to Hill q=2)",
        "measures": "evenness, dominance-weighted",
        "formula": "1-D = 1 - Σ pᵢ²;  ²D = 1/Σpᵢ²",
        "sensitivity": "Dominated by abundant species. Robust to rare taxa and sequencing depth.",
        "requires_rarefaction": False,
    },
    "faith_pd": {
        "hill_order": None,
        "full_name": "Faith's Phylogenetic Diversity",
        "measures": "phylogenetic richness",
        "formula": "PD = sum of branch lengths spanning observed taxa",
        "sensitivity": "Phylogenetically informed richness. Two related species contribute less than two distant ones.",
        "requires_rarefaction": True,
    },
    "chao1": {
        "hill_order": 0,
        "full_name": "Chao1 richness estimator",
        "measures": "estimated true richness (including unobserved)",
        "formula": "Ŝ = S_obs + f₁²/(2f₂)",
        "sensitivity": "Extrapolates total richness from singletons/doubletons. Robust to incomplete sampling.",
        "requires_rarefaction": False,
    },
    "pielou_e": {
        "hill_order": None,
        "full_name": "Pielou's evenness J'",
        "measures": "evenness only (independent of richness)",
        "formula": "J' = H' / ln(S)",
        "sensitivity": "Pure evenness measure. 0=one species dominates, 1=perfectly even.",
        "requires_rarefaction": True,
    },
}

HILL_NUMBER_FRAMEWORK = """
Hill numbers unify diversity indices on a single scale:
  q=0: Observed richness (equally weights all species)
  q=1: Exponential of Shannon (weighs by abundance proportionally)
  q=2: Inverse Simpson (emphasizes dominant species)
  q→∞: Berger-Parker (only the most dominant species)

As q increases, the index becomes less sensitive to rare species.
Plotting ⁰D, ¹D, ²D together reveals whether diversity differences
are driven by rare taxa (large gap at q=0) or dominant taxa (gap at q=2).
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 4. β多様性 — 回転分割 vs 入れ子構造
# ═══════════════════════════════════════════════════════════════════════════════

BETA_METRICS = {
    "bray_curtis": {
        "type": "quantitative, non-phylogenetic",
        "formula": "BC = Σ|xᵢ-yᵢ| / Σ(xᵢ+yᵢ)",
        "what_it_captures": "Compositional dissimilarity based on abundance differences.",
        "sensitive_to": "Dominant taxa. Less affected by rare species.",
        "is_compositional": False,
    },
    "jaccard": {
        "type": "qualitative (presence/absence), non-phylogenetic",
        "formula": "J = 1 - |A∩B| / |A∪B|",
        "what_it_captures": "Shared vs unique taxa (ignores abundance).",
        "sensitive_to": "Rare taxa presence/absence. Very sensitive to sequencing depth.",
        "is_compositional": False,
    },
    "unweighted_unifrac": {
        "type": "qualitative, phylogenetic",
        "formula": "UF = unique_branch_lengths / total_branch_lengths",
        "what_it_captures": "Which evolutionary lineages are present vs absent.",
        "sensitive_to": "Rare lineages. Detects community membership differences.",
        "is_compositional": False,
    },
    "weighted_unifrac": {
        "type": "quantitative, phylogenetic",
        "formula": "WUF = Σ|pᵢ-qᵢ| × bᵢ / Σ bᵢ",
        "what_it_captures": "Abundance-weighted phylogenetic dissimilarity.",
        "sensitive_to": "Dominant lineages. Robust to rare taxa noise.",
        "is_compositional": False,
    },
    "aitchison": {
        "type": "quantitative, compositional",
        "formula": "d = ||clr(x) - clr(y)||₂",
        "what_it_captures": "Compositionally valid distance (Aitchison geometry).",
        "sensitive_to": "Log-ratio differences. Handles compositionality correctly.",
        "is_compositional": True,
    },
}

BETA_PARTITIONING = """
Beta diversity can be partitioned (Baselga 2010):
  β_total = β_turnover + β_nestedness

  - Turnover: species replacement between sites
    (site A has sp1, site B has sp2 instead)
  - Nestedness: species loss/gain
    (site B is a subset of site A)

If β_turnover >> β_nestedness: communities have different compositions.
If β_nestedness >> β_turnover: one group is a subset of another (e.g., diversity loss).
This distinction is critical for interpreting antibiotic/disease effects:
  - Antibiotic treatment often causes nestedness (diversity loss)
  - Different environments often cause turnover (species replacement)
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 統計検定の決定木
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestRecommendation:
    """統計検定の推奨"""
    test_name: str
    reason: str
    assumptions: list[str]
    alternatives: list[str]
    interpretation_guide: str
    effect_size_method: str = ""
    python_implementation: str = ""


def recommend_alpha_test(profile: DataProfile) -> TestRecommendation:
    """α多様性の適切な検定を推奨"""
    if profile.n_groups < 2:
        return TestRecommendation(
            test_name="Descriptive statistics only",
            reason="Only 1 group — no comparison possible",
            assumptions=[], alternatives=[],
            interpretation_guide="Report mean ± SD, median, range, and rarefaction curves.",
        )

    if profile.n_groups == 2:
        if profile.is_paired:
            return TestRecommendation(
                test_name="Wilcoxon signed-rank test" + (" (exact)" if profile.min_group_size < 20 else ""),
                reason=f"2 paired groups, n={profile.min_group_size}",
                assumptions=["Paired observations", "Symmetric difference distribution"],
                alternatives=["Paired t-test (if normal)", "Permutation test"],
                interpretation_guide=(
                    "Tests median of paired differences. Report W, p-value, and matched-pairs r = Z/√N. "
                    + ("SMALL SAMPLE: use exact p-value. " if profile.min_group_size < 20 else "")
                ),
                effect_size_method="matched_pairs_rank_biserial: r = Z / sqrt(N)",
            )
        else:
            return TestRecommendation(
                test_name="Mann-Whitney U test" + (" (exact)" if profile.min_group_size < 20 else ""),
                reason=f"2 independent groups, n_min={profile.min_group_size}",
                assumptions=["Independent samples", "Similar distribution shapes"],
                alternatives=["Welch's t-test (if normal)", "Permutation test", "Bootstrap CI"],
                interpretation_guide=(
                    "Tests if one group tends to have larger values. "
                    "Report U, p-value, and Cliff's delta. "
                    "Cliff's delta: |d|<0.147 negligible, <0.33 small, <0.474 medium, else large. "
                    + (f"WARNING: n={profile.min_group_size} has very low power. "
                       "Non-significant p ≠ no effect. Always report effect sizes. "
                       if profile.min_group_size < 5 else "")
                ),
                effect_size_method="Cliff's delta: d = (Σ sign(xᵢ-yⱼ)) / (n₁×n₂)",
            )

    # 3+ groups
    if profile.is_paired:
        return TestRecommendation(
            test_name="Friedman test + Nemenyi post-hoc",
            reason=f"{profile.n_groups} paired/repeated groups",
            assumptions=["Repeated measures on same subjects", "Ordinal or continuous data"],
            alternatives=["Repeated measures ANOVA (if normal)", "Aligned rank transform ANOVA"],
            interpretation_guide=(
                "Friedman tests overall difference. If significant, Nemenyi identifies which pairs differ. "
                "Report χ², df, p-value, and pairwise p-values. "
                "Effect size: Kendall's W (concordance coefficient)."
            ),
            effect_size_method="Kendall's W = χ² / (N × (k-1))",
        )
    else:
        return TestRecommendation(
            test_name="Kruskal-Wallis H + Dunn's post-hoc (Bonferroni)",
            reason=f"{profile.n_groups} independent groups",
            assumptions=["Independent samples", "Similar shapes across groups"],
            alternatives=["One-way ANOVA + Tukey HSD (if normal)", "Permutation ANOVA"],
            interpretation_guide=(
                "KW tests overall difference. If p<0.05, Dunn's for pairwise with Bonferroni correction. "
                "Report H, df, p-value, pairwise adjusted p. "
                "Effect size: ε² = H / (n-1). Small: 0.01, medium: 0.06, large: 0.14."
            ),
            effect_size_method="epsilon_squared: ε² = H / (N - 1)",
        )


def recommend_beta_test(profile: DataProfile) -> TestRecommendation:
    """β多様性の群間比較"""
    if profile.n_groups < 2:
        return TestRecommendation(
            test_name="No group comparison",
            reason="Single group — ordination for exploration only",
            assumptions=[], alternatives=[],
            interpretation_guide="Use PCoA/NMDS to visualize community structure.",
        )

    assumptions = [
        "Independent samples (or stratify for nested designs)",
        "CRITICAL: Groups must have similar multivariate dispersion (homogeneity of variances). "
        "A significant PERMANOVA can mean centroid difference OR dispersion difference. "
        "ALWAYS run PERMDISP (betadisper) to distinguish these.",
    ]
    if profile.min_group_size < 5:
        assumptions.append(
            f"WARNING: n_min={profile.min_group_size}. PERMANOVA with very small groups "
            "has low power and p-values may be unreliable. Use ≥999 permutations."
        )

    return TestRecommendation(
        test_name="PERMANOVA (Anderson, 2001) + PERMDISP",
        reason=f"{profile.n_groups} groups, n={profile.n_samples}",
        assumptions=assumptions,
        alternatives=[
            "ANOSIM (rank-based, less powerful)",
            "MRPP (Multi-Response Permutation Procedure)",
            "db-RDA (distance-based RDA, for continuous covariates)",
            "adonis2 in R (PERMANOVA with covariates)",
        ],
        interpretation_guide=(
            "PERMANOVA pseudo-F = (SS_between/df_between) / (SS_within/df_within). "
            "Report: pseudo-F, R² (effect size), p-value (from 999+ permutations). "
            "R² interpretation: 0.05–0.10 small, 0.10–0.25 medium, >0.25 large. "
            "ALWAYS pair with PERMDISP to check dispersion homogeneity."
        ),
        effect_size_method="R² = SS_between / SS_total",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 組成データ解析
# ═══════════════════════════════════════════════════════════════════════════════

COMPOSITIONAL_DATA_THEORY = """
Key principle (Aitchison 1986, Gloor et al. 2017):
  Microbiome data is COMPOSITIONAL — relative abundances sum to 1.
  This means:
  - Standard correlation (Pearson/Spearman) produces spurious negative correlations
  - Euclidean distance is inappropriate for relative abundance
  - Standard statistical tests on proportions can be misleading

Solutions:
  1. CLR (Centered Log-Ratio): clr(x) = ln(x/g(x)) where g = geometric mean
     - Preserves subcompositional coherence
     - Euclidean distance on CLR = Aitchison distance
     - Requires pseudocount for zeros (typically 0.5 or 1/n_features)

  2. ALR (Additive Log-Ratio): alr(x) = ln(xᵢ/x_ref)
     - Requires choosing a reference taxon
     - Interpretable as fold-change relative to reference

  3. ILR (Isometric Log-Ratio): orthonormal basis in simplex
     - Mathematically rigorous but hard to interpret

  4. PhILR (Phylogenetic ILR): uses phylogenetic tree as basis
     - Biologically informed ILR coordinates

When to use CLR:
  - PCA/ordination on abundance data
  - Correlation analysis between taxa
  - Differential abundance testing (ALDEx2 approach)

When CLR is NOT needed:
  - Bray-Curtis distance (already handles compositionality for ordination)
  - UniFrac (phylogenetic, designed for abundance data)
  - PERMANOVA on Bray-Curtis (valid without CLR)
"""


def recommend_compositional_method(profile: DataProfile) -> dict:
    """組成データ特性に基づいて手法を推奨"""
    result = {
        "transform": "none",
        "reason": "",
        "ordination": "PCoA on Bray-Curtis",
        "differential_method": "",
        "differential_reason": "",
        "correlation_method": "",
        "warnings": [],
    }

    if profile.sparsity > 0.85:
        result["warnings"].append(
            f"Very high sparsity ({profile.sparsity:.0%} zeros). "
            "Filter ASVs with prevalence <5% before CLR transform (zeros need pseudocount). "
            "For differential abundance, use methods robust to zeros (ANCOM-BC, Bray-Curtis-based tests)."
        )

    if profile.read_depth_cv > 0.5:
        result["transform"] = "CLR"
        result["reason"] = (
            f"High read depth variability (CV={profile.read_depth_cv:.2f}). "
            "CLR transform recommended: removes compositional bias and normalizes for depth."
        )
        result["ordination"] = "PCA on CLR (= Aitchison distance PCoA)"
        result["correlation_method"] = "Spearman on CLR-transformed data (or SparCC for strict compositionality)"
    else:
        result["transform"] = "relative_abundance"
        result["reason"] = "Read depth relatively uniform. Relative abundance normalization sufficient."
        result["correlation_method"] = "Spearman on relative abundance (note: may have spurious negative correlations)"

    # 差次豊度手法の選択
    if profile.n_groups >= 2:
        if profile.min_group_size >= 15:
            result["differential_method"] = "ALDEx2-style (Dirichlet Monte Carlo → CLR → Welch's t / Wilcoxon)"
            result["differential_reason"] = (
                "Adequate sample size. ALDEx2 properly handles compositionality via "
                "Monte Carlo sampling from Dirichlet distribution → CLR → per-taxon testing. "
                "BH-FDR correction across taxa."
            )
        elif profile.min_group_size >= 5:
            result["differential_method"] = "Mann-Whitney per genus on relative abundance + BH-FDR"
            result["differential_reason"] = (
                f"n={profile.min_group_size}: non-parametric per-taxon test with FDR correction. "
                "Report effect sizes (fold-change + Cliff's delta) alongside p-values."
            )
        else:
            result["differential_method"] = "Descriptive only (fold-change + CI, no formal testing)"
            result["differential_reason"] = (
                f"n={profile.min_group_size} too small for reliable per-taxon testing. "
                "Report log2 fold-changes with bootstrap confidence intervals."
            )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 順序付け手法
# ═══════════════════════════════════════════════════════════════════════════════

ORDINATION_GUIDE = {
    "PCoA": {
        "full_name": "Principal Coordinates Analysis (metric MDS)",
        "input": "Distance matrix",
        "preserves": "Metric distances between samples",
        "when_to_use": "Default ordination. Reports % variance explained per axis.",
        "limitations": "Negative eigenvalues possible with non-Euclidean metrics.",
        "recommendation_score": lambda p: 10,
    },
    "NMDS": {
        "full_name": "Non-Metric Multidimensional Scaling",
        "input": "Distance matrix",
        "preserves": "Rank order of distances",
        "when_to_use": "When rank order matters. Report stress (<0.2 acceptable, <0.1 good).",
        "limitations": "Non-deterministic. No variance explained. Use multiple random starts.",
        "recommendation_score": lambda p: 8,
    },
    "PCA_CLR": {
        "full_name": "PCA on CLR-transformed abundances",
        "input": "Feature table (CLR)",
        "preserves": "Aitchison distance (compositionally valid)",
        "when_to_use": "When compositional bias is concern. Allows biplot (taxon loading arrows).",
        "limitations": "Requires pseudocount for zeros.",
        "recommendation_score": lambda p: 9 if p.read_depth_cv > 0.3 else 6,
    },
    "t-SNE": {
        "full_name": "t-distributed Stochastic Neighbor Embedding",
        "input": "Distance matrix",
        "preserves": "Local structure only",
        "when_to_use": "Cluster visualization. DO NOT interpret inter-cluster distances.",
        "limitations": "Non-deterministic. Perplexity-sensitive. Only local structure preserved.",
        "recommendation_score": lambda p: 7 if p.n_samples >= 30 else 3,
    },
    "UMAP": {
        "full_name": "Uniform Manifold Approximation and Projection",
        "input": "Distance matrix",
        "preserves": "Local + some global structure",
        "when_to_use": "Similar to t-SNE but better global structure preservation.",
        "limitations": "Hyperparameter-sensitive (n_neighbors, min_dist).",
        "recommendation_score": lambda p: 7 if p.n_samples >= 20 else 3,
    },
}


def recommend_ordinations(profile: DataProfile) -> list[dict]:
    """順序付け手法を推奨順で返す"""
    recs = []
    for name, info in ORDINATION_GUIDE.items():
        score = info["recommendation_score"](profile)
        recs.append({"method": name, "score": score, "reason": info["when_to_use"]})
    return sorted(recs, key=lambda x: -x["score"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 差次豊度解析手法の比較
# ═══════════════════════════════════════════════════════════════════════════════

DIFFERENTIAL_ABUNDANCE_METHODS = {
    "aldex2": {
        "name": "ALDEx2 (Fernandes et al. 2014)",
        "approach": "Compositional (Dirichlet → CLR → per-taxon test)",
        "strengths": "Properly handles compositionality. Low false positive rate.",
        "weaknesses": "Conservative (may miss subtle effects). Requires >10 samples/group.",
        "when_to_use": "Default recommendation for compositional-aware differential abundance.",
    },
    "ancom_bc": {
        "name": "ANCOM-BC (Lin & Peddada 2020)",
        "approach": "Bias correction for compositionality + linear model",
        "strengths": "Estimates absolute abundance changes. Handles covariates.",
        "weaknesses": "Assumes compositionality bias is uniform across taxa.",
        "when_to_use": "When you want to estimate absolute (not relative) changes.",
    },
    "deseq2": {
        "name": "DESeq2 (Love et al. 2014)",
        "approach": "Negative binomial GLM on raw counts",
        "strengths": "Well-tested. Handles low counts with shrinkage estimators.",
        "weaknesses": "Not designed for compositional data. Higher false positive rate for microbiome.",
        "when_to_use": "When compositionality is less of a concern (e.g., low-diversity environments).",
    },
    "mann_whitney_fdr": {
        "name": "Mann-Whitney U per taxon + BH-FDR",
        "approach": "Non-parametric per-taxon test on relative abundance",
        "strengths": "Simple, interpretable, no distributional assumptions.",
        "weaknesses": "Does not account for compositionality. Lower power with FDR correction.",
        "when_to_use": "Quick exploration. Always pair with effect sizes (fold-change, Cliff's delta).",
    },
    "lefse": {
        "name": "LEfSe (LDA Effect Size)",
        "approach": "KW test → pairwise Wilcoxon → LDA effect size",
        "strengths": "Combines statistical significance with biological effect size.",
        "weaknesses": "Not compositionally aware. LDA step can be unstable with few features.",
        "when_to_use": "When ranking biomarker taxa by effect magnitude.",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ネットワーク解析
# ═══════════════════════════════════════════════════════════════════════════════

NETWORK_ANALYSIS = {
    "spearman_correlation": {
        "method": "Pairwise Spearman on relative abundance",
        "issue": "Spurious negative correlations due to compositionality.",
        "when_ok": "Quick exploration. Use with caution.",
    },
    "sparcc": {
        "method": "SparCC (Friedman & Alm 2012)",
        "approach": "Iterative estimation of true correlation from compositional data.",
        "when_to_use": "Gold standard for compositional correlation. Computationally expensive.",
    },
    "spiec_easi": {
        "method": "SPIEC-EASI (Kurtz et al. 2015)",
        "approach": "Sparse inverse covariance estimation on CLR data.",
        "when_to_use": "When you want conditional dependencies (direct interactions only).",
    },
    "topology_metrics": {
        "modularity": "Community structure within the network. High modularity = distinct microbial guilds.",
        "hub_taxa": "Nodes with high degree/betweenness centrality = potential keystone species.",
        "clustering_coefficient": "Local connectivity. High = taxa tend to co-occur in clusters.",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 機械学習の適用判断
# ═══════════════════════════════════════════════════════════════════════════════

def recommend_ml_approach(profile: DataProfile) -> dict:
    """機械学習の適用可能性を判断"""
    if profile.min_group_size < 10:
        return {
            "feasible": False,
            "reason": (
                f"n={profile.min_group_size} per group is insufficient for reliable ML classification. "
                "With p >> n (features >> samples), overfitting is almost certain. "
                "Stick to univariate statistical tests."
            ),
        }

    if profile.min_group_size < 30:
        return {
            "feasible": True,
            "method": "Random Forest with Leave-One-Out or repeated 5-fold CV",
            "reason": (
                f"n={profile.min_group_size}: ML is possible but requires careful cross-validation. "
                "Use LOOCV or repeated stratified k-fold. Report mean ± SD accuracy. "
                "Feature importance ranking is more valuable than classification accuracy."
            ),
            "warnings": [
                "Do NOT report accuracy from a single train/test split.",
                "Use permutation importance, not impurity-based importance.",
                "p >> n: pre-filter to top 50–100 taxa by variance before fitting.",
            ],
        }

    return {
        "feasible": True,
        "method": "Random Forest with stratified 10-fold CV; consider also XGBoost",
        "reason": (
            f"n={profile.min_group_size}: adequate for ML classification. "
            "Use stratified 10-fold CV. Report AUC-ROC in addition to accuracy. "
            "Feature importance identifies potential biomarkers."
        ),
        "warnings": [
            "Always compare ML accuracy against random baseline.",
            "Report feature importance with confidence intervals (permutation-based).",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. 生態学的解釈
# ═══════════════════════════════════════════════════════════════════════════════

ECOLOGICAL_CONCEPTS = {
    "core_microbiome": {
        "definition": "Taxa present in ≥X% of samples (typically 80–100%).",
        "significance": "Core taxa represent the stable community foundation. Transient taxa appear sporadically.",
        "analysis": "Compare core taxa between groups. Reduced core = potential dysbiosis.",
    },
    "dysbiosis": {
        "indicators": [
            "Decreased alpha diversity (Shannon, observed ASVs)",
            "Elevated Proteobacteria (especially Enterobacteriaceae)",
            "Loss of obligate anaerobes (Faecalibacterium, Roseburia)",
            "Reduced evenness (few taxa dominate)",
            "Increased between-subject variability (beta dispersion)",
        ],
        "caution": "Dysbiosis is a descriptive term, not a diagnosis. Always define criteria explicitly.",
    },
    "species_abundance_distribution": {
        "lognormal": "Most natural communities follow a lognormal SAD. Deviation may indicate disturbance.",
        "logseries": "Characteristic of communities with many rare species (Fisher's alpha).",
        "rank_abundance": "Steep curve = dominated by few species. Flat curve = even community.",
    },
    "ecological_succession": {
        "relevance": "In longitudinal studies, community changes may follow succession patterns.",
        "analysis": "Plot beta diversity vs time. Use trajectory analysis (PCoA animation or arrows).",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 12. 研究デザインの評価
# ═══════════════════════════════════════════════════════════════════════════════

STUDY_DESIGN_CHECKS = {
    "batch_effects": {
        "description": "Systematic technical variation between sequencing runs/extraction batches.",
        "detection": "PCoA colored by batch. If batches cluster separately, batch effect is present.",
        "solutions": [
            "Include batch as covariate in statistical models (PERMANOVA with strata)",
            "Use ComBat or similar batch correction (controversial for microbiome)",
            "Best: randomize samples across batches during wet lab",
        ],
    },
    "confounding": {
        "description": "Variables correlated with the treatment that independently affect the microbiome.",
        "common_confounders": ["age", "sex", "BMI", "diet", "medication", "cage/housing"],
        "detection": "Check metadata for variables that differ between groups.",
        "solutions": ["Stratified analysis", "Include as covariates in models", "Match or block"],
    },
    "cage_effect": {
        "description": "In animal studies, mice in the same cage share microbiomes via coprophagy.",
        "impact": "Cage is a confounder — samples within a cage are not independent.",
        "solution": "Use cage as random effect or stratification variable. Report cage structure.",
    },
    "technical_vs_biological_replicates": {
        "technical": "Same biological sample sequenced multiple times. Tests reproducibility.",
        "biological": "Different individuals/samples. Tests biological variation.",
        "mistake": "Treating technical replicates as biological replicates inflates sample size.",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 13. 多重検定補正
# ═══════════════════════════════════════════════════════════════════════════════

MULTIPLE_TESTING = {
    "bonferroni": {
        "method": "Bonferroni correction: α_adj = α / m",
        "controls": "Family-wise error rate (FWER)",
        "when_to_use": "Conservative. Use when false positives are very costly.",
        "limitation": "Very conservative with many tests. Often no significant results.",
    },
    "holm": {
        "method": "Holm-Bonferroni (step-down procedure)",
        "controls": "FWER (less conservative than Bonferroni)",
        "when_to_use": "Preferred over Bonferroni — uniformly more powerful with same FWER control.",
    },
    "bh_fdr": {
        "method": "Benjamini-Hochberg FDR correction",
        "controls": "False Discovery Rate (expected proportion of false positives among rejections)",
        "when_to_use": "Standard for microbiome differential abundance. FDR < 0.05 means ≤5% of discoveries are false.",
        "limitation": "Assumes independence or positive dependence of p-values.",
    },
    "by_fdr": {
        "method": "Benjamini-Yekutieli FDR correction",
        "controls": "FDR under arbitrary dependence",
        "when_to_use": "When taxa are strongly correlated (which they always are in microbiome data).",
        "limitation": "More conservative than BH.",
    },
    "recommendation": (
        "For microbiome differential abundance: BH-FDR (q < 0.05) is standard. "
        "For pairwise post-hoc tests: Bonferroni or Holm. "
        "Always report BOTH raw p-values AND adjusted q-values."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# 14. 統計的検出力
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_power_context(profile: DataProfile) -> dict:
    """検出力の文脈情報"""
    n = profile.min_group_size

    if n >= 30:
        level, guidance = "adequate", (
            "Adequate for most analyses. Standard non-parametric tests have reasonable power. "
            "FDR correction feasible. Consider multivariate methods (PERMANOVA, ML).")
    elif n >= 10:
        level, guidance = "moderate", (
            f"n={n}: moderate power. Detects large effects (d≈0.8). "
            "May miss subtle differences. Focus on effect sizes alongside p-values.")
    elif n >= 5:
        level, guidance = "low", (
            f"n={n}: low power. Only extreme effects detectable (d≈1.2+). "
            "ALWAYS report effect sizes. Non-significant p ≠ no effect. "
            "This is a pilot study — frame conclusions accordingly.")
    else:
        level, guidance = "very_low", (
            f"n={n}: very low power. Formal testing unreliable. "
            "Focus on descriptive statistics, effect sizes, and confidence intervals. "
            "Do NOT over-interpret p-values. Report as exploratory.")

    return {"power_level": level, "guidance": guidance, "n_per_group": n}


# ═══════════════════════════════════════════════════════════════════════════════
# 15. 解析フロー決定木 — 全知識を統合して解析戦略を生成
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AnalysisDecision:
    """1つの解析決定"""
    analysis_key: str
    reason: str
    priority: int
    domain_rationale: str


def build_domain_driven_plan(
    profile: DataProfile,
    research_question: str,
    available_keys: set[str],
) -> list[AnalysisDecision]:
    """全ドメイン知識を統合して解析プランを構築"""
    decisions: list[AnalysisDecision] = []
    power = estimate_power_context(profile)
    comp = recommend_compositional_method(profile)
    alpha_rec = recommend_alpha_test(profile)
    beta_rec = recommend_beta_test(profile)
    quality_issues = assess_data_quality(profile)
    taxonomy_findings = assess_taxonomy(profile)
    ml_rec = recommend_ml_approach(profile)

    def _add(key: str, reason: str, priority: int, rationale: str):
        if key in available_keys and not any(d.analysis_key == key for d in decisions):
            decisions.append(AnalysisDecision(key, reason, priority, rationale))

    # ── 1. Quality checks (always first) ────────────────────────────
    _add("dada2_stats", "Quality assessment is always the first step",
         10, "DADA2 stats reveal filtering/merging/chimera issues before downstream analysis.")
    _add("read_depth", "Sequencing depth determines which analyses are valid",
         10, "Uneven depth creates spurious diversity differences (McMurdie & Holmes 2014).")

    has_depth_issue = any(q["category"] == "read_depth" for q in quality_issues)
    has_depth_cv_issue = profile.read_depth_cv > 0.5

    if has_depth_issue or has_depth_cv_issue:
        _add("rarefaction",
             f"Read depth issue detected (CV={profile.read_depth_cv:.2f}) — rarefaction curves critical",
             10, "Must check if observed diversity differences are artifacts of unequal sequencing depth.")

    _add("asv_frequency", "ASV frequency distribution reveals data structure",
         7, "Histogram of ASV total counts identifies singletons, rare taxa proportion, and potential contaminants.")

    # ── 2. Composition overview ─────────────────────────────────────
    _add("phylum_barplot", "Phylum overview — broadest taxonomic view",
         9, "Phylum composition is least affected by taxonomic misassignment. "
         "Reveals Firmicutes/Bacteroidetes ratio and Proteobacteria levels.")

    if profile.has_taxonomy:
        _add("genus_barplot", "Genus-level composition — standard 16S resolution",
             9, "16S V3-V4 provides reliable genus classification. Key resolution for microbiome studies.")
        _add("family_barplot", "Family-level bridges phylum and genus views",
             6, "Family-level composition can reveal patterns obscured at genus level (e.g., Lachnospiraceae diversity).")

        if profile.n_groups >= 2:
            _add("genus_heatmap", "Clustered heatmap independently confirms group structure",
                 8, "Hierarchical clustering by genus abundance provides a complementary view to ordination.")

    # ── 3. Alpha diversity ──────────────────────────────────────────
    if profile.n_groups >= 2:
        _add("alpha_boxplot",
             f"Alpha comparison: {alpha_rec.test_name}",
             9, alpha_rec.interpretation_guide[:200])

        if profile.alpha_significant:
            _add("alpha_raincloud",
                 f"Alpha significant (p={profile.alpha_p:.4f}) — show full distribution",
                 8, "Raincloud plots reveal distribution shape (bimodality, skewness) hidden by boxplots.")
            if profile.n_groups == 2:
                _add("alpha_effectsize",
                     "Quantify effect magnitude — effect size > p-value",
                     8, alpha_rec.effect_size_method or "Cliff's delta for non-parametric effect size.")
        else:
            if power["power_level"] in ("low", "very_low"):
                _add("rarefaction",
                     f"Alpha not significant but power={power['power_level']}",
                     8, f"n={power['n_per_group']}: {power['guidance'][:150]}")

    if not any(d.analysis_key == "rarefaction" for d in decisions):
        _add("rarefaction", "Rarefaction curves — sampling adequacy check",
             7, "Essential for interpreting richness-based metrics. Check if curves plateau.")

    # ── 4. Beta diversity ───────────────────────────────────────────
    ord_recs = recommend_ordinations(profile)

    if profile.n_groups >= 2:
        _add("pcoa_all", "Primary ordination with % variance explained",
             9, beta_rec.interpretation_guide[:150])
        _add("nmds", "NMDS — non-metric alternative (report stress value)",
             7, ORDINATION_GUIDE["NMDS"]["when_to_use"])

        if profile.beta_significant:
            _add("permanova",
                 f"Beta significant (p≈{profile.beta_p:.3f}) — full PERMANOVA",
                 10, "Run with 999 permutations. Report pseudo-F, R², and p-value.")
            _add("beta_dispersion",
                 "CRITICAL: distinguish location vs dispersion difference",
                 9, beta_rec.assumptions[1] if len(beta_rec.assumptions) > 1 else "Check PERMDISP.")
            _add("sample_dendrogram", "Hierarchical clustering visualization",
                 6, "UPGMA dendrogram provides alternative view of sample clustering.")

            if has_depth_cv_issue:
                _add("pca_clr", "CLR-PCA for compositionally valid ordination",
                     8, comp["reason"][:150])

        for orec in ord_recs:
            if orec["method"] == "t-SNE" and orec["score"] >= 5:
                _add("tsne", "t-SNE for local cluster structure",
                     5, ORDINATION_GUIDE["t-SNE"]["when_to_use"])
            if orec["method"] == "UMAP" and orec["score"] >= 5:
                _add("umap_ordination", "UMAP for local+global structure",
                     5, ORDINATION_GUIDE["UMAP"]["when_to_use"])

    # ── 5. Differential abundance ───────────────────────────────────
    if profile.n_groups >= 2 and profile.high_variance_genera:
        hv = ", ".join(profile.high_variance_genera[:3])

        if profile.n_groups == 2:
            _add("volcano", f"Differential genera detected ({hv})",
                 9, comp.get("differential_reason", "Per-taxon test + FDR.")[:150])
            _add("effect_size_forest", "Forest plot — effect sizes for each taxon",
                 8, "Cliff's delta more informative than p-values for differential abundance.")
            _add("ma_plot", "MA plot — abundance vs fold-change",
                 6, "Reveals if differential abundance is driven by rare or abundant taxa.")

        _add("lefse_style", "LEfSe — rank biomarkers by effect size",
             8, DIFFERENTIAL_ABUNDANCE_METHODS["lefse"]["strengths"])
        _add("genus_violin", f"Violin plots for differential genera: {hv}",
             7, "Full distribution reveals bimodality or outlier-driven effects.")
        _add("genus_boxplot_grouped", "Group-wise boxplots with statistical annotation",
             7, "Boxplot + jitter with p-value annotation for top differential genera.")

        if profile.n_groups >= 3:
            _add("multi_group_differential",
                 "Multi-group KW + Dunn's post-hoc with FDR",
                 8, "Pairwise comparisons identify which groups differ for each taxon.")

    # ── 6. Ecological interpretation ────────────────────────────────
    if profile.has_taxonomy:
        _add("core_microbiome", "Core microbiome — stable community foundation",
             6, ECOLOGICAL_CONCEPTS["core_microbiome"]["analysis"])
        _add("indicator_species", "Indicator species — group-specific biomarkers",
             6, "IndVal combines specificity and fidelity. Identifies taxa characteristic of each group.")

    if profile.n_groups >= 2:
        if profile.n_groups == 3:
            _add("ternary_plot", "Ternary plot for 3-group comparison",
                 5, "Visualizes taxon enrichment across 3 groups simultaneously.")
        _add("upset_shared_taxa", "UpSet diagram — shared/unique taxa between groups",
             5, "Superior to Venn diagrams for showing intersection sizes.")
        if profile.n_groups <= 3:
            _add("venn_diagram", "Venn diagram of shared ASVs",
                 4, "Classic shared/unique visualization for 2-3 groups.")

    # ── 7. Network & correlation ────────────────────────────────────
    if profile.n_genera >= 10:
        _add("cooccurrence_network", "Co-occurrence network — ecological interactions",
             5, NETWORK_ANALYSIS["spearman_correlation"]["method"] + ". " + NETWORK_ANALYSIS["topology_metrics"]["hub_taxa"])
        _add("correlation_clustermap", "Genus correlation structure",
             5, "Clustered heatmap identifies co-varying taxon modules.")

    # ── 8. Advanced ─────────────────────────────────────────────────
    _add("taxonomy_alluvial", "Taxonomy flow — Phylum→Class→Order→Family→Genus",
         4, "Alluvial plot shows taxonomic hierarchy and abundance flow.")
    _add("rank_abundance", "Rank-abundance curves — community evenness",
         5, ECOLOGICAL_CONCEPTS["species_abundance_distribution"]["rank_abundance"])
    _add("sample_similarity_heatmap", "Sample-sample similarity matrix",
         4, "Heatmap of 1-BC distance with hierarchical clustering.")

    if profile.n_groups >= 2:
        _add("taxa_prevalence_heatmap", "Prevalence across groups",
             5, "Binary prevalence comparison reveals core-group-specific taxa.")
        _add("diversity_correlation", "Diversity vs metadata correlations",
             4, "Scatter plots of alpha diversity vs continuous metadata variables.")

    # ── 9. Publication composites ───────────────────────────────────
    _add("composite_main", "Main 4-panel composite figure",
         8, "Publication-ready: composition + diversity + ordination + differential.")
    _add("composite_supplementary", "Supplementary 6-panel composite",
         5, "Extended results for supplementary materials.")
    _add("statistical_summary_table", "Statistical summary table (Table 1)",
         7, "All test results in one table: test, statistic, p, q, effect size.")

    decisions.sort(key=lambda d: -d.priority)
    return decisions
