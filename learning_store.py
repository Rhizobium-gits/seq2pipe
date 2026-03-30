#!/usr/bin/env python3
"""
learning_store.py — 学習ストア + セーフティネット
=================================================
wrong skip のパターンを記録し、次回同じパターンが来たら
skip を防止する学習機構。

仕組み:
  1. 各判断の結果を JSON で記録 (learning_log.jsonl)
  2. wrong skip が検出されたら「保護ルール」を生成
  3. 次回の判断時に保護ルールを適用 → skip を阻止
  4. 保護ルールは confidence が蓄積すると解除される

これにより v3 Bayes の精度を保ちつつ、
wrong skip を 0 に近づける。

使い方:
  store = LearningStore("~/.seq2pipe/learning")
  # 判断後
  store.record(step, decision, was_correct)
  # 次回の判断前
  protected = store.get_protected_steps()
  # → protected にあるステップは skip しない
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class LearningStore:
    """
    ファイルベースの学習ストア。
    ~/.seq2pipe/learning/ に JSON Lines でログを保存。
    """

    def __init__(self, store_dir: Optional[str] = None):
        if store_dir is None:
            store_dir = os.path.join(Path.home(), ".seq2pipe", "learning")
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self._log_path = os.path.join(store_dir, "learning_log.jsonl")
        self._rules_path = os.path.join(store_dir, "protection_rules.json")
        self._rules = self._load_rules()

    # ── Recording ──

    def record_decision(self, step: str, skipped: bool,
                        expert_would_run: bool,
                        context: dict):
        """
        1つの判断を記録。
        wrong skip なら自動的に保護ルールを生成。
        """
        is_wrong_skip = skipped and expert_would_run
        is_wrong_run = (not skipped) and (not expert_would_run)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "skipped": skipped,
            "expert_would_run": expert_would_run,
            "correct": skipped != expert_would_run if expert_would_run else skipped == (not expert_would_run),
            "wrong_skip": is_wrong_skip,
            "wrong_run": is_wrong_run,
            "context": {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in context.items()
            },
        }

        # Correct: decision matches expert
        entry["correct"] = (not is_wrong_skip) and (not is_wrong_run)

        # JSONL に追記
        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

        # Wrong skip → 保護ルール自動生成
        if is_wrong_skip:
            self._add_protection(step, context)

        return entry

    # ── Protection Rules ──

    def _add_protection(self, step: str, context: dict):
        """
        wrong skip のパターンから保護ルールを生成。
        同じような文脈で同じステップが skip されないようにする。
        """
        # パターンキー: step + 関連する条件
        pattern_key = self._make_pattern_key(step, context)

        if pattern_key not in self._rules:
            self._rules[pattern_key] = {
                "step": step,
                "created": datetime.now(timezone.utc).isoformat(),
                "occurrences": 0,
                "pattern": self._extract_pattern(step, context),
            }

        self._rules[pattern_key]["occurrences"] += 1
        self._rules[pattern_key]["last_seen"] = datetime.now(timezone.utc).isoformat()
        self._save_rules()

    def _make_pattern_key(self, step: str, context: dict) -> str:
        """文脈からパターンキーを生成"""
        # beta 系のステップ → beta の有意性がキー
        if "beta" in step or step in ("permanova_detail",):
            return f"{step}:b_sig={context.get('b_sig', '?')}"
        # alpha 系
        if "alpha" in step:
            return f"{step}:a_sig={context.get('a_sig', '?')}"
        # taxonomy 系
        if step in ("differential_volcano", "lefse", "indicator_species",
                     "picrust2", "network_analysis"):
            return f"{step}:has_d={context.get('has_d', '?')}"
        return f"{step}:generic"

    def _extract_pattern(self, step: str, context: dict) -> dict:
        """保護ルールのパターン条件"""
        pattern = {"step": step}
        if "beta" in step or step in ("permanova_detail",):
            pattern["condition"] = "b_sig"
            pattern["value"] = context.get("b_sig")
        elif "alpha" in step:
            pattern["condition"] = "a_sig"
            pattern["value"] = context.get("a_sig")
        else:
            pattern["condition"] = "has_d"
            pattern["value"] = context.get("has_d")
        return pattern

    def get_protected_steps(self, context: dict) -> set[str]:
        """
        現在の文脈で保護されているステップを返す。
        これらのステップは skip してはいけない。
        """
        protected = set()
        for key, rule in self._rules.items():
            pattern = rule["pattern"]
            step = pattern["step"]
            cond = pattern.get("condition")
            val = pattern.get("value")

            # 文脈がパターンに一致するか
            if cond and context.get(cond) == val:
                protected.add(step)

        return protected

    def _load_rules(self) -> dict:
        if os.path.exists(self._rules_path):
            try:
                with open(self._rules_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_rules(self):
        with open(self._rules_path, "w") as f:
            json.dump(self._rules, f, indent=2, default=str)

    # ── Analytics ──

    def get_stats(self) -> dict:
        """学習ログの統計"""
        if not os.path.exists(self._log_path):
            return {"total": 0}

        total = correct = wrong_skip = wrong_run = 0
        step_wrongs = Counter()

        with open(self._log_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    total += 1
                    if entry.get("correct"): correct += 1
                    if entry.get("wrong_skip"):
                        wrong_skip += 1
                        step_wrongs[entry["step"]] += 1
                    if entry.get("wrong_run"): wrong_run += 1
                except json.JSONDecodeError:
                    pass

        return {
            "total": total,
            "correct": correct,
            "wrong_skip": wrong_skip,
            "wrong_run": wrong_run,
            "accuracy": correct / total if total > 0 else 0,
            "false_negative_rate": wrong_skip / total if total > 0 else 0,
            "n_rules": len(self._rules),
            "top_wrong_steps": step_wrongs.most_common(5),
        }

    def reset(self):
        """学習データをリセット"""
        for p in [self._log_path, self._rules_path]:
            if os.path.exists(p):
                os.remove(p)
        self._rules = {}
