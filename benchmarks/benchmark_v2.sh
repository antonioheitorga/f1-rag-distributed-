#!/bin/bash
# benchmark_v2.sh — focado em llama3.2:1b (cabe em t3.medium 3.7GB RAM)
#
# Complementa benchmark.sh. Mede:
#   1. Quantização do llama3.2:1b
#   2. Tokens/seg de geração (5 runs)
#   3. Concorrência com modelo que efetivamente carrega
#
# Salva em ~/benchmark-v2-results.txt

set -e

OUT=~/benchmark-v2-results.txt
MODEL="llama3.2:1b"

echo "Benchmark v2 — $MODEL em t3.medium — $(date -u +%Y-%m-%dT%H:%M:%SZ)" > $OUT
echo "Host: $(hostname) | CPU: $(nproc) cores | RAM: $(free -h | awk '/^Mem/{print $2}')" >> $OUT
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 1. Quantização
# ----------------------------------------------------------------------------
echo "==== 1. Quantização $MODEL ====" | tee -a $OUT
ollama show $MODEL >> $OUT 2>&1
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 2. Warmup + Generation tokens/seg
# ----------------------------------------------------------------------------
echo "==== 2. Generation tokens/seg — $MODEL (5 runs após warmup) ====" | tee -a $OUT
echo "Prompt: 'Explain in 100 words how Formula 1 cars generate downforce.'" >> $OUT
echo "" >> $OUT

# Warmup (carrega modelo na RAM)
echo "Warmup (carregando modelo na RAM)..." | tee -a $OUT
curl -s http://localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"Hi\",\"stream\":false}" > /tmp/warmup.json
if grep -q error /tmp/warmup.json; then
    echo "ERRO no warmup:" | tee -a $OUT
    cat /tmp/warmup.json | tee -a $OUT
    exit 1
fi
echo "Warmup ok. Modelo carregado." | tee -a $OUT
echo "" >> $OUT

PROMPT="Explain in 100 words how Formula 1 cars generate downforce."
JSON=$(jq -nc --arg m "$MODEL" --arg p "$PROMPT" '{model:$m, prompt:$p, stream:false}')

total_tps=0
for i in 1 2 3 4 5; do
    curl -s http://localhost:11434/api/generate -d "$JSON" > /tmp/gen.json
    line=$(python3 -c "
import json
with open('/tmp/gen.json') as f:
    d = json.load(f)
if 'eval_count' not in d:
    print('ERROR:', d.get('error', 'no eval_count'))
else:
    tokens = d['eval_count']
    ns = d['eval_duration']
    tps = tokens / ns * 1e9
    total = d['total_duration'] / 1e9
    print(f'  Run $i: tokens={tokens}, eval_duration={ns/1e6:.0f}ms, total={total:.1f}s, tokens_per_sec={tps:.2f}')
")
    echo "$line" | tee -a $OUT
    tps=$(echo "$line" | grep -oP 'tokens_per_sec=\K[0-9.]+' || echo "0")
    total_tps=$(python3 -c "print($total_tps + $tps)")
done
avg_tps=$(python3 -c "print(f'{$total_tps / 5:.2f}')")
echo "  Média: $avg_tps tokens/seg" | tee -a $OUT
echo "" >> $OUT

# ----------------------------------------------------------------------------
# 3. Concorrência
# ----------------------------------------------------------------------------
echo "==== 3. Concorrência — 2 generations paralelas ====" | tee -a $OUT
SHORT='{"model":"'"$MODEL"'","prompt":"List 5 Formula 1 teams.","stream":false}'

echo "--- Baseline: 1 generation solo ---" | tee -a $OUT
solo_start=$(date +%s%N)
curl -s http://localhost:11434/api/generate -d "$SHORT" > /tmp/solo.json
solo_end=$(date +%s%N)
solo_ms=$(( (solo_end - solo_start) / 1000000 ))
solo_tokens=$(python3 -c "import json; print(json.load(open('/tmp/solo.json')).get('eval_count', 0))")
echo "  Tempo solo: ${solo_ms}ms, tokens gerados: $solo_tokens" | tee -a $OUT
echo "" >> $OUT

echo "--- 2 generations paralelas ---" | tee -a $OUT
par_start=$(date +%s%N)
(curl -s http://localhost:11434/api/generate -d "$SHORT" > /tmp/par1.json) &
(curl -s http://localhost:11434/api/generate -d "$SHORT" > /tmp/par2.json) &
wait
par_end=$(date +%s%N)
par_ms=$(( (par_end - par_start) / 1000000 ))
par1_tokens=$(python3 -c "import json; print(json.load(open('/tmp/par1.json')).get('eval_count', 0))")
par2_tokens=$(python3 -c "import json; print(json.load(open('/tmp/par2.json')).get('eval_count', 0))")
echo "  Tempo paralelo (2 chamadas): ${par_ms}ms" | tee -a $OUT
echo "  Tokens: par1=$par1_tokens, par2=$par2_tokens" | tee -a $OUT
ratio=$(python3 -c "print(f'{$par_ms / $solo_ms:.2f}')")
echo "  Ratio paralelo/solo: ${ratio}x" | tee -a $OUT
echo "  → ratio ~2.0x = serialização interna; ~1.0x = paralelismo real" | tee -a $OUT
echo "" >> $OUT

echo "==== Concluído. Resultados em $OUT ====" | tee -a $OUT
