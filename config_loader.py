#!/usr/bin/env python3
"""
config_loader.py
================
YAML config 駆動設計。CLI フラグ > config.yaml > デフォルト値 の優先順位で
パラメータを解決する。
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Optional


def _deep_merge(base: dict, override: dict) -> dict:
    """override の値で base を再帰的に上書き"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        elif v is not None:
            result[k] = v
    return result


def load_config(config_path: Optional[str] = None, cli_overrides: Optional[dict] = None) -> dict:
    """
    設定をロードする。優先順位:
      1. cli_overrides (コマンドライン引数)
      2. config_path の YAML ファイル
      3. デフォルト値 (config.yaml 内蔵)
    """
    # デフォルト値
    defaults = {
        "pipeline": {"mode": "ai-driven", "fastq_dir": "", "output_dir": "",
                      "paired_end": True, "n_threads": 4},
        "dada2": {"trim_left_f": "auto", "trim_left_r": "auto",
                  "trunc_len_f": "auto", "trunc_len_r": "auto",
                  "sampling_depth": "auto"},
        "metadata": {"path": "", "group_column": "", "research_question": ""},
        "taxonomy": {"classifier_path": ""},
        "llm": {"model": "qwen2.5-coder:7b", "endpoint": "http://localhost:11434",
                "max_retries": 3, "temperature": 0.1},
        "ai_driven": {"replan_interval": 4, "max_investigations": 8,
                       "novelty_trigger": 0.7},
        "eval_weights": {
            "statistical_significance": 0.20, "biological_relevance": 0.18,
            "actionability": 0.15, "novelty": 0.12, "data_quality": 0.10,
            "effect_magnitude": 0.10, "confidence": 0.08, "reproducibility": 0.07,
        },
        "output": {"figure_dpi": 150, "figure_format": "png",
                   "generate_report": True, "report_format": "html"},
        "logging": {"level": "INFO", "file": "", "include_timestamps": True,
                    "log_eval_scores": True, "log_decisions": True,
                    "save_eval_json": True},
    }

    config = dict(defaults)

    # YAML ファイルからロード
    if config_path is None:
        # デフォルトパス: seq2pipe ディレクトリの config.yaml
        candidate = Path(__file__).parent / "config.yaml"
        if candidate.exists():
            config_path = str(candidate)

    if config_path and Path(config_path).exists():
        try:
            import yaml
            with open(config_path) as f:
                file_config = yaml.safe_load(f) or {}
            config = _deep_merge(config, file_config)
        except ImportError:
            # PyYAML がない場合は簡易パーサーでフォールバック
            config = _deep_merge(config, _parse_yaml_simple(config_path))

    # CLI overrides を適用
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)

    # 環境変数によるオーバーライド
    env_map = {
        "SEQ2PIPE_MODEL": ("llm", "model"),
        "SEQ2PIPE_THREADS": ("pipeline", "n_threads"),
        "SEQ2PIPE_LOG_LEVEL": ("logging", "level"),
        "QIIME2_AI_MODEL": ("llm", "model"),
    }
    for env_key, (section, key) in env_map.items():
        val = os.environ.get(env_key)
        if val:
            if section in config:
                config[section][key] = val

    return config


def _parse_yaml_simple(path: str) -> dict:
    """PyYAML なしの簡易 YAML パーサー (フラットキーのみ)"""
    result = {}
    current_section = None
    try:
        with open(path) as f:
            for line in f:
                line = line.rstrip()
                if not line or line.lstrip().startswith("#"):
                    continue
                # セクションヘッダ
                if not line.startswith(" ") and line.endswith(":"):
                    current_section = line.rstrip(":").strip()
                    if current_section not in result:
                        result[current_section] = {}
                    continue
                # キー: 値
                if ":" in line and current_section:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val == "":
                        continue
                    # 型推定
                    if val.lower() in ("true", "yes"):
                        val = True
                    elif val.lower() in ("false", "no"):
                        val = False
                    elif val.lower() == "auto":
                        val = "auto"
                    else:
                        try:
                            val = int(val)
                        except ValueError:
                            try:
                                val = float(val)
                            except ValueError:
                                pass
                    result[current_section][key] = val
    except Exception:
        pass
    return result
