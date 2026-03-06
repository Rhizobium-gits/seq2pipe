#!/usr/bin/env python3
"""
test/example_report_generation.py
==================================
report_generator.py のレポート生成の動作例。

2 種類のレポートを自動生成する:
    1. HTML レポート (generate_html_report)  → --auto モードの STEP 3
    2. LaTeX/PDF レポート (generate_latex_report) → 修正モード or --chat

HTML レポート実行例:
    python -c "
    import sys; sys.path.insert(0, '.')
    from report_generator import generate_html_report
    generate_html_report(
        figure_dir='~/seq2pipe_results/.../figures',
        output_dir='~/seq2pipe_results/...',
        session_dir='~/seq2pipe_results/...',
    )
    "
"""

# =====================================================================
# HTML レポートの構造
# =====================================================================
# generate_html_report() が生成する自己完結型 HTML の構造:

HTML_STRUCTURE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>seq2pipe Analysis Report</title>
    <style>
        /* CSS Variables: --c-text, --c-muted, --c-border, --c-accent */
        /* System font stack: -apple-system, BlinkMacSystemFont, ... */
        /* .methods-grid: 2列グリッド */
        /* .method-item: 各解析手法カード */
        /* .eq: 数式表示（monospace） */
    </style>
</head>
<body>
    <!-- ヘッダー -->
    <header>
        <h1>seq2pipe Analysis Report</h1>
        <p class="meta">生成日時 / パイプラインバージョン</p>
    </header>

    <!-- 目次 (TOC) -->
    <nav id="toc">
        <h2>Contents</h2>
        <ul>
            <li><a href="#cat-alpha">Alpha Diversity</a></li>
            <li><a href="#cat-beta">Beta Diversity</a></li>
            <li><a href="#cat-composition">Taxonomic Composition</a></li>
            <li><a href="#cat-stats">Statistical Analysis</a></li>
            <li><a href="#cat-community">Community Structure</a></li>
        </ul>
    </nav>

    <!-- パイプラインステップ表示 -->
    <section id="steps">
        <div class="step">
            <span class="dot done"></span> STEP 1: QIIME2 Pipeline
        </div>
        <div class="step">
            <span class="dot done"></span> STEP 1.5: Comprehensive Analysis (29 figures)
        </div>
        <div class="step">
            <span class="dot done"></span> STEP 2: Adaptive Agent
        </div>
        <div class="step">
            <span class="dot done"></span> STEP 3: Report Generation
        </div>
    </section>

    <!-- カテゴリ別セクション -->
    <section id="cat-alpha">
        <h2>Alpha Diversity</h2>

        <!-- 図 -->
        <div class="figure-grid">
            <figure>
                <img src="data:image/png;base64,..." alt="fig03">
                <figcaption>fig03: Alpha diversity boxplot</figcaption>
            </figure>
        </div>

        <!-- 解析手法カード -->
        <div class="methods-grid">
            <div class="method-item">
                <h4>Shannon Entropy</h4>
                <p class="eq">H = -&Sigma; p_i log(p_i)</p>
                <p>群集の多様性を情報エントロピーで定量化。
                   値が高いほど均等で多様な群集。</p>
                <p class="reveals">群集の均等性と種の豊富さを同時に評価</p>
            </div>
            <div class="method-item">
                <h4>Faith's Phylogenetic Diversity</h4>
                <p class="eq">PD = &Sigma; branch_lengths</p>
                <p>系統樹上の枝長の総和。進化的多様性を反映。</p>
                <p class="reveals">サンプルが含む系統的多様性の幅</p>
            </div>
        </div>
    </section>

    <!-- ... 他のカテゴリも同様 ... -->
</body>
</html>
"""

# =====================================================================
# _ANALYSIS_CATEGORIES データ構造
# =====================================================================
# report_generator.py 内で定義。各カテゴリに属する図と解析手法を管理。

ANALYSIS_CATEGORIES_EXAMPLE = [
    {
        "id": "alpha",
        "title": "Alpha Diversity",
        "figures": ["fig03", "fig04", "fig11", "fig16", "fig28"],
        "methods": [
            {
                "name": "Shannon Entropy",
                "equation": "H = -&Sigma; p<sub>i</sub> log(p<sub>i</sub>)",
                "description": "情報エントロピーに基づく多様性指数",
                "reveals": "群集の均等性と種の豊富さ",
            },
            {
                "name": "Simpson Diversity",
                "equation": "D = 1 - &Sigma; p<sub>i</sub>&sup2;",
                "description": "ランダムに選んだ2個体が異なる種である確率",
                "reveals": "群集の優占度",
            },
        ],
    },
    {
        "id": "beta",
        "title": "Beta Diversity",
        "figures": ["fig05", "fig06", "fig07", "fig08", "fig09", "fig17"],
        "methods": [
            {
                "name": "Bray-Curtis Dissimilarity",
                "equation": "BC = 1 - 2C / (S<sub>A</sub> + S<sub>B</sub>)",
                "description": "存在量ベースのサンプル間非類似度",
                "reveals": "サンプル間の群集構造の違い",
            },
        ],
    },
    # ... composition, stats, community ...
]

# =====================================================================
# LaTeX レポート生成
# =====================================================================
# generate_latex_report() は以下を実行:
#   1. 全生成図を収集
#   2. lualatex or xelatex を自動検出
#   3. LaTeX テンプレート + 図を埋め込み
#   4. 最大 3 回コンパイル（相互参照解決のため）
#   5. report.tex + report.pdf を出力
#
# LaTeX エンジン優先順位:
#   tectonic > lualatex > xelatex > (tex ファイルのみ保存)
