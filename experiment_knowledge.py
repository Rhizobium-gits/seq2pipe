#!/usr/bin/env python3
"""
experiment_knowledge.py
=======================
実験系の学術知識データベース。

実験の説明文から実験タイプを認識し、文献に基づく予測・仮説・
注目すべき指標を自動生成する。世界中の研究で蓄積された知見を
解析フローに反映させる。

参考文献:
  Theriot et al. (2014) — Antibiotic-induced shifts in the mouse gut microbiome
  Turnbaugh et al. (2006) — Obesity-associated gut microbiome
  David et al. (2014) — Diet rapidly alters the human gut microbiome
  Langille et al. (2013) — Predictive functional profiling (PICRUSt)
  Costello et al. (2009) — Bacterial community variation in body habitats
  Dethlefsen & Relman (2011) — Incomplete recovery after antibiotics
  Manichanh et al. (2006) — IBD microbiome
  Qin et al. (2012) — Type 2 diabetes metagenome
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# 実験タイプ定義 — 文献に基づく期待パターンと仮説
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExperimentHypothesis:
    """文献に基づく仮説"""
    hypothesis: str
    literature_basis: str
    expected_direction: str       # "increase" | "decrease" | "shift" | "disrupt"
    target_taxa: list[str] = field(default_factory=list)
    target_metrics: list[str] = field(default_factory=list)
    analysis_to_confirm: str = ""


@dataclass
class ExperimentType:
    """実験タイプとその文献的知見"""
    name: str
    description: str
    keywords: list[str]           # 実験系説明文からのマッチングキーワード
    expected_changes: list[str]   # 予測される変化
    key_taxa_to_watch: dict[str, str]   # taxon → "expected change and why"
    key_metrics: list[str]        # 注目すべきメトリクス
    hypotheses: list[ExperimentHypothesis] = field(default_factory=list)
    comparisons_to_prioritize: list[str] = field(default_factory=list)  # 優先すべき比較タイプ
    warnings: list[str] = field(default_factory=list)


# ── 実験タイプデータベース ────────────────────────────────────────────────────

EXPERIMENT_TYPES: list[ExperimentType] = [

    # ──────────────────────────────────────────────────────
    # 1. 抗生物質投与実験
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="antibiotic_treatment",
        description="Antibiotic treatment effect on gut microbiome",
        keywords=[
            "antibiotic", "antibiotics", "抗生物質", "抗菌薬",
            "ampicillin", "アンピシリン", "vancomycin", "バンコマイシン",
            "metronidazole", "メトロニダゾール", "ciprofloxacin",
            "neomycin", "ネオマイシン", "streptomycin",
            "broad-spectrum", "広域", "abx",
        ],
        expected_changes=[
            "Alpha diversity: significant DECREASE (Shannon, Observed ASVs)",
            "Beta diversity: clear group SEPARATION (PERMANOVA significant)",
            "Proteobacteria: INCREASE (especially Enterobacteriaceae bloom)",
            "Firmicutes: DECREASE (loss of obligate anaerobes)",
            "SCFA producers: DECREASE (Faecalibacterium, Roseburia, Coprococcus)",
            "Pathobionts: INCREASE (Escherichia, Enterococcus, Klebsiella)",
            "Evenness: DECREASE (community becomes dominated by few resistant taxa)",
            "Recovery: partial recovery after antibiotic cessation (Dethlefsen & Relman 2011)",
        ],
        key_taxa_to_watch={
            "Lactobacillus": "Often DECREASES with broad-spectrum antibiotics but may be resistant to vancomycin",
            "Faecalibacterium": "Major butyrate producer — its loss indicates functional SCFA impairment",
            "Roseburia": "Butyrate producer — sensitive to most antibiotics",
            "Enterococcus": "Intrinsically resistant to many antibiotics — often BLOOMS",
            "Escherichia": "Facultative anaerobe — thrives in post-antibiotic oxidative environment",
            "Clostridioides": "C. difficile risk increases with antibiotic-induced dysbiosis",
            "Bacteroides": "Can be resistant or sensitive depending on antibiotic class",
            "Akkermansia": "Mucin degrader — may INCREASE in dysbiotic conditions",
        },
        key_metrics=["shannon", "observed_features", "faith_pd", "bray_curtis", "weighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Alpha diversity decreases significantly in antibiotic-treated group",
                literature_basis="Theriot et al. 2014; Dethlefsen & Relman 2011",
                expected_direction="decrease",
                target_metrics=["shannon", "observed_features"],
                analysis_to_confirm="alpha_boxplot with Mann-Whitney U test",
            ),
            ExperimentHypothesis(
                hypothesis="Proteobacteria bloom in antibiotic-treated group (>15% relative abundance)",
                literature_basis="Shin et al. 2015 — Proteobacteria as dysbiosis marker",
                expected_direction="increase",
                target_taxa=["Proteobacteria", "Escherichia", "Enterobacteriaceae"],
                analysis_to_confirm="phylum_barplot + genus-level differential abundance",
            ),
            ExperimentHypothesis(
                hypothesis="SCFA-producing bacteria decrease, disrupting butyrate production potential",
                literature_basis="Ríos-Covián et al. 2016 — SCFA producers and gut health",
                expected_direction="decrease",
                target_taxa=["Faecalibacterium", "Roseburia", "Coprococcus", "Eubacterium"],
                analysis_to_confirm="genus_violin for SCFA producers per group",
            ),
            ExperimentHypothesis(
                hypothesis="Co-occurrence network structure is disrupted by antibiotic treatment",
                literature_basis="Antibiotic-induced loss of ecological interactions",
                expected_direction="disrupt",
                analysis_to_confirm="Per-group co-occurrence network comparison",
            ),
        ],
        comparisons_to_prioritize=[
            "between_group (overall)",
            "within_time (baseline → post-treatment)",
            "within_time (treatment → recovery)",
        ],
        warnings=[
            "Cage effects: if animals share cages, cage is a confounder — coprophagy transmits microbiomes",
            "Antibiotic residues in samples may affect DNA extraction efficiency",
            "Broad-spectrum vs narrow-spectrum antibiotics produce very different patterns",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 2. 食餌介入実験
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="diet_intervention",
        description="Diet-induced changes in gut microbiome",
        keywords=[
            "diet", "食餌", "食事", "high-fat", "高脂肪", "HFD",
            "low-fiber", "low fiber", "高繊維", "high-fiber",
            "western diet", "plant-based", "vegan", "vegetarian",
            "ketogenic", "ケトン食", "caloric restriction", "カロリー制限",
            "prebiotic", "プレバイオティクス", "inulin", "イヌリン",
            "fructooligosaccharide", "FOS", "GOS",
        ],
        expected_changes=[
            "F/B ratio: SHIFTS with diet (high-fat → increased F/B in some studies)",
            "Fiber-degrading bacteria: INCREASE with high-fiber diet (Prevotella, Bifidobacterium)",
            "SCFA production capacity: CHANGES with fiber availability",
            "Alpha diversity: may INCREASE with diverse plant-based diet (McDonald et al. 2018)",
            "Rapid shifts: gut microbiome can change within 24-48 hours of dietary change (David et al. 2014)",
        ],
        key_taxa_to_watch={
            "Prevotella": "Associated with high-fiber, plant-rich diet",
            "Bacteroides": "Associated with animal protein and fat-rich (Western) diet",
            "Bifidobacterium": "Increases with prebiotic supplementation (FOS, GOS, inulin)",
            "Ruminococcus": "Key fiber degrader — decreases on low-fiber diet",
            "Faecalibacterium": "Butyrate producer — responds to fiber availability",
            "Akkermansia": "May increase with caloric restriction; associated with lean phenotype",
            "Lactobacillus": "Can increase with fermented food consumption",
        },
        key_metrics=["shannon", "bray_curtis", "weighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Firmicutes/Bacteroidetes ratio shifts with dietary change",
                literature_basis="Turnbaugh et al. 2006; Ley et al. 2006",
                expected_direction="shift",
                target_taxa=["Firmicutes", "Bacteroidetes"],
                analysis_to_confirm="phylum_barplot + F/B ratio comparison",
            ),
            ExperimentHypothesis(
                hypothesis="Fiber-degrading bacteria (Prevotella, Ruminococcus) respond to fiber content",
                literature_basis="De Filippo et al. 2010 — rural vs urban gut microbiome",
                expected_direction="shift",
                target_taxa=["Prevotella", "Ruminococcus", "Bifidobacterium"],
                analysis_to_confirm="genus_violin for fiber-degrading taxa",
            ),
        ],
        comparisons_to_prioritize=[
            "within_time (baseline → intervention)",
            "between_group (diet A vs diet B)",
        ],
        warnings=[
            "Diet effects can be confounded by host genetics and baseline microbiome",
            "Short-term vs long-term dietary changes produce different patterns",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 3. 疾患 vs 健常 比較
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="disease_comparison",
        description="Disease vs healthy microbiome comparison",
        keywords=[
            "disease", "疾患", "患者", "patient", "healthy", "健常",
            "IBD", "crohn", "クローン", "colitis", "大腸炎",
            "diabetes", "糖尿病", "obesity", "肥満",
            "cancer", "がん", "CRC", "colorectal",
            "allergy", "アレルギー", "asthma", "喘息",
            "autism", "自閉症", "depression", "うつ",
            "NAFLD", "肝臓", "liver",
        ],
        expected_changes=[
            "Alpha diversity: often DECREASED in disease (dysbiosis hypothesis)",
            "Beta diversity: significant SEPARATION between disease and healthy",
            "Biomarkers: disease-specific taxa enrichment/depletion",
            "Functional shifts: altered metabolic potential",
        ],
        key_taxa_to_watch={
            "Faecalibacterium prausnitzii": "Anti-inflammatory — DECREASED in IBD (Sokol et al. 2008)",
            "Akkermansia muciniphila": "Mucin degrader — decreased in obesity, increased with metformin",
            "Fusobacterium nucleatum": "ENRICHED in colorectal cancer (Kostic et al. 2012)",
            "Ruminococcus gnavus": "INCREASED in IBD, produces pro-inflammatory polysaccharides",
            "Escherichia/Shigella": "INCREASED in various inflammatory conditions",
            "Bifidobacterium": "Often DECREASED in dysbiotic states",
            "Prevotella copri": "Associated with rheumatoid arthritis (Scher et al. 2013)",
        },
        key_metrics=["shannon", "observed_features", "bray_curtis", "unweighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Disease group shows reduced alpha diversity (dysbiosis)",
                literature_basis="Lozupone et al. 2012 — diversity and disease",
                expected_direction="decrease",
                target_metrics=["shannon", "observed_features"],
                analysis_to_confirm="alpha_boxplot + rarefaction",
            ),
            ExperimentHypothesis(
                hypothesis="Disease-associated biomarker taxa are enriched/depleted",
                literature_basis="Disease-specific literature",
                expected_direction="shift",
                analysis_to_confirm="lefse_style + volcano plot",
            ),
        ],
        comparisons_to_prioritize=[
            "between_group (disease vs healthy)",
        ],
        warnings=[
            "Medication use is a major confounder in disease studies",
            "Age, sex, BMI must be controlled or reported",
            "Cross-sectional design cannot establish causation",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 4. 環境・生態学サンプリング
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="environmental_survey",
        description="Environmental microbiome survey across sites/conditions",
        keywords=[
            "soil microbiome", "土壌微生物", "water microbiome", "水質微生物",
            "sediment", "堆積物", "rhizosphere", "根圏", "phyllosphere", "葉圏",
            "marine microbiome", "海洋微生物", "freshwater microbiome",
            "air sample", "大気サンプル", "built environment",
            "sampling site", "サンプリングサイト",
            "depth gradient", "elevation gradient",
            "seasonal variation", "環境勾配",
        ],
        expected_changes=[
            "High beta diversity between sites (environmental filtering)",
            "Alpha diversity varies with environmental gradients",
            "Community composition driven by pH, temperature, moisture, nutrients",
            "Distance-decay relationship: communities more different at greater distances",
        ],
        key_taxa_to_watch={
            "Acidobacteria": "Dominant in acidic soils, declines with pH increase",
            "Cyanobacteria": "Photosynthetic — enriched in light-exposed aquatic environments",
            "Actinobacteria": "Common in dry soils, important decomposers",
            "Proteobacteria": "Ubiquitous — different classes dominate different environments",
            "Chloroflexi": "Often found in anaerobic sediments",
        },
        key_metrics=["shannon", "observed_features", "bray_curtis", "jaccard", "unweighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Community composition correlates with environmental gradients",
                literature_basis="Fierer & Jackson 2006 — soil pH as diversity predictor",
                expected_direction="shift",
                analysis_to_confirm="diversity_correlation + PERMANOVA with continuous covariates",
            ),
        ],
        comparisons_to_prioritize=[
            "between_group (site/condition comparisons)",
        ],
        warnings=[
            "Spatial autocorrelation may inflate significance in geographically structured data",
            "Temporal variation (seasonality) can confound spatial patterns",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 5. 糞便移植 (FMT)
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="fecal_transplant",
        description="Fecal microbiota transplantation study",
        keywords=[
            "FMT", "fecal transplant", "糞便移植", "fecal microbiota",
            "donor", "ドナー", "recipient", "レシピエント",
            "engraftment", "生着", "colonization", "定着",
            "germ-free", "無菌", "gnotobiotic", "ノトバイオート",
        ],
        expected_changes=[
            "Recipient microbiome shifts toward donor profile",
            "Engraftment efficiency varies by taxon (obligate anaerobes establish slower)",
            "Alpha diversity: increases in recipient (if previously depleted)",
            "Beta diversity: recipient-donor distance decreases over time",
        ],
        key_taxa_to_watch={
            "Bacteroides": "Often among first to engraft (robust colonizer)",
            "Faecalibacterium": "Important for engraftment success — strict anaerobe",
            "Lactobacillus": "May establish quickly in GF mice",
            "Clostridiales": "Slow engraftment — requires established anaerobic niche",
        },
        key_metrics=["shannon", "bray_curtis", "weighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Recipient microbiome converges toward donor profile over time",
                literature_basis="Li et al. 2016 — FMT engraftment dynamics",
                expected_direction="shift",
                analysis_to_confirm="PCoA trajectory + beta diversity vs time",
            ),
        ],
        comparisons_to_prioritize=[
            "within_time (pre-FMT → post-FMT in recipient)",
            "between_group (donor vs recipient at each timepoint)",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 6. プロバイオティクス介入
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="probiotic_intervention",
        description="Probiotic supplementation study",
        keywords=[
            "probiotic", "プロバイオティクス", "Lactobacillus",
            "Bifidobacterium", "supplementation", "サプリメント",
            "VSL#3", "yogurt", "ヨーグルト", "fermented", "発酵",
        ],
        expected_changes=[
            "Probiotic strain: DETECTABLE during supplementation, may decline after cessation",
            "Alpha diversity: minimal change in healthy subjects (Suez et al. 2018)",
            "Resident community: may show subtle shifts in related taxa",
            "Functional changes possible without large compositional shifts",
        ],
        key_taxa_to_watch={
            "Lactobacillus": "Target probiotic genus — check species-level if possible",
            "Bifidobacterium": "Common probiotic genus — monitor engraftment",
        },
        key_metrics=["shannon", "bray_curtis"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Probiotic strain detectable during supplementation period",
                literature_basis="Zmora et al. 2018 — personalized probiotic colonization",
                expected_direction="increase",
                target_taxa=["Lactobacillus", "Bifidobacterium"],
                analysis_to_confirm="genus_violin for probiotic taxa across timepoints",
            ),
        ],
        comparisons_to_prioritize=[
            "within_time (baseline → supplementation → washout)",
            "between_group (probiotic vs placebo)",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 7. 発達・加齢研究
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="developmental_aging",
        description="Microbiome changes during development or aging",
        keywords=[
            "infant", "乳児", "newborn", "新生児", "neonate",
            "child", "小児", "adolescent", "思春期",
            "aging", "加齢", "elderly", "高齢者",
            "birth", "出産", "delivery", "分娩",
            "breastmilk", "母乳", "formula", "人工乳",
            "weaning", "離乳",
        ],
        expected_changes=[
            "Infant: low diversity at birth, rapid increase during first year",
            "Bifidobacterium dominant in breastfed infants, declining with weaning",
            "Adult-like community established by age 3 (Yatsunenko et al. 2012)",
            "Elderly: reduced diversity, increased Proteobacteria",
        ],
        key_taxa_to_watch={
            "Bifidobacterium": "Dominant in breastfed infants, keystone for early development",
            "Bacteroides": "Increases with solid food introduction",
            "Clostridium": "Gradually increases during infancy",
            "Escherichia": "Early colonizer — decreases as anaerobes establish",
        },
        key_metrics=["shannon", "observed_features", "bray_curtis"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Microbiome diversity and composition correlate with developmental stage",
                literature_basis="Yatsunenko et al. 2012; Bäckhed et al. 2015",
                expected_direction="shift",
                analysis_to_confirm="Alpha trajectory + PCoA trajectory over time",
            ),
        ],
        comparisons_to_prioritize=[
            "within_time (developmental trajectory)",
            "between_group (breastfed vs formula, or age groups)",
        ],
    ),

    # ──────────────────────────────────────────────────────
    # 8. 体部位比較
    # ──────────────────────────────────────────────────────
    ExperimentType(
        name="body_site_comparison",
        description="Microbiome comparison across body sites",
        keywords=[
            "body site", "体部位", "oral microbiome", "口腔微生物",
            "skin microbiome", "皮膚微生物", "vaginal microbiome", "膣微生物",
            "nasal microbiome", "鼻腔微生物", "body habitat",
        ],
        expected_changes=[
            "Dramatically different communities across body sites (HMP, Costello et al. 2009)",
            "Gut: highest diversity, Firmicutes/Bacteroidetes dominant",
            "Skin: low diversity, Propionibacterium/Staphylococcus dominant",
            "Oral: moderate diversity, Streptococcus dominant",
            "Vaginal: low diversity, Lactobacillus dominant (in healthy state)",
        ],
        key_taxa_to_watch={
            "Streptococcus": "Dominant in oral cavity",
            "Propionibacterium": "Dominant on skin (especially face)",
            "Staphylococcus": "Common skin commensal",
            "Lactobacillus": "Dominant in healthy vaginal microbiome",
            "Bacteroides": "Primarily gut-associated",
        },
        key_metrics=["shannon", "bray_curtis", "unweighted_unifrac"],
        hypotheses=[
            ExperimentHypothesis(
                hypothesis="Body sites harbor fundamentally different microbial communities",
                literature_basis="Costello et al. 2009; HMP Consortium 2012",
                expected_direction="shift",
                analysis_to_confirm="PCoA colored by body site + PERMANOVA",
            ),
        ],
        comparisons_to_prioritize=[
            "between_group (site A vs site B)",
        ],
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 実験タイプ認識
# ═══════════════════════════════════════════════════════════════════════════════

def detect_experiment_type(
    experiment_description: str,
    research_question: str = "",
) -> list[ExperimentType]:
    """実験系の説明文から該当する実験タイプを検出（複数可）"""
    text = (experiment_description + " " + research_question).lower()
    matched: list[tuple[int, ExperimentType]] = []

    for etype in EXPERIMENT_TYPES:
        score = 0
        for kw in etype.keywords:
            if kw.lower() in text:
                score += 1
        if score > 0:
            matched.append((score, etype))

    matched.sort(key=lambda x: -x[0])
    return [et for _, et in matched]


# ═══════════════════════════════════════════════════════════════════════════════
# 実験コンテキスト生成 — AIプランニングに渡す知識ブロック
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExperimentContext:
    """実験系に特化した文脈情報"""
    experiment_types: list[ExperimentType] = field(default_factory=list)
    all_hypotheses: list[ExperimentHypothesis] = field(default_factory=list)
    taxa_to_watch: dict[str, str] = field(default_factory=dict)
    prioritized_comparisons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expected_changes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.experiment_types:
            names = ", ".join(et.name for et in self.experiment_types)
            lines.append(f"Detected experiment types: {names}")

        if self.expected_changes:
            lines.append("\nExpected changes (from literature):")
            for change in self.expected_changes[:10]:
                lines.append(f"  - {change}")

        if self.all_hypotheses:
            lines.append(f"\nTestable hypotheses ({len(self.all_hypotheses)}):")
            for h in self.all_hypotheses:
                lines.append(f"  [{h.expected_direction}] {h.hypothesis}")
                lines.append(f"    Literature: {h.literature_basis}")
                lines.append(f"    Confirm with: {h.analysis_to_confirm}")

        if self.taxa_to_watch:
            lines.append(f"\nKey taxa to monitor ({len(self.taxa_to_watch)}):")
            for taxon, note in list(self.taxa_to_watch.items())[:10]:
                lines.append(f"  {taxon}: {note}")

        if self.prioritized_comparisons:
            lines.append(f"\nPrioritized comparisons:")
            for comp in self.prioritized_comparisons:
                lines.append(f"  - {comp}")

        if self.warnings:
            lines.append(f"\nStudy design warnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")

        return "\n".join(lines)


def build_experiment_context(
    experiment_description: str,
    research_question: str = "",
) -> ExperimentContext:
    """実験系説明文から文脈情報を構築"""
    types = detect_experiment_type(experiment_description, research_question)
    ctx = ExperimentContext(experiment_types=types)

    for et in types:
        ctx.expected_changes.extend(et.expected_changes)
        ctx.all_hypotheses.extend(et.hypotheses)
        ctx.taxa_to_watch.update(et.key_taxa_to_watch)
        ctx.prioritized_comparisons.extend(et.comparisons_to_prioritize)
        ctx.warnings.extend(et.warnings)

    # 重複除去
    ctx.expected_changes = list(dict.fromkeys(ctx.expected_changes))
    ctx.prioritized_comparisons = list(dict.fromkeys(ctx.prioritized_comparisons))
    ctx.warnings = list(dict.fromkeys(ctx.warnings))

    return ctx
