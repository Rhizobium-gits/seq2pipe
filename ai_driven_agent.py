#!/usr/bin/env python3
"""
ai_driven_agent.py
==================
AI 駆動解析モード（--ai-driven / モード 5）。

AI（LLM）が自らデータを偵察し、実験デザインと研究目的に基づいて
解析プランを立案。各ステップの結果を見て次の解析を動的に決定する。
人間の生物情報学者のように「データを見て → 判断して → 次を決める」
適応的解析ループを実現する。

フロー:
  Phase 1: データ偵察（決定論的に基本統計量を抽出）
  Phase 2: AI プランニング（LLM がプランを JSON で返す）
  Phase 3: 適応的実行ループ（結果を見てプランを動的に修正）
"""

from __future__ import annotations

import json
import re
import csv
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

import sys
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import (
    _run_code, _extract_code, _detect_missing_module, pip_install,
)
from manual_auto_agent import (
    ExperimentalDesign, parse_metadata, ANALYSIS_REGISTRY, AnalysisSpec,
    _select_stat_test, _expand_prompt, _build_step_prompt, AnalysisStep,
)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: データ偵察 — 決定論的にデータの基本統計量を抽出
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DataRecon:
    """データ偵察の結果"""
    n_samples: int = 0
    n_asvs: int = 0
    total_reads: int = 0
    min_reads: int = 0
    max_reads: int = 0
    median_reads: int = 0
    sample_ids: list[str] = field(default_factory=list)
    has_taxonomy: bool = False
    n_genera: int = 0
    top_phyla: list[str] = field(default_factory=list)
    top_genera: list[str] = field(default_factory=list)
    alpha_metrics: list[str] = field(default_factory=list)
    beta_metrics: list[str] = field(default_factory=list)
    has_denoising: bool = False
    denoising_pass_rate: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Samples: {self.n_samples}",
            f"ASVs: {self.n_asvs}",
            f"Total reads: {self.total_reads:,}",
            f"Reads/sample: min={self.min_reads:,}, median={self.median_reads:,}, max={self.max_reads:,}",
        ]
        if self.has_taxonomy:
            lines.append(f"Genera detected: {self.n_genera}")
            if self.top_phyla:
                lines.append(f"Top phyla: {', '.join(self.top_phyla[:5])}")
            if self.top_genera:
                lines.append(f"Top genera: {', '.join(self.top_genera[:8])}")
        if self.alpha_metrics:
            lines.append(f"Alpha metrics: {', '.join(self.alpha_metrics)}")
        if self.beta_metrics:
            lines.append(f"Beta metrics: {', '.join(self.beta_metrics)}")
        if self.has_denoising:
            lines.append(f"Denoising pass rate: {self.denoising_pass_rate:.1%}")
        return "\n".join(lines)


def run_data_recon(
    export_files: dict[str, list[str]],
    log_callback: Optional[Callable[[str], None]] = None,
) -> DataRecon:
    """エクスポートファイルから基本統計量を決定論的に抽出"""
    import statistics

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    recon = DataRecon()

    # feature table
    ft_paths = export_files.get("feature_table", [])
    if ft_paths:
        try:
            _log("  📊 Feature table を解析中...")
            with open(ft_paths[0]) as f:
                lines = f.readlines()
            # skip comment line
            header_idx = 0
            for i, line in enumerate(lines):
                if line.startswith("#OTU") or (i > 0 and not line.startswith("#")):
                    header_idx = i
                    break
            header = lines[header_idx].strip().split("\t")
            sample_ids = header[1:]
            recon.sample_ids = sample_ids
            recon.n_samples = len(sample_ids)

            # count ASVs and reads
            asv_count = 0
            sample_reads = {s: 0 for s in sample_ids}
            for line in lines[header_idx + 1:]:
                if not line.strip():
                    continue
                parts = line.strip().split("\t")
                asv_count += 1
                for j, sid in enumerate(sample_ids):
                    if j + 1 < len(parts):
                        try:
                            sample_reads[sid] += int(float(parts[j + 1]))
                        except (ValueError, IndexError):
                            pass

            recon.n_asvs = asv_count
            reads_list = list(sample_reads.values())
            if reads_list:
                recon.total_reads = sum(reads_list)
                recon.min_reads = min(reads_list)
                recon.max_reads = max(reads_list)
                recon.median_reads = int(statistics.median(reads_list))
            _log(f"    {recon.n_samples} samples, {recon.n_asvs} ASVs, "
                 f"{recon.total_reads:,} total reads")
        except Exception as e:
            _log(f"    ⚠️ Feature table 解析失敗: {e}")

    # taxonomy
    tax_paths = export_files.get("taxonomy", [])
    if tax_paths:
        try:
            _log("  🧬 Taxonomy を解析中...")
            recon.has_taxonomy = True
            phyla: dict[str, int] = {}
            genera: dict[str, int] = {}
            with open(tax_paths[0]) as f:
                header = f.readline()  # skip header
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 2:
                        continue
                    taxon = parts[1]
                    # phylum
                    m = re.search(r"p__([^;]+)", taxon)
                    if m:
                        p = m.group(1).strip()
                        if p and p != "__":
                            phyla[p] = phyla.get(p, 0) + 1
                    # genus
                    m = re.search(r"g__([^;]+)", taxon)
                    if m:
                        g = m.group(1).strip()
                        if g and g != "__":
                            genera[g] = genera.get(g, 0) + 1

            recon.n_genera = len(genera)
            recon.top_phyla = sorted(phyla, key=phyla.get, reverse=True)[:10]
            recon.top_genera = sorted(genera, key=genera.get, reverse=True)[:15]
            _log(f"    {recon.n_genera} genera, top phyla: {', '.join(recon.top_phyla[:3])}")
        except Exception as e:
            _log(f"    ⚠️ Taxonomy 解析失敗: {e}")

    # alpha
    alpha_paths = export_files.get("alpha", [])
    for ap in alpha_paths:
        name = Path(ap).parent.name or Path(ap).stem
        recon.alpha_metrics.append(name)
    if recon.alpha_metrics:
        _log(f"  📐 Alpha metrics: {', '.join(recon.alpha_metrics)}")

    # beta
    beta_paths = export_files.get("beta", [])
    for bp in beta_paths:
        name = Path(bp).parent.name or Path(bp).stem
        recon.beta_metrics.append(name)
    if recon.beta_metrics:
        _log(f"  📐 Beta metrics: {', '.join(recon.beta_metrics)}")

    # denoising
    den_paths = export_files.get("denoising", [])
    if den_paths:
        try:
            recon.has_denoising = True
            with open(den_paths[0]) as f:
                header = f.readline().strip().split("\t")
                input_idx = next((i for i, h in enumerate(header) if "input" in h.lower()), None)
                nonchim_idx = next((i for i, h in enumerate(header)
                                    if "non-chimeric" in h.lower() or "nonchimeric" in h.lower()), None)
                if input_idx is not None and nonchim_idx is not None:
                    total_in = 0
                    total_out = 0
                    for line in f:
                        parts = line.strip().split("\t")
                        try:
                            total_in += int(parts[input_idx])
                            total_out += int(parts[nonchim_idx])
                        except (ValueError, IndexError):
                            pass
                    if total_in > 0:
                        recon.denoising_pass_rate = total_out / total_in
            _log(f"  🔬 Denoising pass rate: {recon.denoising_pass_rate:.1%}")
        except Exception:
            pass

    return recon


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: AI プランニング — LLM が解析プランを立案
# ─────────────────────────────────────────────────────────────────────────────

def _build_registry_menu(
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
) -> str:
    """レジストリから選択可能な解析のメニューを構築"""
    available_cats = set(export_files.keys())
    lines = []
    for spec in ANALYSIS_REGISTRY:
        # データ要件チェック
        missing = [r for r in spec.requires if r not in available_cats and r != "metadata"]
        if missing:
            continue
        # グループ数チェック
        if spec.min_groups > 0 and design.n_groups < spec.min_groups:
            continue
        if design.n_groups > spec.max_groups:
            continue
        if spec.needs_timepoint and not design.is_longitudinal:
            continue
        if spec.needs_paired and not design.is_paired:
            continue
        lines.append(f'  - key="{spec.key}", phase="{spec.phase}", title="{spec.title}"')
    return "\n".join(lines)


def _build_planning_prompt(
    research_question: str,
    design: ExperimentalDesign,
    recon: DataRecon,
    registry_menu: str,
) -> str:
    """LLM に解析プランを立案させるプロンプト"""
    stat_test = _select_stat_test(design)
    return f"""You are an expert microbiome bioinformatician planning an analysis strategy.

## RESEARCH QUESTION
{research_question}

## EXPERIMENTAL DESIGN
{design.summary()}

## DATA RECONNAISSANCE
{recon.summary()}

## RECOMMENDED STATISTICAL TEST
{stat_test}

## AVAILABLE ANALYSES (select from this menu)
{registry_menu}

## YOUR TASK
Based on the research question, experimental design, and data characteristics,
create an ordered analysis plan. Think like a real bioinformatician:

1. Start with data quality checks (always important)
2. Then exploratory analyses to understand the overall structure
3. Focus on analyses that DIRECTLY address the research question
4. Add hypothesis-driven analyses based on what you expect to find
5. End with publication-quality composite figures

For each analysis, explain WHY it's important for this specific research question.

## OUTPUT FORMAT
Return a JSON array. Each element:
{{"key": "<analysis_key from menu>", "reason": "<why this analysis matters for this research question>", "priority": <1-10, 10=most important>}}

IMPORTANT:
- Select 15-25 analyses (not all of them — be selective)
- Order by logical flow, not just priority
- Always start with at least 1 quality check
- Focus on analyses relevant to the RESEARCH QUESTION
- Skip analyses that don't help answer the research question
- Include at least 1 publication composite at the end

Return ONLY the JSON array, no other text."""


def _parse_plan_json(content: str) -> list[dict]:
    """LLM の出力から JSON 配列を抽出"""
    # ```json ... ``` ブロックを探す
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 裸の JSON 配列を探す
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return []


def ai_plan_analysis(
    research_question: str,
    design: ExperimentalDesign,
    recon: DataRecon,
    export_files: dict[str, list[str]],
    model: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """LLM に解析プランを立案させる。失敗時はフォールバック。"""
    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    registry_menu = _build_registry_menu(design, export_files)
    prompt = _build_planning_prompt(research_question, design, recon, registry_menu)

    _log("  🧠 AI が解析プランを立案中...")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a microbiome bioinformatics expert. "
                "Return ONLY a JSON array as specified. No explanation."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _agent.call_ollama(messages, model)
        content = response.get("content", "")
        plan_items = _parse_plan_json(content)
        if plan_items:
            _log(f"  ✅ AI が {len(plan_items)} ステップのプランを立案")
            return plan_items
    except Exception as e:
        _log(f"  ⚠️ AI プランニング失敗: {e}")

    _log("  ⚠️ AI プラン解析失敗 → フォールバック（品質+主要解析を自動選択）")
    return _fallback_plan(design, export_files)


def _fallback_plan(
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
) -> list[dict]:
    """LLM プランニング失敗時のフォールバック: 主要解析を自動選択"""
    available_cats = set(export_files.keys())
    plan = []
    # 最低限の品質 + 主要解析
    priority_keys = [
        "read_depth", "phylum_barplot", "genus_barplot", "genus_heatmap",
        "alpha_boxplot", "rarefaction", "pcoa_all", "nmds",
        "volcano", "lefse_style", "cooccurrence_network", "composite_main",
    ]
    for key in priority_keys:
        spec = next((s for s in ANALYSIS_REGISTRY if s.key == key), None)
        if not spec:
            continue
        missing = [r for r in spec.requires if r not in available_cats and r != "metadata"]
        if missing:
            continue
        if spec.min_groups > 0 and design.n_groups < spec.min_groups:
            continue
        if design.n_groups > spec.max_groups:
            continue
        plan.append({"key": key, "reason": "Core analysis (fallback)", "priority": 5})
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: 適応的リプランニング — 結果を見て次を決める
# ─────────────────────────────────────────────────────────────────────────────

def _build_replan_prompt(
    research_question: str,
    design: ExperimentalDesign,
    completed_steps: list[dict],
    remaining_keys: list[str],
    registry_menu: str,
) -> str:
    """ステップ完了後に次のアクションを判断させるプロンプト"""
    completed_text = ""
    for s in completed_steps[-6:]:
        status = "SUCCESS" if s["success"] else "FAILED"
        completed_text += f'\n  - [{status}] {s["title"]}'
        if s.get("stdout_summary"):
            completed_text += f'\n    Output: {s["stdout_summary"][:200]}'
        if s.get("figures"):
            completed_text += f'\n    Figures: {len(s["figures"])} generated'

    remaining_text = "\n".join(f"  - {k}" for k in remaining_keys[:10])

    return f"""You are a microbiome bioinformatician reviewing analysis progress.

## RESEARCH QUESTION
{research_question}

## EXPERIMENTAL DESIGN
{design.summary()}

## COMPLETED ANALYSES
{completed_text}

## REMAINING PLANNED ANALYSES
{remaining_text}

## ALL AVAILABLE ANALYSES (can add from this menu)
{registry_menu}

## YOUR TASK
Based on the results so far, decide:
1. Should any remaining analyses be SKIPPED? (e.g., alpha showed no significance → skip effect size forest)
2. Should any NEW analyses be ADDED? (e.g., unexpected pattern found → add deeper investigation)
3. Should the ORDER be changed? (e.g., strong beta result → move PERMANOVA up)

Return a JSON object:
{{
  "skip": ["key1", "key2"],
  "add": [{{"key": "analysis_key", "reason": "why add this", "priority": 8}}],
  "reorder": ["key_first", "key_second"],
  "reasoning": "Brief explanation of your decisions"
}}

If no changes needed, return: {{"skip": [], "add": [], "reorder": [], "reasoning": "Plan is on track"}}
Return ONLY the JSON, no other text."""


def _parse_replan_json(content: str) -> dict:
    """リプランニング JSON を解析"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 結果データクラス
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AIDrivenStepResult:
    """1ステップの結果"""
    key: str
    title: str
    reason: str
    success: bool
    figures: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    code: str = ""


@dataclass
class AIDrivenResult:
    """AI 駆動解析の全体結果"""
    recon: DataRecon
    initial_plan: list[dict] = field(default_factory=list)
    results: list[AIDrivenStepResult] = field(default_factory=list)
    all_figures: list[str] = field(default_factory=list)
    replan_history: list[dict] = field(default_factory=list)
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_by_ai: int = 0
    added_by_ai: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# メイン実行エンジン
# ─────────────────────────────────────────────────────────────────────────────

def run_ai_driven(
    research_question: str,
    design: ExperimentalDesign,
    export_files: dict[str, list[str]],
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
    replan_interval: int = 4,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> AIDrivenResult:
    """
    AI 駆動解析モードのメイン実行エンジン。

    Phase 1: データ偵察
    Phase 2: AI プランニング
    Phase 3: 適応的実行ループ（replan_interval ステップごとにリプランニング）
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    result = AIDrivenResult()

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: データ偵察
    # ═══════════════════════════════════════════════════════════════════
    _log(f"\n{'═' * 56}")
    _log(f"  🔍 Phase 1: Data Reconnaissance")
    _log(f"{'═' * 56}")

    recon = run_data_recon(export_files, log_callback)
    result.recon = recon
    _log(f"\n{recon.summary()}\n")

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: AI プランニング
    # ═══════════════════════════════════════════════════════════════════
    _log(f"{'═' * 56}")
    _log(f"  🧠 Phase 2: AI Analysis Planning")
    _log(f"{'═' * 56}")

    plan_items = ai_plan_analysis(
        research_question, design, recon, export_files, model, log_callback,
    )
    result.initial_plan = plan_items

    # plan_items をキーで AnalysisSpec に変換
    spec_map: dict[str, AnalysisSpec] = {s.key: s for s in ANALYSIS_REGISTRY}
    plan_queue: list[dict] = []
    for item in plan_items:
        key = item.get("key", "")
        if key in spec_map:
            plan_queue.append(item)

    _log(f"\n  📋 AI Analysis Plan ({len(plan_queue)} steps):")
    for i, item in enumerate(plan_queue, 1):
        reason = item.get("reason", "")[:60]
        _log(f"    {i:2d}. {item['key']}  — {reason}")
    _log("")

    # ═══════════════════════════════════════════════════════════════════
    # Phase 3: 適応的実行ループ
    # ═══════════════════════════════════════════════════════════════════
    _log(f"{'═' * 56}")
    _log(f"  🔄 Phase 3: Adaptive Execution Loop")
    _log(f"{'═' * 56}\n")

    completed_info: list[dict] = []
    registry_menu = _build_registry_menu(design, export_files)
    step_counter = 0
    total_planned = len(plan_queue)

    while plan_queue:
        item = plan_queue.pop(0)
        key = item["key"]
        spec = spec_map.get(key)
        if not spec:
            continue

        step_counter += 1
        reason = item.get("reason", "")

        _log(f"{'─' * 48}")
        _log(f"  📊 Step {step_counter}: {spec.title}")
        _log(f"  💡 Reason: {reason[:80]}")
        _log(f"  Phase: {spec.phase}")
        _log(f"{'─' * 48}")

        # パッケージインストール
        for pkg in spec.extra_packages:
            try:
                __import__(pkg.replace("-", "_").split("[")[0])
            except ImportError:
                approved = install_callback(pkg) if install_callback else True
                if approved:
                    pip_install(pkg, log_callback)

        # AnalysisStep を構築
        expanded = _expand_prompt(spec, design, metadata_path, research_question)
        analysis_step = AnalysisStep(
            step_num=step_counter,
            spec=spec,
            code_prompt=expanded,
            figure_prefix=f"ai{step_counter:02d}_{spec.key}",
        )

        # プロンプト構築
        prior_summaries = [
            f"{c['title']}: {'OK' if c['success'] else 'FAILED'}"
            + (f" | {c.get('stdout_summary', '')[:100]}" if c.get("stdout_summary") else "")
            for c in completed_info[-4:]
        ]
        prompt = _build_step_prompt(
            step=analysis_step,
            design=design,
            export_files=export_files,
            figure_dir=figure_dir,
            metadata_path=metadata_path,
            research_question=research_question,
            prior_results=prior_summaries,
        )

        # LLM コード生成
        _log("  LLM にコード生成を依頼中...")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a microbiome analysis expert. "
                    "Generate only Python code without explanation. "
                    "Wrap code in ```python ... ```."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"  ❌ Ollama エラー: {e}")
            step_result = AIDrivenStepResult(
                key=key, title=spec.title, reason=reason, success=False, stderr=str(e),
            )
            result.results.append(step_result)
            result.failed_steps += 1
            completed_info.append({
                "key": key, "title": spec.title, "success": False,
                "stdout_summary": "", "figures": [],
            })
            continue

        code = _extract_code(response.get("content", ""))
        if not code:
            _log("  ⚠️ コード生成なし。スキップ。")
            step_result = AIDrivenStepResult(
                key=key, title=spec.title, reason=reason, success=False,
                stderr="No code generated",
            )
            result.results.append(step_result)
            result.failed_steps += 1
            completed_info.append({
                "key": key, "title": spec.title, "success": False,
                "stdout_summary": "", "figures": [],
            })
            continue

        _log(f"  コード生成完了 ({len(code.splitlines())} 行)")

        # 実行 + リトライ
        last_code = code
        step_success = False
        new_figs: list[str] = []
        last_stdout = ""
        last_stderr = ""

        for attempt in range(max_retries):
            _log(f"  実行中... (試行 {attempt + 1}/{max_retries})")
            success, stdout, stderr, figs = _run_code(
                last_code, output_dir, figure_dir, log_callback
            )
            last_stdout = stdout
            last_stderr = stderr

            if success:
                step_success = True
                new_figs = figs
                break

            missing_pkg = _detect_missing_module(stderr)
            if missing_pkg:
                approved = install_callback(missing_pkg) if install_callback else True
                if approved and pip_install(missing_pkg, log_callback):
                    continue

            if attempt < max_retries - 1:
                _log("  LLM にコード修正を依頼中...")
                fix_msgs = messages + [
                    {"role": "assistant", "content": f"```python\n{last_code}\n```"},
                    {"role": "user", "content": f"Error:\n```\n{stderr[:1500]}\n```\nFix. Return complete script in ```python...```."},
                ]
                try:
                    fix_resp = _agent.call_ollama(fix_msgs, model)
                    fixed = _extract_code(fix_resp.get("content", ""))
                    if fixed:
                        last_code = fixed
                except Exception:
                    pass

        # 結果記録
        step_result = AIDrivenStepResult(
            key=key, title=spec.title, reason=reason,
            success=step_success, figures=new_figs,
            stdout=last_stdout, stderr=last_stderr, code=last_code,
        )
        result.results.append(step_result)

        stdout_summary = ""
        if step_success:
            result.completed_steps += 1
            result.all_figures.extend(new_figs)
            fig_names = [Path(f).name for f in new_figs]
            _log(f"  ✅ 成功 — 図: {fig_names}" if new_figs else "  ✅ 成功")
            if last_stdout and len(last_stdout.strip()) < 500:
                stdout_summary = last_stdout.strip()[:200]
        else:
            result.failed_steps += 1
            _log(f"  ❌ 失敗: {last_stderr[:200]}")

        completed_info.append({
            "key": key, "title": spec.title, "success": step_success,
            "stdout_summary": stdout_summary,
            "figures": [Path(f).name for f in new_figs],
        })

        # ── 適応的リプランニング ──────────────────────────────────
        if plan_queue and step_counter % replan_interval == 0:
            _log(f"\n  🔄 Adaptive Replanning (after step {step_counter})...")
            remaining_keys = [it["key"] for it in plan_queue]

            replan_prompt = _build_replan_prompt(
                research_question, design, completed_info,
                remaining_keys, registry_menu,
            )
            replan_msgs = [
                {
                    "role": "system",
                    "content": "You are a microbiome bioinformatics expert. Return ONLY JSON.",
                },
                {"role": "user", "content": replan_prompt},
            ]
            try:
                replan_resp = _agent.call_ollama(replan_msgs, model)
                replan_data = _parse_replan_json(replan_resp.get("content", ""))

                if replan_data:
                    result.replan_history.append(replan_data)
                    reasoning = replan_data.get("reasoning", "")
                    if reasoning:
                        _log(f"    AI reasoning: {reasoning[:120]}")

                    # スキップ適用
                    skip_keys = set(replan_data.get("skip", []))
                    if skip_keys:
                        before = len(plan_queue)
                        plan_queue = [it for it in plan_queue if it["key"] not in skip_keys]
                        skipped = before - len(plan_queue)
                        if skipped:
                            result.skipped_by_ai += skipped
                            _log(f"    ⏭ AI が {skipped} ステップをスキップ: {skip_keys}")

                    # 追加適用
                    add_items = replan_data.get("add", [])
                    for add_item in add_items:
                        add_key = add_item.get("key", "")
                        if add_key in spec_map and add_key not in [it["key"] for it in plan_queue]:
                            already_done = {c["key"] for c in completed_info}
                            if add_key not in already_done:
                                plan_queue.append(add_item)
                                result.added_by_ai += 1
                                _log(f"    ➕ AI が追加: {add_key} — {add_item.get('reason', '')[:60]}")

                    # 並べ替え適用
                    reorder = replan_data.get("reorder", [])
                    if reorder:
                        key_to_item = {it["key"]: it for it in plan_queue}
                        new_queue = []
                        for rk in reorder:
                            if rk in key_to_item:
                                new_queue.append(key_to_item.pop(rk))
                        new_queue.extend(key_to_item.values())
                        plan_queue = new_queue
                        _log(f"    🔀 AI がプランを並べ替え")

                    _log(f"    📋 残りプラン: {len(plan_queue)} ステップ")
            except Exception as e:
                _log(f"    ⚠️ リプランニング失敗（続行）: {e}")

    # 最終サマリー
    _log(f"\n{'═' * 56}")
    _log(f"  🏁 AI-Driven Analysis Complete")
    _log(f"  ✅ Completed: {result.completed_steps}")
    _log(f"  ❌ Failed:    {result.failed_steps}")
    _log(f"  ⏭  Skipped by AI: {result.skipped_by_ai}")
    _log(f"  ➕ Added by AI:   {result.added_by_ai}")
    _log(f"  🔄 Replanning events: {len(result.replan_history)}")
    _log(f"  📊 Total figures: {len(result.all_figures)}")
    _log(f"{'═' * 56}\n")

    return result
