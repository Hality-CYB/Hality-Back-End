<!--
  PREENCHIMENTO OBRIGATÓRIO
  PR sem issue vinculada, descrição do impacto ou evidência dos testes será
  devolvido para ajustes antes da review. Se uma seção não se aplicar,
  escreva "não se aplica" e justifique. Não remova as seções.
-->

## Issue relacionada

<!-- Use "Closes #123" para fechar a issue automaticamente no merge.
     Se a demanda estiver no GitLab da AGES, informe o link ou ID do card. -->

Closes #

## Resumo da mudança

<!-- Descreva em 2 a 5 itens o que mudou e por quê. Inclua as rotas, serviços,
     modelos ou integrações afetados quando isso ajudar na revisão. -->

-

## Tipo de mudança

<!-- Marque todas as opções aplicáveis. -->

- [ ] `feature` — adiciona comportamento ou endpoint novo
- [ ] `fix` — corrige um comportamento existente
- [ ] `refactor` — reorganiza o código sem alterar o comportamento esperado
- [ ] `db` — altera modelos, schema ou migrations do banco
- [ ] `chore` — dependências, configuração, CI/CD, documentação ou manutenção

## Impacto na API

<!-- Informe endpoints incluídos ou alterados, payloads, respostas, códigos de
     status e eventuais mudanças incompatíveis. Se não houver impacto, escreva
     "não se aplica". -->

- Endpoints/contratos afetados:
- Compatibilidade ou breaking change:

## Banco de dados e configuração

<!-- Explique migrations, alterações de dados, novas variáveis de ambiente,
     seeds ou passos especiais de deploy. Nunca inclua segredos. -->

- Migration necessária: não se aplica
- Variáveis de ambiente/configuração: não se aplica
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

1.

## Checklist

- [ ] Branch criada a partir de `develop` e nomeada como `<tipo>/<descrição-em-kebab-case>`
- [ ] `uv.lock` foi atualizado quando houve alteração de dependências
- [ ] Migrations foram criadas e testadas quando houve mudança no banco
- [ ] `uv run ruff check .` passa
- [ ] `uv run ruff format --check .` passa
- [ ] `uv run pytest` passa
- [ ] Testei os endpoints ou fluxos afetados, incluindo erros e validações relevantes
- [ ] Revisei meu próprio diff e removi debug, código morto e arquivos acidentais
- [ ] Não incluí segredos, credenciais ou dados sensíveis
- [ ] Issue vinculada e impacto descrito acima

## Observações para o time

<!-- Registre decisões técnicas, riscos, pontos de atenção para a review,
     limitações conhecidas ou passos de deploy. -->
