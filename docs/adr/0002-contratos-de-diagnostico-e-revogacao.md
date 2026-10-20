# ADR 0002: Contratos de diagnóstico e efeito da revogação de consentimento

- Status: aceito para os contratos; **proposto (bloqueado)** para o efeito da revogação
- Data: 2026-10-19
- Escopo: US-071, DELTA-12, AC-16, AC-18, AC-37 a AC-40
- Owner da decisão pendente: jurídico/Hality (OPEN-06)

## Contexto

Paciente, profissional e admin consomem o mesmo diagnóstico, mas os contratos
eram implícitos: o detalhe do paciente não tinha schema, a mensagem de erro
gravada pelo mock ia crua para o cliente, nada registrava se o resultado veio
de mock ou de modelo, e uma anamnese podia ser editada ou excluída depois de
gerar um diagnóstico (a exclusão levava o diagnóstico junto, em CASCADE).

## Decisão

1. **Status com semântica fixa** (`StatusDiagnostico`, CHECK no banco):
   `processando` e `falha` nunca expõem classificação, escala, confiança nem
   revisão; `aguardando_revisao` expõe a sugestão automática; `concluido`
   expõe a revisão profissional mais recente. A regra vive em um só helper
   (`_tem_resultado`) e em `STATUS_COM_RESULTADO`.
2. **Erro público seguro**: o banco guarda `erro_codigo` (catálogo em
   `app/core/erros_diagnostico.py`) e `erro` (detalhe interno). As APIs
   devolvem `erro` (mensagem do catálogo) e `erro_codigo`; a coluna interna
   nunca é serializada.
3. **Rastreabilidade sem invenção**: `origem_resultado` (`mock`, `modelo`,
   `legado`), `modelo_provider` e `modelo_versao`. Provider e versão só
   existem para `modelo` (CHECK). O mock grava `mock` com ambos nulos; o
   backfill marca o que já existia como `legado`. A origem aparece para
   profissional e admin, não para o paciente.
4. **Anamnese imutável depois do uso**: uma avaliação por anamnese (UNIQUE
   mantido); PUT/DELETE de anamnese com diagnóstico → 409; a FK passa a NO
   ACTION (bloqueia apagar só a anamnese, mas mantém o CASCADE de `users`).
   O envio do diagnóstico e a alteração da anamnese travam a mesma linha
   (`FOR UPDATE`), sem corrida entre checar e alterar.
5. **Original preservado**: `imagens` é 1:N com `UNIQUE(diagnostico_id,
   ordem)`; o arquivo é gravado em modo exclusivo (nunca sobrescreve) e a
   linha guarda `sha256`, `content_type` e `tamanho_bytes`.
6. **Questionário**: versões publicadas são imutáveis; a versão de fallback
   `2026-08-v1` passa a existir em `questionarios`, com data anterior a
   qualquer versão real (não vira a vigente).
7. **Consentimento**: o bloqueio de novos envios sem `health_data` vigente
   continua como está. `image_training` é independente e não bloqueia o
   diagnóstico.

## Decisão pendente: efeito da revogação sobre dados existentes

Hoje revogar `health_data` impede **novos** envios. Não está definido o que
acontece com o que já existe:

- diagnósticos, anamneses e imagens anteriores continuam visíveis ao
  paciente, ao profissional vinculado e ao admin?
- devem ser ocultados, anonimizados ou excluídos? Em quanto tempo?
- revisões profissionais já feitas são preservadas (obrigação de prontuário)?
- revogar `image_training` exige marcar ou excluir imagens de um futuro
  dataset (DEC-04/DEC-07)?

Até a resposta do jurídico (OPEN-06), o comportamento atual é mantido e
nenhuma regra provisória é implementada.

## Fora de escopo

Novo score, métrica de acurácia, modelo real e SLA clínico.

## Consequências

- O payload do paciente ganha `erro_codigo`; o texto de `erro` muda para a
  mensagem do catálogo. Os demais campos seguem iguais.
- Profissional e admin ganham `origem` no resultado automático e `erro_codigo`.
- Clientes que editavam ou excluíam uma anamnese já usada passam a receber 409.
- A escala de saburra continua sem faixa oficial (o seed usa 0–6 e o mock usa
  24/49/68); definir a faixa é parte do "novo score".
