#!/usr/bin/env python3
"""
test/example_seq_type_detection.py
====================================
16S アンプリコン vs ショットガンメタゲノム 自動判定の動作例。

cli.py の _detect_seq_type() が 4 指標で判定する。

実行:
    python -c "
    import sys; sys.path.insert(0, '.')
    from cli import _detect_dada2_params
    result = _detect_dada2_params('/path/to/fastq')
    print(result['seq_type'], result['seq_type_confidence'])
    for r in result['seq_type_reasons']:
        print(f'  - {r}')
    "
"""

# =====================================================================
# 判定ロジック: 4 指標スコアリング
# =====================================================================
#
# 指標 1: リード長の変動係数 (CV)
#   アンプリコン: CV ≈ 0.0 (全リード同一長、同一プライマー由来)
#   ショットガン: CV > 0.05 (ゲノムのランダム断片)
#   重み: 2.0
#
# 指標 2: リード数
#   アンプリコン: < 200,000 (ターゲット領域のみ増幅)
#   ショットガン: > 500,000 (ゲノム全体をカバー)
#   重み: 1.5
#
# 指標 3: ユニーク配列率 (先頭 500 リード中)
#   アンプリコン: < 0.70 (同一遺伝子領域なので重複多い)
#   ショットガン: > 0.95 (ゲノム全体からランダムなので重複少ない)
#   重み: 2.0
#
# 指標 4: 16S プライマー配列の一致率
#   アンプリコン: > 0.70 (先頭にプライマー配列が検出される)
#   ショットガン: ≈ 0.0 (プライマーなし)
#   重み: 3.0 (最強シグナル)

# =====================================================================
# 16S アンプリコンデータの判定結果例 (~/input)
# =====================================================================
AMPLICON_RESULT = {
    "seq_type": "amplicon",
    "confidence": 0.86,
    "evidence": {
        "read_length_cv": 0.0,        # 全リード 301bp で完全均一
        "read_count_est": 30357,      # ~3万リード（アンプリコン範囲）
        "unique_ratio": 0.898,        # 500リード中 89.8% がユニーク（中間的）
        "primer_match": "",           # トリム済みデータのためプライマー未検出
        "primer_match_rate": 0.185,
    },
    "reasons": [
        "リード長が均一 (CV=0.0000)",
        "リード数がアンプリコン範囲 (30,357)",
        "ユニーク配列率は中間的 (89.8%)",
        "既知の 16S プライマー配列は検出されず",
    ],
}

# =====================================================================
# ショットガンメタゲノムデータの判定結果例（想定）
# =====================================================================
SHOTGUN_RESULT = {
    "seq_type": "shotgun",
    "confidence": 0.82,
    "evidence": {
        "read_length_cv": 0.08,       # リード長にばらつき
        "read_count_est": 2500000,    # 250万リード（ショットガン範囲）
        "unique_ratio": 0.992,        # ほぼ全リードがユニーク
        "primer_match": "",
        "primer_match_rate": 0.005,
    },
    "reasons": [
        "リード長にばらつき (CV=0.0800)",
        "リード数が多い (2,500,000)",
        "ユニーク配列率が非常に高い (99.2%)",
        "既知の 16S プライマー配列は検出されず",
    ],
}

# =====================================================================
# 検出対象の 16S プライマー
# =====================================================================
PRIMERS = {
    "27F":   "AGAGTTTGATCMTGGCTCAG",   # V1-V2 領域
    "341F":  "CCTACGGGNGGCWGCAG",       # V3-V4 領域
    "515F":  "GTGYCAGCMGCCGCGGTAA",     # V4 領域
    "515Fn": "GTGCCAGCMGCCGCGGTAA",     # V4 領域 (Caporaso)
    "799F":  "AACMGGATTAGATACCCKG",      # V5-V6 領域
}

# --force-amplicon フラグ:
#   ショットガン判定でも強制的にアンプリコンとして処理する。
#   ./launch.sh --fastq-dir ~/data --auto --force-amplicon

if __name__ == "__main__":
    import json
    print("=== 16S Amplicon Example ===")
    print(json.dumps(AMPLICON_RESULT, indent=2, ensure_ascii=False))
    print()
    print("=== Shotgun Metagenome Example ===")
    print(json.dumps(SHOTGUN_RESULT, indent=2, ensure_ascii=False))
