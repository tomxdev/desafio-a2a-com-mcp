# A Ponte: um agente A2A com MCP por dentro

Entrega do desafio da Hill Valley Tech: um servidor MCP que expõe as salas de reunião,
e um agente que consome esse servidor por dentro (como host MCP) e se oferece ao mundo
por fora (como servidor A2A).

Dois processos separados, que conversam por HTTP:

```
cliente A2A  ──JSON-RPC──▶  agente (7300)  ──Streamable HTTP──▶  servidor MCP (7301)
                            /a2a                                  /mcp
                            /.well-known/agent-card.json
```

O agente traduz protocolo; o servidor MCP é o único dono do domínio. Não há LLM no
caminho de execução: o pedido chega em formato fixo e a decisão é por regra.

---

## Como rodar

Requisitos: **Python 3.10 ou superior** e Git. Nada além disso.

### 1. Clonar e entrar na pasta

```bash
git clone https://github.com/tomxdev/desafio-a2a-com-mcp.git
cd desafio-a2a-com-mcp
```

### 2. Criar o ambiente e instalar

Linux / macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

> No Windows o executável chama-se `python`; em muitas distribuições Linux e no macOS,
> `python3`. Onde este README escreve `python3`, use `python` no Windows, e vice-versa.

### 3. Gerar e exportar a chave do `requestState`

A chave protege a integridade do `requestState` do MRTR. Ela vem do ambiente e **nunca**
do código, porque este repositório é público. Gere a sua:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

E exporte, colando o valor gerado:

```bash
export REQUEST_STATE_SECRET=<cole aqui o valor gerado>     # Linux / macOS
```

```powershell
$env:REQUEST_STATE_SECRET = "<cole aqui o valor gerado>"   # Windows PowerShell
```

Alternativa: copie `.env.example` para `.env`, preencha o valor lá e use os scripts de
subida (`./subir-mcp.sh` e `./subir-agente.sh`, ou `.\subir-mcp.ps1` e
`.\subir-agente.ps1`), que carregam o `.env` sozinhos. O `.env` está no `.gitignore`.

O servidor MCP **recusa subir** sem essa chave, ou com menos de 32 bytes, em vez de
subir inseguro.

### 4. Subir os dois processos

Cada um em um terminal, com o **stderr do servidor MCP visível**. O servidor MCP
primeiro: o agente descobre as tools na subida.

Terminal 1 — servidor MCP (porta 7301):

```bash
python3 "servidor-mcp/servidor.py"
```

Terminal 2 — agente (porta 7300):

```bash
python3 "agente/servidor.py"
```

### 5. Rodar o validador

Em um terceiro terminal:

```bash
python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

> Rode sempre com os **dois processos recém-iniciados**. As reservas criadas por uma
> execução mudam o resultado da seguinte, então rodar duas vezes seguidas sem reiniciar
> produz falsos negativos.

### Conferir o card

```bash
curl http://localhost:7300/.well-known/agent-card.json
```

### Ferramenta de apoio

`agente/ciclo_manual.py` percorre o ciclo de MRTR inteiro sem A2A nenhum — descoberta,
resource, reserva livre, conflito, pausa, retomada, recusa e erro de execução. Serve
para conferir no stderr do servidor MCP o `tools/list` anterior ao primeiro `tools/call`,
o `traceparent` propagado e o par de `tools/call` com ids diferentes:

```bash
python3 "agente/ciclo_manual.py"
```

### Testes

```bash
pip install -e ".[dev]"
python3 -m pytest
```

---

## Onde a ponte acontece

A ponte inteira mora em **`agente/ponte.py`**.

O `input_required` do MCP vira `TASK_STATE_INPUT_REQUIRED` em
**`_pausar()` (`agente/ponte.py:46`)**. Ela recebe a `Pausa` que
`agente/cliente_mcp.py` extraiu do `input_required` cru, guarda o `requestState` no
campo `Task.pausa` — estado interno, que fica de fora de `Task.como_json()` e por isso
nunca aparece numa resposta A2A — e move a Task com a linha
`alternativas: <ids separados por virgula e espaco>`, montada por
`linha_de_alternativas()` e sem prefixo nem saudação.

O `requestState` volta para o servidor em **`continuar()` (`agente/ponte.py:112`)**.
Quando a escolha é válida, ela chama `host.retomar()` (linha 143) com os argumentos
originais guardados na Task, e `agente/cliente_mcp.py:177` repete o `tools/call`
levando `inputResponses` com **a mesma chave** que veio no `inputRequests` e o
`request_state` **ecoado sem modificação**. O id do JSON-RPC é novo, porque o SDK
numera cada chamada — a spec exige que sejam requests independentes.

Detalhe que vale citar: uma escolha fora do enum **não gera round-trip nenhum**. A Task
continua pausada, a lista é repetida igual e o `requestState` não é gasto.

---

## Decisões técnicas

### Como o `requestState` é protegido, e por quanto tempo vale

O selo é do próprio SDK: `RequestStateSecurity(keys=[chave], ttl=900.0)`, instalado em
`servidor-mcp/servidor.py`. É AES-256-GCM — cifra e autentica —, então uma adulteração é
detectada e rejeitada com `-32602`. **Vale 15 minutos**, dentro da faixa de 5 a 30 que o
desafio pede: o suficiente para cobrir uma pausa de Task sem manter um token útil por
tempo demais.

A chave vem de `REQUEST_STATE_SECRET` (`servidor-mcp/seguranca.py`), aceita hexadecimal
ou texto cru, exige no mínimo 32 bytes e **nunca** tem valor embutido no código.

O ponto que separa a entrega ingênua: a política padrão do SDK é `ephemeral()`, que gera
uma chave nova por processo. Com ela o caminho feliz passa, mas um retry apresentado
depois de um restart é recusado. Como o estado viaja no token e não no servidor, a chave
precisa ser fixa. Isso está verificado: token emitido por um processo, processo morto,
processo novo com a mesma chave, retry concluído.

O boundary do SDK também vincula o token aos argumentos originais, então um retry com
argumentos adulterados é rejeitado em vez de tomar efeito.

### Onde mora o estado

| Estado | Onde | Sobrevive a restart? |
| --- | --- | --- |
| Salas e política | `dados/`, carregados na subida | — (somente leitura) |
| Reservas | memória do servidor MCP (`servidor-mcp/dominio.py`) | não, e não precisa |
| Tasks A2A | memória do agente (`agente/tarefas.py`) | não, e não precisa |
| `requestState` | **no próprio token**, selado | **sim** |

O servidor MCP não guarda nada entre o `input_required` e o retry. É essa a diferença
entre os dois mecanismos: o MCP resolve a ausência de sessão com um token que viaja, o
A2A com uma Task que fica.

### Desenho do MRTR

A tool `reservar_sala` recebe a escolha por
`Annotated[ElicitationResult[Escolha], Resolve(escolha_de_sala)]`. O resolver está em
`servidor-mcp/elicitacao.py` e roda em todas as rodadas, inclusive no retry.

Duas escolhas não óbvias:

- **O union `ElicitationResult[...]` é obrigatório.** Com a anotação desembrulhada
  (`Annotated[Escolha, Resolve(...)]`), uma recusa do usuário vira erro de execução, e o
  contrato exige que ela conclua normalmente, com `reservado: false`.
- **As mensagens de erro viajam em `ToolError`**, nunca em `ValueError`. Uma exceção
  comum é tratada como crash pelo SDK e o cliente recebe apenas
  `Error executing tool <nome>`, sem o texto — e o validador compara o texto exato.

### O agente vê o `input_required` cru

O cliente MCP do SDK **só declara a capability de elicitation quando um
`elicitation_callback` está registrado**, e sem ela o servidor recusa com `-32021`. Mas
pelo caminho de alto nível esse callback responde a pergunta sozinho, o ciclo fecha por
dentro e a Task nunca pausaria.

A saída, em `agente/cliente_mcp.py`: registrar o callback **apenas para declarar a
capability** e dirigir o ciclo por `session.call_tool(..., allow_input_required=True)`,
que devolve o `input_required` cru sem nunca chamá-lo. O callback instalado levanta erro
se rodar, para uma regressão aparecer alto em vez de sumir.

### Limitações reais do SDK encontradas

**O cliente sobrescreve as `clientCapabilities` passadas por `meta=`.** O desafio pede
que o agente declare a capability na forma `{"elicitation": {"form": {}}}`. O cliente do
SDK monta `{"elicitation": {"form": {}, "url": {}}}` e ignora qualquer valor que o
chamador passe nesse campo. O stamp faz atribuição direta:

```python
# .venv/Lib/site-packages/mcp/client/session.py, _make_modern_stamp
meta[CLIENT_CAPABILITIES_META_KEY] = capabilities
```

E as capabilities vêm de `_build_capabilities`, que emite sempre os dois modos quando há
callback:

```python
elicitation = (
    types.ElicitationCapability(form=types.FormElicitationCapability(), url=types.UrlElicitationCapability())
    if self._elicitation_callback is not _default_elicitation_callback
    else None
)
```

O `form` exigido está declarado; o `url` extra é imposto pelo SDK e não há como
removê-lo sem reescrever o transporte.

### Outras notas

- **A versão da política no artifact vem do resource**, lido pelo agente na subida, e não
  do que a tool devolveu: ler a política é escolha da aplicação.
- **O nome do campo da elicitation é lido do próprio schema**, e não fixo como `"sala"`.
  O agente traduz protocolo, não domínio.
- **Os caminhos dos endpoints ficam fora do `.env.example`** de propósito. O Git Bash
  converte um valor como `/mcp` para um caminho do Windows (`C:/Program Files/Git/mcp`)
  ao passá-lo a um processo nativo. Eles seguem configuráveis por `MCP_PATH` e
  `AGENTE_PATH`, com `/mcp` e `/a2a` como padrão no código; quem precisar mudá-los no
  Git Bash deve exportar `MSYS_NO_PATHCONV=1`.
- **Ordem das alternativas na conferência manual.** O passo 7 do fluxo do avaliador lista
  `sala-fusca, sala-mirante` **com os processos recém-iniciados**. Rodando logo depois do
  validador, a `sala-fusca` das 14h já foi reservada pela verificação 30 e a lista sai
  como `alternativas: sala-mirante` — que é, aliás, o que a própria
  `exemplos/wire/08-a2a-send-message.json` mostra. Os dois resultados estão corretos; o
  que muda é o estado em memória.

### Estrutura

```
servidor-mcp/
  servidor.py     transporte, tools e resource (composicao)
  elicitacao.py   o resolver do MRTR: quando e o que perguntar
  regras.py       janela, duracao, intervalo, sobreposicao, alternativas
  dominio.py      dados de dados/ e as reservas em memoria
  seguranca.py    a chave do requestState
  log.py          metodo, id e traceparent no stderr

agente/
  servidor.py     entrypoint
  servidor_a2a.py rotas e despacho JSON-RPC
  ponte.py        >>> a ponte: input_required <-> Task <<<
  cliente_mcp.py  host MCP, com o input_required cru
  tarefas.py      Task: identidade, estado e produto
  pedido.py       leitura do formato fixo
  card.py         Agent Card v1.0
  ciclo_manual.py ferramenta de depuracao
```

---

## Saída do validador

Última execução, com os dois processos recém-iniciados. Código de saída **0**.

```
trace-id desta execucao: cf032724e4151df0d1dbac71279f6b47
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```

### Verificações fora do validador

O próprio `validador/README.md` diz que duas exigências ficam no fluxo do avaliador.
Ambas conferidas:

```
retry apos REINICIAR o servidor MCP  -> http 200 | complete | res-0003 em sala-fusca
trace-id do validador no stderr      -> 4 ocorrencias
tools/list antes do 1o tools/call    -> linha 4 (list) contra linha 7 (call)
par de tools/call da mesma reserva   -> id=5 (inicial) e id=6 (retry)
requestState com 1 caractere trocado -> http 400 | -32602
sem a capability de elicitation      -> http 400 | -32021 | {"elicitation":{"form":{}}}
```
