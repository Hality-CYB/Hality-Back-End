# Operação de backup e deploy

O destino é a EC2 da aplicação em `us-east-2`. A instância privada do modelo
não participa destes procedimentos. O backup diário ocorre às 06:00 UTC e um
novo backup é exigido antes de cada deploy de front ou back. Backups lógicos
são gravados em `backups/postgres/` no bucket privado do projeto, criptografados
por SSE-S3. A expiração começa após 30 dias; por ser um bucket versionado,
uma versão expirada pode permanecer não corrente por pelo menos mais um dia,
e a remoção física pelo S3 é assíncrona.

Os dumps contêm dados sensíveis de saúde. Nunca os exponha em logs, artefatos
do Actions, mensagens ou estações de trabalho não autorizadas. O backup não
inclui o frontend, arquivos locais, credenciais, roles globais do PostgreSQL,
certificados, imagens S3 ou configuração da instância. Defina recuperação
separada para estes itens. O dump é consistente no instante em que é criado;
alterações posteriores podem ser perdidas em uma restauração.

## Restauração sob controle de um administrador

1. Identifique um backup e a versão do banco, avalie impacto e preserve a
   instância atual. Prepare um PostgreSQL 17 isolado e acesso restrito ao dump.
2. Baixe o objeto por canal autenticado, em diretório temporário com `umask 077`.
   Valide o arquivo com `pg_restore --list` e restaure em um banco vazio usando
   `pg_restore --exit-on-error`. Para ensaio isolado sem as roles originais,
   use `--no-owner --no-acl`; isso não recupera proprietários e permissões.
3. Para recuperação real, um administrador deve recriar as roles necessárias
   e suas credenciais a partir de fonte segura, restaurar proprietários e
   privilégios conforme a configuração aprovada e verificar extensões,
   migrações, integridade e acesso da aplicação. Não copie senhas para logs.
4. Só o administrador decide quando substituir o banco em uso. Remova com
   segurança as cópias temporárias e registre o resultado sem dados pessoais.

## Falhas de deploy

O Actions consulta o resultado do comando SSM. Falha no backup interrompe antes
do build e da atualização. Falha de build, migration ou saúde interrompe o
fluxo e exige análise; nenhuma migration é revertida automaticamente. Localize
o comando pelo ID exibido no Actions e consulte o resultado no Systems Manager
com acesso restrito. Consulte o estado dos containers e os endpoints de saúde;
evite divulgar logs de aplicação, configuração e dados pessoais.

Os dois componentes usam `/var/lock/hality-deploy.lock`. Cada deploy confere
se o commit ainda é o HEAD remoto da `main` depois de adquirir a trava e após o
build. Os serviços são atualizados isoladamente: backend atualiza API e worker;
frontend atualiza apenas o frontend. São necessárias verificações funcionais
de compatibilidade entre versões quando houver alterações coordenadas de API.
