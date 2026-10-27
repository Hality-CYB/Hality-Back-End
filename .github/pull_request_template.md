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


## Tipo de mudança

<!-- Marque todas as opções aplicáveis. -->


## Impacto na API

<!-- Informe endpoints incluídos ou alterados, payloads, respostas, códigos de
     status e eventuais mudanças incompatíveis. Se não houver impacto, escreva
     "não se aplica". -->


## Banco de dados e configuração

<!-- Explique migrations, alterações de dados, novas variáveis de ambiente,
     seeds ou passos especiais de deploy. Nunca inclua segredos. -->


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


## Observações para o time

<!-- Registre decisões técnicas, riscos, pontos de atenção para a review,
     limitações conhecidas ou passos de deploy. -->
