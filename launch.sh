#!/bin/bash
# ============================================================
# seq2pipe — 起動スクリプト
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# .env からモデル設定を読み込む
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi
export QIIME2_AI_MODEL="${QIIME2_AI_MODEL:-qwen2.5-coder:7b}"

# カラー
CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
GREEN='\033[0;32m'; RESET='\033[0m'; BOLD='\033[1m'

# ============================================================
# Ollama 起動確認・自動起動
# ============================================================
if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo -e "${YELLOW}Ollama が起動していません。自動起動を試みます...${RESET}"

    if command -v ollama &>/dev/null; then
        # Linux: systemctl は timeout 付きで試みる（非 systemd 環境でのハング防止）
        OS_INNER="$(uname -s)"
        OLLAMA_BG_PID=""
        # Linux: service マネージャーを試みるが exit code は信頼しない
        if [[ "$OS_INNER" == "Linux" ]]; then
            if command -v systemctl &>/dev/null; then
                timeout 5 sudo systemctl start ollama 2>/dev/null || \
                timeout 5 systemctl --user start ollama 2>/dev/null || true
            fi
            if command -v service &>/dev/null; then
                timeout 5 service ollama start 2>/dev/null || true
            fi
        fi
        # API が応答しない場合は必ず nohup で直接起動（service/systemctl の exit code 不問）
        if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
            nohup ollama serve > /tmp/ollama.log 2>&1 &
            OLLAMA_BG_PID=$!
            echo -e "${CYAN}Ollama をバックグラウンドで起動しました (PID: $OLLAMA_BG_PID)${RESET}"
        fi

        # 起動待機（最大 120 秒）
        for i in {1..120}; do
            sleep 1
            if curl -s http://localhost:11434/api/tags &>/dev/null; then
                echo -e "${GREEN}✅ Ollama 起動確認（${i} 秒）${RESET}"
                break
            fi
            if [[ -n "${OLLAMA_BG_PID:-}" ]] && ! kill -0 "$OLLAMA_BG_PID" 2>/dev/null; then
                echo -e "${RED}❌ Ollama プロセスがクラッシュしました。${RESET}"
                cat /tmp/ollama.log 2>/dev/null | tail -20
                exit 1
            fi
            if [[ $i -eq 120 ]]; then
                echo -e "${RED}❌ Ollama の起動に失敗しました（120 秒タイムアウト）。${RESET}"
                echo "   ログ: $(cat /tmp/ollama.log 2>/dev/null | tail -5)"
                echo "   手動で 'ollama serve' を別ターミナルで実行してから再試行してください。"
                exit 1
            fi
            if (( i % 10 == 0 )); then
                echo "   待機中... ${i}/120 秒"
            fi
        done
    else
        echo -e "${RED}❌ Ollama がインストールされていません。${RESET}"
        echo "   先に ./setup.sh を実行してください。"
        exit 1
    fi
fi

# ============================================================
# モデル確認
# ============================================================
MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print('\n'.join(m['name'] for m in d.get('models',[])))" \
    2>/dev/null || echo "")

if [[ -z "$MODELS" ]]; then
    echo -e "${YELLOW}⚠️  モデルがインストールされていません。${RESET}"
    echo -e "   推奨: ${CYAN}ollama pull qwen2.5-coder:7b${RESET}"
    echo ""
    read -rp "今すぐ qwen2.5-coder:7b をダウンロードしますか? [y/N]: " DO_PULL
    if [[ "${DO_PULL,,}" == "y" ]]; then
        ollama pull qwen2.5-coder:7b
    else
        exit 1
    fi
fi

# ============================================================
# Docker 確認（警告のみ、必須ではない）
# ============================================================
OS="$(uname -s)"
if [[ "$OS" == "Darwin" ]]; then
    DOCKER_CMD="/Applications/Docker.app/Contents/Resources/bin/docker"
    [[ ! -f "$DOCKER_CMD" ]] && DOCKER_CMD="$(command -v docker || echo '')"
else
    DOCKER_CMD="$(command -v docker || echo '')"
fi

if [[ -n "$DOCKER_CMD" ]] && command -v "$DOCKER_CMD" &>/dev/null; then
    if ! "$DOCKER_CMD" info &>/dev/null 2>&1; then
        echo -e "${YELLOW}Docker が起動していません。${RESET}"
        echo "   QIIME2 コマンドを実行する場合は Docker を起動してください。"
        echo "   （会話・スクリプト生成のみなら起動不要です）"
        echo ""
    fi
fi

# ============================================================
# エージェント起動
# ============================================================
echo -e "${CYAN}${BOLD}seq2pipe を起動しています...${RESET}"
echo -e "${CYAN}   モデル: ${QIIME2_AI_MODEL}${RESET}"
echo ""

exec python3 "$SCRIPT_DIR/qiime2_agent.py"
