# Benchmarks do servidor de inferência (Ollama)

Dados coletados em 2026-05-26 para sustentar a Seção 7 do documento técnico (bônus SLM auto-hospedado).

## Ambiente de teste

| Item | Valor |
|---|---|
| Instância | AWS EC2 `t3.medium` |
| vCPUs | 2 |
| RAM | 3.7 GiB |
| GPU | nenhuma (CPU-only) |
| SO | Ubuntu 22.04 LTS |
| Ollama | 0.24.0 |
| Região | us-east-1 |

## Modelos avaliados

| Modelo | Parâmetros | Quantização | Context length | Embedding length | Tamanho em disco |
|---|---|---|---|---|---|
| `llama3.1:8b` | 8.0B | Q4_K_M | 131072 | 4096 | 4.9 GB |
| `llama3.2:1b` | 1.2B | Q8_0 | 131072 | 2048 | 1.3 GB |
| `nomic-embed-text` | 137M | F16 (não quantizado) | 2048 | 768 | 274 MB |

`llama3.1:8b` é o modelo de geração usado pelo agente Generator do projeto (rodado localmente na máquina do desenvolvedor via Streamlit). `nomic-embed-text` é o modelo de embedding usado pelos workers EC2 na fase de ingestão distribuída.

## Resultado 1: Llama 3.1 8B não cabe em t3.medium

**Descoberta:** o modelo da aplicação (`llama3.1:8b` Q4_K_M, ~5 GB em RAM) **não carrega em t3.medium** (3.7 GB total). A API HTTP do Ollama retorna erro silencioso e `ollama ps` mostra nenhum modelo carregado.

**Implicação arquitetural:** se o objetivo for distribuir também a inferência do generator (não só o embedding), é preciso escolher instâncias maiores. O spec da disciplina sugere (Seção 7.3):
- **t3.large/xlarge (8-16 GB CPU)** para modelos 1-3B → viável para `llama3.2:1b`/`gemma3:2b`
- **g4dn.xlarge (16 GB VRAM T4)** para modelos 7-8B → viável para `llama3.1:8b` com Q4
- **g5.xlarge (24 GB VRAM A10G)** para modelos até 13B

No nosso projeto, **só o embedder foi distribuído na AWS**. O generator roda localmente (Streamlit) porque a interface de queries é single-user e o overhead de provisionar GPU não se justifica para fins didáticos.

## Resultado 2: tokens/seg — Llama 3.2 1B em t3.medium

Modelo: `llama3.2:1b` Q8_0
Prompt: `"Explain in 100 words how Formula 1 cars generate downforce."`
Método: 5 runs após warmup, parsing de `eval_count / eval_duration` retornados pela API.

| Run | Tokens gerados | Eval duration | Tokens/seg |
|---|---|---|---|
| 1 | 122 | 20.4 s | 5.99 |
| 2 | 120 | 19.4 s | 6.19 |
| 3 | 123 | 20.8 s | 5.92 |
| 4 | 120 | 19.4 s | 6.19 |
| 5 | 120 | 19.4 s | 6.19 |
| **Média** | — | — | **6.10 tokens/seg** |

Consistente com o spec da disciplina, que descreve "3 a 10 tokens por segundo" como faixa esperada para modelos pequenos em CPU (Seção 7.3 Opção B).

## Resultado 3: latência de embedding — nomic-embed-text em t3.medium

Modelo: `nomic-embed-text` F16
Prompt: chunk típico do corpus FIA (~500 caracteres em inglês).
Método: 10 runs.

| Run | Latência |
|---|---|
| 1 | 1916 ms (cold start) |
| 2 | 553 ms |
| 3 | 552 ms |
| 4 | 553 ms |
| 5 | 551 ms |
| 6 | 567 ms |
| 7 | 554 ms |
| 8 | 548 ms |
| 9 | 555 ms |
| 10 | 562 ms |
| **Média steady-state (runs 2-10)** | **555 ms/embedding** |

**Throughput:** ~1.8 embeddings/seg por worker.

Cruzando com os dados da ingestão real (Sessão B, 3 workers EC2 paralelos):
- Total: 3.127 chunks inseridos
- Tempo agregado de processamento: 24 min
- Throughput agregado: ~2.2 chunks/seg (3 workers × ~0.7 chunks/seg cada, considerando overhead de extração PDF + chunking + SQS)
- Throughput teórico ideal: 3 × 1.8 = 5.4 emb/seg

A diferença (2.2 vs 5.4) é explicada pelas etapas não-embedding: extração PDF (pdfplumber), chunking, parsing, e a inserção sequencial em ChromaDB.

## Resultado 4: paralelismo da aplicação × paralelismo interno do servidor

**Pergunta:** o Ollama pode atender múltiplas requisições de geração simultâneas, ou serializa internamente?

**Método:** disparar 2 chamadas idênticas a `/api/generate` em paralelo via `&` do bash, medir tempo total vs tempo de uma chamada solo.

| Cenário | Tempo |
|---|---|
| 1 chamada solo (49 tokens) | 8.87 s |
| 2 chamadas paralelas (46 + 53 tokens) | 17.74 s |
| **Ratio paralelo/solo** | **2.00x** |

**Conclusão:** ratio de exatamente 2.00x indica **serialização completa** no servidor — sem overhead extra, mas também sem paralelismo. Cada requisição espera a anterior terminar.

### Interação com o paralelismo da aplicação

Esse comportamento explica resultados observados em outras fases:

1. **Paralelismo local com ProcessPoolExecutor (Fase 4.1, 6 workers):** o speedup medido foi de **1.56x** (não 6x), confirmando que o gargalo era o Ollama serializando — os 6 processos da aplicação esperavam na fila do único servidor de inferência.

2. **Paralelismo distribuído na AWS (Fase 4.7, 3 EC2):** speedup quase linear de **~3x**, porque cada EC2 tem seu próprio servidor Ollama local independente. Não há fila compartilhada.

### Lição arquitetural

Para se beneficiar de paralelismo CPU-intensivo com Ollama, **uma instância de servidor por worker** é necessária. Soluções alternativas para escalar 1 servidor para N workers:

- **vLLM** com continuous batching (sugerido no spec §7.3 Opção C) — paraleliza requisições compartilhando GPU
- **Múltiplos containers Ollama** em portas diferentes na mesma máquina (consome RAM proporcionalmente)
- **Llama.cpp server** com flag `--parallel` (suporte experimental)

Nenhuma dessas foi necessária no projeto porque o paralelismo foi resolvido por arquitetura (1 worker = 1 EC2 = 1 Ollama), trade-off válido para o escopo acadêmico.

## Resumo executivo

| Pergunta | Resposta |
|---|---|
| Qual modelo de geração? | Llama 3.1 8B Q4_K_M (local), Llama 3.2 1B Q8_0 (avaliado em t3.medium) |
| Qual modelo de embedding? | nomic-embed-text F16 |
| Quantização usada? | Q4_K_M (8B), Q8_0 (1B), F16 (embed) |
| Tokens/seg por worker? | 6.10 t/s para Llama 3.2 1B em t3.medium CPU |
| Latência de embedding? | 555 ms steady-state |
| Servidor Ollama paraleliza? | **Não** — serializa requisições (ratio 2.00x para 2 calls paralelas) |
| Implicação para escala? | 1 worker AWS = 1 Ollama dedicado; não compartilhar servidor de inferência entre workers |
