#!/usr/bin/env python3
"""
test/example_code_agent.py
===========================
code_agent.py のツール呼び出し型コード生成エージェントの動作例。

LLM が「先に読む、後で書く」の原則で自律的にコードを生成・修正する。

code_agent.py は 5 つのツールを LLM に提供:
    list_files      エクスポートディレクトリのファイル一覧
    read_file       ファイルの中身を読む（列名・形式確認用）
    write_file      Python スクリプトを書き出す
    run_python      QIIME2 conda 環境の Python で実行
    install_package pip install（ユーザー承認後）

典型的な LLM ↔ ツール 対話ログ:
"""

# =====================================================================
# 1. LLM → list_files（ファイル探索）
# =====================================================================
TOOL_CALL_1 = {
    "name": "list_files",
    "arguments": {}
}

TOOL_RESULT_1 = """
feature_table/
  feature-table.biom.tsv  (245 KB)
taxonomy/
  taxonomy.tsv  (189 KB)
alpha/
  shannon_vector/alpha-diversity.tsv  (1 KB)
  observed_features_vector/alpha-diversity.tsv  (1 KB)
  faith_pd_vector/alpha-diversity.tsv  (1 KB)
beta/
  braycurtis_distance_matrix/distance-matrix.tsv  (3 KB)
  jaccard_distance_matrix/distance-matrix.tsv  (3 KB)
  unweighted_unifrac_distance_matrix/distance-matrix.tsv  (3 KB)
  weighted_unifrac_distance_matrix/distance-matrix.tsv  (3 KB)
"""

# =====================================================================
# 2. LLM → read_file（データ形式確認）
# =====================================================================
TOOL_CALL_2 = {
    "name": "read_file",
    "arguments": {"path": "feature_table/feature-table.biom.tsv"}
}

TOOL_RESULT_2 = """
# Constructed from biom file
#OTU ID	TEST01_SpRn	TEST02_SpRn	TEST03_SpRn	...
0a1b2c3d	152	0	89	...
1d2e3f4g	0	234	12	...
...
"""

# =====================================================================
# 3. LLM → write_file（スクリプト生成）
# =====================================================================
TOOL_CALL_3 = {
    "name": "write_file",
    "arguments": {
        "path": "analysis_script.py",
        "content": """
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

EXPORT = Path("EXPORT_DIR")
FIG_DIR = Path("FIGURE_DIR")

# Feature table
ft = pd.read_csv(EXPORT / "feature_table/feature-table.biom.tsv",
                 sep="\\t", skiprows=1, index_col=0)
ft = ft.select_dtypes(include=[np.number])

# Shannon diversity
shannon = pd.read_csv(
    EXPORT / "alpha/shannon_vector/alpha-diversity.tsv",
    sep="\\t", index_col=0)

fig, ax = plt.subplots(figsize=(10, 5))
vals = shannon.iloc[:, 0].sort_values(ascending=False)
ax.bar(vals.index, vals.values, color="steelblue")
ax.set_ylabel("Shannon Diversity Index")
ax.set_xlabel("Sample")
ax.set_title("Shannon Alpha Diversity per Sample")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.savefig(FIG_DIR / "shannon_per_sample.png", dpi=200)
plt.close()
print("shannon_per_sample.png saved")
"""
    }
}

# =====================================================================
# 4. LLM → run_python（実行）
# =====================================================================
TOOL_CALL_4 = {
    "name": "run_python",
    "arguments": {"path": "analysis_script.py"}
}

# 成功時:
TOOL_RESULT_4_SUCCESS = """
EXIT CODE: 0
STDOUT:
shannon_per_sample.png saved

NEW FIGURES: ['shannon_per_sample.png']
"""

# エラー時（NEVER GIVE UP 方針で LLM が自動修正）:
TOOL_RESULT_4_ERROR = """
EXIT CODE: 1
STDERR:
Traceback (most recent call last):
  File "analysis_script.py", line 8, in <module>
    ft = pd.read_csv(EXPORT / "feature_table/feature-table.biom.tsv",
FileNotFoundError: [Errno 2] No such file or directory: 'EXPORT_DIR/feature_table/feature-table.biom.tsv'
"""

# =====================================================================
# 5. LLM → write_file（エラー修正 → 再実行）
# =====================================================================
# LLM はトレースバックを読んでパスを修正:
TOOL_CALL_5_FIX = {
    "name": "write_file",
    "arguments": {
        "path": "analysis_script.py",
        "content": "# ... パスを修正して再生成 ..."
    }
}

# → run_python で再実行 → EXIT CODE: 0 → 完了

# =====================================================================
# 小型 LLM フォールバック機構
# =====================================================================
# 7B 以下のモデルが tool_calls を正しく出力できない場合の4層フォールバック:
#
# 1. テキストベースツール呼び出しパーサ:
#    LLM が ```json でツール呼び出しをテキスト出力 → 正規表現で抽出
#
# 2. Auto-inject run_python:
#    write_file で .py を書いた直後、LLM が run_python を呼ぶのを待たず自動実行
#
# 3. ステップ 6 フォールバック（1ショット生成）:
#    5ステップ後も run_python が0回 → run_code_agent() に切り替え
#
# 4. 繰り返し検出:
#    同じ50文字チャンクが4回連続 or 応答20,000文字超 → 強制終了
