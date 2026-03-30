#!/usr/bin/env python3
"""
reasoning_engine.py — v3 Adaptive Reasoning Engine
====================================================
v2 DecisionEngine の上位互換。静的 if 文ではなく、
蓄積された発見の文脈に基づいて推論チェーンを構築し、
後のステップの判断を前のステップの結果で動的に調整する。

v2 との違い:
  v2: if p < 0.05 → add (各ステップ独立に判断)
  v3: "alpha weak + rarefaction confirms real + beta ns"
      → "specific taxa differ but community structure is similar"
      → differential analysis 優先、ordination 低優先

推論チェーン:
  Observation → Interpretation → Hypothesis → Action

各 Observation は前ステップの DataSnapshot から生成され、
Interpretation は蓄積された Observation の文脈で生成される。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Observation:
    """1ステップから得られた観測"""
    step_key: str
    category: str  # alpha, beta, taxonomy, quality
    finding: str   # "alpha p=0.034, effect=0.05"
    significance: float  # 0-1
    direction: str  # "significant", "non-significant", "ambiguous"


@dataclass
class Interpretation:
    """複数の Observation から導かれた解釈"""
    summary: str
    confidence: float  # 0-1
    based_on: list[str] = field(default_factory=list)  # step_keys


@dataclass
class Hypothesis:
    """解釈から導かれた仮説"""
    statement: str
    test_with: list[str]  # 検証すべき解析 step keys
    priority: int  # 1-10


@dataclass
class ReasoningChain:
    """推論チェーン全体"""
    observations: list[Observation] = field(default_factory=list)
    interpretations: list[Interpretation] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    context: dict = field(default_factory=dict)  # 蓄積された文脈

    def summary(self) -> str:
        lines = [f"Observations: {len(self.observations)}"]
        for o in self.observations[-3:]:
            lines.append(f"  [{o.category}] {o.finding} → {o.direction}")
        lines.append(f"Interpretations: {len(self.interpretations)}")
        for i in self.interpretations[-2:]:
            lines.append(f"  {i.summary} (conf={i.confidence:.2f})")
        lines.append(f"Hypotheses: {len(self.hypotheses)}")
        for h in self.hypotheses[-2:]:
            lines.append(f"  {h.statement} → test: {h.test_with}")
        lines.append(f"Context: {self.context}")
        return "\n".join(lines)


class ReasoningEngine:
    """
    文脈依存の推論エンジン。
    各ステップの結果を Observation として受け取り、
    蓄積された Observation の文脈で Interpretation を生成し、
    それに基づいて次のステップを決定する。

    v2 DecisionEngine との互換: decide() メソッドは同じインターフェース。
    """

    def __init__(self):
        self.chain = ReasoningChain()
        # 推論規則（文脈依存）
        self._rules = self._build_rules()

    def observe(self, step_key: str, snapshot) -> Observation:
        """DataSnapshot から Observation を生成"""
        # Alpha
        if "alpha" in step_key:
            tests = snapshot.alpha_group_tests if hasattr(snapshot, 'alpha_group_tests') else []
            if tests:
                min_p = min(t["p"] for t in tests)
                max_effect = max(t.get("effect_size", 0) for t in tests)
                if min_p < 0.05 and max_effect > 0.5:
                    obs = Observation(step_key, "alpha",
                        f"alpha p={min_p:.4g}, effect={max_effect:.2f} → strong",
                        1.0 - min_p, "significant")
                elif min_p < 0.05:
                    obs = Observation(step_key, "alpha",
                        f"alpha p={min_p:.4g}, effect={max_effect:.2f} → weak signal",
                        0.5, "ambiguous")
                else:
                    obs = Observation(step_key, "alpha",
                        f"alpha p={min_p:.4g} → not significant",
                        0.0, "non-significant")
            else:
                obs = Observation(step_key, "alpha", "no alpha tests available", 0.0, "unknown")

        # Beta
        elif "beta" in step_key or "pcoa" in step_key or "permanova" in step_key:
            pvals = snapshot.beta_pvalues if hasattr(snapshot, 'beta_pvalues') else {}
            ratios = snapshot.beta_within_vs_between if hasattr(snapshot, 'beta_within_vs_between') else {}
            if pvals:
                min_p = min(pvals.values())
                max_ratio = max((v.get("ratio", 0) for v in ratios.values()), default=0)
                if min_p < 0.05 and max_ratio > 2.0:
                    obs = Observation(step_key, "beta",
                        f"PERMANOVA p={min_p:.4g}, ratio={max_ratio:.1f} → clear separation",
                        1.0 - min_p, "significant")
                elif min_p < 0.05:
                    obs = Observation(step_key, "beta",
                        f"PERMANOVA p={min_p:.4g}, ratio={max_ratio:.1f} → weak separation",
                        0.5, "ambiguous")
                else:
                    obs = Observation(step_key, "beta",
                        f"PERMANOVA p={min_p:.4g} → no group separation",
                        0.0, "non-significant")
            else:
                obs = Observation(step_key, "beta", "no beta tests available", 0.0, "unknown")

        # Taxonomy
        elif "taxonomy" in step_key or "differential" in step_key or "volcano" in step_key:
            diff = snapshot.group_differential_genera if hasattr(snapshot, 'group_differential_genera') else []
            if diff:
                max_fc = max(g["fold_change"] for g in diff)
                n_sig = sum(1 for g in diff if g["fold_change"] > 2)
                obs = Observation(step_key, "taxonomy",
                    f"{n_sig} genera >2x, max fc={max_fc:.0f}x",
                    min(1.0, n_sig / 10), "significant" if n_sig >= 3 else "ambiguous")
            else:
                obs = Observation(step_key, "taxonomy", "no differential data", 0.0, "unknown")

        # Quality
        elif "qc" in step_key or "rarefaction" in step_key or "denoising" in step_key:
            sparsity = snapshot.sparsity if hasattr(snapshot, 'sparsity') else 0
            obs = Observation(step_key, "quality",
                f"sparsity={sparsity:.0%}",
                1.0 - sparsity, "ambiguous" if sparsity > 0.9 else "non-significant")

        else:
            obs = Observation(step_key, "other", "unclassified step", 0.5, "unknown")

        self.chain.observations.append(obs)
        self._update_context(obs)
        return obs

    def _update_context(self, obs: Observation):
        """Observation から文脈を更新"""
        ctx = self.chain.context

        if obs.category == "alpha":
            ctx["alpha_direction"] = obs.direction
            ctx["alpha_finding"] = obs.finding

        elif obs.category == "beta":
            ctx["beta_direction"] = obs.direction
            ctx["beta_finding"] = obs.finding

        elif obs.category == "taxonomy":
            ctx["taxonomy_direction"] = obs.direction
            ctx["taxonomy_finding"] = obs.finding

        elif obs.category == "quality":
            ctx["quality_finding"] = obs.finding

        # 文脈の組み合わせから解釈を生成
        self._generate_interpretations()

    def _generate_interpretations(self):
        """蓄積された文脈から解釈を生成 — ここが v2 にない推論"""
        ctx = self.chain.context
        interps = []

        alpha_d = ctx.get("alpha_direction", "unknown")
        beta_d = ctx.get("beta_direction", "unknown")
        tax_d = ctx.get("taxonomy_direction", "unknown")

        # ── 文脈依存の推論パターン ──

        # Pattern 1: alpha sig + beta ns → 個別菌は変わるが群集構造は保存
        if alpha_d in ("significant", "ambiguous") and beta_d == "non-significant":
            interps.append(Interpretation(
                "Alpha differs but community structure is preserved. "
                "Individual taxa shift but overall composition remains similar.",
                0.7, based_on=["alpha", "beta"]))
            ctx["strategy"] = "taxa_focused"  # differential analysis 優先

        # Pattern 2: alpha ns + beta sig → 組成シフトだが多様性は同じ
        elif alpha_d == "non-significant" and beta_d in ("significant", "ambiguous"):
            interps.append(Interpretation(
                "Diversity is similar but composition differs. "
                "Suggests taxon replacement rather than diversity loss.",
                0.7, based_on=["alpha", "beta"]))
            ctx["strategy"] = "ordination_focused"  # ordination + differential

        # Pattern 3: both sig → 強いシグナル、全方位解析
        elif alpha_d == "significant" and beta_d == "significant":
            interps.append(Interpretation(
                "Both diversity and composition differ. Strong biological signal. "
                "Full analytical suite is warranted.",
                0.9, based_on=["alpha", "beta"]))
            ctx["strategy"] = "comprehensive"

        # Pattern 4: both ns → シグナルなし
        elif alpha_d == "non-significant" and beta_d == "non-significant":
            interps.append(Interpretation(
                "No significant differences in diversity or composition. "
                "Exploratory visualization only; statistical follow-ups likely uninformative.",
                0.8, based_on=["alpha", "beta"]))
            ctx["strategy"] = "minimal"

        # Pattern 4b: both ambiguous → 探索的だがフォローアップは限定
        if alpha_d == "ambiguous" and beta_d == "ambiguous":
            if "strategy" not in ctx:
                interps.append(Interpretation(
                    "Both alpha and beta show ambiguous signals. "
                    "Borderline results warrant cautious exploration.",
                    0.5, based_on=["alpha", "beta"]))
                ctx["strategy"] = "exploratory"

        # Pattern 4c: one ambiguous + one unknown → 探索的
        if "strategy" not in ctx:
            if alpha_d != "unknown" or beta_d != "unknown":
                ctx["strategy"] = "exploratory"
                interps.append(Interpretation(
                    "Partial data available; exploratory analysis recommended.",
                    0.4, based_on=["alpha", "beta"]))
            else:
                ctx["strategy"] = "exploratory"

        # Pattern 5: alpha ambiguous + rarefaction done
        if alpha_d == "ambiguous" and "rarefaction_done" in ctx:
            if ctx.get("rarefaction_confirms_artifact", False):
                interps.append(Interpretation(
                    "Weak alpha signal confirmed as sampling artifact by rarefaction.",
                    0.9, based_on=["alpha", "rarefaction"]))
                ctx["alpha_direction"] = "non-significant"  # 信頼度を下げる
                ctx["strategy"] = ctx.get("strategy", "minimal")
            else:
                interps.append(Interpretation(
                    "Weak alpha signal is not a sampling artifact. Real but small effect.",
                    0.7, based_on=["alpha", "rarefaction"]))
                ctx["alpha_direction"] = "significant"  # 信頼度を上げる

        # Pattern 6: high sparsity + differential
        if ctx.get("quality_finding", "").startswith("sparsity=9") and tax_d == "significant":
            interps.append(Interpretation(
                "High sparsity with differential taxa: compositional artifacts likely. "
                "Extreme fold changes in rare taxa should be interpreted cautiously.",
                0.8, based_on=["quality", "taxonomy"]))
            ctx["compositional_caution"] = True

        # Pattern 7: taxonomy significant but few genera
        if tax_d == "significant" and "taxonomy_finding" in ctx:
            finding = ctx["taxonomy_finding"]
            if "1 genera" in finding or "2 genera" in finding:
                interps.append(Interpretation(
                    "Few differential genera: effect may be driven by a single taxon bloom. "
                    "Targeted follow-up on the dominant taxon is more informative than broad surveys.",
                    0.6, based_on=["taxonomy"]))

        self.chain.interpretations = interps  # 最新の解釈で置換

    def decide(self, remaining_keys: list[str]) -> "Decision":
        """
        蓄積された推論チェーンに基づいて判断。
        v2 DecisionEngine と同じインターフェースだが、
        前ステップの結果が後の判断に影響する。
        """
        from eval_mediator import Decision

        d = Decision()
        ctx = self.chain.context
        strategy = ctx.get("strategy", "comprehensive")
        remaining_set = set(remaining_keys)
        completed = {o.step_key for o in self.chain.observations}

        alpha_d = ctx.get("alpha_direction", "unknown")
        beta_d = ctx.get("beta_direction", "unknown")
        tax_d = ctx.get("taxonomy_direction", "unknown")

        # ── Strategy-based decisions ──

        if strategy == "minimal":
            # 両方 ns → ほぼ全てスキップ
            for key in ["alpha_effect_size", "alpha_trajectory",
                        "beta_nmds", "beta_tsne", "permanova_detail",
                        "beta_dispersion", "beta_heatmap", "beta_trajectory",
                        "differential_volcano", "lefse", "indicator_species",
                        "multi_group_differential", "effect_size_forest",
                        "picrust2", "ml_classifier"]:
                if key in remaining_set:
                    d.skip.append(key)
            d.reasoning.append(f"strategy=minimal: no significant signals → skip {len(d.skip)} follow-ups")

        elif strategy == "taxa_focused":
            # alpha sig + beta ns → differential を優先、ordination を低優先
            for key in ["beta_nmds", "beta_tsne", "beta_dispersion",
                        "beta_heatmap", "beta_trajectory", "permanova_detail"]:
                if key in remaining_set:
                    d.skip.append(key)
            # differential を追加
            for key in ["differential_volcano", "lefse", "indicator_species"]:
                if key not in completed and key not in remaining_set:
                    d.add.append({"key": key, "reason": f"taxa_focused strategy: {ctx.get('alpha_finding','')}", "priority": 3})
            d.reasoning.append("strategy=taxa_focused: alpha sig + beta ns → prioritize differential, skip ordination")

        elif strategy == "ordination_focused":
            # alpha ns + beta sig → ordination を優先
            for key in ["alpha_effect_size", "alpha_trajectory"]:
                if key in remaining_set:
                    d.skip.append(key)
            for key in ["beta_nmds", "beta_dispersion", "permanova_detail"]:
                if key not in completed and key not in remaining_set:
                    d.add.append({"key": key, "reason": "ordination_focused: beta sig → deep ordination", "priority": 3})
            d.reasoning.append("strategy=ordination_focused: alpha ns + beta sig → prioritize ordination")

        elif strategy == "comprehensive":
            # 両方 sig → 全て実行、ただし優先順位をつける
            d.reasoning.append("strategy=comprehensive: both sig → full analysis suite")

        # ── 文脈依存の追加規則 ──

        # compositional caution
        if ctx.get("compositional_caution"):
            d.investigate.append({
                "title": "Compositional artifact check",
                "hypothesis": "High sparsity + extreme fold changes → filter rare taxa and recompute",
                "method": "Filter ASVs < 0.1% mean relative abundance, recompute fold changes",
                "code_instructions": "Filter feature table by mean relative abundance > 0.001, "
                    "recompute group-level genus abundances, compare filtered vs unfiltered fold changes",
                "priority": 2,
            })
            d.reasoning.append("compositional_caution: high sparsity → add artifact check")

        # Confidence adjustment based on accumulated evidence
        if alpha_d == "ambiguous" and "rarefaction" not in completed:
            if "alpha_rarefaction" not in remaining_set:
                d.add.append({"key": "alpha_rarefaction",
                    "reason": "alpha ambiguous → rarefaction needed to confirm/deny",
                    "priority": 2})
            d.reasoning.append("alpha ambiguous → rarefaction needed for confirmation")

        return d

    def _build_rules(self) -> list:
        """将来的にルールを外部ファイルから読み込む拡張点"""
        return []

    def get_reasoning_summary(self) -> str:
        """推論チェーンの要約"""
        return self.chain.summary()
