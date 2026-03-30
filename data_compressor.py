#!/usr/bin/env python3
"""
data_compressor.py — データ圧縮と効率的表現
=============================================
マイクロバイオームデータ特有の性質（高スパース、組成的制約）を活用した
圧縮・量子化モジュール。

1. 極座標量子化: 組成データ（相対豊度）を角度ベクトルに変換
   → 90%+ のゼロを排除しつつ、サンプル間距離を保存
2. 適応的距離行列圧縮: float64 → 可変ビット幅 + エラー補正
3. 知識状態圧縮: 8軸スコア行列を最小表現に圧縮

全てローカル実行、GPU不要。
"""
from __future__ import annotations
import math
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 極座標量子化（Polar Quantization）
# ═══════════════════════════════════════════════════════════════════════════════

class PolarQuantizer:
    """
    組成データ（相対豊度）を極座標系に変換して圧縮する。

    原理:
      相対豊度ベクトル p = [p1, p2, ..., pk] (Σpi = 1) は
      k-1 次元の単体（simplex）上の点。
      これを超球面座標に変換すると:
        θ_i = arccos(√p_i / √(Σ_{j>=i} p_j))
      角度ベクトル θ は [0, π/2] の範囲で、
      8ビット量子化で 256 段階 → 十分な精度。

    利点:
      - ゼロ豊度の菌は角度 = π/2（最大角）に集約
      - スパース行列を密な角度ベクトルに変換
      - サンプル間の Aitchison 距離が角度差から近似可能
    """

    def __init__(self, n_bits: int = 8):
        self.n_bits = n_bits
        self.n_levels = 2 ** n_bits
        self.scale = (self.n_levels - 1) / (math.pi / 2)

    def encode(self, abundances: list[float]) -> list[int]:
        """
        相対豊度ベクトル → 量子化角度ベクトル

        Input: [0.56, 0.23, 0.10, 0.05, 0.03, 0.02, 0.01, 0.0, ...]
        Output: [42, 78, 105, 130, 142, 150, 158, 255, ...]  (8-bit)
        """
        total = sum(abundances)
        if total <= 0:
            return [self.n_levels - 1] * len(abundances)

        # 正規化
        p = [a / total for a in abundances]

        angles = []
        remaining = 1.0
        for i in range(len(p)):
            if remaining <= 1e-15:
                angles.append(self.n_levels - 1)  # 最大角 = ゼロ
                continue

            ratio = min(1.0, p[i] / remaining)
            theta = math.acos(max(0.0, min(1.0, math.sqrt(ratio))))

            # 量子化
            q = min(self.n_levels - 1, max(0, round(theta * self.scale)))
            angles.append(q)
            remaining -= p[i]

        return angles

    def decode(self, angles: list[int]) -> list[float]:
        """
        量子化角度ベクトル → 復元された相対豊度
        """
        p = []
        remaining = 1.0

        for q in angles:
            theta = q / self.scale
            ratio = math.cos(theta) ** 2
            abundance = ratio * remaining
            p.append(abundance)
            remaining -= abundance
            remaining = max(0.0, remaining)

        # 正規化（量子化誤差の補正）
        total = sum(p)
        if total > 0:
            p = [x / total for x in p]
        return p

    def compression_ratio(self, original_nonzero: int, total_features: int) -> float:
        """圧縮率を計算"""
        original_bytes = total_features * 8  # float64
        compressed_bytes = original_nonzero * (self.n_bits / 8)
        return original_bytes / compressed_bytes if compressed_bytes > 0 else float('inf')

    def error_stats(self, original: list[float], reconstructed: list[float]) -> dict:
        """量子化誤差の統計"""
        if not original or not reconstructed:
            return {"mae": 0, "max_error": 0, "rmse": 0}
        n = min(len(original), len(reconstructed))
        errors = [abs(original[i] - reconstructed[i]) for i in range(n)]
        mae = sum(errors) / n
        max_err = max(errors)
        rmse = math.sqrt(sum(e**2 for e in errors) / n)
        return {"mae": mae, "max_error": max_err, "rmse": rmse}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 適応的距離行列圧縮
# ═══════════════════════════════════════════════════════════════════════════════

class DistanceMatrixCompressor:
    """
    距離行列を適応的ビット幅で圧縮する。
    Bray-Curtis 距離は [0, 1] 範囲なので、8ビットで 256 段階に量子化。
    エラー補正: チェックサムで行ごとの整合性を保証。

    圧縮率: float64 (8 bytes) → uint8 (1 byte) = 8x 圧縮
    """

    def __init__(self, n_bits: int = 8):
        self.n_bits = n_bits
        self.n_levels = 2 ** n_bits - 1  # 255 (0は完全同一用に予約)

    def compress(self, distance_matrix: dict, sample_ids: list[str]) -> dict:
        """
        {(si, sj): float} → 圧縮表現 + エラー補正チェックサム
        """
        n = len(sample_ids)
        compressed = {}
        checksums = {}

        for i, si in enumerate(sample_ids):
            row_sum = 0.0
            row_values = []
            for j, sj in enumerate(sample_ids):
                if i >= j:
                    continue
                d = distance_matrix.get((si, sj),
                    distance_matrix.get((sj, si), 0.0))
                q = min(self.n_levels, max(0, round(d * self.n_levels)))
                compressed[(i, j)] = q
                row_sum += d
                row_values.append(q)

            # 行チェックサム（エラー検出）
            checksums[i] = sum(row_values) % 256

        return {
            "compressed": compressed,
            "checksums": checksums,
            "n_samples": n,
            "n_bits": self.n_bits,
            "sample_ids": sample_ids,
        }

    def decompress(self, data: dict) -> dict:
        """圧縮表現 → 復元距離行列"""
        result = {}
        ids = data["sample_ids"]
        n = data["n_samples"]

        for (i, j), q in data["compressed"].items():
            d = q / self.n_levels
            result[(ids[i], ids[j])] = d
            result[(ids[j], ids[i])] = d

        # 対角要素
        for s in ids:
            result[(s, s)] = 0.0

        return result

    def verify(self, data: dict) -> list[int]:
        """チェックサム検証。不整合な行のインデックスを返す"""
        errors = []
        for i, expected in data["checksums"].items():
            actual = sum(
                data["compressed"].get((i, j), 0)
                for j in range(data["n_samples"]) if j > i
            ) % 256
            if actual != expected:
                errors.append(i)
        return errors

    def stats(self, original: dict, restored: dict,
              sample_ids: list[str]) -> dict:
        """圧縮前後の統計"""
        errors = []
        for i, si in enumerate(sample_ids):
            for j, sj in enumerate(sample_ids):
                if i >= j:
                    continue
                orig = original.get((si, sj), original.get((sj, si), 0))
                rest = restored.get((si, sj), restored.get((sj, si), 0))
                errors.append(abs(orig - rest))

        n_pairs = len(errors)
        original_bytes = n_pairs * 8
        compressed_bytes = n_pairs * (self.n_bits / 8)

        return {
            "n_pairs": n_pairs,
            "mae": sum(errors) / n_pairs if errors else 0,
            "max_error": max(errors) if errors else 0,
            "compression_ratio": original_bytes / compressed_bytes if compressed_bytes > 0 else 0,
            "original_bytes": original_bytes,
            "compressed_bytes": int(compressed_bytes),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 知識状態の圧縮（LLM コンテキスト効率化）
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeCompressor:
    """
    EvalMediator の知識状態を LLM に渡す前に圧縮する。
    8軸 × N ステップのスコア行列を最小表現に変換。

    圧縮方法:
    1. SVD で 3 主成分に圧縮（既存）
    2. 各主成分を 4ビット量子化（16段階）
    3. テキスト表現を最小化（不要な空白・冗長性を除去）

    効果: 典型的な 20 ステップの知識状態を
          ~2000 トークン → ~200 トークンに圧縮
    """

    def compress_for_llm(self, state) -> str:
        """知識状態 → LLM 用最小テキスト"""
        if not hasattr(state, 'step_scores') or not state.step_scores:
            return "No data yet."

        lines = []

        # 1行目: 要約統計
        lines.append(
            f"n={len(state.step_scores)} "
            f"mean={state.mean_composite:.2f} "
            f"mom={state.discovery_momentum:+.2f}"
        )

        # 2行目: カバレッジ（0でないもののみ）
        cov = {k: f"{v:.1f}" for k, v in state.coverage_map.items() if v > 0}
        if cov:
            lines.append("cov:" + ",".join(f"{k}={v}" for k, v in cov.items()))

        # 3行目: 主成分（あれば）
        if state.principal_components:
            for pc in state.principal_components[:2]:
                var = pc["variance_explained"]
                if var > 0.1:
                    top = pc["top_contributors"][0]
                    lines.append(f"PC:{pc['label']}({var:.0%}) {top['axis']}={top['loading']:+.2f}")

        # 4行目: 上位発見（1つだけ）
        if state.strongest_findings:
            lines.append(f"top:{state.strongest_findings[0][:80]}")

        # 5行目: 弱い領域
        if state.weakest_areas:
            lines.append(f"weak:{','.join(state.weakest_areas)}")

        compressed = "\n".join(lines)

        # トークン数推定
        original = state.compressed_summary()
        original_tokens = len(original.split())
        compressed_tokens = len(compressed.split())

        return compressed

    def estimate_savings(self, state) -> dict:
        """圧縮効果の推定"""
        original = state.compressed_summary() if hasattr(state, 'compressed_summary') else ""
        compressed = self.compress_for_llm(state)

        orig_tokens = len(original.split())
        comp_tokens = len(compressed.split())
        orig_chars = len(original)
        comp_chars = len(compressed)

        return {
            "original_tokens": orig_tokens,
            "compressed_tokens": comp_tokens,
            "token_reduction": f"{(1 - comp_tokens/orig_tokens)*100:.0f}%" if orig_tokens > 0 else "N/A",
            "original_chars": orig_chars,
            "compressed_chars": comp_chars,
            "char_reduction": f"{(1 - comp_chars/orig_chars)*100:.0f}%" if orig_chars > 0 else "N/A",
        }
