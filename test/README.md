# test/ — seq2pipe 各モードの動作例

seq2pipe の各モードが実際にローカルで動いた時に、どんなコードが生成・実行されるかをまとめたものです。

## ファイル一覧

| ファイル | 内容 |
|---------|------|
| `example_mode1_specified.py` | モード 1（指定解析）: ユーザーが `--prompt` で指示 → LLM がコード生成 → 振り返り修正ループ |
| `example_mode2_auto.py` | モード 2（`--auto` 完全自律）: 4ステップ自動化パイプライン全体の流れと生成コード |
| `example_mode3_chat.py` | モード 3（`--chat` 対話）: 実験説明 → 解析プラン → 自動実行 → 対話追加 → レポート |
| `example_analysis_standalone.py` | `analysis.py` 単体: 29図の決定論的生成 + `generate_analysis_summary()` の出力例 |
| `example_code_agent.py` | `code_agent.py`: LLM ↔ ツール対話ログ（list_files → read_file → write_file → run_python） |
| `example_report_generation.py` | `report_generator.py`: HTML/LaTeX レポートの構造と生成フロー |
| `example_seq_type_detection.py` | 16S/ショットガン自動判定: 4指標スコアリングの判定ロジックと結果例 |

## 実行コマンド早見表

```bash
# モード 1: 指定解析
./launch.sh --fastq-dir ~/input --prompt "属レベルの積み上げ棒グラフ"

# モード 2: 完全自律（最も一般的）
./launch.sh --fastq-dir ~/input --auto

# モード 3: 対話
./launch.sh --fastq-dir ~/input --chat

# 既存データから再解析
./launch.sh --export-dir ~/seq2pipe_results/.../exported/ --prompt "PCoA"
```

## 4ステップパイプライン（--auto モード）

```
STEP 1    QIIME2 パイプライン（DADA2, 系統樹, 分類, 多様性）
  ↓
STEP 1.5  決定論的包括解析（analysis.py → 29 図、LLM 不使用）
  ↓
STEP 2    適応型自律エージェント（LLM がデータを読んで深掘り解析）
  ↓
STEP 3    HTML レポート自動生成（数式・解説付き）
```
