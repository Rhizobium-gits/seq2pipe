# seq2pipe 🧬

**sequence → pipeline** — ローカル LLM（Ollama）を使って、生配列データから QIIME2 解析パイプラインを自動生成する AI エージェントです。
クラウド・API キー不要で、すべてあなたのマシン上で動作します。

---

## 概要

このツールは以下を自動で行います：

1. **データ構造の自動認識** — あなたの FASTQ ファイル・メタデータ・既存 QZA を調査
2. **解析パイプラインの生成** — データに合わせた QIIME2 コマンド群を生成
3. **スクリプトの書き出し** — すぐ実行できる `.sh` スクリプトを出力
4. **操作ガイドの生成** — 可視化方法を含む `README.md` をデータに合わせて生成

---

## 必要なもの

| ソフトウェア | 用途 | インストール |
|---|---|---|
| Ollama | ローカル LLM の実行 | `./setup.sh` で自動 |
| Docker Desktop | QIIME2 の実行環境 | [公式サイト](https://www.docker.com/products/docker-desktop/) |
| Python 3.9 以上 | エージェントスクリプト | 通常インストール済み |

**ディスク容量の目安:**

| 用途 | 容量 |
|---|---|
| LLM モデル（qwen2.5-coder:7b） | 約 4.7 GB |
| QIIME2 Docker イメージ | 約 4 GB |
| SILVA 138 参照ファイル | 約 30 GB |

---

## クイックスタート

### STEP 1: セットアップ（初回のみ）

```bash
cd ~/qiime2-local-ai
chmod +x setup.sh launch.sh
./setup.sh
```

`setup.sh` が行うこと：
- Ollama のインストール
- LLM モデルのダウンロード（推奨: qwen2.5-coder:7b）
- Docker Desktop の確認

### STEP 2: Docker Desktop を起動

アプリケーションフォルダから Docker Desktop を起動します。
（タスクバーに Docker アイコンが表示されるまで待ってください）

### STEP 3: エージェントを起動

```bash
./launch.sh
```

または直接:

```bash
ollama serve &   # 別ターミナルで起動しておく
python3 qiime2_agent.py
```

---

## エージェントとの対話例

起動すると AI が挨拶します。以下のように会話を進めてください：

```
🤖 AI: こんにちは！解析したいデータのディレクトリパスを教えてください。

あなた > /Users/yourname/microbiome-data/

🔧 ツール実行: inspect_directory
  → ディレクトリ内容を自動調査...

🤖 AI: ペアエンドFASTQを16サンプル検出しました。
       V1-V3領域（27F/338R）用のパイプラインを生成します。
       どのような解析を行いたいですか？
       1) 分類学的組成の解析（バーチャート）
       2) α・β多様性の比較
       3) 両方

あなた > 両方やりたい

🤖 AI: 了解です。以下のファイルを生成します...
```

### 主な質問と応答例

| あなたの質問 | AI の動作 |
|---|---|
| `~/data を解析して` | ディレクトリを自動調査、データ形式を判定 |
| `マニフェストを作って` | FASTQ 一覧から manifest.tsv を自動生成 |
| `スクリプトを書いて` | run_pipeline.sh を生成・保存 |
| `どう可視化すればいい?` | view.qiime2.org での操作を説明 |
| `メモリエラーが出た` | トラブルシューティングを案内 |

---

## 生成されるファイル

エージェントが出力するファイルの例（あなたのデータに合わせて内容が変わります）：

```
<あなたのデータディレクトリ>/
├── manifest.tsv                   # QIIME2 インポート用マニフェスト
├── metadata.tsv                   # メタデータテンプレート（未作成の場合）
├── setup_classifier.sh            # SILVA 138 分類器のセットアップ
├── run_pipeline.sh                # 解析パイプライン全体
├── run_01_import.sh               # STEP別スクリプト（必要な場合）
├── run_02_dada2.sh
├── run_03_taxonomy.sh
├── run_04_diversity.sh
├── results/                       # 解析結果の出力先
│   ├── paired-end-demux.qza
│   ├── table.qza
│   ├── rep-seqs.qza
│   ├── taxonomy.qza
│   ├── taxa-bar-plots.qzv        ← ★ 分類組成バーチャート
│   ├── core-metrics-results/
│   │   ├── shannon_vector.qza
│   │   └── *.qzv
│   └── ancombc-results.qzv       ← 差次解析（オプション）
└── ANALYSIS_README.md             # このデータ専用の操作ガイド
```

---

## 解析結果の可視化

QIIME2 の `.qzv` ファイルは以下の方法で可視化できます：

### 方法 1: QIIME2 View（推奨・インストール不要）

👉 **https://view.qiime2.org** をブラウザで開き、`.qzv` ファイルをドラッグ＆ドロップ

### 方法 2: コマンドライン

```bash
qiime tools view results/taxa-bar-plots.qzv
```

### 主要な可視化ファイルとその見方

#### taxa-bar-plots.qzv — 分類組成バーチャート

- 各サンプルの微生物組成を積み上げ棒グラフで表示
- 「Taxonomic Level」を変更して門〜属レベルで切り替え可能
- 「Sort samples by metadata column」でグループ別に並び替え

#### core-metrics-results/emperor.qzv — PCoA プロット（β多様性）

- 各サンプルの類似度を 3D で可視化
- 色を変えてグループ間の違いを確認

#### core-metrics-results/shannon-significance.qzv — α多様性

- Shannon 多様性指数のグループ比較（箱ひげ図）
- Kruskal-Wallis 検定の結果を確認

#### ancombc-results.qzv — 差次解析

- グループ間で有意に豊富な分類群を棒グラフで表示

---

## SILVA 138 分類器のセットアップ（初回のみ、約 30GB・2〜5時間）

エージェントが生成する `setup_classifier.sh` を実行してください：

```bash
# Docker Desktop を起動した状態で実行
./setup_classifier.sh
```

処理の流れ：
1. SILVA 138 参照配列をダウンロード（300 MB）
2. SILVA 分類ラベルをダウンロード（18 MB）
3. V1-V3 領域を抽出（1〜2 時間）
4. Naive Bayes 分類器を学習（1〜3 時間）

> **一度作成した分類器は再利用可能です。** 次の実験でも同じファイルを使えます。

---

## トラブルシューティング

### Ollama に接続できない

```bash
# Ollama を手動起動
ollama serve

# 別ターミナルでエージェントを起動
./launch.sh
```

### Docker: permission denied

```bash
# macOS: Docker Desktop を起動してから再試行
open /Applications/Docker.app
```

### モデルが遅い / メモリ不足

```bash
# より軽量なモデルに切り替える
QIIME2_AI_MODEL=qwen2.5-coder:3b ./launch.sh
# または
QIIME2_AI_MODEL=llama3.2:3b ./launch.sh
```

### classify-sklearn でメモリエラー

Docker Desktop の設定でメモリ上限を 8GB 以上に引き上げてください：
`Docker Desktop → Settings → Resources → Memory → 8GB 以上`

そして `--p-n-jobs` を 1 に減らして再実行：

```bash
# エージェントに伝えてください:
# 「メモリエラーが出たので --p-n-jobs 1 でスクリプトを修正して」
```

### 分類結果が全て Unassigned

エージェントに以下を伝えてください：
```
classify-sklearn の結果が全て Unassigned になった。
rep-seqs.qza の配列がリバースコンプリメントかもしれない。
--p-confidence を 0.5 に下げてスクリプトを修正して。
```

---

## 使用モデルの変更

```bash
# .env ファイルを編集
echo "QIIME2_AI_MODEL=qwen2.5-coder:3b" > .env

# または起動時に環境変数で指定
QIIME2_AI_MODEL=llama3.2:3b ./launch.sh
```

推奨モデルと必要 RAM：

| モデル | RAM 推奨 | 特徴 |
|---|---|---|
| qwen2.5-coder:7b | 8GB 以上 | コード生成に最適（推奨） |
| qwen2.5-coder:3b | 4GB 以上 | 軽量・高速 |
| llama3.2:3b | 4GB 以上 | 汎用・会話能力高め |
| qwen3:8b | 16GB 以上 | 最高品質・推論能力も高い |

---

## 参考リンク

- [QIIME2 公式ドキュメント](https://docs.qiime2.org/)
- [QIIME2 View（可視化サイト）](https://view.qiime2.org)
- [QIIME2 Forum（質問・トラブルシューティング）](https://forum.qiime2.org/)
- [SILVA データベース](https://www.arb-silva.de/)
- [Ollama 公式サイト](https://ollama.com/)
- [vibe-local（このツールの参考実装）](https://github.com/ochyai/vibe-local)

---

## ライセンス

- このツール: MIT License
- SILVA 138 データ: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- QIIME2: BSD License
