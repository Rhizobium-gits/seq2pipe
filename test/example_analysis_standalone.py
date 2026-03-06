#!/usr/bin/env python3
"""
test/example_analysis_standalone.py
====================================
analysis.py の決定論的解析モジュール単体実行例。

LLM を使わず、QIIME2 エクスポートデータから 29 種類の図を生成する。
このモジュールは STEP 1.5 として --auto モードの中核を担う。

単体実行:
    python -c "
    import sys; sys.path.insert(0, '.')
    from analysis import run_comprehensive_analysis
    saved, summary = run_comprehensive_analysis(
        export_dir='~/seq2pipe_results/.../exported',
        figure_dir='~/seq2pipe_results/.../figures',
        session_dir='~/seq2pipe_results/...',
    )
    print(f'{len(saved)} figures saved')
    print(f'{len(summary.get(\"interesting_patterns\", []))} patterns detected')
    "

生成される 29 図:
    fig01_dada2_stats.png          DADA2 デノイジング統計
    fig02_sequencing_depth.png     シーケンシング深度
    fig03_alpha_diversity.png      α多様性ボックスプロット
    fig04_shannon_per_sample.png   Shannon 多様性（サンプル別）
    fig05_pcoa_braycurtis.png      PCoA (Bray-Curtis) + 分散説明率
    fig06_pcoa_jaccard.png         PCoA (Jaccard) + 分散説明率
    fig07_pcoa_unweighted_unifrac.png  PCoA (Unweighted UniFrac)
    fig08_pcoa_weighted_unifrac.png    PCoA (Weighted UniFrac)
    fig09_beta_distance_heatmaps.png   β多様性ヒートマップ (2x2)
    fig10_top30_asv_heatmap.png    Top 30 ASV ヒートマップ
    fig11_alpha_correlation.png    α多様性相関
    fig12_richness_vs_depth.png    ASV リッチネス vs 深度
    fig13_genus_composition.png*   属レベル組成（積み上げ棒）
    fig14_phylum_composition.png*  門レベル組成（積み上げ棒）
    fig15_genus_heatmap.png*       属レベルヒートマップ
    fig16_rarefaction.png          ラレファクションカーブ
    fig17_nmds_braycurtis.png      NMDS (Bray-Curtis)
    fig18_rank_abundance.png       Rank-Abundance カーブ
    fig19_alluvial.png             分類学的 Alluvial プロット
    fig20_cooccurrence_network.png 属間共起ネットワーク
    fig21_family_composition.png*  科レベル組成（積み上げ棒）
    fig22_core_microbiome.png*     コアマイクロバイオーム
    fig23_volcano.png*†            差次的存在量ボルケーノプロット
    fig24_dendrogram.png           サンプルデンドログラム (UPGMA)
    fig25_genus_correlation.png*   属間 Spearman 相関
    fig26_class_composition.png*   綱レベル組成（積み上げ棒）
    fig27_order_composition.png*   目レベル組成（積み上げ棒）
    fig28_simpson_pielou.png       Simpson 多様性 + Pielou 均等度
    fig29_asv_overlap.png          サンプル間 ASV 共有パターン

    * = SILVA 138 分類器が必要
    † = Benjamini-Hochberg FDR 補正
"""

# ─── generate_analysis_summary() の出力例 ─────────────────────────────
# STEP 1.5 完了後に返される構造化サマリー。
# このデータが STEP 2 の適応型自律エージェントに渡される。

example_summary = {
    "n_samples": 10,
    "n_asvs": 1333,
    "sample_ids": [
        "TEST01", "TEST02", "TEST03", "TEST04", "TEST05",
        "TEST06", "TEST07", "TEST08", "TEST09", "TEST10",
    ],
    "sequencing_depth": {
        "min": 27010,
        "max": 28500,
        "mean": 27800,
    },
    "top_phyla": [
        ("Firmicutes", 45.2),
        ("Bacteroidota", 22.1),
        ("Proteobacteria", 15.3),
        ("Actinobacteriota", 8.7),
        ("Verrucomicrobiota", 3.1),
    ],
    "top_genera": [
        ("Bacteroides", 12.3),
        ("Prevotella", 8.1),
        ("Blautia", 6.5),
        ("Faecalibacterium", 5.8),
        ("Roseburia", 4.2),
        ("Bifidobacterium", 3.9),
        ("Ruminococcus", 3.1),
        ("Akkermansia", 2.8),
        ("Lachnospira", 2.4),
        ("Dialister", 2.0),
    ],
    "core_genera": [
        "Bacteroides", "Blautia", "Faecalibacterium", "Roseburia",
    ],
    "dominant_genus_per_sample": {
        "TEST01": "Bacteroides",
        "TEST02": "Prevotella",
        "TEST03": "Bacteroides",
        "TEST04": "Blautia",
        "TEST05": "Bacteroides",
        "TEST06": "Faecalibacterium",
        "TEST07": "Bacteroides",
        "TEST08": "Prevotella",
        "TEST09": "Bacteroides",
        "TEST10": "Blautia",
    },
    "high_variance_genera": [
        ("Prevotella", 1.32),
        ("Akkermansia", 1.15),
    ],
    "alpha_summary": {
        "Shannon": {
            "mean": 6.21,
            "std": 0.34,
            "min_sample": "TEST05",
            "max_sample": "TEST02",
        },
        "Faith PD": {
            "mean": 18.5,
            "std": 2.1,
            "min_sample": "TEST05",
            "max_sample": "TEST07",
        },
    },
    "outlier_samples": ["TEST05"],
    "interesting_patterns": [
        "Sample TEST05 has unusually low Shannon diversity (5.42, mean=6.21)",
        "Genus Prevotella shows high inter-sample variance (CV=1.32)",
        "Firmicutes dominates in 8/10 samples (>40% relative abundance)",
    ],
}

if __name__ == "__main__":
    import json
    print("=== analysis_summary example ===")
    print(json.dumps(example_summary, indent=2, ensure_ascii=False))
