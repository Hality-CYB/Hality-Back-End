# ADR 0001: Publicação de conteúdo e exportação para rotulagem

- Status: aceito para conteúdo; bloqueado para dataset
- Data: 2026-09-24
- Escopo: US-120/US-130, DELTA-08/DELTA-09/DELTA-13, AC-30 a AC-33

## Contexto

Conteúdos clínicos possuem estrutura JSON por tipo e associação opcional a uma
classificação. Faltavam operações administrativas, autoria e uma fronteira explícita
entre material em preparação e material aprovado para pacientes. A exportação de
diagnósticos para rotulagem também não tem contrato de consentimento, anonimização,
retenção ou responsabilidade clínica definido.

## Decisão

1. Estender `conteudos`, preservando `categoria`, `conteudo`,
   `classificacao_ids`, `aparece_na_home`, `status` e `ordem`, com ids dos
   administradores autor/editor/publicador e instante de publicação.
2. Todo conteúdo nasce `rascunho`, salvo decisão explícita de publicação no
   comando administrativo. Criar ou alterar para `publicado` registra publicador
   e instante.
3. O CRUD fica sob `/admin/conteudos` e exige usuário ativo autenticado por JWT
   com papel `admin` ou flag `is_superuser`.
4. Queries de diagnóstico e home filtram `status = publicado` e exigem autoria.
   A resposta ao paciente continua sem campos administrativos.
5. Não criar endpoint de exportação/rotulagem nesta entrega. O dataset permanece
   bloqueado até haver aprovação dos itens abaixo.

## Pré-condições para exportação

- base legal/consentimento e finalidade documentadas;
- conjunto mínimo de campos e anonimização validados por privacidade;
- responsável clínico, taxonomia e versionamento de rótulos definidos;
- controle de acesso, trilha de auditoria, retenção e descarte definidos;
- proibição de usar revisão clínica como rótulo de treino de forma implícita;
- teste de reidentificação e aprovação formal antes da primeira exportação.

## Consequências

Conteúdo pode ser preparado e revisado sem exposição acidental. Publicação passa
a ser atribuível, e registros legados migram como `rascunho`. O id de autoria vem
do usuário resolvido pelo JWT, nunca do corpo da requisição.
Não existe caminho executável para exportar dados enquanto as pré-condições estiverem
pendentes.
