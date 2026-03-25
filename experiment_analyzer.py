"""
experiment_analyzer.py — メタデータから実験デザインを完全自動解析し、
全ての意味のある比較プランを生成する。

LLMに一切依存しない決定論的モジュール。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import numpy as np

# ── パターン辞書 ──────────────────────────────────────────

_TIMEPOINT_PATTERNS = re.compile(
    r"(?i)^(time\s*point|timepoint|time|hour|day|week|month|"
    r"dpi|hpi|visit|stage|phase|period|t\d|tp\d)$"
)
_SUBJECT_PATTERNS = re.compile(
    r"(?i)^(subject|patient|donor|mouse|animal|individual|"
    r"participant|host|cage|pen|tank|replicate|rep|sample.?id.?bio)$"
)
_IGNORE_PATTERNS = re.compile(
    r"(?i)^(sample.?id|sample.?name|barcode|linker|primer|"
    r"description|#q2:types|feature.?id|index|filename|"
    r"collection.?date|extract.?group)$"
)
_NUMERIC_TIME_PATTERN = re.compile(r"^(\d+\.?\d*)\s*(h|hr|hour|d|day|w|wk|week|m|mo|month)s?$", re.I)
_REVERSE_TIME_PATTERN = re.compile(r"^(h|hr|hour|d|day|w|wk|week|m|mo|month|visit|v|t|tp|stage|phase)s?\s*(\d+\.?\d*)$", re.I)


# ── データクラス ──────────────────────────────────────────

@dataclass
class FactorInfo:
    """メタデータの1列（因子）の情報"""
    column: str
    levels: List[str]
    n_levels: int
    role: str  # "group", "timepoint", "subject", "covariate", "ignore"
    is_ordered: bool = False
    order: Optional[List[str]] = None
    sample_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def is_balanced(self) -> bool:
        counts = list(self.sample_counts.values())
        return len(set(counts)) == 1 if counts else False


@dataclass
class Comparison:
    """1つの比較"""
    type: str          # "pairwise", "multi_group", "time_series", "interaction", "nested"
    factor: str        # 主因子の列名
    levels: List[str]  # 比較する水準
    description: str   # 人間可読な説明
    subset: Optional[Dict[str, str]] = None  # サブセット条件 {"gravity": "0g"}
    second_factor: Optional[str] = None      # 交互作用の場合
    priority: int = 5  # 1=最重要, 10=補足的


@dataclass
class ExperimentDesign:
    """実験デザインの完全な記述"""
    n_samples: int
    factors: Dict[str, FactorInfo]
    timepoint_col: Optional[str] = None
    subject_col: Optional[str] = None
    group_factors: List[str] = field(default_factory=list)
    primary_factor: Optional[str] = None
    design_type: str = "unknown"  # "one_way", "factorial", "longitudinal", "repeated_measures", "nested"
    comparisons: List[Comparison] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Samples: {self.n_samples}",
            f"Design: {self.design_type}",
            f"Primary factor: {self.primary_factor}",
        ]
        if self.timepoint_col:
            f = self.factors[self.timepoint_col]
            lines.append(f"Timepoint: {self.timepoint_col} ({f.n_levels} levels: {', '.join(f.levels)})")
        if self.subject_col:
            f = self.factors[self.subject_col]
            lines.append(f"Subject: {self.subject_col} ({f.n_levels} subjects)")
        for gf in self.group_factors:
            f = self.factors[gf]
            lines.append(f"Factor '{gf}': {f.n_levels} levels — {', '.join(f.levels)} "
                         f"(n={list(f.sample_counts.values())})")
        lines.append(f"Comparisons planned: {len(self.comparisons)}")
        return "\n".join(lines)


# ── 時間順序の推定 ────────────────────────────────────────

def _parse_time_value(s: str) -> Optional[float]:
    """時間文字列を数値に変換（時間単位に正規化）"""
    stripped = s.strip()
    # パターン1: "8h", "14day", "3.5week"
    m = _NUMERIC_TIME_PATTERN.match(stripped)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        multiplier = {"h": 1, "hr": 1, "hour": 1,
                      "d": 24, "day": 24,
                      "w": 168, "wk": 168, "week": 168,
                      "m": 720, "mo": 720, "month": 720}
        return val * multiplier.get(unit, 1)
    # パターン2: "day7", "visit3", "t2", "phase1"
    m2 = _REVERSE_TIME_PATTERN.match(stripped)
    if m2:
        unit = m2.group(1).lower()
        val = float(m2.group(2))
        multiplier = {"h": 1, "hr": 1, "hour": 1,
                      "d": 24, "day": 24,
                      "w": 168, "wk": 168, "week": 168,
                      "m": 720, "mo": 720, "month": 720}
        return val * multiplier.get(unit, val)  # visit等は数値そのまま
    # 純粋な数値
    try:
        return float(stripped)
    except (ValueError, TypeError):
        return None


def _order_time_levels(levels: List[str]) -> Tuple[List[str], bool]:
    """時間水準をソートし、順序付けが可能だったかを返す"""
    # "baseline" は常に先頭
    baseline_labels = {"baseline", "pre", "before", "control", "t0", "day0", "0h", "0d"}
    baselines = [l for l in levels if l.lower() in baseline_labels]
    others = [l for l in levels if l.lower() not in baseline_labels]

    parsed = [(l, _parse_time_value(l)) for l in others]
    if all(p[1] is not None for p in parsed):
        sorted_others = [l for l, _ in sorted(parsed, key=lambda x: x[1])]
        return baselines + sorted_others, True

    # 数値パースできない場合はアルファベット順
    return baselines + sorted(others), False


# ── メイン解析関数 ────────────────────────────────────────

def analyze_experiment(metadata_path: str | Path) -> ExperimentDesign:
    """メタデータTSVから実験デザインを完全自動解析する"""
    df = pd.read_csv(metadata_path, sep="\t", dtype=str)

    # #q2:types 行を除外
    df = df[~df.iloc[:, 0].str.startswith("#", na=False)].reset_index(drop=True)
    id_col = df.columns[0]
    df = df.set_index(id_col)
    n_samples = len(df)

    # ── 各列を分類 ──
    factors: Dict[str, FactorInfo] = {}
    timepoint_col = None
    subject_col = None

    for col in df.columns:
        if _IGNORE_PATTERNS.match(col):
            continue

        values = df[col].dropna()
        values = values[values != "NA"]
        if len(values) == 0:
            continue

        unique = sorted(values.unique().tolist())
        n_unique = len(unique)
        counts = values.value_counts().to_dict()

        # 役割の判定
        role = "group"

        if _TIMEPOINT_PATTERNS.match(col) and timepoint_col is None:
            role = "timepoint"
            timepoint_col = col
        elif _SUBJECT_PATTERNS.match(col) and subject_col is None:
            role = "subject"
            subject_col = col
        elif n_unique == 1:
            role = "ignore"
        elif n_unique == n_samples:
            # 全サンプルでユニーク → ID的な列
            if _SUBJECT_PATTERNS.match(col):
                role = "subject"
                subject_col = col
            else:
                role = "ignore"
        elif n_unique > 20:
            role = "covariate"  # 連続変数扱い

        fi = FactorInfo(
            column=col, levels=unique, n_levels=n_unique,
            role=role, sample_counts=counts
        )

        # 時系列の順序付け
        if role == "timepoint":
            ordered, is_ordered = _order_time_levels(unique)
            fi.is_ordered = is_ordered
            fi.order = ordered
            fi.levels = ordered

        factors[col] = fi

    # ── group 因子の特定 ──
    group_factors = [k for k, v in factors.items()
                     if v.role == "group" and 2 <= v.n_levels <= 15]

    # 主因子 = 水準数が最も多い group 因子（同数なら先にある列）
    primary_factor = None
    if group_factors:
        primary_factor = max(group_factors,
                             key=lambda k: (factors[k].n_levels, -list(factors.keys()).index(k)))

    # ── デザインタイプの判定 ──
    has_time = timepoint_col is not None
    has_subject = subject_col is not None
    n_group_factors = len(group_factors)

    if has_time and has_subject:
        design_type = "repeated_measures"
    elif has_time:
        design_type = "longitudinal"
    elif n_group_factors >= 2:
        design_type = "factorial"
    elif n_group_factors == 1:
        design_type = "one_way"
    else:
        design_type = "descriptive"

    design = ExperimentDesign(
        n_samples=n_samples,
        factors=factors,
        timepoint_col=timepoint_col,
        subject_col=subject_col,
        group_factors=group_factors,
        primary_factor=primary_factor,
        design_type=design_type,
    )

    # ── 比較プランの生成 ──
    design.comparisons = _generate_comparisons(design, df)

    return design


def _generate_comparisons(design: ExperimentDesign, df: pd.DataFrame) -> List[Comparison]:
    """実験デザインから全ての意味のある比較を生成する"""
    comps: List[Comparison] = []
    factors = design.factors

    # ── 1. 各group因子の全体比較 ──
    for gf in design.group_factors:
        f = factors[gf]
        if f.n_levels == 2:
            comps.append(Comparison(
                type="pairwise", factor=gf, levels=f.levels,
                description=f"{f.levels[0]} vs {f.levels[1]} (overall)",
                priority=2,
            ))
        elif f.n_levels >= 3:
            comps.append(Comparison(
                type="multi_group", factor=gf, levels=f.levels,
                description=f"{gf}: {f.n_levels}-group comparison ({', '.join(f.levels)})",
                priority=2,
            ))
            # ペアワイズ
            for a, b in combinations(f.levels, 2):
                comps.append(Comparison(
                    type="pairwise", factor=gf, levels=[a, b],
                    description=f"{gf}: {a} vs {b}",
                    priority=4,
                ))

    # ── 2. 時系列比較 ──
    if design.timepoint_col:
        tf = factors[design.timepoint_col]
        # 全体の時系列
        comps.append(Comparison(
            type="time_series", factor=design.timepoint_col,
            levels=tf.levels,
            description=f"Time series: {' → '.join(tf.levels)}",
            priority=1,
        ))
        # 各group因子内の時系列
        for gf in design.group_factors:
            for level in factors[gf].levels:
                comps.append(Comparison(
                    type="time_series", factor=design.timepoint_col,
                    levels=tf.levels,
                    description=f"Time series within {gf}={level}: {' → '.join(tf.levels)}",
                    subset={gf: level},
                    priority=3,
                ))

    # ── 3. 各タイムポイントでの群間比較 ──
    if design.timepoint_col:
        tf = factors[design.timepoint_col]
        for gf in design.group_factors:
            f = factors[gf]
            for tp in tf.levels:
                if f.n_levels == 2:
                    comps.append(Comparison(
                        type="pairwise", factor=gf, levels=f.levels,
                        description=f"{f.levels[0]} vs {f.levels[1]} at {design.timepoint_col}={tp}",
                        subset={design.timepoint_col: tp},
                        priority=3,
                    ))
                else:
                    comps.append(Comparison(
                        type="multi_group", factor=gf, levels=f.levels,
                        description=f"{gf} comparison at {design.timepoint_col}={tp}",
                        subset={design.timepoint_col: tp},
                        priority=4,
                    ))

    # ── 4. 交互作用 ──
    if len(design.group_factors) >= 2:
        for a, b in combinations(design.group_factors, 2):
            comps.append(Comparison(
                type="interaction", factor=a, levels=factors[a].levels,
                second_factor=b,
                description=f"Interaction: {a} × {b}",
                priority=3,
            ))
    if design.timepoint_col:
        for gf in design.group_factors:
            comps.append(Comparison(
                type="interaction", factor=gf, levels=factors[gf].levels,
                second_factor=design.timepoint_col,
                description=f"Interaction: {gf} × {design.timepoint_col}",
                priority=2,
            ))

    # ── 5. 被験者/ドナー効果 ──
    if design.subject_col:
        sf = factors[design.subject_col]
        if sf.n_levels >= 2:
            comps.append(Comparison(
                type="multi_group", factor=design.subject_col,
                levels=sf.levels,
                description=f"Subject/Donor variability ({sf.n_levels} subjects)",
                priority=5,
            ))

    # 優先度でソート
    comps.sort(key=lambda c: c.priority)
    return comps
