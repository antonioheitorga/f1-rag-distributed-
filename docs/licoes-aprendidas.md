# Lições aprendidas — sessões de deploy AWS Academy (2026-05-26)

Registro factual dos erros encontrados durante as duas sessões de deploy real em AWS Academy (Sessão B do §4.7 + sessão de benchmark SLM e gravação da demo). Cada item segue o formato: **sintoma → causa raiz → solução → aprendizado**.

Documentação registrada como evidência do processo iterativo de debugging que ocorreu — útil pra recall em futuras sessões, pra mostrar maturidade no documento técnico, e pra alimentar a Seção 9 do entregável §8.2 ("Lições aprendidas").

---

## Bloco 1 — Restrições do ambiente AWS Academy

### 1.1 Filtro de AMI sem resultados

**Sintoma:** `data.aws_ami.ubuntu: Your query returned no results.` durante `terraform plan`.

**Causa:** o filtro original era `ubuntu/images/hvm-ssd-gp3/ubuntu-jammy-22.04-amd64-server-*`. O AWS Academy aparentemente não expõe AMIs com o naming `hvm-ssd-gp3` na região us-east-1 que recebemos.

**Solução:** trocar pra `ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*` (commit `14c79a4`).

**Aprendizado:** filtros de data source funcionam em produção mas podem não funcionar no Academy. Validar com `aws ec2 describe-images --owners 099720109477 --filters "Name=name,Values=ubuntu/images/*jammy*" --query 'Images[*].Name' | head` antes de declarar IaC pronto.

### 1.2 `iam:CreateRole` proibido

**Sintoma:** `AccessDenied: User ... is not authorized to perform: iam:CreateRole`.

**Causa:** a role `voclabs` do Academy bloqueia criação/modificação de IAM. Estávamos tentando criar `aws_iam_role`, `aws_iam_role_policy` e `aws_iam_instance_profile` customizados pro princípio do menor privilégio.

**Solução:** substituir os 3 recursos IAM por uma referência ao `LabInstanceProfile` pré-criado pelo Academy (commit `14c79a4`).

**Aprendizado:** o Academy fornece um Instance Profile genérico com permissões amplas. Princípio do menor privilégio fica comprometido, mas é trade-off do ambiente acadêmico — em produção real, criaríamos role customizado.

### 1.3 Pré-requisitos não documentados (SSH key + PATH)

**Sintoma:** `terraform plan` falhou em `aws_key_pair.worker` por `~/.ssh/id_ed25519.pub` inexistente; comandos `aws` e `terraform` "não reconhecidos" no PowerShell.

**Causa:** AWS CLI e Terraform foram instalados via `winget` na sessão anterior, mas o instalador não adicionou ao PATH global. A chave SSH nunca foi gerada.

**Solução:**
- `ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519` (gera par)
- `$env:PATH += ";C:\Program Files\Amazon\AWSCLIV2;$env:USERPROFILE\AppData\Local\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe"` (adiciona ao PATH da sessão)

**Aprendizado:** o PATH adicionado via `$env:PATH +=` **não persiste entre janelas do PowerShell** — toda nova sessão de shell precisa re-exportar. Para uso recorrente, registrar permanentemente via `System Properties → Environment Variables` ou `[System.Environment]::SetEnvironmentVariable`. Em multi-window setups (como o da demo), isso vira fonte de erro silencioso.

### 1.4 Credenciais AWS expiram

**Sintoma:** `InvalidClientTokenId: The security token included in the request is invalid` após algumas horas.

**Causa:** o `AWS_SESSION_TOKEN` do Academy tem validade limitada (~4h, mesmo se o lab ainda estiver rodando).

**Solução:** re-copiar as 3 variáveis do `AWS Details` no Academy e re-exportar.

**Aprendizado:** session tokens não são permanentes. Em sessões longas, ter o bloco de exportação no clipboard ou num script utility (`scripts/export-aws.ps1`). Em uma das tentativas, colamos `"..."` literal no token por engano — outro motivo pra ter o bloco real disponível.

---

## Bloco 2 — Bugs externos (não nossos)

### 2.1 Ollama 0.24.0 panic em `envconfig.Models()`

**Sintoma:** durante `user_data.sh` no cloud-init, comando `ollama pull nomic-embed-text` crasha com stack trace em `goroutine 1 [running]` apontando pra `envconfig/config.go:120 (Models)` e `config.go:325 (AsMap)`. Todas as 5 tentativas do retry loop falham.

**Causa raiz:** versão 0.24.0 do Ollama tem bug de panic quando `$HOME` não está setado. Em `cloud-init`, scripts user_data rodam como root **sem $HOME definido**. Quando SSH-ado interativamente como `ubuntu`, o problema não aparece porque `$HOME=/home/ubuntu`.

**Solução:** bypass do CLI. Usar a API HTTP do Ollama (servida pelo systemd service, que tem env próprio correto):
```bash
curl -X POST http://localhost:11434/api/pull \
    -H 'Content-Type: application/json' \
    -d '{"model":"nomic-embed-text"}'
```

**Aprendizado:** versões recentes de ferramentas podem ter bugs que só disparam em cenários não-interativos. Quando há CLI **e** HTTP API pra mesma funcionalidade, a HTTP API costuma ser mais robusta (env do daemon é melhor controlado que env do usuário).

### 2.2 Ollama serializa requisições internamente

**Sintoma:** ProcessPoolExecutor com 6 workers locais entregou speedup de apenas 1.56x (não 6x esperado pelo paralelismo embaraçoso).

**Causa:** o servidor Ollama trata uma requisição por vez. 6 processos enviando embeddings simultaneamente formaram fila no único servidor.

**Validação empírica (Sessão de benchmark):** disparamos 2 chamadas `/api/generate` em paralelo via bash `&`. Tempo paralelo = 2.00x exato do tempo solo. Confirma serialização completa.

**Aprendizado:** paralelismo da aplicação só rende se cada worker tem seu próprio servidor de inferência. Por isso a arquitetura distribuída do Harness (1 EC2 = 1 Ollama dedicado) entrega speedup quase linear (~3x), enquanto ProcessPoolExecutor local (6 processos, 1 Ollama) cresceu apenas 1.56x. Pra compartilhar servidor entre workers, usar vLLM (continuous batching) ou múltiplos containers Ollama em portas diferentes.

### 2.3 Llama 3.1 8B Q4_K_M não cabe em t3.medium

**Sintoma:** benchmark de geração retornou `KeyError: 'eval_count'` silencioso 3 vezes seguidas. `ollama ps` mostrou zero modelos carregados.

**Causa:** modelo precisa ~5 GB de RAM; t3.medium tem 3.7 GB total. API retornou erro genérico em vez de OOM explícito.

**Solução:** trocar pra `llama3.2:1b` (Q8_0, ~1.3 GB) que cabe. Documentar limitação no `benchmarks/results.md` — pra distribuir modelos 7-8B precisaria t3.large (8 GB) ou g4dn.xlarge (GPU).

**Aprendizado:** validar memória requerida do modelo antes de escolher instância. Spec §7.3 do enunciado tinha tabela exata: 1-3B em t3.large CPU, 7-9B em g4dn.xlarge GPU. Ignorei na primeira passada — devia ter consultado primeiro.

---

## Bloco 3 — Bugs do nosso código (dívida técnica que vazou)

### 3.1 Defaults agressivos no Dockerfile

**Sintoma:** worker EC2 conectou em `harness-rag-localstack:4566` em vez da SQS real da AWS. Logs mostraram `EndpointConnectionError`.

**Causa:** o `Dockerfile` tinha defaults para dev local com docker-compose:
```dockerfile
ENV AWS_ENDPOINT_URL=http://harness-rag-localstack:4566 \
    AWS_ACCESS_KEY_ID=test \
    AWS_SECRET_ACCESS_KEY=test
```
Esses defaults sobrescrevem o IAM Role da EC2 — `boto3` prefere env vars sobre Instance Metadata.

**Solução:** remover os 3 defaults problemáticos do Dockerfile. Dev local segue funcionando porque `docker-compose.yml` já passa as envs explicitamente (commit `14c79a4`).

**Aprendizado:** defaults em Dockerfile devem ser apenas valores neutros (PYTHONUNBUFFERED, PYTHONPATH). Configuração de ambiente (endpoints, credenciais) é responsabilidade de quem orquestra o container. Defaults agressivos viram bombas-relógio quando o container migra entre ambientes.

### 3.2 Fallback hardcoded em código Python

**Sintoma:** mesmo após remover defaults do Dockerfile, worker ainda conectou em `localhost:4566`.

**Causa:** `worker.py`, `producer.py`, `metrics.py` e `metrics_viewer.py` tinham:
```python
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
```
Quando a env não está setada, cai no fallback hardcoded de LocalStack.

**Solução:** trocar fallback pra `None`:
```python
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None
```
`boto3` com `endpoint_url=None` usa endpoint default da AWS real (commits `e89f688`, `7647bde`).

**Aprendizado:** defaults em código Python têm o mesmo problema dos defaults em Dockerfile — escolhas que servem dev viram bugs em prod. Padrão correto: **se a env não está setada explicitamente, usa default público (AWS), não fallback privado (LocalStack)**. Dev local sempre tem que passar a env explícita.

### 3.3 `get_collection` quebra em deploy distribuído

**Sintoma:** worker EC2 lançou `InvalidCollectionException: Collection fia_2026_regulations does not exist`.

**Causa:** `dados/ingestion.py` chamava `client.get_collection(collection_name)`. Em dev local, o producer rodava primeiro e criava a collection no MESMO ChromaDB que o worker depois usava (volume compartilhado no docker-compose). Em deploy distribuído, cada EC2 tem seu próprio `/data/vectorstore` — vazio.

**Solução:** trocar pra `client.get_or_create_collection(collection_name)`. Idempotente — não quebra fluxo local (commit `48e239a`).

**Aprendizado:** suposições implícitas sobre estado compartilhado quebram em distribuído. O fluxo "producer cria collection que worker consome" funcionava só porque dividiam volume de disco. Em arquiteturas onde producer e worker não compartilham storage, cada worker tem que ser idempotente sobre o próprio store.

---

## Bloco 4 — Erros de processo / coordenação (humanos)

### 4.1 `terraform validate` ≠ apply de teste

**Sintoma:** Sessão A escreveu Terraform completo, validou com `terraform validate` + `fmt`, e declarou pronto. Sessão B fez `apply` real e quebrou em 4 lugares diferentes (AMI, IAM, Ollama, Dockerfile vazando).

**Causa:** `terraform validate` checa só sintaxe e referências internas. Não testa contra a API da AWS real, não detecta restrições de IAM, não roda o user_data.

**Solução pra próxima vez:** 1 ciclo de `apply` + `destroy` curto antes de declarar IaC pronto. Mesmo com `worker_count=1` e instância barata, valida o caminho crítico.

**Aprendizado:** o tempo "economizado" por pular o teste real foi pago de volta com juros em debugging na Sessão B (~2 horas vs ~15 min que o ciclo apply/destroy teria custado).

### 4.2 `purge-queue` tem cooldown

**Sintoma:** purguei a fila, esperei rodar producer de novo, comportamento errado — workers idle apesar de mensagens chegarem.

**Causa:** purge-queue tem cooldown de 60 segundos. Se chamar de novo dentro desse período, o segundo purge silenciosamente não faz nada.

**Solução:** esperar 60s entre purges. Se precisar fluxo limpo na demo, melhor publicar fresco em fila vazia em vez de purgar+publicar.

**Aprendizado:** algumas APIs AWS têm rate-limits ou cooldowns não-óbvios. Quando comportamento aparenta "não fez nada", checar se há restrição temporal.

### 4.3 Worker-1 degradada após benchmarks

**Sintoma:** durante a gravação da demo, worker-1 ficou aparentemente travada — não consumiu mensagens em paralelo com workers 2 e 3.

**Causa:** worker-1 foi usada pra rodar os benchmarks (pulled llama3.1:8b + llama3.2:1b, modelos grandes carregaram parcialmente na RAM). t3.medium com 3.7GB RAM ficou apertado. O processo Ollama do container concorria com modelos extra que ficaram no swap.

**Solução cosmética:** workers 2 e 3 (limpas) processaram em paralelo na gravação — paralelismo demonstrado mesmo com 1/3 degradada.

**Aprendizado:** não misturar workloads (benchmark + processamento real) no mesmo host com recursos apertados. Em produção, hosts de benchmark seriam separados dos hosts de workers. Em demo, sempre rodar com hosts "limpos" recém-criados.

### 4.4 Escape de aspas em PowerShell → SSH → Bash → JSON

**Sintoma:** `curl -d '{\"model\":\"...\"}'` via PowerShell-em-cima-de-SSH retornou `{"error":"invalid character ':' in string escape code"}`.

**Causa:** PowerShell preprocessa a string antes de mandar pro SSH; SSH manda pro bash remoto; bash interpreta como argumento de curl. Em 3 camadas de escape de aspas, qualquer engano quebra o JSON.

**Solução:** escrever script localmente, fazer `scp` pra EC2, executar via SSH. Ou usar o CLI nativo (`ollama pull X`) em vez de chamadas HTTP via curl.

**Aprendizado:** quando há mais de 1 camada de escape, escrever script + scp é mais robusto que tentar one-liner inline. Investimento de 2 min em organizar bem evita 20 min de debugging de escape.

### 4.5 Mensagens "duplicadas" na fila (visibility timeout)

**Sintoma:** durante a demo, fila mostrou 9 mensagens visíveis em vez das 6 que o producer publicou.

**Causa:** visibility timeout do SQS é 600s (10 min). Mensagens "in flight" (recebidas mas ainda não deletadas) ficam invisíveis pros outros workers durante esse período. Se o worker que pegou demora ou crasha, a mensagem volta a ficar visível e outro worker pega — gerando reprocessamento.

**Solução:** comportamento esperado, não é bug. Pra demo limpa, esperar fila esvaziar 100% antes de gravar. Ou ajustar visibility timeout em workloads que precisam de garantia "at most once".

**Aprendizado:** SQS Standard é "at least once" — mesma mensagem pode ser entregue múltiplas vezes. Worker tem que ser idempotente sobre reprocessamento (no nosso caso, ChromaDB upsert reescreve o chunk, sem erro). DLQ pega mensagens que foram retried `maxReceiveCount` vezes (3 no nosso caso) — combo SQS+DLQ+idempotência é o padrão de mercado.

---

## Síntese: padrões recorrentes

1. **Defaults pra dev vazam pra prod** (3.1, 3.2): toda config "conveniente" pra desenvolvimento vira armadilha em deploy real. Padrão correto: defaults neutros + envs explícitas em cada ambiente.

2. **Validação sintática ≠ validação semântica** (4.1): ferramentas como `terraform validate` ou `python -m py_compile` só checam estrutura. Testar de verdade requer exercitar contra o ambiente alvo.

3. **Documentação assumida ≠ documentação explícita** (1.3, 1.4): "precisa de chave SSH" + "credenciais expiram" são óbvios pra quem já fez, invisíveis pra quem está fazendo a primeira vez. Documentar pré-requisitos zero-assumption.

4. **Bugs de versão em ferramentas externas existem** (2.1): Ollama 0.24.0 com panic conhecido. Pinning de versão e workarounds documentados pra próximo deploy.

5. **Arquitetura precisa casar com o comportamento real do servidor de inferência** (2.2): paralelismo da aplicação só rende se o servidor não serializa internamente. Lição central do bônus SLM.
