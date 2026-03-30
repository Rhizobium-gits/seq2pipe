#!/usr/bin/env python3
"""
bayesian_reasoner.py — ベイズ推論ベースの解析判断エンジン
=========================================================
if 文の条件分岐ではなく、仮説ごとの確信度をベイズ更新で蓄積し、
確信度に基づいて次の解析を判断する。

仕組み:
  1. 仮説を定義 ("alpha_differs", "community_shifts", etc.)
  2. 各仮説に事前確率 (prior) を設定
  3. 各ステップの結果が尤度 (likelihood) を提供
  4. ベイズの定理で事後確率 (posterior) を更新
  5. 事後確率に基づいて次のステップを決定

if 文との違い:
  if 文: p < 0.05 → True/False の二値判断
  ベイズ: p=0.034 → P(alpha_differs) が 0.5 → 0.72 に更新
         effect=0.05 → P(alpha_differs) が 0.72 → 0.58 に下降
         observed_features p=0.0007 → 0.58 → 0.81 に再上昇
         → 複数の証拠が確信度を連続的に更新

これにより「p は有意だが effect が小さい。しかし別のメトリクスでも
確認されたので real signal の可能性が高い」という推論が数学的に表現される。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════════════════════════
# 仮説定義
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Hypothesis:
    """検証すべき仮説"""
    name: str
    description: str
    prior: float  # 事前確率 P(H)
    posterior: float = 0.0  # 事後確率（更新後）
    evidence_history: list = field(default_factory=list)
    # 確信度が高い場合に追加すべき解析
    if_confident: list[str] = field(default_factory=list)
    # 確信度が低い場合にスキップすべき解析
    if_unconfident: list[str] = field(default_factory=list)
    # 確信度が中間の場合に検証すべき解析
    if_uncertain: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.posterior = self.prior


# デフォルト仮説セット
DEFAULT_HYPOTHESES = [
    Hypothesis(
        name="alpha_differs",
        description="Alpha diversity significantly differs between groups",
        prior=0.5,
        if_confident=["alpha_effect_size", "alpha_raincloud", "alpha_pairwise"],
        if_unconfident=["alpha_effect_size", "alpha_trajectory"],
        if_uncertain=["alpha_rarefaction"],  # 確認のため
    ),
    Hypothesis(
        name="community_shifts",
        description="Community composition shifts between groups (beta diversity)",
        prior=0.5,
        if_confident=["beta_nmds", "beta_dispersion", "permanova_detail",
                       "pcoa_3d", "distance_boxplot"],
        if_unconfident=["beta_nmds", "beta_tsne", "beta_heatmap",
                         "beta_trajectory", "permanova_detail", "beta_dispersion"],
        if_uncertain=["beta_dispersion"],  # Anderson (2001): 必ず確認
    ),
    Hypothesis(
        name="taxa_differential",
        description="Specific taxa are differentially abundant between groups",
        prior=0.5,
        if_confident=["differential_volcano", "lefse", "indicator_species",
                       "log2fc_heatmap", "waterfall_plot", "abundance_stripplot"],
        if_unconfident=["differential_volcano", "lefse", "indicator_species"],
        if_uncertain=["taxa_bubble_chart"],
    ),
    Hypothesis(
        name="functional_shift",
        description="Microbial functional profile shifts between groups",
        prior=0.3,  # 低い事前確率（taxa_differential が確認されてから上がる）
        if_confident=["picrust2", "network_analysis", "random_forest_importance"],
        if_unconfident=["picrust2", "network_analysis"],
        if_uncertain=[],
    ),
    Hypothesis(
        name="sampling_artifact",
        description="Observed differences are due to uneven sampling depth",
        prior=0.2,
        if_confident=[],  # artifact なら follow-up は無意味
        if_unconfident=[],
        if_uncertain=["alpha_rarefaction", "rarefaction"],
    ),
    Hypothesis(
        name="compositional_artifact",
        description="Extreme fold changes are compositional artifacts (rare taxa bias)",
        prior=0.2,
        if_confident=[],  # artifact なら differential は信頼できない
        if_unconfident=[],
        if_uncertain=[],
    ),
    Hypothesis(
        name="underpowered",
        description="Study is underpowered to detect true differences",
        prior=0.3,
        if_confident=[],  # underpowered なら p 値は信頼できない
        if_unconfident=[],
        if_uncertain=["alpha_effect_size", "diversity_profile"],
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 尤度関数: 各観測が各仮説にどれだけの証拠を提供するか
# ═══════════════════════════════════════════════════════════════════════════════

def _p_to_likelihood(p_value: float, direction: str = "support") -> tuple[float, float]:
    """
    p 値から尤度比を計算。
    Returns: (P(data|H_true), P(data|H_false))

    p=0.001 → 強い支持 → (0.95, 0.05)
    p=0.05  → 弱い支持 → (0.65, 0.35)
    p=0.5   → 中立     → (0.50, 0.50)
    p=0.9   → 反証     → (0.10, 0.90)
    """
    if direction == "support":
        # p が小さいほど仮説を支持
        strength = min(1.0, max(0.0, -math.log10(max(p_value, 1e-10)) / 4.0))
        l_true = 0.5 + 0.45 * strength   # 0.50 ~ 0.95
        l_false = 1.0 - l_true            # 0.05 ~ 0.50
    else:
        # p が大きいほど仮説を支持（反証の場合）
        strength = min(1.0, max(0.0, p_value * 2))
        l_true = 0.5 + 0.45 * strength
        l_false = 1.0 - l_true
    return l_true, l_false


def _effect_to_likelihood(effect: float, threshold: float = 0.5) -> tuple[float, float]:
    """
    効果量から尤度比を計算。
    large effect → 仮説支持
    small effect → 弱い反証
    """
    if effect >= threshold:
        strength = min(1.0, effect / (threshold * 2))
        return 0.5 + 0.4 * strength, 0.5 - 0.4 * strength
    else:
        weakness = 1.0 - effect / threshold
        return 0.5 - 0.3 * weakness, 0.5 + 0.3 * weakness


def _ratio_to_likelihood(ratio: float, threshold: float = 2.0) -> tuple[float, float]:
    """
    between/within 距離比から尤度比。
    ratio > threshold → 群間分離を支持
    """
    if ratio >= threshold:
        strength = min(1.0, (ratio - 1.0) / (threshold - 1.0))
        return 0.5 + 0.4 * strength, 0.5 - 0.4 * strength
    elif ratio > 1.0:
        return 0.55, 0.45  # 弱い支持
    else:
        return 0.3, 0.7  # 分離なし


# ═══════════════════════════════════════════════════════════════════════════════
# BayesianReasoner
# ═══════════════════════════════════════════════════════════════════════════════

class BayesianReasoner:
    """
    ベイズ推論ベースの解析判断エンジン。

    使い方:
        reasoner = BayesianReasoner()
        reasoner.update_from_snapshot("alpha_boxplot", snapshot)
        reasoner.update_from_snapshot("beta_pcoa", snapshot)
        decision = reasoner.decide(remaining_steps)
    """

    def __init__(self, hypotheses: Optional[list[Hypothesis]] = None,
                 confidence_threshold: float = 0.7,
                 uncertainty_range: tuple[float, float] = (0.3, 0.7),
                 log_callback: Optional[Callable] = None):
        self.hypotheses = {h.name: Hypothesis(
            name=h.name, description=h.description, prior=h.prior,
            if_confident=list(h.if_confident),
            if_unconfident=list(h.if_unconfident),
            if_uncertain=list(h.if_uncertain),
        ) for h in (hypotheses or DEFAULT_HYPOTHESES)}
        self.confidence_threshold = confidence_threshold
        self.uncertainty_range = uncertainty_range
        self._log = log_callback or (lambda msg: None)
        self._update_count = 0

    def _bayes_update(self, hypothesis: Hypothesis,
                      l_true: float, l_false: float,
                      evidence_name: str):
        """
        ベイズの定理:
        P(H|D) = P(D|H) * P(H) / P(D)
        P(D) = P(D|H)*P(H) + P(D|~H)*P(~H)
        """
        prior = hypothesis.posterior
        p_d = l_true * prior + l_false * (1 - prior)

        if p_d > 0:
            posterior = l_true * prior / p_d
        else:
            posterior = prior

        # クリップ（0.01 ~ 0.99 で極端を避ける）
        posterior = max(0.01, min(0.99, posterior))

        old = hypothesis.posterior
        hypothesis.posterior = posterior
        hypothesis.evidence_history.append({
            "evidence": evidence_name,
            "l_true": round(l_true, 3),
            "l_false": round(l_false, 3),
            "prior": round(old, 3),
            "posterior": round(posterior, 3),
            "delta": round(posterior - old, 3),
        })

        direction = "↑" if posterior > old else "↓" if posterior < old else "→"
        self._log(f"    [{hypothesis.name}] {old:.3f} {direction} {posterior:.3f} "
                  f"(evidence: {evidence_name}, LR={l_true/l_false:.2f})")

    def update_from_snapshot(self, step_key: str, snapshot):
        """
        DataSnapshot から各仮説の確信度をベイズ更新する。
        1つのステップが複数の仮説に同時に証拠を提供する。
        """
        self._update_count += 1
        self._log(f"  [Bayes] Update #{self._update_count} from {step_key}:")

        # ── Alpha diversity tests ──
        alpha_tests = getattr(snapshot, 'alpha_group_tests', [])
        for test in alpha_tests:
            p = test["p"]
            effect = test.get("effect_size", 0)
            metric = test.get("metric", "alpha")

            # alpha_differs 仮説を更新
            l_t, l_f = _p_to_likelihood(p)
            self._bayes_update(self.hypotheses["alpha_differs"],
                             l_t, l_f, f"{metric} p={p:.4g}")

            if effect > 0:
                l_t, l_f = _effect_to_likelihood(effect)
                self._bayes_update(self.hypotheses["alpha_differs"],
                                 l_t, l_f, f"{metric} effect={effect:.3f}")

            # underpowered の証拠（p が borderline で effect が小さい場合）
            if 0.01 < p < 0.1 and effect < 0.3:
                self._bayes_update(self.hypotheses["underpowered"],
                                 0.7, 0.3, f"borderline p + small effect")

            # sampling_artifact: p 有意だが effect 極小 → artifact 疑い
            if p < 0.05 and effect < 0.1:
                self._bayes_update(self.hypotheses["sampling_artifact"],
                                 0.65, 0.35, f"sig p but tiny effect")

        # ── Beta diversity tests ──
        beta_p = getattr(snapshot, 'beta_pvalues', {})
        beta_ratio = getattr(snapshot, 'beta_within_vs_between', {})

        for metric, p in beta_p.items():
            l_t, l_f = _p_to_likelihood(p)
            self._bayes_update(self.hypotheses["community_shifts"],
                             l_t, l_f, f"{metric} PERMANOVA p={p:.4g}")

        for metric, info in beta_ratio.items():
            ratio = info.get("ratio", 1.0)
            l_t, l_f = _ratio_to_likelihood(ratio)
            self._bayes_update(self.hypotheses["community_shifts"],
                             l_t, l_f, f"{metric} ratio={ratio:.2f}")

        # ── Differential genera ──
        diff = getattr(snapshot, 'group_differential_genera', [])
        if diff:
            n_sig = sum(1 for g in diff if g["fold_change"] > 2)
            max_fc = max(g["fold_change"] for g in diff)

            # taxa_differential
            if n_sig >= 3:
                self._bayes_update(self.hypotheses["taxa_differential"],
                                 0.85, 0.15, f"{n_sig} genera >2x fc")
            elif n_sig >= 1:
                self._bayes_update(self.hypotheses["taxa_differential"],
                                 0.65, 0.35, f"{n_sig} genus >2x fc")

            # functional_shift (taxa が変われば機能も変わる可能性)
            if n_sig >= 5:
                self._bayes_update(self.hypotheses["functional_shift"],
                                 0.75, 0.25, f"{n_sig} differential genera → functional shift likely")

            # compositional_artifact (極端な fc + 低豊度)
            if max_fc > 50:
                low_abd = any(
                    max(g.get("group_a_mean", 0), g.get("group_b_mean", 0)) < 1.0
                    for g in diff if g["fold_change"] > 50
                )
                if low_abd:
                    self._bayes_update(self.hypotheses["compositional_artifact"],
                                     0.80, 0.20, f"fc={max_fc:.0f}x at low abundance")

        # ── Quality metrics ──
        sparsity = getattr(snapshot, 'sparsity', 0)
        if sparsity > 0.9:
            self._bayes_update(self.hypotheses["compositional_artifact"],
                             0.65, 0.35, f"sparsity={sparsity:.0%}")
            self._bayes_update(self.hypotheses["underpowered"],
                             0.60, 0.40, f"sparse feature table")

        reads = getattr(snapshot, 'reads_per_sample', {})
        if reads:
            import statistics as _st
            vals = list(reads.values())
            if len(vals) > 1 and _st.mean(vals) > 0:
                cv = _st.stdev(vals) / _st.mean(vals)
                if cv > 0.5:
                    self._bayes_update(self.hypotheses["sampling_artifact"],
                                     0.70, 0.30, f"read depth CV={cv:.2f}")

    def decide(self, remaining_keys: list[str]) -> "Decision":
        """
        確信度に基づいて判断。
        各仮説の事後確率が confidence_threshold を超えたら confident、
        uncertainty_range 内なら uncertain、下回ったら unconfident。
        """
        from eval_mediator import Decision
        d = Decision()
        remaining_set = set(remaining_keys)

        skip_candidates = set()
        add_candidates = {}

        for h_name, h in self.hypotheses.items():
            p = h.posterior
            lo, hi = self.uncertainty_range

            if p >= self.confidence_threshold:
                # 確信 → confident アクション
                for key in h.if_confident:
                    if key not in remaining_set:
                        add_candidates[key] = {
                            "key": key,
                            "reason": f"P({h_name})={p:.2f} ≥ {self.confidence_threshold} → {h.description}",
                            "priority": max(1, int(10 * (1 - p))),
                        }
                d.reasoning.append(
                    f"CONFIDENT: P({h_name})={p:.2f} — {h.description}")

            elif p <= (1 - self.confidence_threshold):
                # 反証 → unconfident アクション (skip)
                for key in h.if_unconfident:
                    if key in remaining_set:
                        skip_candidates.add(key)
                d.reasoning.append(
                    f"REJECTED: P({h_name})={p:.2f} — {h.description}")

            elif lo <= p <= hi:
                # 不確実 → uncertain アクション (検証追加)
                for key in h.if_uncertain:
                    if key not in remaining_set:
                        add_candidates[key] = {
                            "key": key,
                            "reason": f"P({h_name})={p:.2f} uncertain → verify",
                            "priority": 3,
                        }
                d.reasoning.append(
                    f"UNCERTAIN: P({h_name})={p:.2f} — needs verification")

        # artifact 仮説が confident → differential 結果を割引
        if self.hypotheses["compositional_artifact"].posterior >= self.confidence_threshold:
            d.investigate.append({
                "title": "Compositional artifact reanalysis",
                "hypothesis": f"P(compositional_artifact)={self.hypotheses['compositional_artifact'].posterior:.2f} — filter rare taxa and retest",
                "method": "Filter ASVs < 0.1% mean relative abundance, recompute differential analysis",
                "code_instructions": "Filter feature table, recompute genus fold changes, compare filtered vs unfiltered",
                "priority": 1,
            })

        # sampling_artifact confident → rarefaction 必須
        if self.hypotheses["sampling_artifact"].posterior >= self.confidence_threshold:
            if "alpha_rarefaction" not in remaining_set and "rarefaction" not in remaining_set:
                add_candidates["alpha_rarefaction"] = {
                    "key": "alpha_rarefaction",
                    "reason": f"P(sampling_artifact)={self.hypotheses['sampling_artifact'].posterior:.2f} → confirm with rarefaction",
                    "priority": 1,
                }

        d.skip = sorted(skip_candidates)
        d.add = sorted(add_candidates.values(), key=lambda x: x.get("priority", 5))

        return d

    def get_state(self) -> dict:
        """現在の全仮説の確信度を返す"""
        return {
            h_name: {
                "posterior": round(h.posterior, 4),
                "prior": round(h.prior, 4),
                "n_updates": len(h.evidence_history),
                "status": (
                    "confident" if h.posterior >= self.confidence_threshold
                    else "rejected" if h.posterior <= (1 - self.confidence_threshold)
                    else "uncertain"
                ),
                "last_evidence": h.evidence_history[-1] if h.evidence_history else None,
            }
            for h_name, h in self.hypotheses.items()
        }

    def get_reasoning_trace(self) -> str:
        """人間可読な推論過程"""
        lines = ["=== Bayesian Reasoning Trace ==="]
        for h_name, h in self.hypotheses.items():
            status = "CONFIDENT" if h.posterior >= self.confidence_threshold else \
                     "REJECTED" if h.posterior <= (1 - self.confidence_threshold) else \
                     "uncertain"
            bar = "█" * int(h.posterior * 20) + "░" * (20 - int(h.posterior * 20))
            lines.append(f"  {h_name:25s} [{bar}] {h.posterior:.3f} ({status})")
            for ev in h.evidence_history[-3:]:
                delta = ev["delta"]
                arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
                lines.append(f"    {arrow} {ev['evidence']:40s} {ev['prior']:.3f}→{ev['posterior']:.3f}")
        return "\n".join(lines)
