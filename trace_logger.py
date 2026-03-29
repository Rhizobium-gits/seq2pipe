#!/usr/bin/env python3
"""
trace_logger.py
===============
構造化ロギングとトレーシング。
各ステップの判断・スコア・エラーを JSON Lines 形式で記録し、
実行後の分析・再現性検証を可能にする。
"""
from __future__ import annotations
import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable


class TraceLogger:
    """
    構造化ログを JSON Lines (.jsonl) で出力するロガー。
    各エントリはタイムスタンプ・イベントタイプ・ペイロードを含む。
    """

    def __init__(
        self,
        output_dir: str = "",
        log_file: str = "",
        level: str = "INFO",
        console_callback: Optional[Callable[[str], None]] = None,
    ):
        self.level = level.upper()
        self._levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        self._min_level = self._levels.get(self.level, 1)
        self._console_cb = console_callback
        self._entries = []
        self._start_time = time.time()

        # JSONL file
        self._jsonl_path = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            self._jsonl_path = os.path.join(output_dir, "trace.jsonl")
        elif log_file:
            self._jsonl_path = log_file

    def _emit(self, level: str, event: str, **payload):
        """1エントリを記録"""
        if self._levels.get(level, 1) < self._min_level:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.time() - self._start_time, 2),
            "level": level,
            "event": event,
            **payload,
        }
        self._entries.append(entry)

        # JSONL 書き込み
        if self._jsonl_path:
            with open(self._jsonl_path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

        # コンソール出力
        if self._console_cb:
            msg = self._format_console(entry)
            self._console_cb(msg)

    def _format_console(self, entry: dict) -> str:
        """コンソール用のフォーマット"""
        elapsed = entry.get("elapsed_s", 0)
        event = entry.get("event", "")
        level = entry.get("level", "INFO")

        prefix = f"[{elapsed:7.1f}s] "
        if level == "ERROR":
            prefix += "ERROR: "
        elif level == "WARNING":
            prefix += "WARN: "

        # ペイロードの主要フィールドを抽出
        details = []
        for k in ["step", "title", "score", "decision", "error"]:
            if k in entry:
                details.append(f"{k}={entry[k]}")

        detail_str = " | ".join(details) if details else ""
        return f"{prefix}{event}" + (f" ({detail_str})" if detail_str else "")

    # ── Public API ──

    def step_start(self, step_num: int, key: str, title: str, is_investigation: bool = False):
        self._emit("INFO", "step_start",
                    step=step_num, key=key, title=title,
                    type="investigation" if is_investigation else "registry")

    def step_end(self, step_num: int, key: str, success: bool,
                 n_figures: int = 0, retries: int = 1):
        self._emit("INFO", "step_end",
                    step=step_num, key=key, success=success,
                    figures=n_figures, retries=retries)

    def eval_score(self, step_num: int, key: str, composite: float,
                   axes: dict, findings: list):
        self._emit("DEBUG", "eval_score",
                    step=step_num, key=key, composite=round(composite, 4),
                    axes={k: round(v, 3) for k, v in axes.items()},
                    findings=findings[:3])

    def decision(self, step_num: int, skip: list, add: list,
                 investigate: list, reasoning: list):
        self._emit("INFO", "decision",
                    step=step_num, skip=skip,
                    add=[a.get("key", a) if isinstance(a, dict) else a for a in add],
                    investigate=[i.get("title", i) if isinstance(i, dict) else i for i in investigate],
                    reasoning=reasoning[:3])

    def replan(self, step_num: int, source: str, changes: dict):
        """source: 'python' | 'llm' | 'merged'"""
        self._emit("INFO", "replan",
                    step=step_num, source=source, changes=changes)

    def error(self, step_num: int, error_type: str, message: str):
        self._emit("ERROR", "code_error",
                    step=step_num, error_type=error_type,
                    message=message[:500])

    def llm_call(self, purpose: str, model: str, tokens_est: int = 0):
        self._emit("DEBUG", "llm_call",
                    purpose=purpose, model=model, tokens_est=tokens_est)

    def phase(self, name: str, **details):
        self._emit("INFO", "phase", name=name, **details)

    def summary(self, **metrics):
        self._emit("INFO", "run_summary", **metrics)

    # ── Analysis ──

    def get_entries(self, event: Optional[str] = None) -> list[dict]:
        if event:
            return [e for e in self._entries if e.get("event") == event]
        return list(self._entries)

    def get_step_timeline(self) -> list[dict]:
        """ステップごとのタイムラインを返す"""
        starts = {e["step"]: e for e in self._entries if e.get("event") == "step_start"}
        ends = {e["step"]: e for e in self._entries if e.get("event") == "step_end"}
        scores = {e["step"]: e for e in self._entries if e.get("event") == "eval_score"}

        timeline = []
        for step_num in sorted(starts.keys()):
            s = starts[step_num]
            e = ends.get(step_num, {})
            sc = scores.get(step_num, {})
            timeline.append({
                "step": step_num,
                "key": s.get("key"),
                "title": s.get("title"),
                "type": s.get("type"),
                "success": e.get("success"),
                "retries": e.get("retries", 1),
                "figures": e.get("figures", 0),
                "composite": sc.get("composite"),
                "start_time": s.get("elapsed_s"),
                "end_time": e.get("elapsed_s"),
            })
        return timeline
