#!/usr/bin/env python3
"""
bulletproof_coder.py — 絶対に成功するコード生成
=================================================
LLM の失敗原因を全て構造的に排除する。

失敗原因と対策:
  1. import 忘れ → テンプレートで全 import を保証
  2. ファイル形式の無知 → テンプレートで読み込み済み
  3. 変数名の推測 → 実行時の locals() を LLM に渡す
  4. カラム名の推測 → DataFrame の .columns を LLM に渡す
  5. 同じエラーの繰り返し → エラー行のスコープ情報を渡す
  6. モジュール不在 → 使用可能モジュールをホワイトリスト化

戦略:
  Step 1: データを読み込み、変数の「カタログ」を生成
  Step 2: カタログを LLM に渡して分析コードを書かせる
  Step 3: エラー時は locals() のスナップショットで具体的に修正指示
  Step 4: 最大リトライ後はテンプレートで 100% 保証
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, Callable


def _build_catalog(export_files: dict, metadata_path: str, group_column: str,
                   figure_dir: str) -> tuple[str, str]:
    """
    データを実際に読み込み、利用可能な変数の「カタログ」を生成。
    LLM はこのカタログを見てコードを書く。推測の余地をゼロにする。

    Returns: (setup_code, catalog_text)
    """
    setup_lines = [
        "import matplotlib; matplotlib.use('Agg')",
        "import matplotlib.pyplot as plt",
        "import pandas as pd",
        "import numpy as np",
        "import os",
        "from scipy import stats as scipy_stats",
        "",
        f"FIGDIR = r'{figure_dir}'",
        "os.makedirs(FIGDIR, exist_ok=True)",
        "DPI = 150",
        "",
        "# ── Data Loading ──",
    ]
    catalog_lines = ["AVAILABLE VARIABLES (use EXACTLY these names):"]
    var_names = []

    # Feature table
    ft_paths = export_files.get("feature_table", [])
    if ft_paths and Path(ft_paths[0]).exists():
        with open(ft_paths[0]) as f:
            first = f.readline()
        if first.startswith("# "):
            setup_lines.append(f"ft = pd.read_csv(r'{ft_paths[0]}', sep='\\t', skiprows=1, index_col=0)")
        else:
            setup_lines.append(f"ft = pd.read_csv(r'{ft_paths[0]}', sep='\\t', index_col=0)")
        setup_lines.append("_ft_info = f'ft: {{ft.shape[0]}} rows x {{ft.shape[1]}} cols, columns={{list(ft.columns[:3])}}...'")
        catalog_lines.append("  ft: DataFrame (rows=ASVs, cols=samples)")
        var_names.append("ft")

    # Taxonomy
    tax_paths = export_files.get("taxonomy", [])
    if tax_paths and Path(tax_paths[0]).exists():
        with open(tax_paths[0]) as f:
            header = f.readline().strip().split("\t")
        taxon_col = next((h for h in header if h.lower() in ("taxon","taxonomy")), None)
        setup_lines.append(f"tax = pd.read_csv(r'{tax_paths[0]}', sep='\\t', index_col=0)")
        if taxon_col:
            setup_lines.append(f"tax['Genus'] = tax['{taxon_col}'].str.extract(r'g__([^;]+)')[0].fillna('Unknown')")
        catalog_lines.append(f"  tax: DataFrame, columns={header[:3]}...")
        if taxon_col:
            catalog_lines.append(f"  tax['Genus']: genus names extracted from '{taxon_col}'")
        var_names.append("tax")

    # Metadata
    if metadata_path and Path(metadata_path).exists():
        setup_lines.append(f"meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')")
        setup_lines.append("meta = meta.set_index(meta.columns[0])")
        setup_lines.append(f"group_col = '{group_column}'")
        setup_lines.append("groups = sorted(meta[group_col].dropna().unique().tolist())")
        catalog_lines.append(f"  meta: DataFrame indexed by sample ID")
        catalog_lines.append(f"  group_col: '{group_column}'")
        catalog_lines.append(f"  groups: list of group names")
        var_names.extend(["meta", "group_col", "groups"])

    # Alpha
    alpha_paths = export_files.get("alpha", [])
    for ap in alpha_paths:
        if Path(ap).exists():
            vname = "alpha_" + Path(ap).parent.name.replace("-","_")
            setup_lines.append(f"{vname} = pd.read_csv(r'{ap}', sep='\\t', index_col=0)")
            setup_lines.append(f"{vname}_col = {vname}.columns[0]")
            catalog_lines.append(f"  {vname}: DataFrame, value column = {vname}_col")
            var_names.extend([vname, f"{vname}_col"])

    # Beta
    beta_paths = export_files.get("beta", [])
    for bp in beta_paths:
        if Path(bp).exists():
            vname = "dm_" + Path(bp).parent.name.replace("-","_")
            setup_lines.append(f"{vname} = pd.read_csv(r'{bp}', sep='\\t', index_col=0)")
            catalog_lines.append(f"  {vname}: DataFrame (square distance matrix)")
            var_names.append(vname)

    # 変数名リストを生成
    setup_lines.append("")
    setup_lines.append(f"_all_vars = {var_names}")
    setup_lines.append("print('Loaded:', _all_vars)")

    setup_code = "\n".join(setup_lines)
    catalog_text = "\n".join(catalog_lines)
    return setup_code, catalog_text


class BulletproofCoder:
    """
    絶対に成功するコード生成エンジン。
    """

    def __init__(self, log_callback: Optional[Callable] = None):
        self._log = log_callback or (lambda msg: print(msg))

    def generate(
        self,
        task_key: str,
        task_description: str,
        export_files: dict,
        metadata_path: str,
        group_column: str,
        figure_dir: str,
        llm_call: Callable,
        extract_code: Callable,
        run_code: Callable,
        max_retries: int = 7,
    ) -> dict:

        setup_code, catalog = _build_catalog(
            export_files, metadata_path, group_column, figure_dir)

        save_code = f"""
# ── Save ──
_fig_path = os.path.join(FIGDIR, '{task_key}.png')
fig.savefig(_fig_path, dpi=DPI, bbox_inches='tight')
plt.close('all')
print(f'SAVED: {{_fig_path}}')
"""

        # ── LLM プロンプト: 変数カタログ付き ──
        base_prompt = f"""Write ONLY the analysis code. All data is already loaded.

{catalog}

TASK: {task_description}

RULES:
1. Use ONLY the variable names listed above — do NOT invent names
2. Do NOT import anything — all imports are done
3. Do NOT read files — all data is loaded
4. Create: fig, ax = plt.subplots(...)
5. Do NOT call plt.show() or fig.savefig()
6. scipy.stats is available as scipy_stats
7. For alpha data: use {{}}_col for the value column name
8. For boxplot: extract values as .values.flatten() before passing to boxplot

Output ONLY Python code:"""

        msgs = [{"role":"system","content":
                 "You are a Python data analyst. Write ONLY analysis code. "
                 "All variables are pre-loaded. Use EXACTLY the variable names given."},
                {"role":"user","content": base_prompt}]

        code = None
        last_error = ""

        for attempt in range(max_retries):
            self._log(f"  [{task_key}] Attempt {attempt+1}/{max_retries}")

            try:
                if attempt == 0:
                    resp = llm_call(msgs)
                    layer_b = extract_code(resp.get("content", ""))
                else:
                    # 具体的なエラー情報 + 変数スコープ
                    error_context = self._build_error_context(last_error, setup_code)
                    fix_msgs = msgs + [
                        {"role": "assistant", "content": f"```python\n{layer_b}\n```"},
                        {"role": "user", "content": error_context},
                    ]
                    resp = llm_call(fix_msgs)
                    new_b = extract_code(resp.get("content", ""))
                    if new_b:
                        layer_b = new_b

                if not layer_b:
                    continue

                # クリーニング
                layer_b = self._clean(layer_b)

                # 結合 + 実行
                full_code = setup_code + "\n\n# ── Analysis ──\n" + layer_b + "\n" + save_code
                success, stdout, stderr, figs = run_code(full_code)

                if success:
                    self._log(f"  [{task_key}] LLM SUCCESS on attempt {attempt+1}")
                    return {"success": True, "code": full_code, "method": "llm",
                            "attempts": attempt+1, "figures": figs}

                last_error = stderr
                err_summary = self._summarize_error(stderr, layer_b)
                self._log(f"  [{task_key}] {err_summary}")

            except Exception as e:
                last_error = str(e)
                self._log(f"  [{task_key}] Exception: {e}")

        # ── テンプレートフォールバック ──
        self._log(f"  [{task_key}] → Template fallback")
        fb_code = self._fallback(task_key, setup_code, save_code)
        if fb_code:
            success, stdout, stderr, figs = run_code(fb_code)
            if success:
                return {"success": True, "code": fb_code, "method": "template",
                        "attempts": max_retries, "figures": figs}

        return {"success": False, "code": "", "method": "failed",
                "attempts": max_retries, "figures": []}

    def _build_error_context(self, stderr: str, setup_code: str) -> str:
        """エラー時の具体的修正指示"""
        # エラー行を特定
        lines = stderr.strip().split("\n")
        error_line = next((l for l in reversed(lines) if "Error" in l), "")

        # 変数名エラーの場合、利用可能な変数を列挙
        m = re.search(r"name '(\w+)' is not defined", error_line)
        if m:
            wrong_name = m.group(1)
            # setup_code から実際の変数名を抽出
            actual_vars = re.findall(r"^(\w+)\s*=\s*pd\.read_csv", setup_code, re.MULTILINE)
            actual_vars += ["ft", "meta", "group_col", "groups", "tax"]
            return (
                f"ERROR: '{wrong_name}' does not exist.\n"
                f"Available variables are EXACTLY: {actual_vars}\n"
                f"Use one of these. Do NOT invent variable names.\n"
                f"Write corrected code:"
            )

        # KeyError の場合
        m = re.search(r"KeyError: ['\"](.+?)['\"]", error_line)
        if m:
            wrong_key = m.group(1)
            return (
                f"ERROR: Column '{wrong_key}' does not exist.\n"
                f"For alpha data: the value column is stored in *_col variable.\n"
                f"For metadata: group column is group_col = '{self}'.\n"
                f"Use .columns to check available columns.\n"
                f"Write corrected code:"
            )

        return (
            f"ERROR:\n{stderr[-500:]}\n\n"
            f"Fix the code. Use ONLY pre-loaded variables. "
            f"Do NOT import or read files.\n"
            f"Write corrected code:"
        )

    def _summarize_error(self, stderr: str, code: str) -> str:
        lines = [l.strip() for l in stderr.split("\n") if l.strip()]
        for l in reversed(lines):
            if "Error" in l:
                return l[:80]
        return "unknown error"

    def _clean(self, code: str) -> str:
        lines = []
        for line in code.split("\n"):
            s = line.strip()
            if s.startswith("import ") or s.startswith("from "): continue
            if "pd.read_csv" in s: continue
            if "matplotlib.use" in s: continue
            if "plt.show()" in s: continue
            if ".savefig(" in s: continue
            if "os.makedirs" in s and "FIGDIR" not in s: continue
            lines.append(line)
        return "\n".join(lines)

    def _fallback(self, task_key: str, setup: str, save: str) -> Optional[str]:
        fb = {
"alpha_boxplot": """
alpha_var = [v for k,v in list(locals().items()) if k.startswith('alpha_') and hasattr(v,'columns') and not k.endswith('_col')]
if alpha_var:
    adf = alpha_var[0]; acol = adf.columns[0]
    common = sorted(set(meta.index) & set(adf.index))
    fig, ax = plt.subplots(figsize=(8,5))
    data = [adf.loc[adf.index.isin(meta.loc[common][meta.loc[common,group_col]==g].index), acol].dropna().values for g in groups]
    data = [d for d in data if len(d)>0]
    if data:
        bp=ax.boxplot(data, labels=groups[:len(data)], patch_artist=True)
        for p,c in zip(bp['boxes'],plt.cm.Set2(np.linspace(0,1,len(data)))): p.set_facecolor(c)
        if len(data)>=2:
            try:
                H,pv=scipy_stats.kruskal(*data); ax.set_title(f'Alpha (KW p={pv:.4g})')
            except: ax.set_title('Alpha Diversity')
        else: ax.set_title('Alpha Diversity')
    ax.set_ylabel(acol)
else:
    fig,ax=plt.subplots(); ax.text(0.5,0.5,'No alpha data',ha='center')
""",
"beta_pcoa": """
dm_var = [v for k,v in list(locals().items()) if k.startswith('dm_') and hasattr(v,'shape') and v.shape[0]==v.shape[1]]
if dm_var:
    dm=dm_var[0]; common=sorted(set(dm.index)&set(meta.index)); dc=dm.loc[common,common]
    n=len(common); D=dc.values.astype(float); H2=np.eye(n)-np.ones((n,n))/n; B=-0.5*H2@(D**2)@H2
    ev,ec=np.linalg.eigh(B); idx=np.argsort(ev)[::-1]; ev=ev[idx]; ec=ec[:,idx]
    p1=ec[:,0]*np.sqrt(max(ev[0],0)); p2=ec[:,1]*np.sqrt(max(ev[1],0))
    fig,ax=plt.subplots(figsize=(8,6))
    gp=meta.loc[common,group_col]
    for g in sorted(gp.dropna().unique()): mask=gp==g; ax.scatter(p1[mask],p2[mask],label=g,s=40,alpha=0.7)
    tv=sum(max(e,0) for e in ev[:10])
    if tv>0: ax.set_xlabel(f'PC1 ({max(ev[0],0)/tv*100:.1f}%)'); ax.set_ylabel(f'PC2 ({max(ev[1],0)/tv*100:.1f}%)')
    ax.set_title('PCoA'); ax.legend()
else:
    fig,ax=plt.subplots(); ax.text(0.5,0.5,'No distance matrix',ha='center')
""",
"genus_barplot": """
if 'tax' in dir() and hasattr(tax,'Genus'):
    fc=ft.loc[:,ft.columns.isin(meta.index)]; fc2=fc.copy()
    fc2['G']=tax.reindex(fc.index)['Genus'].fillna('Unk')
    gs=fc2.groupby('G').sum(); gr=gs.div(gs.sum())*100
    top=gr.mean(axis=1).nlargest(15).index; gt=gr.loc[top]
    fig,ax=plt.subplots(figsize=(12,6))
    gt.T.plot(kind='bar',stacked=True,ax=ax,colormap='tab20')
    ax.set_title('Top 15 Genera'); ax.legend(bbox_to_anchor=(1.05,1),fontsize=5)
else:
    fig,ax=plt.subplots(); ax.text(0.5,0.5,'No taxonomy',ha='center')
""",
"rarefaction": """
fc=ft.loc[:,ft.columns.isin(meta.index)]
fig,ax=plt.subplots(figsize=(8,5))
for g in groups:
    sids=[s for s in meta[meta[group_col]==g].index if s in fc.columns]
    if not sids: continue
    depths=[];rich=[]; mx=int(fc[sids].sum().min()) if sids else 0
    for d in range(100,max(mx,200),max(mx//20,100)):
        obs=[]
        for s in sids:
            col=fc[s].values; total=col.sum()
            if total<d: continue
            p=col/total; obs.append(sum(1-(1-pi)**d for pi in p if pi>0))
        if obs: depths.append(d); rich.append(np.mean(obs))
    if depths: ax.plot(depths,rich,label=g,linewidth=2)
ax.set_xlabel('Depth'); ax.set_ylabel('Expected ASVs'); ax.set_title('Rarefaction'); ax.legend()
""",
"cooccurrence_network": """
fc=ft.loc[:,ft.columns.isin(meta.index)]
top20=fc.sum(axis=1).nlargest(20).index; ftt=fc.loc[top20].T
corr=ftt.corr(method='spearman')
fig,ax=plt.subplots(figsize=(8,7))
im=ax.imshow(corr.values,cmap='RdBu_r',vmin=-1,vmax=1)
ax.set_xticks(range(len(corr))); ax.set_xticklabels([str(x)[:8] for x in corr.columns],rotation=90,fontsize=4)
ax.set_yticks(range(len(corr))); ax.set_yticklabels([str(x)[:8] for x in corr.index],fontsize=4)
ax.set_title('Top 20 Correlation'); plt.colorbar(im,ax=ax)
""",
        }
        code = fb.get(task_key)
        if code:
            return setup + "\n" + code + "\n" + save
        return None
