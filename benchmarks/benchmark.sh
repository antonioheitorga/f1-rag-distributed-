#!/bin/bash
# benchmark.sh — coleta dados pra Seção 7 do documento técnico
#
# Roda na EC2 t3.medium com Ollama nativo. Mede:
#   1. Quantização e tamanho dos modelos
#   2. Tokens/seg do Llama 3.1 8B (3 runs)
#   3. Latência de embedding do nomic-embed-text (10 runs)
#   4. Comportamento concorrente do servidor Ollama (2 calls paralelas)
#
# Output salvo em ~/benchmark-results.txt

set -e

OUT=~/benchmark-results.txt
echo "Benchmark Ollama em t3.medium — $(date -u +%Y-%m-%dT%H:%M:%SZ)" > $OUT
echo "Host: $(hostname) | CPU: $(nproc) cores | RAM: $(free -h | awk '/^Mem/{print $2}')" >> $OUT
echo "Ollama: $(ollama --version 2>&1 | head -1)" >> $OUT
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 1. Modelos e quantização
# ----------------------------------------------------------------------------
echo "==== 1. Modelos instalados e quantização ====" | tee -a $OUT
echo "" >> $OUT
echo "--- llama3.1:8b ---" >> $OUT
ollama show llama3.1:8b >> $OUT 2>&1
echo "" >> $OUT
echo "--- nomic-embed-text ---" >> $OUT
ollama show nomic-embed-text >> $OUT 2>&1
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 2. Generation benchmark — Llama 3.1 8B
# ----------------------------------------------------------------------------
echo "==== 2. Generation tokens/seg — Llama 3.1 8B (3 runs) ====" | tee -a $OUT
echo "Prompt: 'Explain in 100 words how Formula 1 cars generate downforce.'" >> $OUT
echo "" >> $OUT

for i in 1 2 3; do
    echo "Run $i:" | tee -a $OUT
    curl -s http://localhost:11434/api/generate -d '{
      "model": "llama3.1:8b",
      "prompt": "Explain in 100 words how Formula 1 cars generate downforce.",
      "stream": false
    }' | python3 -c "
import sys, json
d = json.load(sys.stdin)
tokens = d['eval_count']
ns = d['eval_duration']
tps = tokens / ns * 1e9
print(f'  tokens={tokens}, eval_duration={ns/1e6:.0f}ms, tokens_per_sec={tps:.2f}')
" | tee -a $OUT
done
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 3. Embedding benchmark — nomic-embed-text
# ----------------------------------------------------------------------------
echo "==== 3. Embedding latency — nomic-embed-text (10 runs) ====" | tee -a $OUT
echo "Prompt: chunk típico de regulamento FIA (~500 chars)" >> $OUT
echo "" >> $OUT

PROMPT="Article 1.1. The 2026 FIA Formula One World Championship is conducted in accordance with the FIA International Sporting Code, its appendices, the Formula One Technical Regulations, the Formula One Sporting Regulations and the Formula One Financial Regulations. Each Competitor undertakes, on behalf of itself, its directors, employees, agents and drivers to observe all of these rules. The final text of these Sporting Regulations shall be the English version should any dispute arise."

total_ms=0
for i in $(seq 1 10); do
    start=$(date +%s%N)
    curl -s http://localhost:11434/api/embeddings -d "$(jq -nc --arg p "$PROMPT" '{model:"nomic-embed-text", prompt:$p}')" > /dev/null
    end=$(date +%s%N)
    ms=$(( (end - start) / 1000000 ))
    total_ms=$(( total_ms + ms ))
    echo "  Run $i: ${ms}ms" | tee -a $OUT
done
avg=$(( total_ms / 10 ))
echo "  Média: ${avg}ms/embedding" | tee -a $OUT
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 4. Concorrência — 2 generations em paralelo vs serial
# ----------------------------------------------------------------------------
echo "==== 4. Comportamento concorrente — 2 generations em paralelo ====" | tee -a $OUT
echo "Hipótese: se Ollama serializa, tempo total ≈ 2× tempo de 1 chamada solo." >> $OUT
echo "Se paraleliza, tempo total ≈ 1× tempo solo." >> $OUT
echo "" >> $OUT

CONCURRENT_PROMPT='{"model":"llama3.1:8b","prompt":"List 5 famous Formula 1 drivers.","stream":false}'

echo "--- Baseline: 1 generation solo ---" | tee -a $OUT
solo_start=$(date +%s%N)
curl -s http://localhost:11434/api/generate -d "$CONCURRENT_PROMPT" > /tmp/solo.json
solo_end=$(date +%s%N)
solo_ms=$(( (solo_end - solo_start) / 1000000 ))
echo "  Tempo solo: ${solo_ms}ms" | tee -a $OUT
echo "" >> $OUT

echo "--- 2 generations paralelas ---" | tee -a $OUT
par_start=$(date +%s%N)
(curl -s http://localhost:11434/api/generate -d "$CONCURRENT_PROMPT" > /tmp/par1.json) &
(curl -s http://localhost:11434/api/generate -d "$CONCURRENT_PROMPT" > /tmp/par2.json) &
wait
par_end=$(date +%s%N)
par_ms=$(( (par_end - par_start) / 1000000 ))
echo "  Tempo paralelo (2 chamadas): ${par_ms}ms" | tee -a $OUT
ratio=$(python3 -c "print(f'{$par_ms / $solo_ms:.2f}')")
echo "  Ratio paralelo/solo: ${ratio}x" | tee -a $OUT
echo "  → ratio ~2.0x = serialização interna; ~1.0x = paralelismo real" | tee -a $OUT
echo "" >> $OUT

echo "==== Benchmark concluído. Resultados em $OUT ====" | tee -a $OUT
