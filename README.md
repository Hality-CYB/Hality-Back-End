# hality-back

Backend em FastAPI, gerenciado com [uv](https://docs.astral.sh/uv/).

## Como iniciar o projeto

Existem dois caminhos: rodar a **API local com o banco em container** (melhor pro dia a dia de desenvolvimento, porque o reload automático é instantâneo) ou rodar a **API também em container** (ver [Rodando a API com Docker](#rodando-a-api-com-docker)). O passo a passo abaixo é o primeiro caso.

### Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker](https://docs.docker.com/get-docker/) (para o Postgres)

### Passo a passo (depois do clone)

```bash
# 1. entrar na pasta do projeto
cd hality-back

# 2. instalar as dependências (cria o .venv automaticamente)
uv sync

# 3. copiar o arquivo de variáveis de ambiente
cp .env.example .env        # Windows: copy .env.example .env
```

```bash
# 4. subir só o banco em container (a API vai rodar local)

# Linux/macOS
docker run -d --name hality-db \
  -e POSTGRES_USER=hality \
  -e POSTGRES_PASSWORD=hality \
  -e POSTGRES_DB=hality \
  -p 5432:5432 \
  -v hality_postgres_data:/var/lib/postgresql/data \
  postgres:17-alpine
```

```powershell
# Windows (PowerShell)
docker run -d --name hality-db `
  -e POSTGRES_USER=hality `
  -e POSTGRES_PASSWORD=hality `
  -e POSTGRES_DB=hality `
  -p 5432:5432 `
  -v hality_postgres_data:/var/lib/postgresql/data `
  postgres:17-alpine
```

```bash
# 5. aplicar as migrations no banco
uv run alembic upgrade head

# 6. subir o servidor em modo desenvolvimento (reload automático)
uv run fastapi dev app/main.py
```

A API sobe em http://localhost:8000 — docs interativas em `/docs` (Swagger) e `/redoc`.

Para confirmar que a conexão com o banco está de pé:

```bash
curl http://localhost:8000/api/v1/health     # {"status":"ok"}          — só a API
curl http://localhost:8000/api/v1/health/db  # {"status":"ok",...}      — API + banco
```

O `/health/db` executa um `SELECT 1` de verdade no Postgres. Se ele responder `503 database unavailable`, o problema é conexão com o banco (container no ar? `.env` correto?), não a API.

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

## Sumário

- [Rodando a API com Docker](#rodando-a-api-com-docker)
- [Banco de dados](#banco-de-dados)
- [Seeds](#seeds)
- [Arquitetura](#arquitetura)
- [Detalhamento](#detalhamento)
- [Convenções](#convenções)

## Rodando a API com Docker

O `Dockerfile` empacota **só este backend**. O Postgres continua sendo um container separado (ver [passo a passo](#passo-a-passo-depois-do-clone)) — não há orquestração no repositório.

### Comandos

```bash
# buildar a imagem (Linux/macOS/Windows — mesmo comando)
docker build -t hality-api .
```

```bash
# subir a API conectando no banco que já está rodando

# Linux/macOS
docker run --rm -p 8000:8000 --env-file .env \
  -e POSTGRES_HOST=host.docker.internal \
  --add-host=host.docker.internal:host-gateway \
  hality-api
```

```powershell
# Windows (PowerShell)
docker run --rm -p 8000:8000 --env-file .env `
  -e POSTGRES_HOST=host.docker.internal `
  --add-host=host.docker.internal:host-gateway `
  hality-api
```

`POSTGRES_HOST` precisa ser sobrescrito porque, de dentro do container, `localhost` é o próprio container e não a sua máquina.

Alternativa mais limpa: colocar os dois containers na mesma rede e usar o nome do container do banco como host.

```bash
# Linux/macOS/Windows — mesmo comando
docker network create hality-net
docker network connect hality-net hality-db
```

```bash
# Linux/macOS
docker run --rm -p 8000:8000 --env-file .env \
  --network hality-net \
  -e POSTGRES_HOST=hality-db \
  hality-api
```

```powershell
# Windows (PowerShell)
docker run --rm -p 8000:8000 --env-file .env `
  --network hality-net `
  -e POSTGRES_HOST=hality-db `
  hality-api
```

A imagem sobe direto o `uvicorn` — as migrations **não** rodam sozinhas. Aplique antes (`uv run alembic upgrade head`) ou rode dentro do container:

```bash
# Linux/macOS
docker run --rm --env-file .env --network hality-net \
  -e POSTGRES_HOST=hality-db \
  hality-api alembic upgrade head
```

```powershell
# Windows (PowerShell)
docker run --rm --env-file .env --network hality-net `
  -e POSTGRES_HOST=hality-db `
  hality-api alembic upgrade head
```

### Detalhes da imagem

O `Dockerfile` é **multi-stage**: um estágio instala as dependências e outro, bem menor, só recebe o resultado pronto. Isso evita mandar compilador, cache e ferramenta de build pra imagem final. O container roda com usuário **não-root**.

O estágio `builder` usa a imagem oficial do `uv` e instala as dependências a partir do `uv.lock` (`uv sync --locked --no-dev`, sem as libs de desenvolvimento); o estágio `runtime` é um `python:3.12-slim` que recebe só o `.venv` e o código.

## Banco de dados

O banco é **PostgreSQL**, acessado com [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/) em modo **assíncrono** (driver `asyncpg`), e as mudanças de schema são versionadas com [Alembic](https://alembic.sqlalchemy.org/).

Por que async: o FastAPI roda sobre `asyncio`, e um endpoint `async def` que faz uma query bloqueante trava o event loop inteiro. Com `asyncpg` + `AsyncSession`, a aplicação libera o loop enquanto espera o banco responder.

### Configuração da conexão

A URL de conexão não é escrita à mão: ela é **montada** em `app/core/config.py` a partir das variáveis abaixo, expostas na propriedade `settings.database_url`.

| Variável | Padrão | Descrição |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Host do banco. Com a API **dentro de um container**, use o nome do container do banco (ex.: `hality-db`) ou `host.docker.internal`. |
| `POSTGRES_PORT` | `5432` | Porta do banco. |
| `POSTGRES_USER` | `hality` | Usuário. |
| `POSTGRES_PASSWORD` | `hality` | Senha. Só serve para desenvolvimento — em produção deve vir de um segredo, nunca do `.env` versionado. |
| `POSTGRES_DB` | `hality` | Nome do banco. |
| `DB_ECHO` | `false` | Se `true`, loga no console todo SQL executado. Útil pra debugar, barulhento demais pro dia a dia. |

O resultado é uma URL no formato:

```
postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>
```

> A pegadinha mais comum: com a API **local** o host é `localhost`; com a API **dentro de um container** `localhost` aponta pro próprio container. Nesse caso sobrescreva a variável no `docker run` (`-e POSTGRES_HOST=...`) em vez de mexer no seu `.env`.

### Usando o banco num endpoint

A sessão vem por injeção de dependência, através do atalho `DbSession` (definido em `app/api/deps.py`). O SQL fica isolado num módulo `app/db/<recurso>_queries.py` — funções simples, sem regra de negócio; quem decide o que fazer com o resultado é o service:

```python
# app/db/user_queries.py — só SQL, nenhuma regra de negócio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def listar(db: AsyncSession) -> list[User]:
    resultado = await db.execute(select(User))
    return list(resultado.scalars().all())
```

```python
# app/services/user_service.py — regra de negócio, chama o módulo de queries
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import user_queries
from app.schemas.user import UserRead


async def listar_usuarios(db: AsyncSession) -> list[UserRead]:
    usuarios = await user_queries.listar(db)
    return [UserRead.model_validate(u) for u in usuarios]
```

```python
# app/api/v1/endpoints/user.py — só HTTP
from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.user import UserRead
from app.services import user_service

router = APIRouter(tags=["users"])


@router.get("/users")
async def list_users(db: DbSession) -> list[UserRead]:
    return await user_service.listar_usuarios(db)
```

Repare a cadeia: o endpoint só recebe a requisição e chama o service; o service concentra a regra de negócio e chama o módulo de queries; o módulo de queries só sabe SQL (usa o **model**, `User`) e nunca decide formato de resposta — quem monta o **schema** (`UserRead`) de volta é o service. É a separação descrita em [Arquitetura](#arquitetura).

Não existe uma camada de `Repository`/interface trocável entre o service e o banco — de propósito. Esse projeto usa um único banco (Postgres) e os testes já batem no banco real (não mockam acesso a dados), então uma interface pensada pra "trocar a implementação de persistência" não tem, hoje, nenhuma implementação alternativa pra justificar existir. Se isso mudar, essa decisão deve ser revisitada — mas não antes disso. Ver `app/db/anamnese_queries.py` para um exemplo completo, com `INSERT`/`SELECT`/`UPDATE`/`DELETE`.

O `get_db` (em `app/db/session.py`) abre a sessão no início da request e a fecha no final, mesmo se o endpoint levantar exceção. Nunca instancie uma sessão na mão dentro do endpoint.

### Migrations com Alembic

Toda mudança de schema (criar tabela, adicionar coluna, criar índice) vira um arquivo versionado em `alembic/versions/`, que entra no Git junto com o código. Assim o banco de todo mundo — e o de produção — evolui na mesma ordem.

**Nunca edite uma migration que já foi para a `develop`.** Se precisa corrigir algo, gere uma nova migration por cima.

```bash
# 1. criar o model em app/models/ e importá-lo em app/models/__init__.py
#    (o Alembic só enxerga o que estiver registrado no Base.metadata)

# 2. gerar a migration comparando os models com o banco atual
uv run alembic revision --autogenerate -m "cria tabela de usuarios"

# 3. LER o arquivo gerado em alembic/versions/ antes de aplicar

# 4. aplicar no banco
uv run alembic upgrade head
```

Outros comandos:

```bash
uv run alembic current           # em qual revisão o banco está
uv run alembic history           # histórico de migrations
uv run alembic downgrade -1      # desfaz a última migration
```

O `--autogenerate` compara os models com o schema real do banco, mas **não é infalível** — ele costuma não detectar renomeação de tabela/coluna (gera um `drop` + `create`, o que apaga dados) e mudanças em tipos customizados. Por isso o passo 3 não é opcional.

Se a API estiver rodando em container, use `docker exec <container> alembic <comando>` no lugar de `uv run alembic <comando>`.

## Seeds

O projeto tem um script (`scripts/seed.py`) que popula o banco local com dados de exemplo — usuários (admin, profissionais e pacientes), classificações de diagnóstico, conteúdos, diagnósticos, imagens e dicas da home. Serve pra ter dados prontos ao desenvolver ou testar endpoints manualmente, sem precisar cadastrar tudo na mão.

### Como aplicar

```bash
# 1. banco em container e migrations em dia

# Linux/macOS
docker run -d --name hality-db \
  -e POSTGRES_USER=hality \
  -e POSTGRES_PASSWORD=hality \
  -e POSTGRES_DB=hality \
  -p 5432:5432 \
  -v hality_postgres_data:/var/lib/postgresql/data \
  postgres:17-alpine
```

```powershell
# Windows (PowerShell)
docker run -d --name hality-db `
  -e POSTGRES_USER=hality `
  -e POSTGRES_PASSWORD=hality `
  -e POSTGRES_DB=hality `
  -p 5432:5432 `
  -v hality_postgres_data:/var/lib/postgresql/data `
  postgres:17-alpine
```

```bash
uv run alembic upgrade head

# 2. rodar o seed
uv run python -m scripts.seed
```

Se a API estiver rodando em container, use `docker exec <container> python -m scripts.seed` no lugar de `uv run python -m scripts.seed`.

### O que o seed cria

| Tabela | Registros |
|---|---|
| `users` | 1 admin, 2 profissionais, 3 pacientes |
| `profissionais` | 2 (vinculados aos usuários profissionais) |
| `pacientes_profissionais` | 3 vínculos paciente↔profissional |
| `classificacoes_diagnostico` | 4 (`saudavel`, `halitose_leve`, `halitose_social`, `halitose_severa`) |
| `conteudos_diagnostico` | 4 (dicas e protocolos, um deles genérico sem classificação) |
| `diagnosticos` | 3 (um por paciente, em status diferentes: `gerado`, `revisado`, `em_revisao`) |
| `imagens` | 4 (vinculadas aos diagnósticos) |
| `dicas` | 4 (conteúdo educativo exibido na home) |

Todos os usuários de seed usam a senha `hality123` (hash bcrypt via `pwdlib`) — só serve pra desenvolvimento local, nunca use esses dados em produção.

### Idempotência

O script **apaga** os dados das tabelas de negócio (na ordem reversa das foreign keys) antes de inserir de novo. Ou seja, pode rodar `uv run python -m scripts.seed` quantas vezes quiser — sempre termina com a mesma massa de dados, sem erro de chave duplicada. Isso também significa que ele **não deve rodar contra um banco com dados reais**.

## Arquitetura

O projeto segue uma organização **por camada** (horizontal): os arquivos são agrupados pelo *tipo* de responsabilidade que têm, não pelo domínio/feature a que pertencem. Ou seja, todo endpoint HTTP fica em `api/`, toda regra de negócio em `services/`, toda entidade de banco em `models/`, e assim por diante — independente de ser sobre "usuário", "pedido" etc.

Fluxo de uma requisição:

```
Request → api/ (endpoint) → services/ (regra de negócio) → db/*_queries.py (SQL) → models/ (tabela)
                ↓                        ↓
            schemas/ (valida        schemas/ (formata
             entrada)                  saída)
```

- **api** é o único ponto que conhece HTTP (status code, path, query params). Não deve ter regra de negócio.
- **services** concentra a lógica de negócio e não depende do FastAPI — poderia ser chamado por um script, um worker, um CLI, etc.
- **db** guarda a conexão (`base.py`, `session.py`) e, por recurso, um módulo `<recurso>_queries.py` com funções simples de acesso a dados — sem classe, sem interface trocável (`Repository`/`Protocol`). O service chama essas funções em vez de escrever SQL direto ou de passar por uma abstração de "múltiplas implementações possíveis" que, neste projeto, não existe (um único banco, testes de integração contra banco real). Ver [Usando o banco num endpoint](#usando-o-banco-num-endpoint).
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
        anamnese.py
  models/
    user.py
    anamnese.py
  schemas/
  services/
  db/
    base.py
    session.py
    anamnese_queries.py
alembic/
  env.py
  versions/
tests/
.env.example
alembic.ini
Dockerfile
```

- **`app/main.py`** — ponto de entrada. Cria a instância do `FastAPI`, registra middlewares (CORS) e inclui o router principal (`api_router`).

- **`app/core/config.py`** — configurações da aplicação via [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Lê variáveis do `.env` (ver `.env.example`) e expõe através de `get_settings()`, com cache (`lru_cache`) para não reler o arquivo a cada chamada.

- **`app/api/deps.py`** — dependências reutilizáveis via `Depends`. Hoje expõe `SettingsDep` (configurações) e `DbSession` (sessão de banco); é aqui que entrariam também usuário autenticado, paginação, etc.

- **`app/api/v1/api.py`** — agrega os routers de cada recurso da v1 num único `api_router`, que é incluído em `main.py` com o prefixo `/api/v1`. Versionar assim (`v1`, `v2`, ...) permite quebrar contrato de API no futuro sem afetar clientes antigos.

- **`app/api/v1/endpoints/`** — um arquivo por recurso, cada um com seu próprio `APIRouter` (ex.: `health.py`, `anamnese.py`). É aqui que futuros recursos (ex.: `auth.py`, `diagnostico.py`) devem entrar, com o service correspondente em `services/`, as queries em `db/` e o model em `models/`.

- **`app/models/`** — entidades de banco de dados (ORM), todas herdando de `Base` (ex.: `user.py`, `anamnese.py`). Todo model novo precisa ser importado em `app/models/__init__.py`, senão o Alembic não o enxerga na hora do `--autogenerate`.

- **`app/schemas/`** — schemas Pydantic de entrada e saída da API (request/response). É aqui que ficam os DTOs — não existe pasta separada para isso, o schema já cumpre esse papel.

- **`app/services/`** — regras de negócio. Recebe/devolve dados (schemas ou tipos simples), chama `db/` quando precisa ler/persistir algo, e não sabe nada sobre HTTP.

- **`app/db/`** — conexão com o banco e acesso a dados. `base.py` define a classe `Base` (`DeclarativeBase`) da qual todo model herda e que carrega o `metadata` usado pelas migrations; `session.py` cria o engine assíncrono e a dependência `get_db`, que abre e fecha uma sessão por request; e um arquivo `<recurso>_queries.py` por entidade (ex.: `anamnese_queries.py`) com as funções que fazem `SELECT`/`INSERT`/`UPDATE`/`DELETE` daquele recurso — só SQL, chamadas pelo service correspondente. Ver [Usando o banco num endpoint](#usando-o-banco-num-endpoint).

- **`alembic/`** e **`alembic.ini`** — migrations. O `env.py` puxa a URL de conexão do `app/core/config.py` (em vez de duplicá-la no `.ini`) e roda em modo assíncrono; `versions/` guarda os arquivos de migration versionados no Git. Ver [Banco de dados](#banco-de-dados).

- **`Dockerfile`** — imagem da API (multi-stage, usuário não-root). Ver [Rodando a API com Docker](#rodando-a-api-com-docker).

- **`tests/`** — testes com `pytest`. Espelha a estrutura do `app/` conforme cresce (ex.: `tests/api/v1/test_health.py`, quando fizer sentido separar por pasta).

- **`.env.example`** — modelo de variáveis de ambiente; copie para `.env` (que fica fora do git) antes de rodar o projeto.

- **`.vscode/`** — `settings.json` (format on save + organize imports com Ruff) e `extensions.json` (extensão recomendada).

- **`pyproject.toml`** — dependências do projeto e configuração do Ruff (`[tool.ruff]`).

## Convenções

### Padrão de branches

O repo tem duas branches "permanentes": `develop` (onde o time integra o trabalho do dia a dia) e `main` (produção/release — o CI roda em Pull Requests pra ambas). Toda branch nova nasce a partir da `develop` e volta pra ela via Pull Request.

O nome segue o formato:

```
<tipo>/<descrição-curta-em-kebab-case>
```

- **kebab-case** = tudo minúsculo, palavras separadas por hífen, sem acento e sem espaço (ex.: `cadastro-de-usuario`, não `Cadastro De Usuário`).
- A descrição deve dizer *o quê*, de forma curta — não precisa repetir o tipo nem detalhar o "como".

Os três tipos e quando usar cada um:

| Tipo | Quando usar | Exemplos |
|---|---|---|
| `feature/` | Algo novo — uma funcionalidade que o sistema **não fazia antes** e passa a fazer. | `feature/cadastro-de-usuario`, `feature/auth-jwt`, `feature/listagem-de-pedidos` |
| `fix/` | Correção de um **comportamento que já existia mas estava errado** (bug). Se o sistema tinha um comportamento incorreto e você está consertando, é `fix/`. | `fix/token-nao-expira`, `fix/cors-bloqueando-frontend`, `fix/validacao-de-email` |
| `chore/` | Tudo que **não muda o comportamento do sistema para quem usa a API** — configuração, dependências, CI/CD, documentação, formatação, refatoração sem mudar comportamento. | `chore/atualizar-dependencias`, `chore/configurar-ci`, `chore/documentar-readme` |

**Como diferenciar `fix/` de `chore/` na prática:** pergunte "isso corrige um bug que afeta o resultado/comportamento da aplicação?". Se sim → `fix/`. Se é manutenção/organização que não muda o que a aplicação faz (ex.: trocar versão do Ruff, ajustar `.gitignore`, mexer no workflow de CI) → `chore/`.

### Padrão de nomenclatura de arquivos

O projeto é Python, então os arquivos `.py` seguem o [PEP 8](https://peps.python.org/pep-0008/#package-and-module-names): **snake_case** (tudo minúsculo, palavras separadas por `_`). Nunca `CamelCase.py` nem `kebab-case.py` para módulos Python.

Além da regra geral, cada pasta tem sua própria convenção de nome de arquivo, pra facilitar achar as coisas:

- **`app/api/v1/endpoints/<recurso>.py`** — nome do recurso no singular (ex.: `user.py`, `auth.py`). Cada arquivo contém um único `APIRouter` daquele recurso.
- **`app/services/<recurso>_service.py`** — nome do recurso + sufixo `_service`, pra deixar explícito que é a camada de regra de negócio (ex.: `user_service.py`, `auth_service.py`).
- **`app/db/<recurso>_queries.py`** — nome do recurso + sufixo `_queries`, pra deixar explícito que só tem acesso a dados (SQL), sem regra de negócio (ex.: `anamnese_queries.py`). Funções `async def` simples — sem classe, sem interface. Ver [Arquitetura](#arquitetura).
- **`app/models/<recurso>.py`** — nome do recurso no singular; dentro do arquivo fica a classe da entidade (ex.: `user.py` define a classe `User`).
- **`app/schemas/<recurso>.py`** — mesmo nome do recurso; dentro do arquivo ficam as classes Pydantic relacionadas àquele recurso (ex.: `user.py` define `UserCreate`, `UserRead`, etc.).
- **`tests/test_<caminho_espelhado>.py`** — sempre com o prefixo `test_`. Não é estética: é assim que o `pytest` **descobre os testes automaticamente** (ele procura por arquivos `test_*.py`). Ex.: o teste de `app/api/v1/endpoints/health.py` fica em `tests/test_health.py`.
- **`__init__.py`** — arquivo vazio presente em toda pasta dentro de `app/`. Não é conteúdo, é o que transforma uma pasta comum num **pacote Python importável** (sem ele, `from app.services import ...` não funcionaria).
- **Arquivos de configuração na raiz** (`pyproject.toml`, `.env.example`, `.gitignore`, `uv.lock`) usam o nome exato que a ferramenta correspondente exige (uv, Python, git) — não são uma convenção nossa, então não seguem snake_case.
