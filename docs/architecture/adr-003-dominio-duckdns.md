# ADR-003 - Domínio público Duck DNS

Data: 03/11/2026. Substitui a decisão de hostname da [ADR-002](adr-002-https-sem-dominio.md), mantendo seu histórico e o contrato de exposição.

### Decisão

O endereço canônico é **https://hality-cyb.duckdns.org**. Após verificar o servidor EC2 e a associação do Elastic IP fixo `18.221.65.196`, a migração ocorreu por corte direto: `18-221-65-196.sslip.io` deixou de ser servido, sem transição com os dois hosts.

### Operação

- No `.env` do servidor, configurar:

  ```dotenv
  DOMAIN=hality-cyb.duckdns.org
  PUBLIC_URL=https://hality-cyb.duckdns.org
  CORS_ORIGINS=["https://hality-cyb.duckdns.org"]
  GOOGLE_REDIRECT_URI=https://hality-cyb.duckdns.org/api/v1/auth/google/callback
  GOOGLE_FRONTEND_REDIRECT_URL=https://hality-cyb.duckdns.org/login/google
  IDENTITY_TOKEN_BASE_URL=https://hality-cyb.duckdns.org
  ```

- Reconstruir o frontend, pois `PUBLIC_URL` é argumento de build, e recriar os serviços que recebem as variáveis alteradas.
- O Caddy obteve certificado público Let's Encrypt via HTTP-01. Com o Elastic IP fixo, não é necessário token Duck DNS; manter DNS e portas 80 e 443 acessíveis e preservar os volumes de certificados.
- Na mesma mudança, `ENVIRONMENT` passou a `production` e o envio de e-mail usa Resend. O responsável pelo cliente Google deve cadastrar o callback exato acima; o cadastro estava pendente após o corte.
- Cookies são específicos do host: usuários precisam entrar novamente. Links antigos continuam apontando para o host anterior.

### Rollback

Restaurar o `.env` anterior protegido, reconstruir o frontend com o `PUBLIC_URL` anterior e recriar os serviços afetados. Confirmar roteamento e certificado do host anterior e o cadastro do callback correspondente no Google; preservar os volumes e validar o acesso após a reversão.
