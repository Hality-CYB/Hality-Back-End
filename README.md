# hality-back

Backend em FastAPI, gerenciado com [uv](https://docs.astral.sh/uv/).

## Sumário

- [Como iniciar o projeto](#como-iniciar-o-projeto)
- [Arquitetura](#arquitetura)
- [Detalhamento](#detalhamento)

## Como iniciar o projeto

### Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Passo a passo (depois do clone)

```bash
# 1. entrar na pasta do projeto
cd hality-back

# 2. instalar as dependências (cria o .venv automaticamente)
uv sync

# 3. copiar o arquivo de variáveis de ambiente
cp .env.example .env

# 4. subir o servidor em modo desenvolvimento (reload automático)
uv run fastapi dev app/main.py
```

A API sobe em http://localhost:8000 — docs interativas em `/docs` (Swagger) e `/redoc`.

### Gerenciando dependências

```bash
# adicionar uma dependência de produção
uv add <pacote>

# adicionar uma dependência de desenvolvimento (ex.: lint, testes)
uv add --dev <pacote>

# remover uma dependência
uv remove <pacote>

# reinstalar tudo a partir do uv.lock (ex.: depois de puxar mudanças de outra pessoa)
uv sync
```

`uv add`/`uv remove` já atualizam o `pyproject.toml` e o `uv.lock` automaticamente — não precisa editar esses arquivos na mão.

### Outros comandos úteis

```bash
# rodar os testes
uv run pytest

# lint
uv run ruff check .

# formatar o código
uv run ruff format .
```

> No VS Code, instale a extensão recomendada em `.vscode/extensions.json` (Ruff) — o `.vscode/settings.json` já está configurado para formatar e organizar imports automaticamente ao salvar.

### Deploy no FastAPI Cloud

```bash
uv run fastapi deploy
```

## Arquitetura

O projeto segue uma organização **por camada** (horizontal): os arquivos são agrupados pelo *tipo* de responsabilidade que têm, não pelo domínio/feature a que pertencem. Ou seja, todo endpoint HTTP fica em `api/`, toda regra de negócio em `services/`, toda entidade de banco em `models/`, e assim por diante — independente de ser sobre "usuário", "pedido" etc.

Fluxo de uma requisição:

```
Request → api/ (endpoint)  →  services/ (regra de negócio)  →  db/ + models/ (persistência)
                ↓                        ↓
            schemas/ (valida        schemas/ (formata
             entrada)                  saída)
```

- **api** é o único ponto que conhece HTTP (status code, path, query params). Não deve ter regra de negócio.
- **services** concentra a lógica de negócio e não depende do FastAPI — poderia ser chamado por um script, um worker, um CLI, etc.
- **models** e **schemas** são propositalmente separados: `models` é o formato salvo no banco (ORM), `schemas` é o formato trafegado pela API (Pydantic). Nem sempre são iguais (ex.: senha existe no model, nunca no schema de resposta).

Por que não tem pasta `controllers/`: no FastAPI, o módulo de `api/.../endpoints/` já cumpre esse papel (recebe request, chama service, devolve schema) — é o "controller" do framework, então uma pasta separada seria redundante.

## Detalhamento

```
app/
  main.py
  core/
    config.py
  api/
    deps.py
    v1/
      api.py
      endpoints/
        health.py
  models/
  schemas/
  services/
  db/
tests/
.env.example
```

- **`app/main.py`** — ponto de entrada. Cria a instância do `FastAPI`, registra middlewares (CORS) e inclui o router principal (`api_router`).

- **`app/core/config.py`** — configurações da aplicação via [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Lê variáveis do `.env` (ver `.env.example`) e expõe através de `get_settings()`, com cache (`lru_cache`) para não reler o arquivo a cada chamada.

- **`app/api/deps.py`** — dependências reutilizáveis via `Depends` (ex.: settings injetadas, futuramente sessão de banco, usuário autenticado, paginação).

- **`app/api/v1/api.py`** — agrega os routers de cada recurso da v1 num único `api_router`, que é incluído em `main.py` com o prefixo `/api/v1`. Versionar assim (`v1`, `v2`, ...) permite quebrar contrato de API no futuro sem afetar clientes antigos.

- **`app/api/v1/endpoints/`** — um arquivo por recurso, cada um com seu próprio `APIRouter` (ex.: `health.py`). É aqui que futuros recursos (ex.: `auth.py`, `users.py`) devem entrar, com o service correspondente registrado em `services/` e o model em `models/`.

- **`app/models/`** — entidades de banco de dados (ORM). Ainda vazia — será populada quando o banco for configurado (`app/db/`).

- **`app/schemas/`** — schemas Pydantic de entrada e saída da API (request/response). É aqui que ficam os DTOs — não existe pasta separada para isso, o schema já cumpre esse papel.

- **`app/services/`** — regras de negócio. Recebe/devolve dados (schemas ou tipos simples), chama `models`/`db` quando precisa persistir algo, e não sabe nada sobre HTTP.

- **`app/db/`** — configuração de conexão, sessão e engine do banco, além de migrations quando o ORM for definido.

- **`tests/`** — testes com `pytest`. Espelha a estrutura do `app/` conforme cresce (ex.: `tests/api/v1/test_health.py`, quando fizer sentido separar por pasta).

- **`.env.example`** — modelo de variáveis de ambiente; copie para `.env` (que fica fora do git) antes de rodar o projeto.

- **`.vscode/`** — `settings.json` (format on save + organize imports com Ruff) e `extensions.json` (extensão recomendada).

- **`pyproject.toml`** — dependências do projeto e configuração do Ruff (`[tool.ruff]`).
