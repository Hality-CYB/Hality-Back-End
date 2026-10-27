<!--
  PREENCHIMENTO OBRIGATÓRIO
  PR sem issue vinculada, descrição do impacto ou evidência dos testes será
  devolvido para ajustes antes da review. Se uma seção não se aplicar,
  escreva "não se aplica" e justifique. Não remova as seções.
-->

## Issue relacionada

<!-- Use "Closes #123" para fechar a issue automaticamente no merge.
     Se a demanda estiver no GitLab da AGES, informe o link ou ID do card. -->

Closes #117

## Resumo da mudança

<!-- Descreva em 2 a 5 itens o que mudou e por quê. Inclua as rotas, serviços,
     modelos ou integrações afetados quando isso ajudar na revisão. -->

- Adiciona a exportação administrativa de dataset em `POST /admin/datasets/exports`.
- Exporta imagens consentidas de diagnósticos concluídos em um ZIP com `manifest.csv` e `README.md`.
- Aplica a precedência do rótulo Hality sobre o rótulo profissional e inclui origem e versão no manifesto.
- Remove metadados de imagens, valida checksums e revalida a elegibilidade antes de concluir a exportação.

## Tipo de mudança

<!-- Marque todas as opções aplicáveis. -->

- [x] `feature` — adiciona comportamento ou endpoint novo
- [ ] `fix` — corrige um comportamento existente
- [ ] `refactor` — reorganiza o código sem alterar o comportamento esperado
- [ ] `db` — altera modelos, schema ou migrations do banco
- [ ] `chore` — dependências, configuração, CI/CD, documentação ou manutenção

## Impacto na API

<!-- Informe endpoints incluídos ou alterados, payloads, respostas, códigos de
     status e eventuais mudanças incompatíveis. Se não houver impacto, escreva
     "não se aplica". -->

- Endpoints/contratos afetados: `POST /admin/datasets/exports` (admin autenticado), recebendo `{ "diagnostico_ids": [1, 2] }` e retornando um arquivo ZIP (`application/zip`) com cabeçalho `Content-Disposition`.
- Compatibilidade ou breaking change: não se aplica; endpoint novo. A exportação permanece desabilitada por padrão.

## Banco de dados e configuração

<!-- Explique migrations, alterações de dados, novas variáveis de ambiente,
     seeds ou passos especiais de deploy. Nunca inclua segredos. -->

- Migration necessária: não se aplica.
- Variáveis de ambiente/configuração: `DATASET_EXPORT_ENABLED`, `DATASET_EXPORT_MAX_RECORDS` e `DATASET_EXPORT_MAX_BYTES`; a funcionalidade fica desabilitada por padrão.
- Seed ou procedimento adicional: não se aplica

## Como testar

<!-- Liste os comandos e cenários usados na validação. Para endpoints, informe
     rota, método, dados de entrada e resultado esperado. -->

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Cenários adicionais:

1. Exportação válida por administrador: retorna `200` e um ZIP contendo as imagens elegíveis, `manifest.csv` e `README.md`.
2. Seleção duplicada ou vazia: retorna `400`.
3. Diagnóstico inexistente: retorna `404`; item sem consentimento, sem imagem, não concluído ou sem rótulo elegível: retorna `409`.
4. Exportação desabilitada ou alteração de elegibilidade durante o processamento: retorna `409`; excesso de registros ou bytes: retorna `413`.
5. Acesso sem permissão administrativa: permanece bloqueado pelo guard de admin.

## Checklist

- [ ] Branch criada a partir de `develop` e nomeada como `<tipo>/<descrição-em-kebab-case>`
- [ ] `uv.lock` foi atualizado quando houve alteração de dependências
- [ ] Migrations foram criadas e testadas quando houve mudança no banco
- [ ] `uv run ruff check .` passa (não executado nesta sessão)
- [ ] `uv run ruff format --check .` passa (não executado nesta sessão)
- [ ] `uv run pytest` passa (não executado nesta sessão)
- [ ] Testei os endpoints ou fluxos afetados, incluindo erros e validações relevantes (não executado nesta sessão)
- [ ] Revisei meu próprio diff e removi debug, código morto e arquivos acidentais
- [ ] Não incluí segredos, credenciais ou dados sensíveis
- [ ] Issue vinculada e impacto descrito acima

## Observações para o time

<!-- Registre decisões técnicas, riscos, pontos de atenção para a review,
     limitações conhecidas ou passos de deploy. -->

- Referência da demanda: task `117 (301)`.
- A exportação é pseudonimizada, mas não anônima: os pixels das imagens podem identificar uma pessoa.
- O deploy deve habilitar `DATASET_EXPORT_ENABLED` somente após revisar consentimento, armazenamento e limites operacionais.
- O manifesto registra `label_source` e `label_version`; rótulos exclusivamente gerados por IA não são exportados.
