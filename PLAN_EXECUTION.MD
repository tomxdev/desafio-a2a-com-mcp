# Execution Plan

## Objetivo

Entregar dois processos separados e verificáveis, conforme o `PLAN.md`:

1. Um **servidor MCP** em Streamable HTTP na porta 7301 (`/mcp`), com três tools (`listar_salas`, `consultar_disponibilidade`, `reservar_sala`), um resource (`politica://uso`), os dois tipos de erro e o ciclo completo de MRTR na tool de reserva.
2. Um **agente** que é host MCP por dentro (descobre e chama as tools do próprio servidor por HTTP) e servidor **A2A v1.0** por fora, na porta 7300 (`/a2a` + `/.well-known/agent-card.json`), com Task passando por `TASK_STATE_INPUT_REQUIRED`.
3. A **ponte** entre os dois: o `input_required`/`requestState` do MCP vira pausa da Task A2A, e a resposta do cliente A2A vira retry do `tools/call` com id de JSON-RPC novo.
4. Propagação do `traceparent` do cliente A2A até o servidor MCP, registrada no stderr.
5. `README.md` com as quatro seções exigidas.
6. `python validador/validar.py` passando nas 36 verificações, com código de saída 0.

## Contexto

O starter entrega apenas dados e contrato; não há código de aplicação para estender. `dados/`, `validador/` e `exemplos/` são **imutáveis**.

O que torna o desafio difícil é o **estado através de dois protocolos sem sessão**:

- O MCP resolve com **MRTR**: quando a tool precisa de mais informação, ela não pergunta — ela **termina a resposta** com `resultType: "input_required"`, um `inputRequests` (elicitation em *form mode*) e um `requestState` opaco. O cliente responde repetindo o `tools/call` **com id novo**, levando `inputResponses` + o `requestState` ecoado sem modificação.
- O A2A resolve com a **Task**, que tem identidade (`id`/`contextId`), estado (`TASK_STATE_*`) e produto (`artifacts`).
- A ponte é o agente: ele traduz `input_required` → `TASK_STATE_INPUT_REQUIRED`, guarda o `requestState` ligado à Task (sem nunca abri-lo nem expô-lo), e ao receber a continuação repete o request MCP original.

Erros clássicos a evitar (explícitos no enunciado):

- Tratar MRTR como callback. Não existe canal de volta no transporte stateless.
- Usar `elicitation_callback` no cliente MCP do SDK: o cliente responderia sozinho, a Task nunca pausaria e metade do desafio evapora. O agente precisa ver o `input_required` **cru**.
- Reaproveitar o id do JSON-RPC no retry.
- `requestState` sem assinatura (base64 puro): passa no caminho feliz e reprova na verificação.

### Stack e decisões já tomadas

| Decisão | Valor | Motivo |
| --- | --- | --- |
| Linguagem | Python 3.10+ (ambiente local: 3.13.1) | As fixtures de `exemplos/wire/` foram capturadas de uma implementação Python |
| SDK MCP | `mcp==2.2.0` (SDK v2, spec 2026-07-28) | Tem `InputRequiredResult`, `Resolve`/`Elicit` e `RequestStateSecurity` de primeira classe |
| Camada A2A | JSON-RPC escrito à mão sobre Starlette + uvicorn | O validador compara a forma exata do card, da mensagem de pausa e dos artifacts; controle byte a byte vale mais que abstração |
| HTTP client do agente | O cliente do próprio `mcp` SDK, com `allow_input_required=True` | Exigido para ver o `input_required` cru |
| Persistência | Reservas e Tasks em memória; `requestState` selado (viaja no token) | Enunciado: reservas não sobrevivem a restart, `requestState` sobrevive |
| Gitflow | `develop` a partir de `main`; `feature/<fase>` → PR → `develop`; ao final `develop` → `main` | Regra de entrega |

## Requisitos e restrições

### Não negociáveis

- **Dois processos separados.** O agente fala com o servidor MCP por HTTP, como cliente MCP de verdade. Importar a função da tool no agente descaracteriza a entrega.
- **O agente não implementa regra de negócio de sala.** Conflito, política e alternativas são decisão do servidor MCP.
- **Nada de sessão.** Nenhum lado infere versão, capabilities ou contexto de request anterior.
- **O `requestState` é opaco para o agente:** guardar, ecoar, nunca abrir nem interpretar.
- **Sem LLM** no caminho de execução; sem dependência de SDK de provedor no `pyproject.toml`.
- `dados/`, `validador/` e `exemplos/` **não podem ser alterados**.
- Versões travadas no `pyproject.toml`.
- Estrutura do starter mantida: `servidor-mcp/` e `agente/` preenchidas; scripts de apoio podem ficar na raiz.

### Portas e caminhos (padrões obrigatórios, parametrizáveis por env)

- Agente: `7300`, JSON-RPC em `/a2a`, card em `/.well-known/agent-card.json`
- Servidor MCP: `7301`, Streamable HTTP em `/mcp`

### Mensagens de erro (fonte única de verdade, texto exato)

| Situação | Mensagem |
| --- | --- |
| Sala inexistente | `Sala inexistente: <id informado>` |
| Fora da janela | `Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00` |
| Duração > 2h | `Duracao acima do limite: a politica permite no maximo 2 horas` |
| Intervalo invertido/vazio | `Intervalo invalido: fim deve ser posterior a inicio` |
| Conflito sem alternativa | `Sem alternativas disponiveis no intervalo` |

Prefixo do SDK (`Error executing tool <nome>:`) é aceito; texto diferente não é.

### Códigos de erro de protocolo

| Situação | Código | HTTP |
| --- | --- | --- |
| `_meta` sem `protocolVersion` ou sem `clientCapabilities` | `-32602` | 400 |
| Elicitation exigida de cliente sem capability de form | `-32021` + `data.requiredCapabilities` | 400 |
| `requestState` adulterado ou expirado | `-32602` | — |
| `resources/read` de URI inexistente | `-32602` | — |
| Tool inexistente | `-32602` **ou** `isError: true` | — |
| Header que não bate com o corpo | `-32020` | — |

### Regras de domínio

- Janela 08:00–20:00 (-03:00); duração máxima 2h; sem sobreposição na mesma sala.
- **Alternativas:** salas livres no intervalo, com capacidade **≥** à da sala pedida, no máximo **três**, ordenadas por capacidade crescente e, em empate, por id alfabético.
- Nenhuma regra depende da data de hoje; reservar no passado é permitido.
- Ordem de validação (importante para o validador): **sala existe → `fim > inicio` → janela → duração → conflito**.

### Formatos fixos do A2A

- Pedido: `reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>`
- Continuação: `escolha=<id da sala>` ou `escolha=recusar`
- Mensagem de pausa: exatamente `alternativas: <ids separados por virgula e espaco>`, sem prefixo nem saudação, na ordem do enum.

### Mapa das 36 verificações do validador

| # | O que verifica | Fase |
| --- | --- | --- |
| 1, 2 | `tools/list` com as três tools; `inputSchema` de objeto | 3 (parcial), 4, 6 |
| 3 | `listar_salas`: `structuredContent` == JSON do bloco de texto | 3 |
| 4, 5 | `_meta` faltando → `-32602` + HTTP 400 | 3 |
| 6 | Tool inexistente recusada | 4 |
| 7, 8 | `resources/read` da política e de URI inexistente | 5 |
| 9 | Sala inexistente → `isError` com mensagem exata | 6 |
| 10, 11, 12 | Janela, duração, intervalo invertido | 4 |
| 13, 14 | `input_required` com 1 `inputRequest`, form mode, enum na ordem | 7 |
| 15 | Sem capability → `-32021` + HTTP 400 | 8 |
| 16 | Retry conclui a reserva | 8 |
| 17 | `requestState` adulterado → `-32602` | 8 |
| 18 | Argumentos adulterados no retry não tomam efeito | 8 |
| 19 | `decline` conclui sem reservar e sem `isError` | 8 |
| 20 | Conflito sem alternativa → mensagem exata | 7 |
| 21, 22, 23 | Agent Card, interface JSON-RPC v1.0, skill `reservar-sala` | 10 |
| 24, 25, 26 | Task COMPLETED, artifact `reserva` com `politica`, `GetTask` | 10 |
| 27, 28 | Pausa em `TASK_STATE_INPUT_REQUIRED` + linha de alternativas | 11 |
| 29 | Escolha fora do enum mantém a pausa | 11 |
| 30 | Continuação conclui na sala escolhida | 11 |
| 31 | `SendMessage` em Task terminal é recusado | 10 |
| 32 | `escolha=recusar` → `TASK_STATE_CANCELED` | 11 |
| 33 | Duas Tasks pausadas simultaneamente, sem trocar `requestState` | 11 |
| 34 | `requestState` não vaza em resposta A2A | 11 |
| 35 | Sala inexistente → `TASK_STATE_FAILED` com a mensagem da tool | 10 |
| 36 | Determinismo: mesma pausa duas vezes | 11 |

Fora do validador, cobertos pelo "Fluxo do avaliador" (Fase 12): `requestState` válido após restart do servidor MCP; `traceparent` no stderr; `tools/list` antes do primeiro `tools/call`; ids de JSON-RPC diferentes entre request inicial e retry.

## Estratégia de execução

O plano cresce de dentro para fora, exatamente na ordem sugerida pelo enunciado:

```
Fase 1 investigação ──► Fase 2 scaffolding ──► Fase 3 servidor MCP base
                                                      │
        ┌─────────────────────────────────────────────┤
        ▼                    ▼                        ▼
   Fase 4 regras        Fase 5 resource         (transporte pronto)
        │                    │
        └──────► Fase 6 reservar (feliz) ──► Fase 7 MRTR ──► Fase 8 requestState
                                                                    │
                                                    Fase 9 agente host MCP (sem A2A)
                                                                    │
                                                    Fase 10 agente servidor A2A
                                                                    │
                                                    Fase 11 a ponte
                                                                    │
                        Fase 12 validação 36/36 ──► Fase 13 README ──► Fase 14 entrega
```

Dependências principais:

- **Fases 4 e 5 são independentes entre si** e só dependem da Fase 3.
- A Fase 7 depende da Fase 6 (caminho feliz) e da Fase 4 (regra de alternativas).
- A Fase 9 depende do servidor completo (Fase 8) porque o ciclo MRTR é exercitado de ponta a ponta.
- As Fases 10 e 11 são separadas de propósito: a Fase 10 entrega um agente A2A que funciona no caminho feliz e no caminho de falha; a Fase 11 acrescenta **só** a ponte.
- A Fase 1 é de **investigação pura**: ela existe porque alguns comportamentos do SDK precisam ser confirmados antes de escolher o desenho do servidor (ver Riscos).

### Riscos e pontos de investigação

| ID | Risco | Situação |
| --- | --- | --- |
| R1 | O SDK pode **não** rejeitar sozinho `_meta` sem `protocolVersion`/`clientCapabilities` | ✅ **Resolvido na Fase 1:** o SDK rejeita nativamente com `-32602` + HTTP 400. Middleware próprio **não é necessário** |
| R2 | `RequestStateSecurity.ephemeral()` (default) gera chave por processo e quebra após restart | ✅ **Resolvido na Fase 1:** `RequestStateSecurity(keys=[segredo], ttl=...)` sobrevive ao restart, comprovado |
| R3 | A verificação 18 depende de o SDK vincular o token aos argumentos originais | ✅ **Resolvido na Fase 1:** o boundary faz *request binding*; retry com argumentos divergentes → `-32602` |
| R4 | O `-32021` precisa sair com `data.requiredCapabilities` | ✅ **Resolvido na Fase 1:** o resolver produz `-32021` + `data.requiredCapabilities` + HTTP 400, nativamente |
| R5 | `python3` não existe no Windows; o validador do enunciado usa `python3` | Aberto — Fase 13: README documenta `python` e `python3` |
| R6 | Caminhos longos no Windows (limite de 260 chars) quebram `venv`/`ensurepip` | ⚠️ **Confirmado na Fase 1** (`WinError 206` no scratchpad, 241 chars). O projeto está em caminho longo — Fase 2 valida o venv **no próprio diretório do projeto** antes de qualquer outra coisa |
| R7 | Header `Mcp-Name`/`Mcp-Method` que não bate com o corpo é recusado com `-32020` | ✅ **Resolvido na Fase 9:** o cliente do SDK monta os headers corretamente; o servidor recusa divergência nos dois campos, confirmado com teste negativo |
| R8 | A verificação 34 varre **todas** as respostas A2A procurando os 40 primeiros caracteres do `requestState` | ✅ **Resolvido na Fase 11:** o estado pausado fica fora de `Task.como_json()`, com teste travando |
| R9 | O validador exige os dois processos **recém-iniciados**; rodar duas vezes seguidas produz falsos negativos | Aberto — Fase 2 (script de subida) e todas as fases de validação |
| R11 | O Git Bash converte um valor de env como `/mcp` em caminho do Windows | ⚠️ **Descoberto na Fase 8.** Os caminhos saíram do `.env.example`; o servidor recusa caminho sem `/` inicial e aponta `MSYS_NO_PATHCONV=1` |
| R10 | Um `GET` em `/mcp` abre um stream SSE e **trava** o cliente | ⚠️ **Descoberto na Fase 1.** Em teste manual usar sempre `POST`; nunca `curl` sem `-X POST` |

### Decisões arquiteturais

Todas fechadas na Fase 1, com evidência em "Achados da Fase 1".

- **D1 — desenho do MRTR no servidor: RESOLVER.** `Annotated[ElicitationResult[Escolha], Resolve(escolha_de_sala)]` reproduz a fixture 03 campo a campo, incluindo a chave `__main__:escolha_de_sala`, e entrega `-32021`, *request binding* e selo do `requestState` de graça. Restrição herdada: uma tool que usa `Resolve(...)` **não pode** devolver `InputRequiredResult` do corpo — o SDK trata isso como erro de autoria.
- **D2 — TTL do `requestState`: 900 s (15 min).** Dentro da faixa de 5 a 30 minutos exigida.
- **D3 — estrutura de pacotes:** `servidor-mcp/` e `agente/` mantêm o hífen (estrutura obrigatória do starter) e os processos são executados por caminho de arquivo (`python "servidor-mcp/servidor.py"`), sem import entre as pastas.
- **D4 — grafia da capability do agente:** o cliente do SDK declara `{"elicitation": {"form": {}, "url": {}}}` e **sobrescreve** qualquer valor passado em `meta=`. O `form` exigido está declarado; o `url` extra é imposto pelo SDK. Limitação a documentar no README (Fase 13), conforme a regra do enunciado sobre limitações reais do SDK.

### Achados da Fase 1 (evidência)

**Dependências reais de `mcp==2.2.0`** (para travar na Fase 2): `mcp-types==2.2.0`, `starlette==1.7.0`, `uvicorn==0.54.0`, `pydantic==2.13.5`, `cryptography==50.0.1`, `jsonschema==4.26.0`, `anyio==4.15.1`. Atenção: o SDK usa **`httpx2==2.13.1`**, não `httpx`.

**`_meta` incompleto (R1)** — nativo, sem middleware:

```
http 400 | code -32602 | "params._meta is missing the required envelope key(s): io.modelcontextprotocol/protocolVersion"
http 400 | code -32602 | "params._meta is missing the required envelope key(s): io.modelcontextprotocol/clientCapabilities"
```

**Capability faltando (R4)** — idêntico à fixture 06:

```
http 400 | {"code": -32021,
            "message": "Client did not declare the form elicitation capability required by resolver '__main__:escolha_de_sala'",
            "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}}
```

**`requestState` (R2/R3)** — `RequestStateSecurity(keys=[bytes.fromhex(SEGREDO)], ttl=900.0)`:

```
token adulterado             -> http 400 | -32602 "Invalid or expired requestState" (reason: invalid_request_state)
retry com args divergentes   -> http 400 | -32602 "Invalid or expired requestState"   (request binding)
retry honesto                -> http 200 | complete, reserva criada
retry APOS RESTART do processo, mesma chave -> http 200 | complete, reserva criada
duas pausas simultaneas      -> tokens diferentes
```

**Mensagens de erro exatas** — exigem `ToolError` (de `mcp.server.mcpserver.exceptions`). Uma `ValueError` comum é tratada como *crash* e o texto **não** chega ao cliente:

```
ValueError  -> "Error executing tool reservar_sala"                                    (mensagem perdida)
ToolError   -> "Error executing tool reservar_sala: Sala inexistente: sala-delorean"   (prefixo aceito pelo enunciado)
ToolError dentro do resolver -> "Error executing tool reservar_sala: Sem alternativas disponiveis no intervalo"
```

**`structuredContent` == JSON do bloco de texto (verificação 3)** — só quando a tool devolve um **modelo/dict**. Devolver uma `list` produz `structuredContent = {"result": [...]}` enquanto o bloco de texto traz os itens concatenados, e a igualdade falha. A tool precisa devolver um modelo pydantic (ex.: `SalasOut(salas=[...])`).

**`decline` (verificação 19)** — exige o **union**: `Annotated[ElicitationResult[Escolha], Resolve(...)]`. Com a anotação desembrulhada (`Annotated[Escolha, ...]`), o SDK levanta `ToolError` e a chamada vira `isError: true`, reprovando a verificação. Com o union, `decline` cai em `DeclinedElicitation()` e a tool conclui normalmente.

**Enum dinâmico** — `Elicit(message, schema: type[T])` exige um **tipo**; o enum restrito às alternativas calculadas sai de `pydantic.create_model("Escolha", sala=(Literal[tuple(alternativas)], Field(description=...)))`. Isso reproduz `{"description", "enum", "title", "type"}` exatamente como a fixture 03.

**O resolver roda em toda rodada** (inicial e retry). Ele recebe os argumentos da tool por nome, então **também** precisa lidar com sala inexistente antes de calcular alternativas.

**Lado do agente** — o achado mais importante da fase:

| Configuração do `Client` | Resultado |
| --- | --- |
| **sem** `elicitation_callback` | A capability não é declarada → o servidor responde `-32021`. Inviável |
| **com** `elicitation_callback` + `client.call_tool(...)` | O callback responde sozinho, o ciclo fecha e a Task nunca pausa. É a armadilha do enunciado |
| **com** `elicitation_callback` + `client.session.call_tool(..., allow_input_required=True)` | ✅ Devolve `InputRequiredResult` **cru**, e o callback **nunca é invocado** |

O caminho correto é o terceiro: registrar o callback apenas para **declarar a capability**, e dirigir o ciclo pela sessão de baixo nível. Confirmado também que o retry sai com **id de JSON-RPC diferente** do request inicial (`tools/call id=3` → `tools/call id=4`), e que o `traceparent` passado em `meta={"traceparent": ...}` chega ao `_meta` do servidor.

**Log em stderr** — `MCPServer(..., middleware=[log_middleware])`, com `ServerMiddleware` no formato `(ctx, call_next)`. `ctx.method`, `ctx.request_id` e `ctx.params["_meta"]` dão tudo que o enunciado exige:

```
[mcp] metodo=tools/call id=3 traceparent=00-4bf9...4736-00f0...02b7-01 caps={'elicitation': {'form': {}, 'url': {}}}
```

**Também confirmado nativamente:** `resources/read` de URI inexistente → `-32602`; `tools/call` de tool inexistente → `isError: true` com `"Unknown tool: <nome>"` (aceito pela verificação 6).

---

# Fase 1 — Investigação do SDK e decisões de arquitetura

## Objetivo

Confirmar, com código rodando, que o `mcp==2.2.0` entrega o que o desafio exige, e fechar as decisões D1, D2 e D3. Nenhuma linha do entregável é escrita nesta fase — o produto é conhecimento registrado.

## Dependências

Nenhuma.

## Arquivos envolvidos

- Scratchpad da sessão (scripts descartáveis) — **não** versionado
- `PLAN_EXECUTION.MD` (registro das decisões)

## Tarefas

- [x] criar um ambiente virtual descartável no scratchpad e instalar `mcp==2.2.0`
- [x] listar os símbolos relevantes: `InputRequiredResult`, `Resolve`, `Elicit`, `ElicitationResult`, `RequestStateSecurity`, `MCPServer.streamable_http_app`, `Client.call_tool`
- [x] subir um servidor mínimo com uma tool que devolve `InputRequiredResult` e confirmar a forma do JSON na rede contra `exemplos/wire/03-tools-call-conflito-input-required.json`
- [x] **R1:** enviar um `tools/call` sem `io.modelcontextprotocol/protocolVersion` no `_meta` e registrar o código JSON-RPC e o status HTTP devolvidos pelo SDK sem intervenção
- [x] **R1:** repetir sem `io.modelcontextprotocol/clientCapabilities`
- [x] **R3:** completar um ciclo MRTR e reenviar o retry com **argumentos diferentes** dos originais; registrar se o SDK rejeita o token, ignora os argumentos ou aceita os adulterados
- [x] **R2:** confirmar a assinatura de `RequestStateSecurity(keys=..., ttl=...)` e que um token selado com chave fixa é aceito por um processo novo
- [x] **R4:** enviar o mesmo conflito com `clientCapabilities: {}` e confirmar `-32021` com `data.requiredCapabilities` e HTTP 400
- [x] confirmar que `Client.call_tool(..., allow_input_required=True)` devolve o `InputRequiredResult` cru, sem disparar callback
- [x] confirmar que o cliente do SDK envia os headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name`, e como injetar `traceparent` no `_meta`
- [x] registrar as respostas de D1, D2 e D3 na seção "Decisões arquiteturais" deste plano

## Critérios de aceite

- R1, R2, R3 e R4 respondidos com evidência (trecho de saída real colado no plano);
- D1, D2 e D3 decididos e registrados;
- nenhum arquivo do repositório criado ou alterado.

## Validação

- Execução dos scripts de sondagem no scratchpad, com saída colada no plano;
- `git status` limpo (exceto `PLAN.md`/`PLAN_EXECUTION.MD`).

## Resultado esperado

O plano passa a conter as decisões que a Fase 3 e a Fase 8 consomem, e o risco de descobrir uma limitação do SDK no meio da implementação cai a quase zero.

---

# Fase 2 — Scaffolding do repositório e gitflow

## Objetivo

Deixar o esqueleto do projeto pronto para receber código: dependências travadas, variáveis de ambiente, scripts de subida dos dois processos, e o fluxo de branches criado.

## Dependências

Fase 1 (decisão D3 sobre estrutura de pacotes).

## Arquivos envolvidos

- `pyproject.toml` (raiz, novo)
- `.env.example` (raiz, novo)
- `.gitignore` (existente — conferir `.env`, `.venv/`, `__pycache__/`)
- `servidor-mcp/` e `agente/` (estrutura de diretórios)
- `subir-mcp.ps1`, `subir-agente.ps1` (ou equivalentes `.sh`) na raiz

## Tarefas

- [x] **primeiro de tudo (R6):** criar o venv dentro do próprio diretório do projeto e confirmar que `ensurepip` funciona; se der `WinError 206`, decidir e registrar a alternativa antes de seguir
- [x] criar a branch `develop` a partir de `main` e a branch `feature/scaffolding`
- [x] criar `pyproject.toml` na raiz com `requires-python = ">=3.10"` e as dependências travadas, usando as versões confirmadas na Fase 1: `mcp==2.2.0`, `starlette==1.7.0`, `uvicorn==0.54.0` (o SDK já arrasta `mcp-types`, `pydantic`, `cryptography`, `jsonschema` e **`httpx2`** — não declarar `httpx`)
- [x] confirmar que nenhuma dependência de provedor de LLM entra no `pyproject.toml`
- [x] criar `.env.example` com `REQUEST_STATE_SECRET=`, `MCP_PORT=7301`, `AGENTE_PORT=7300`, `MCP_URL=http://127.0.0.1:7301/mcp` e um comentário com o comando de geração do segredo
- [x] conferir que `.gitignore` já cobre `.env`, `.venv/` e `__pycache__/`
- [x] criar os scripts de subida dos dois processos, com caminhos entre aspas (R6) e leitura do `.env`
- [x] criar um venv do projeto e instalar as dependências a partir do `pyproject.toml`
- [x] commit por contexto (4 commits)
- [x] push de `develop` e `feature/scaffolding` para o remoto
- [x] merge de `feature/scaffolding` em `develop` (`--no-ff`)
- [x] **excecao registrada:** sem PR nesta fase — ver "Nota de processo" abaixo

### Nota de processo (decidida na execução)

O `gh` só foi autenticado depois de o merge em `develop` já ter sido feito e
publicado, então um PR `feature/scaffolding` → `develop` nasceria vazio. Rebobinar
`develop` exigiria um force-push, descartado por ser destrutivo. **Esta fase é a
única sem PR próprio**; o scaffolding passa por revisão no PR final `develop` → `main`.

**Regra para todas as fases seguintes:** publicar a branch da fase e abrir o PR
**antes** de mergear. O merge é aplicado pelo `gh pr merge`, nunca localmente.

O `gh` não está no `PATH` dos shells já abertos: usar o caminho completo
`"/c/Program Files/GitHub CLI/gh.exe"`.

## Critérios de aceite

- `pip install -e .` (ou equivalente) funciona a partir de um clone limpo;
- versões travadas, sem faixas abertas;
- `dados/`, `validador/` e `exemplos/` intocados;
- branch `develop` existe no remoto com o scaffolding mergeado (sem PR nesta fase, conforme a nota de processo).

## Validação

- `python -c "import mcp, starlette, uvicorn; print('ok')"`
- `git diff --stat main..develop -- dados validador exemplos` deve vir vazio

## Resultado esperado

Repositório com dependências instaláveis, variáveis de ambiente documentadas e fluxo de branches ativo. Ainda não há processo que suba.

---

# Fase 3 — Servidor MCP: transporte, `_meta`, log e `listar_salas`

## Objetivo

Ter o servidor MCP de pé na 7301 em Streamable HTTP, respondendo `tools/list` e `tools/call` de `listar_salas`, rejeitando `_meta` incompleto e registrando cada request no stderr.

## Dependências

Fases 1 (R1) e 2.

## Arquivos envolvidos

- `servidor-mcp/servidor.py` (novo — composição e transporte)
- `servidor-mcp/dominio.py` (novo — carga de `dados/*.json` e estado em memória)
- `servidor-mcp/log.py` (novo — log estruturado em stderr)

## Tarefas

- [x] localizar e carregar `dados/salas.json` e `dados/reservas.json` em memória, sem escrever de volta no disco
- [x] instanciar `MCPServer("central-de-salas", version="1.0.0", middleware=[log_middleware])` declarando as capabilities de `tools` e `resources`
- [x] expor o app com `streamable_http_app(streamable_http_path="/mcp", stateless_http=True)` e servir na porta 7301 (parametrizável por env, padrão 7301)
- [x] implementar `listar_salas` sem parâmetros, devolvendo um **modelo pydantic** (não uma `list`), para que `structuredContent` e o bloco de texto sejam o mesmo JSON — ver o achado da Fase 1 sobre a verificação 3
- [x] implementar `log_middleware(ctx, call_next)` no formato `ServerMiddleware`, registrando em stderr `ctx.method`, `ctx.request_id` e o `traceparent` de `ctx.params["_meta"]`
- [x] confirmar (R1 já resolvido) que o SDK rejeita nativamente `_meta` sem `protocolVersion`/`clientCapabilities` com `-32602` + HTTP 400, **sem** middleware próprio
- [x] confirmar que a rejeição não infere versão nem capabilities de request anterior
- [x] commit por contexto (3 commits), PR `feature/servidor-mcp-base` → `develop`, merge

## Critérios de aceite

- Servidor sobe na 7301 e responde `tools/list`;
- verificações **3, 4 e 5** do validador passam;
- verificações 1 e 2 passam parcialmente (só `listar_salas` existe — falham até a Fase 6);
- cada request aparece no stderr com método, id e `traceparent`.

## Validação

- `python "servidor-mcp/servidor.py"` sobe sem erro
- `python validador/validar.py --mcp http://localhost:7301` → checks 3, 4, 5 = PASS
- Inspeção manual do stderr com um `curl` carregando `traceparent` no `_meta`

## Resultado esperado

Um servidor MCP mínimo, porém protocolarmente correto: transporte certo, envelope stateless respeitado, erros de `_meta` no lugar e observabilidade funcionando.

---

# Fase 4 — Regras de política e `consultar_disponibilidade`

## Objetivo

Centralizar as regras de domínio no servidor MCP (janela, duração, intervalo, sobreposição, alternativas) e expor `consultar_disponibilidade` com os quatro erros de execução nas mensagens exatas.

## Dependências

Fase 3.

## Arquivos envolvidos

- `servidor-mcp/regras.py` (novo)
- `servidor-mcp/servidor.py` (alterado)
- `servidor-mcp/dominio.py` (alterado)

## Tarefas

- [x] implementar o parsing de ISO 8601 com offset `-03:00`, sem depender da data de hoje
- [x] implementar a validação de sala existente, levantando **`ToolError`** (de `mcp.server.mcpserver.exceptions`) com a mensagem `Sala inexistente: <id informado>` — uma `ValueError` comum perde o texto e reprova o validador
- [x] implementar a validação `fim > inicio`, com a mensagem exata
- [x] implementar a validação de janela 08:00–20:00, com a mensagem exata
- [x] implementar a validação de duração máxima de 2 horas, com a mensagem exata
- [x] fixar a **ordem** de validação: sala → intervalo invertido → janela → duração
- [x] implementar a detecção de sobreposição por sala
- [x] implementar o cálculo de alternativas: livres no intervalo, capacidade ≥ à da sala pedida, máximo 3, ordenadas por capacidade crescente e por id em empate
- [x] implementar `consultar_disponibilidade(sala, inicio, fim)` devolvendo `structuredContent` com o estado de disponibilidade e as reservas em conflito, além do bloco de texto
- [x] garantir que `consultar_disponibilidade` aplica as mesmas validações e devolve os mesmos erros de execução da reserva
- [x] confirmar o comportamento para tool inexistente: o SDK devolve **`isError: true`** com `"Unknown tool: <nome>"`, nunca `-32602`. O validador aceita os dois
- [x] escrever testes unitários das regras (janela, duração, intervalo, sobreposição, ordenação de alternativas)
- [x] commit por contexto, PR `feature/regras-e-disponibilidade` → `develop`, merge

## Critérios de aceite

- Verificações **6, 10, 11 e 12** do validador passam;
- testes unitários das regras passando;
- nenhuma regra de domínio duplicada fora de `regras.py`.

## Validação

- `python -m pytest servidor-mcp/tests` (ou runner escolhido) verde
- `python validador/validar.py --mcp http://localhost:7301` → checks 6, 10, 11, 12 = PASS
- Verificação manual da ordenação de alternativas com um intervalo construído à mão

## Resultado esperado

Todas as regras de negócio vivem em um módulo só, com as mensagens exatas do enunciado, e a tool de consulta já expõe esse comportamento.

---

# Fase 5 — Resource `politica://uso`

## Objetivo

Expor a política de uso como resource MCP e tratar URI inexistente como erro de protocolo.

## Dependências

Fase 3. Independente da Fase 4.

## Arquivos envolvidos

- `servidor-mcp/servidor.py` (alterado)
- `dados/politica-de-uso.md` (somente leitura)

## Tarefas

- [x] registrar o resource na URI `politica://uso` devolvendo o conteúdo de `dados/politica-de-uso.md` com `mimeType: text/markdown`
- [x] garantir que o conteúdo devolvido preserva a primeira linha `versao: 2026-11-01`
- [x] fazer `resources/read` de URI desconhecida devolver `-32602` (nunca `contents` vazio)
- [x] confirmar que o request de `resources/read` também é registrado no stderr

## Critérios de aceite

- Verificações **7 e 8** do validador passam;
- a resposta bate com `exemplos/wire/05-resources-read-politica.json` nos campos que importam (`uri`, `mimeType`, `text`).

## Validação

- `python validador/validar.py --mcp http://localhost:7301` → checks 7, 8 = PASS
- `curl` de `resources/read` comparado manualmente com a fixture 05

## Resultado esperado

O agente já tem de onde ler a versão da política que precisará aparecer no artifact da Task.

---

# Fase 6 — `reservar_sala`: caminho feliz

## Objetivo

Criar reservas quando o intervalo está livre e dentro da política, com o `structuredContent` no formato do contrato. Sem MRTR ainda.

## Dependências

Fases 4 e 5.

## Arquivos envolvidos

- `servidor-mcp/servidor.py` (alterado)
- `servidor-mcp/dominio.py` (alterado — criação de reserva em memória)

## Tarefas

- [x] implementar a geração de id sequencial de reserva no padrão `res-000N`, continuando a partir das reservas do arquivo
- [x] implementar `reservar_sala(sala, inicio, fim, responsavel)` no caminho livre, gravando a reserva em memória
- [x] garantir que a reserva criada é visível para as consultas seguintes do mesmo processo
- [x] devolver `structuredContent` com `reserva`, `reservado`, `sala`, `inicio`, `fim`, `responsavel`, `politica` e `motivo`, e o mesmo JSON no bloco de texto
- [x] preencher `politica` com a versão lida da primeira linha de `dados/politica-de-uso.md`
- [x] aplicar em `reservar_sala` as mesmas validações da Fase 4, com as mensagens exatas
- [x] conferir que as três tools têm `inputSchema` que é objeto JSON Schema válido
- [x] commit por contexto, PR `feature/reservar-caminho-feliz` → `develop`, merge

## Critérios de aceite

- Verificações **1, 2 e 9** do validador passam;
- a resposta bate com `exemplos/wire/02-tools-call-livre.json` nos campos do contrato;
- uma segunda `consultar_disponibilidade` no mesmo intervalo enxerga a reserva recém-criada.

## Validação

- `python validador/validar.py --mcp http://localhost:7301` → checks 1 a 12 = PASS
- Sequência manual `reservar_sala` → `consultar_disponibilidade` no mesmo intervalo

## Resultado esperado

O servidor MCP está completo exceto pelo MRTR: 12 das 20 verificações de MCP passam.

---

# Fase 7 — MRTR: `input_required` com elicitation em form mode

## Objetivo

Fazer o conflito de horário devolver `resultType: "input_required"` com uma única elicitation em form mode restringindo a escolha às alternativas calculadas — e nenhum `input_required` quando não houver alternativa.

## Dependências

Fases 4 e 6, e a decisão **D1** da Fase 1.

## Arquivos envolvidos

- `servidor-mcp/servidor.py` (alterado)
- `servidor-mcp/regras.py` (alterado, se o cálculo de alternativas precisar de ajuste)

## Tarefas

- [x] implementar o resolver `escolha_de_sala(sala, inicio, fim)`, injetado na tool como `Annotated[ElicitationResult[Escolha], Resolve(escolha_de_sala)]` (D1); o **union** é obrigatório, senão `decline` vira `isError` e reprova a verificação 19
- [x] tratar sala inexistente **dentro do resolver** também: ele roda antes do corpo da tool e em todas as rodadas
- [x] gerar o enum dinâmico com `pydantic.create_model("Escolha", sala=(Literal[tuple(alternativas)], Field(description="Sala alternativa escolhida")))`
- [x] confirmar que sai **exatamente uma** entrada em `inputRequests`
- [x] garantir que a entrada é um `elicitation/create` com `mode: "form"` e a mensagem `A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.`
- [x] garantir que o `requestedSchema` é **plano**: um objeto com a propriedade `sala` do tipo string, restrita às alternativas, e `required: ["sala"]`
- [x] garantir que, com duas ou mais alternativas, o schema traz `enum` na ordem definida pela regra (capacidade crescente, id em empate)
- [x] tratar o caso de alternativa única (`enum` de um item ou `const`, ambos aceitos)
- [x] fazer o conflito **sem nenhuma alternativa** levantar `ToolError("Sem alternativas disponiveis no intervalo")` dentro do resolver, sem elicitation
- [x] confirmar que o pedido em conflito **não cria reserva** e não muda o estado em memória
- [x] commit por contexto, PR `feature/mrtr-input-required` → `develop`, merge

## Critérios de aceite

- Verificações **13, 14 e 20** do validador passam;
- a resposta bate com `exemplos/wire/03-tools-call-conflito-input-required.json` em `resultType`, `mode`, `requestedSchema` e presença de `requestState`;
- nenhuma tentativa de o servidor iniciar request para o cliente (sem callback, sem canal de volta).

## Validação

- `python validador/validar.py --mcp http://localhost:7301` → checks 13, 14, 20 = PASS
- `curl` com o corpo de `exemplos/wire/03-...json` comparado campo a campo com a fixture
- Inspeção do stderr: nenhum erro de "transporte sem canal de volta"

## Resultado esperado

O servidor já sabe interromper a resposta pedindo informação. O `requestState` ainda não é confiável — é o assunto da fase seguinte.

---

# Fase 8 — `requestState` protegido, retry e gate de capability

## Objetivo

Tornar o `requestState` íntegro, expirável e independente do processo, concluir a reserva no retry, e recusar com `-32021` o cliente que não declarou elicitation em form mode.

## Dependências

Fase 7, e as respostas de **R2, R3, R4 e D2** da Fase 1.

## Arquivos envolvidos

- `servidor-mcp/servidor.py` (alterado)
- `servidor-mcp/estado.py` (novo, se o selo do `requestState` for montado à mão)
- `.env.example` (alterado)

## Tarefas

- [x] ler `REQUEST_STATE_SECRET` do ambiente e falhar a subida com mensagem clara se ausente ou com menos de 32 bytes
- [x] passar `request_state_security=RequestStateSecurity(keys=[bytes.fromhex(segredo)], ttl=900.0)` no construtor do `MCPServer`, **nunca** a ephemeral (D2 = 900 s)
- [x] garantir que o `requestState` carrega tudo que o servidor precisa para reconstruir o pedido, e que **nada** é guardado em memória entre o `input_required` e o retry
- [x] implementar o retry: ler `inputResponses` e `requestState` de dentro de `params`, reconstruir o pedido e concluir a reserva
- [x] confirmar (R3 já resolvido) que o *request binding* do boundary rejeita com `-32602` um retry com argumentos divergentes
- [x] confirmar que `requestState` adulterado ou expirado é rejeitado com `-32602`
- [x] confirmar (R4 já resolvido) que o resolver produz `-32021` com `data.requiredCapabilities` e HTTP 400 para cliente sem `elicitation.form`
- [x] tratar `DeclinedElicitation()` e `CancelledElicitation()` como conclusão normal: `resultType: "complete"`, sem `isError`, com `reservado: false` e `motivo: "recusado"`
- [x] garantir que nenhum segredo está hardcoded no código
- [x] commit por contexto, PR `feature/request-state-protegido` → `develop`, merge

## Critérios de aceite

- Verificações **15, 16, 17, 18 e 19** passam — e com isso as **20 primeiras** verificações passam;
- um retry apresentado **depois de reiniciar o processo do servidor** conclui a reserva;
- trocar um caractere do `requestState` produz `-32602`, nunca erro interno nem processamento silencioso;
- busca por segredo no código não encontra nada.

## Validação

- `python validador/validar.py --mcp http://localhost:7301` → checks 1 a 20 = PASS
- Teste manual de restart: capturar `requestState` de um conflito, matar e subir o servidor de novo, enviar o retry, conferir a reserva concluída
- Teste manual de adulteração: trocar um caractere do `requestState` e conferir `-32602`
- Teste manual de capability: repetir o conflito com `clientCapabilities: {}` e conferir `-32021` + HTTP 400
- `curl` com o corpo de `exemplos/wire/04-...json` e `11-...json`

## Resultado esperado

Servidor MCP **completo**. As 20 verificações de MCP do validador passam, e o servidor é o único dono das regras de sala.

---

# Fase 9 — O agente como host MCP (sem A2A)

## Objetivo

Um cliente MCP de verdade, dentro do agente, que descobre as tools, lê o resource, propaga `traceparent` e completa o ciclo de MRTR vendo o `input_required` **cru** — validado por um script de linha de comando, antes de existir qualquer A2A.

## Dependências

Fase 8.

## Arquivos envolvidos

- `agente/cliente_mcp.py` (novo)
- `agente/ciclo_manual.py` (novo — script de verificação, mantido no repositório como ferramenta de depuração)

## Tarefas

- [x] criar o cliente MCP apontando para `MCP_URL` (padrão `http://127.0.0.1:7301/mcp`), mantendo o objeto cliente vivo entre chamadas
- [x] emitir `tools/list` **antes** da primeira chamada de tool, e usar a lista descoberta em vez de uma lista fixa no código
- [x] ler o resource `politica://uso` e extrair a versão da primeira linha
- [x] montar o `_meta` de todo request com `io.modelcontextprotocol/protocolVersion` e `io.modelcontextprotocol/clientCapabilities` no formato `{"elicitation": {"form": {}}}`
- [x] garantir que os headers `MCP-Protocol-Version`, `Mcp-Method` e, em `tools/call`/`resources/read`, `Mcp-Name` batem com o corpo (R7)
- [x] aceitar um `traceparent` externo e propagá-lo via `meta={"traceparent": ...}`, mantendo o **mesmo trace-id** e gerando span-id novo
- [x] registrar um `elicitation_callback` **apenas para declarar a capability** (sem ele o servidor responde `-32021`) e dirigir o ciclo por `client.session.call_tool(..., allow_input_required=True)`, que devolve o `InputRequiredResult` cru sem nunca invocar o callback
- [x] manter o `Client` vivo no lifespan da aplicação, já que ele é um `async with`
- [x] registrar no README (Fase 13) que o SDK declara `{"form": {}, "url": {}}` e sobrescreve qualquer `clientCapabilities` passado em `meta=` (D4)
- [x] implementar o retry com id de JSON-RPC novo, levando `inputResponses` com a mesma chave recebida e o `requestState` ecoado sem modificação
- [x] escrever `agente/ciclo_manual.py`, que percorre: descoberta → leitura do resource → reserva livre → conflito → pausa → retomada, imprimindo cada passo
- [x] commit por contexto, PR `feature/agente-host-mcp` → `develop`, merge

## Critérios de aceite

- `ciclo_manual.py` completa o ciclo de MRTR respondendo a elicitation "na mão", sem callback;
- o stderr do servidor MCP mostra `tools/list` **antes** do primeiro `tools/call`;
- o stderr mostra o `traceparent` com o trace-id informado ao script;
- os ids de JSON-RPC do request inicial e do retry são **diferentes**;
- o agente nunca abre nem interpreta o `requestState`.

## Validação

- `python "agente/ciclo_manual.py" --traceparent 00-<trace>-<span>-01` com os dois processos de pé
- Leitura do stderr do servidor MCP conferindo a ordem dos métodos, o trace-id e o par de ids do `tools/call`
- Um teste negativo: enviar `Mcp-Name` divergente do corpo e conferir `-32020`

## Resultado esperado

Metade de dentro do agente pronta e provada isoladamente. Nada de A2A ainda — o que reduz muito o custo de depurar a ponte na Fase 11.

---

# Fase 10 — O agente como servidor A2A

## Objetivo

Publicar o Agent Card, atender `SendMessage` e `GetTask` em `/a2a`, e rodar a máquina de estados da Task nos caminhos que **não** passam pela pausa: sucesso e falha.

## Dependências

Fase 9.

## Arquivos envolvidos

- `agente/servidor_a2a.py` (novo — Starlette, rotas e JSON-RPC)
- `agente/card.py` (novo — Agent Card v1.0)
- `agente/tarefas.py` (novo — repositório de Tasks em memória e máquina de estados)
- `agente/pedido.py` (novo — parser do formato fixo)
- `agente/servidor.py` (novo — entrypoint uvicorn na 7300)

## Tarefas

- [x] implementar `GET /.well-known/agent-card.json` devolvendo o card na forma v1.0
- [x] declarar no card: identidade, `supportedInterfaces` com `url`, `protocolBinding: "JSONRPC"` e `protocolVersion: "1.0"`, `capabilities` e a skill de id `reservar-sala`
- [x] conferir a grafia do card contra `exemplos/wire/07-a2a-agent-card.json` (é `supportedInterfaces`, não `interfaces`; é `protocolBinding`, não `preferredTransport`)
- [x] implementar o endpoint JSON-RPC `/a2a` roteando `SendMessage` e `GetTask`
- [x] implementar o parser de `reservar sala=<id> inicio=<iso> fim=<iso> responsavel=<nome>`
- [x] implementar a Task com `id`, `contextId`, `status`, `history` e `artifacts`, transitando por `TASK_STATE_SUBMITTED` e `TASK_STATE_WORKING`
- [x] implementar o caminho feliz: chamar `reservar_sala` no servidor MCP e concluir em `TASK_STATE_COMPLETED`
- [x] montar o artifact de `name: "reserva"` cujo conteúdo é o JSON da reserva, com o campo `politica` preenchido com a versão **lida do resource**
- [x] implementar o caminho de falha: `isError: true` da tool termina a Task em `TASK_STATE_FAILED` com a **mensagem exata da tool** visível na mensagem de status e no histórico
- [x] implementar `GetTask` devolvendo o estado corrente e os artifacts quando existirem
- [x] recusar com erro JSON-RPC qualquer `SendMessage` que referencie Task em estado terminal
- [x] propagar o header `traceparent` do request A2A para o fluxo MCP daquela Task
- [x] commit por contexto, PR `feature/agente-a2a` → `develop`, merge

## Critérios de aceite

- Verificações **21, 22, 23, 24, 25, 26, 31 e 35** passam;
- o card bate com a fixture 07 na estrutura de `supportedInterfaces` e da skill;
- a forma da Task bate com as fixtures 08, 09 e 10 (`status.message.parts[].text`, `history`, `artifacts[].name`);
- uma Task terminal nunca volta para `WORKING`.

## Validação

- `curl http://localhost:7300/.well-known/agent-card.json` comparado com a fixture 07
- `python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301` → checks 21 a 26, 31, 35 = PASS (27 a 30, 32 a 34, 36 ainda falham)
- `curl` com o corpo de `exemplos/wire/08-a2a-send-message.json`

## Resultado esperado

O agente é descobrível e utilizável por qualquer cliente A2A nos caminhos simples. Falta apenas a pausa — a ponte propriamente dita.

---

# Fase 11 — A ponte

## Objetivo

Costurar os dois mecanismos de estado: `input_required` do MCP vira `TASK_STATE_INPUT_REQUIRED`, o `requestState` fica guardado por Task sem vazar, e a continuação vira retry do `tools/call` com id novo.

## Dependências

Fases 9 e 10.

## Arquivos envolvidos

- `agente/ponte.py` (novo — tradução `input_required` ↔ Task, e guarda do estado pausado)
- `agente/tarefas.py` (alterado — estado pausado por Task)
- `agente/servidor_a2a.py` (alterado — roteamento da continuação)

## Tarefas

- [x] ao receber `input_required` do servidor MCP, colocar a Task em `TASK_STATE_INPUT_REQUIRED`
- [x] devolver como mensagem de texto da Task exatamente `alternativas: <ids separados por virgula e espaco>`, na ordem do enum, sem prefixo nem saudação
- [x] guardar, associado à Task: o `requestState` (opaco), a chave de `inputRequests`, o enum de alternativas e os argumentos do `tools/call` original
- [x] garantir que o `requestState` **não** aparece no card, no artifact, no histórico nem em nenhuma resposta A2A
- [x] implementar a continuação `escolha=<id>`: montar `inputResponses` com a mesma chave e `action: "accept"`, ecoar o `requestState` sem modificação e emitir o `tools/call` com **id de JSON-RPC novo**
- [x] implementar `escolha=recusar`: `action: "decline"`, concluindo a Task em `TASK_STATE_CANCELED`
- [x] implementar escolha fora do enum: a Task **permanece** em `TASK_STATE_INPUT_REQUIRED` e a linha de alternativas é repetida igual
- [x] garantir isolamento por Task: duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva, sem trocar `requestState`
- [x] garantir determinismo: o mesmo pedido enviado duas vezes produz a mesma mensagem de pausa, sem criar reserva
- [x] concluir a Task retomada em `TASK_STATE_COMPLETED` com o artifact da reserva na sala escolhida
- [x] commit por contexto, PR `feature/a-ponte` → `develop`, merge

## Critérios de aceite

- Verificações **27, 28, 29, 30, 32, 33, 34 e 36** passam;
- o `requestState` nunca aparece em corpo de resposta do agente (a verificação 34 varre todas elas);
- o id do retry difere do id do request inicial, comprovado no stderr do servidor MCP;
- o agente não interpreta o `requestState` em nenhum ponto do código.

## Validação

- `python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301` → **36/36 PASS** esperado
- Sequência manual: `curl` com `exemplos/wire/08-...json`, conferir a pausa, continuar com `exemplos/wire/10-...json`, conferir `GetTask`
- Sequência manual de recusa: pedir sala ocupada e responder `escolha=recusar`, conferir `TASK_STATE_CANCELED`
- Leitura do stderr do servidor MCP conferindo o par de `tools/call` da mesma reserva com ids diferentes

## Resultado esperado

O desafio está funcionalmente completo. A ponte existe e é observável de ponta a ponta.

---

# Fase 12 — Validação completa e fluxo do avaliador

## Objetivo

Reproduzir, passo a passo, o que o avaliador vai fazer — inclusive o que o validador automático **não** cobre — e corrigir o que aparecer.

## Dependências

Fase 11.

## Arquivos envolvidos

- Nenhum arquivo novo; correções pontuais onde surgirem falhas

## Tarefas

- [ ] matar os dois processos e subir tudo do zero
- [ ] rodar `python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301` e conferir 36 PASS e código de saída 0
- [ ] localizar no stderr do servidor MCP o `tools/list` anterior ao primeiro `tools/call`
- [ ] localizar no stderr o `traceparent` com o trace-id impresso pelo validador na primeira linha
- [ ] localizar no stderr o par de `tools/call` de uma reserva que passou pela pausa e conferir os ids diferentes
- [ ] `curl` do agent card e conferência contra `exemplos/wire/07-a2a-agent-card.json`
- [ ] enviar manualmente o `SendMessage` de `exemplos/wire/08-...json` e conferir a pausa com a ordem de alternativas
- [ ] continuar com `escolha=sala-mirante` e conferir por `GetTask` a Task COMPLETED com o artifact e o campo `politica`
- [ ] repetir o pedido e responder `escolha=recusar`, conferindo `TASK_STATE_CANCELED`
- [ ] enviar `sala=sala-inexistente` e conferir `TASK_STATE_FAILED` com a mensagem exata no histórico
- [ ] pegar um `requestState` direto do servidor MCP, trocar um caractere, reenviar e conferir `-32602`
- [ ] repetir sem alterar o `requestState`, **reiniciando o servidor MCP** antes do retry, e conferir a reserva concluída
- [ ] repetir o conflito sem declarar elicitation nas capabilities e conferir `-32021` com HTTP 400
- [ ] confirmar `git status` de `dados/`, `validador/` e `exemplos/` sem alterações
- [ ] guardar a saída completa do validador para o README

## Critérios de aceite

- 36/36 PASS com código de saída 0, a partir de processos recém-iniciados;
- os 13 passos do "Fluxo do avaliador" do `PLAN.md` reproduzidos com sucesso;
- `dados/`, `validador/` e `exemplos/` idênticos ao commit inicial;
- saída do validador salva para a documentação.

## Validação

- Código de saída do validador: `0`
- `git diff 263f17e -- dados validador exemplos` vazio
- Evidências dos passos manuais registradas (saída de `curl` e trechos de stderr)

## Resultado esperado

A entrega passa não só no teste automático, mas no roteiro manual que o avaliador vai seguir.

---

# Fase 13 — README da entrega

## Objetivo

Substituir o `README.md` do starter pela documentação da entrega, com as quatro seções exigidas e comandos que funcionam a partir de um clone limpo.

## Dependências

Fase 12 (a saída do validador entra no README).

## Arquivos envolvidos

- `README.md` (substituído)

## Tarefas

- [ ] escrever **Como rodar**: comandos exatos, a partir de um clone limpo, para criar o ambiente, gerar e exportar o `REQUEST_STATE_SECRET`, subir o servidor MCP, subir o agente e rodar o validador
- [ ] documentar o comando de geração do segredo (`python -c "import secrets; print(secrets.token_hex(32))"`) **sem** publicar o valor usado
- [ ] documentar a diferença `python` / `python3` entre Windows e Linux/macOS (R5)
- [ ] escrever **Onde a ponte acontece**: um parágrafo apontando o arquivo e a função em que o `input_required` do MCP vira `TASK_STATE_INPUT_REQUIRED`, e o ponto em que o `requestState` volta para o servidor
- [ ] escrever **Decisões técnicas**: como o `requestState` foi protegido, por quanto tempo vale, e onde mora o estado das Tasks
- [ ] registrar qualquer limitação real do SDK encontrada, com o trecho de evidência
- [ ] escrever **Saída do validador**: a saída completa da última execução, em bloco de código
- [ ] commit por contexto, PR `feature/readme` → `develop`, merge

## Critérios de aceite

- As quatro seções exigidas estão presentes;
- os comandos foram executados a partir de um clone limpo e funcionam;
- nenhum segredo publicado.

## Validação

- Leitura crítica do README seguindo os comandos literalmente
- Conferência item a item contra a seção "6. README" do `PLAN.md`

## Resultado esperado

Um README que permite ao avaliador subir tudo sem perguntar nada.

---

# Fase 14 — Entrega: gitflow, PRs e verificação em clone limpo

## Objetivo

Fechar a entrega na `main`, com histórico por contexto, PRs mergeados, e prova de que um clone limpo funciona seguindo apenas o README.

## Dependências

Fase 13.

## Arquivos envolvidos

- Histórico Git; nenhum arquivo de código novo

## Tarefas

- [ ] revisar o histórico de `develop`: commits por contexto, sem commits de "wip" acumulados
- [ ] abrir o PR `develop` → `main` no remoto e aplicar o merge
- [ ] conferir que a `main` remota contém toda a entrega
- [ ] clonar o repositório em uma pasta limpa fora do diretório de trabalho
- [ ] no clone limpo, seguir **apenas** o README: criar ambiente, exportar o segredo, subir os dois processos
- [ ] rodar o validador no clone limpo e conferir 36/36 com código de saída 0
- [ ] percorrer a checklist de Critérios de Aceite do `PLAN.md` item por item
- [ ] confirmar que não há dependência de SDK de provedor de LLM no `pyproject.toml`
- [ ] confirmar que `dados/`, `validador/` e `exemplos/` continuam idênticos ao starter

## Critérios de aceite

- Entrega completa na branch `main` do remoto;
- todos os PRs de fase abertos e mergeados;
- validador 36/36 em um clone limpo, seguindo só o README;
- todos os itens da checklist do `PLAN.md` marcados.

## Validação

- `git log --oneline main` mostrando o histórico por contexto
- Execução completa do validador no clone limpo
- Checklist do `PLAN.md` percorrida e registrada

## Resultado esperado

Desafio entregue, verificável por terceiros a partir do repositório público.

---

# Controle de progresso

| Fase | Status | Dependências | Resultado |
| --- | --- | --- | --- |
| Fase 1 — Investigação do SDK e decisões | Concluída | - | R1–R4 respondidos; D1–D4 fechados; achados registrados |
| Fase 2 — Scaffolding e gitflow | Concluída | Fase 1 | Deps travadas, .env.example, scripts e .gitattributes; publicado em origin/develop; sem PR (ver nota) |
| Fase 3 — Servidor MCP base | Concluída | Fases 1, 2 | Verificações 2, 3, 4, 5, 6 e 8 passando; log com método, id e traceparent |
| Fase 4 — Regras e `consultar_disponibilidade` | Concluída | Fase 3 | Verificações 10, 11 e 12 passando; 29 testes unitários verdes |
| Fase 5 — Resource `politica://uso` | Concluída | Fase 3 | Verificações 7 e 8 passando; resposta idêntica à fixture 05 |
| Fase 6 — `reservar_sala` caminho feliz | Concluída | Fases 4, 5 | Verificações 1 a 12 e 20 passando; 39 testes verdes |
| Fase 7 — MRTR `input_required` | Concluída | Fases 1 (D1), 6 | **As 20 verificações do lado MCP passam**; resposta idêntica à fixture 03 |
| Fase 8 — `requestState` protegido | Concluída | Fases 1 (R2/R3/R4/D2), 7 | **Servidor MCP completo**: 20/20 e retry sobrevivendo ao restart |
| Fase 9 — Agente host MCP | Concluída | Fase 8 | Ciclo de MRTR completo sem A2A; `tools/list` antes do 1º `tools/call`, traceparent propagado, retry com id novo |
| Fase 10 — Agente servidor A2A | Concluída | Fase 9 | 29 das 36 verificações; card idêntico à fixture 07 |
| Fase 11 — A ponte | Concluída | Fases 9, 10 | **36/36 no validador, exit 0**; retry com id novo confirmado no stderr |
| Fase 12 — Validação e fluxo do avaliador | Pendente | Fase 11 | |
| Fase 13 — README | Pendente | Fase 12 | |
| Fase 14 — Entrega e clone limpo | Pendente | Fase 13 | |

Status possíveis: `Pendente`, `Em andamento`, `Bloqueada`, `Concluída`.

---

# Instruções para próximas sessões

Durante a execução futura deste plano:

1. Sempre leia `PLAN.MD` e `PLAN_EXECUTION.MD` antes de iniciar.
2. Consulte o Controle de progresso.
3. Localize a primeira fase ainda não concluída.
4. Execute somente essa fase, salvo quando houver uma dependência explícita.
5. Não refaça fases marcadas como `Concluída`.
6. Atualize os checkboxes conforme as tarefas forem realizadas.
7. Ao terminar uma fase, execute todas as validações previstas.
8. Somente marque a fase como `Concluída` se os critérios de aceite forem satisfeitos.
9. Registre no plano qualquer decisão relevante descoberta durante a execução (especialmente R1 a R9 e D1 a D3).
10. Atualize o Controle de progresso.
11. Informe claramente qual é a próxima fase a ser executada.
12. Não avance automaticamente para a próxima fase quando houver falhas, dúvidas ou critérios de aceite não atendidos.

## Lembretes permanentes

- O validador exige os **dois processos recém-iniciados**. Rodar duas vezes seguidas sem reiniciar produz falsos negativos.
- `dados/`, `validador/` e `exemplos/` são imutáveis.
- O agente nunca abre o `requestState`, e o servidor MCP é o único dono das regras de sala.
- Nenhum LLM no caminho de execução.
