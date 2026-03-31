#!/usr/bin/env python3
"""
adaptive_coder.py — フィードバック学習型コード生成エンジン
==========================================================
LLM が同じエラーを繰り返す問題を解決する。

従来:
  LLM → error → "Fix it" → 同じ error → "Fix it" → 同じ error ...

改善:
  LLM → error → エラー分析 → 原因特定 → コード直接パッチ
  → パッチ済みコードを実行 → 新しい error → 分析 → パッチ ...
  → 蓄積したパッチをルール化 → 次回は最初から正しいコードを生成

3つの改善:
  1. エラー分析器: stderr からエラーの根本原因を特定
  2. コードパッチャー: LLM に頼らずエラーを直接修正
  3. フィードバックメモリ: 修正パターンを蓄積し次回に活用
"""
from __future__ import annotations

import re
import os
import json
from pathlib import Path
from typing import Optional, Callable
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════════════════
# エラー分析器: stderr → 根本原因 + 修正方法
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorAnalyzer:
    """stderr を解析してエラーの根本原因と修正方法を返す"""

    def analyze(self, code: str, stderr: str) -> dict:
        """
        Returns: {
            "type": "NameError",
            "cause": "matplotlib not imported before use",
            "line_num": 5,
            "fix_type": "add_import",
            "fix_detail": "import matplotlib; matplotlib.use('Agg')",
            "confidence": 0.95,
        }
        """
        result = {"type": "unknown", "cause": "", "line_num": None,
                  "fix_type": "unknown", "fix_detail": "", "confidence": 0.0}

        # エラー行を抽出
        tb_lines = stderr.strip().split("\n")
        error_line = ""
        line_num = None
        for line in reversed(tb_lines):
            line = line.strip()
            # 最終エラーメッセージ
            for et in ["NameError", "KeyError", "ValueError", "TypeError",
                        "AttributeError", "IndexError", "FileNotFoundError",
                        "ModuleNotFoundError", "ImportError"]:
                if line.startswith(et):
                    error_line = line
                    result["type"] = et
                    break
            # 行番号
            m = re.search(r'line (\d+)', line)
            if m and line_num is None:
                line_num = int(m.group(1))

        result["line_num"] = line_num
        if not error_line:
            return result

        # ── NameError 分析 ──
        if result["type"] == "NameError":
            m = re.search(r"name '(\w+)' is not defined", error_line)
            if m:
                name = m.group(1)
                if name == "matplotlib":
                    result.update(cause="matplotlib not imported",
                        fix_type="prepend_line",
                        fix_detail="import matplotlib; matplotlib.use('Agg')",
                        confidence=0.99)
                elif name == "os":
                    result.update(cause="os not imported",
                        fix_type="prepend_line", fix_detail="import os",
                        confidence=0.99)
                elif name == "np":
                    result.update(cause="numpy not imported as np",
                        fix_type="prepend_line", fix_detail="import numpy as np",
                        confidence=0.99)
                elif name == "pd":
                    result.update(cause="pandas not imported as pd",
                        fix_type="prepend_line", fix_detail="import pandas as pd",
                        confidence=0.99)
                elif name == "sns":
                    result.update(cause="seaborn not imported as sns",
                        fix_type="prepend_line", fix_detail="import seaborn as sns",
                        confidence=0.95)
                elif name == "FIGURE_DIR":
                    result.update(cause="FIGURE_DIR not defined",
                        fix_type="prepend_line",
                        fix_detail="FIGURE_DIR = '/tmp/seq2pipe_figures'; import os; os.makedirs(FIGURE_DIR, exist_ok=True)",
                        confidence=0.95)
                elif name == "DPI":
                    result.update(cause="DPI not defined",
                        fix_type="prepend_line", fix_detail="DPI = 150",
                        confidence=0.99)
                else:
                    # 汎用: 未定義変数 → import を推測
                    result.update(cause=f"'{name}' not defined",
                        fix_type="needs_llm",
                        fix_detail=f"Variable '{name}' is used but never defined. Define it before use.",
                        confidence=0.5)

        # ── KeyError 分析 ──
        elif result["type"] == "KeyError":
            m = re.search(r"KeyError: ['\"](.+?)['\"]", error_line)
            if m:
                key = m.group(1)
                if key == "Taxon":
                    result.update(cause="Taxonomy column name mismatch",
                        fix_type="replace_string",
                        fix_detail=("taxonomy['Taxon']",
                                    "taxonomy.iloc[:, 0] if 'Taxon' not in taxonomy.columns else taxonomy['Taxon']"),
                        confidence=0.90)
                elif key in ("body-site", "Subject", "treatment-group"):
                    result.update(cause=f"Group column '{key}' not found after set_index",
                        fix_type="add_before_line",
                        fix_detail=f"# Ensure group column exists\nif '{key}' not in meta.columns:\n    meta = pd.read_csv(metadata_path, sep='\\t')\n    meta = meta.set_index(meta.columns[0])",
                        confidence=0.70)
                else:
                    result.update(cause=f"Column '{key}' not found",
                        fix_type="needs_llm",
                        fix_detail=f"Column '{key}' does not exist. Check available columns with df.columns.",
                        confidence=0.5)

        # ── TypeError 分析 ──
        elif result["type"] == "TypeError":
            if "not subscriptable" in error_line or "not iterable" in error_line:
                result.update(cause="Wrong data type",
                    fix_type="needs_llm",
                    fix_detail="Check the data type of the variable. It may be None or wrong type.",
                    confidence=0.4)
            elif "unexpected keyword" in error_line:
                m2 = re.search(r"'(\w+)'", error_line)
                if m2:
                    result.update(cause=f"Unexpected keyword argument '{m2.group(1)}'",
                        fix_type="remove_kwarg",
                        fix_detail=m2.group(1),
                        confidence=0.80)

        # ── ModuleNotFoundError ──
        elif result["type"] in ("ModuleNotFoundError", "ImportError"):
            m = re.search(r"No module named '(\w+)'", error_line)
            if m:
                mod = m.group(1)
                result.update(cause=f"Module '{mod}' not installed",
                    fix_type="remove_import",
                    fix_detail=mod,
                    confidence=0.85)

        # ── ValueError ──
        elif result["type"] == "ValueError":
            if "could not convert" in error_line or "invalid literal" in error_line:
                result.update(cause="Data type conversion failed",
                    fix_type="needs_llm",
                    fix_detail="Data contains non-numeric values. Add error handling or filter.",
                    confidence=0.4)

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# コードパッチャー: エラー分析結果に基づいてコードを直接修正
# ═══════════════════════════════════════════════════════════════════════════════

class CodePatcher:
    """LLM に頼らずにコードを直接修正"""

    def patch(self, code: str, analysis: dict) -> Optional[str]:
        """
        分析結果に基づいてコードをパッチ。
        Returns: 修正済みコード or None (修正不可能)
        """
        fix_type = analysis.get("fix_type", "unknown")

        if fix_type == "prepend_line":
            line = analysis["fix_detail"]
            # 既に存在するか確認
            if line.split(";")[0].strip() in code:
                return None  # 既にある
            # 先頭に追加 (import 文の前に)
            lines = code.split("\n")
            insert_pos = 0
            for i, l in enumerate(lines):
                if l.strip() and not l.strip().startswith("#"):
                    insert_pos = i
                    break
            lines.insert(insert_pos, line)
            return "\n".join(lines)

        elif fix_type == "replace_string":
            old, new = analysis["fix_detail"]
            if old in code:
                return code.replace(old, new)
            return None

        elif fix_type == "remove_import":
            mod = analysis["fix_detail"]
            lines = code.split("\n")
            new_lines = []
            for l in lines:
                if f"import {mod}" in l or f"from {mod}" in l:
                    new_lines.append(f"# REMOVED: {l.strip()}  # module not available")
                else:
                    new_lines.append(l)
            return "\n".join(new_lines)

        elif fix_type == "remove_kwarg":
            kwarg = analysis["fix_detail"]
            # 正規表現で kwarg=... を削除
            pattern = rf",?\s*{kwarg}\s*=\s*[^,\)]+,?"
            patched = re.sub(pattern, "", code)
            if patched != code:
                return patched
            return None

        elif fix_type == "add_before_line":
            line_num = analysis.get("line_num")
            if line_num:
                lines = code.split("\n")
                if 0 < line_num <= len(lines):
                    fix_lines = analysis["fix_detail"].split("\n")
                    for j, fl in enumerate(fix_lines):
                        lines.insert(line_num - 1 + j, fl)
                    return "\n".join(lines)
            return None

        return None  # needs_llm or unknown


# ═══════════════════════════════════════════════════════════════════════════════
# フィードバックメモリ: 修正パターンを蓄積
# ═══════════════════════════════════════════════════════════════════════════════

class FeedbackMemory:
    """
    エラー → 修正 のパターンを永続化し、
    次回の LLM プロンプトに「過去の教訓」として注入する。
    """

    def __init__(self, store_path: Optional[str] = None):
        if store_path is None:
            store_path = os.path.join(Path.home(), ".seq2pipe", "feedback_memory.json")
        self.store_path = store_path
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        self.memory = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path) as f:
                    return json.load(f)
            except:
                pass
        return {"error_fixes": {}, "successful_patterns": [], "stats": {"total_errors": 0, "auto_fixed": 0, "llm_fixed": 0}}

    def _save(self):
        with open(self.store_path, "w") as f:
            json.dump(self.memory, f, indent=2, default=str)

    def record_auto_fix(self, error_type: str, cause: str, fix: str):
        """自動修正が成功した記録"""
        key = f"{error_type}:{cause}"
        self.memory["error_fixes"][key] = {
            "fix": fix, "count": self.memory["error_fixes"].get(key, {}).get("count", 0) + 1
        }
        self.memory["stats"]["auto_fixed"] += 1
        self.memory["stats"]["total_errors"] += 1
        self._save()

    def record_llm_fix(self, error_type: str, cause: str):
        """LLM に頼った記録"""
        self.memory["stats"]["llm_fixed"] += 1
        self.memory["stats"]["total_errors"] += 1
        self._save()

    def record_success(self, task: str, code_snippet: str):
        """成功パターンを記録"""
        self.memory["successful_patterns"].append({
            "task": task, "snippet": code_snippet[:500]
        })
        if len(self.memory["successful_patterns"]) > 50:
            self.memory["successful_patterns"] = self.memory["successful_patterns"][-50:]
        self._save()

    def build_feedback_prompt(self) -> str:
        """過去の教訓をプロンプトに注入"""
        lines = []
        if self.memory["error_fixes"]:
            lines.append("\n## LEARNED FROM PAST ERRORS (do NOT repeat these):")
            for key, data in sorted(self.memory["error_fixes"].items(),
                                     key=lambda x: -x[1].get("count", 0))[:15]:
                lines.append(f"- {key} → FIX: {data['fix']}")

        stats = self.memory["stats"]
        if stats["total_errors"] > 0:
            auto_rate = stats["auto_fixed"] / stats["total_errors"] * 100
            lines.append(f"\n(Past stats: {stats['total_errors']} errors, "
                        f"{auto_rate:.0f}% auto-fixed, {100-auto_rate:.0f}% needed LLM)")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        return dict(self.memory["stats"])


# ═══════════════════════════════════════════════════════════════════════════════
# AdaptiveCoder: 統合エンジン
# ═══════════════════════════════════════════════════════════════════════════════

class AdaptiveCoder:
    """
    フィードバック学習型コード生成。

    ループ:
      1. LLM にコード生成を依頼（過去のフィードバック付き）
      2. 実行
      3. エラー → ErrorAnalyzer で分析
      4. CodePatcher で自動修正を試みる
      5. 自動修正できなければ、分析結果を含む具体的フィードバックで LLM に再依頼
      6. 成功 or 最大リトライ → テンプレートフォールバック
    """

    def __init__(self, feedback_path: Optional[str] = None,
                 log_callback: Optional[Callable] = None):
        self.analyzer = ErrorAnalyzer()
        self.patcher = CodePatcher()
        self.memory = FeedbackMemory(feedback_path)
        self._log = log_callback or (lambda msg: print(msg))

    def generate_and_run(
        self,
        task: str,
        base_prompt: str,
        llm_call: Callable,
        extract_code: Callable,
        run_code: Callable,
        max_retries: int = 5,
        export_files: dict = None,
        metadata_path: str = "",
        group_column: str = "",
        figure_dir: str = "",
    ) -> dict:
        """
        Returns: {
            "success": bool,
            "code": str,
            "method": "llm" | "auto_patch" | "template_fallback",
            "attempts": int,
            "patches_applied": int,
            "figures": list,
        }
        """
        # フィードバックをプロンプトに注入
        feedback = self.memory.build_feedback_prompt()
        enhanced_prompt = base_prompt + feedback

        msgs = [
            {"role": "system", "content": "Generate only Python code in ```python...```. Follow the LEARNED ERRORS section strictly."},
            {"role": "user", "content": enhanced_prompt},
        ]

        code = None
        patches_applied = 0
        attempt_log = []

        for attempt in range(max_retries):
            self._log(f"    Attempt {attempt+1}/{max_retries}")

            # ── Step 1: コード取得（初回は LLM、リトライは状況次第）──
            try:
                if code is None:
                    # 初回: LLM で生成
                    resp = llm_call(msgs)
                    code = extract_code(resp.get("content", ""))
                    if not code:
                        attempt_log.append({"n": attempt+1, "action": "llm_generate", "result": "no_code"})
                        continue

                # ── Step 2: 基本的な前処理（既知パッチ）──
                from code_learner import CodeLearner
                cl = CodeLearner.__new__(CodeLearner)
                cl.__init__()
                code = cl.postprocess_code(code)

                # ── Step 3: 実行 ──
                success, stdout, stderr, figs = run_code(code)

                if success:
                    self.memory.record_success(task, code[:300])
                    self._log(f"    SUCCESS on attempt {attempt+1}")
                    return {"success": True, "code": code, "method": "llm",
                            "attempts": attempt+1, "patches_applied": patches_applied,
                            "figures": figs, "log": attempt_log}

                # ── Step 4: エラー分析 ──
                analysis = self.analyzer.analyze(code, stderr)
                self._log(f"    Error: {analysis['type']} — {analysis['cause']}")

                # ── Step 5: 自動パッチ試行 ──
                if analysis["confidence"] >= 0.7:
                    patched = self.patcher.patch(code, analysis)
                    if patched and patched != code:
                        self._log(f"    Auto-patch: {analysis['fix_type']}")
                        code = patched
                        patches_applied += 1

                        # パッチ済みコードを再実行
                        success2, stdout2, stderr2, figs2 = run_code(code)
                        if success2:
                            self.memory.record_auto_fix(
                                analysis["type"], analysis["cause"],
                                analysis["fix_detail"] if isinstance(analysis["fix_detail"], str)
                                else str(analysis["fix_detail"]))
                            self._log(f"    AUTO-PATCH SUCCESS!")
                            return {"success": True, "code": code, "method": "auto_patch",
                                    "attempts": attempt+1, "patches_applied": patches_applied,
                                    "figures": figs2, "log": attempt_log}
                        else:
                            # パッチしたが別のエラー → 続行
                            stderr = stderr2
                            analysis = self.analyzer.analyze(code, stderr2)

                # ── Step 6: LLM に具体的フィードバックで再依頼 ──
                specific_feedback = (
                    f"Error on line {analysis.get('line_num', '?')}: {analysis['type']}\n"
                    f"Cause: {analysis['cause']}\n"
                    f"How to fix: {analysis['fix_detail'] if isinstance(analysis['fix_detail'], str) else 'See above'}\n"
                    f"Current code has {len(code.split(chr(10)))} lines.\n"
                    f"IMPORTANT: Do NOT repeat this error. The fix is described above."
                )

                msgs = [
                    {"role": "system", "content": "Fix the Python code. Follow the error analysis exactly."},
                    {"role": "user", "content": enhanced_prompt},
                    {"role": "assistant", "content": f"```python\n{code}\n```"},
                    {"role": "user", "content": specific_feedback},
                ]

                resp = llm_call(msgs)
                new_code = extract_code(resp.get("content", ""))
                if new_code:
                    code = new_code
                    self.memory.record_llm_fix(analysis["type"], analysis["cause"])

                attempt_log.append({
                    "n": attempt+1, "error": analysis["type"],
                    "cause": analysis["cause"][:50],
                    "patched": patches_applied > 0,
                })

            except Exception as e:
                self._log(f"    Exception: {e}")
                attempt_log.append({"n": attempt+1, "error": str(type(e).__name__), "cause": str(e)[:50]})
                code = None  # 次のループで LLM に再生成させる

        # ── テンプレートフォールバック ──
        self._log(f"    All {max_retries} attempts failed → template fallback")
        if export_files and figure_dir:
            from code_learner import CodeLearner
            cl = CodeLearner()
            template = cl.get_template_fallback(task, export_files, metadata_path,
                                                 group_column, figure_dir)
            if template:
                success, stdout, stderr, figs = run_code(template)
                if success:
                    return {"success": True, "code": template, "method": "template_fallback",
                            "attempts": max_retries, "patches_applied": patches_applied,
                            "figures": figs, "log": attempt_log}

        return {"success": False, "code": code or "", "method": "failed",
                "attempts": max_retries, "patches_applied": patches_applied,
                "figures": [], "log": attempt_log}
