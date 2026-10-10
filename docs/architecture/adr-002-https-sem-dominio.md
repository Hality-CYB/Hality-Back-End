# INFRA-02 — Decisão técnica de HTTPS sem domínio próprio
Data: 09/10/2026. Resultado do spike: critérios AC-I02-01, AC-I02-02 e AC-I02-03 documentados abaixo. Revisão por outra pessoa pendente, conforme Definition of Done do épico #145.

### Decisão
Usar **Caddy como reverse proxy**, com **hostname gratuito sslip.io apontando para o Elastic IP** e **certificado público do Let's Encrypt**, com emissão e renovação automáticas. Não é necessário comprar domínio. O acesso oficial da clínica será pelo hostname HTTPS, não pelo IP literal.

Padrão de hostname: `hality.<IP-com-hifens>.sslip.io`. Exemplo apenas ilustrativo: `hality.203-0-113-10.sslip.io`; o endereço é reservado para documentação e não deve ser usado no deploy. O valor real será definido após associação do Elastic IP em INFRA-06.

A decisão independe de o modelo ficar em uma ou duas EC2: front, API e proxy continuam na EC2 da aplicação.

### Alternativas avaliadas

| Alternativa | Vantagens | Limitações | Esforço relativo | Resultado |
| --- | --- | --- | --- | --- |
| HTTP no IP + câmera nativa/galeria | Configuração mínima; dispensa certificado | HTTP em IP público não é contexto seguro para getUserMedia; tráfego e autenticação sem TLS; pior experiência | Baixo | Descartada para produção |
| Certificado autoassinado | Não depende de CA pública nem DNS externo | Alertas e necessidade de instalar confiança em cada dispositivo; inadequado para acesso simples da clínica | Baixo na emissão, médio na operação | Reservada a testes locais controlados |
| sslip.io + Let's Encrypt + Caddy | Sem compra de domínio; certificado confiável; proxy, redirects e renovação no mesmo serviço | Dependência de DNS externo e limites de emissão da CA; IP deve permanecer fixo | Baixo/médio | Escolhida para o MVP |
| Let's Encrypt diretamente para IP | Certificado confiável sem serviço DNS externo | Certificados de 160 horas; exige cliente compatível, renovação e recarga automatizadas; maior complexidade com cliente separado | Médio | Alternativa futura se DNS externo se tornar impeditivo |

Certificados públicos para IP **já estão disponíveis**. O Let's Encrypt documenta Certbot >=5.4 para emissão via webroot, perfil shortlived, e necessidade de deploy hook para recarregar o servidor. A escolha por hostname decorre da operação mais simples, não da indisponibilidade dessa alternativa. Fontes: [disponibilidade e validade](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability/), [suporte Certbot](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/).

### Contrato de exposição para INFRA-08

- Origem única: `https://HOST_PUBLICO`.
- `/api` e `/api/*`: encaminhar para `api:8000`, preservando o caminho completo, inclusive `/api/v1`. Usar roteamento que não remova o prefixo (evitar handle_path).
- Demais caminhos: encaminhar para `frontend:3000`.
- HTTP redireciona para HTTPS; os desafios ACME são tratados pelo proxy.
- `NEXT_PUBLIC_API_URL=https://HOST_PUBLICO`, sem `/api` e sem barra final, passado no build. O cliente existente já acrescenta `/api/v1`.
- `NEXT_PUBLIC_API_MOCKING=disabled` no build.
- CORS com a origem HTTPS exata; validar cookies Secure, refresh de sessão e reconhecimento de HTTPS atrás do proxy. Confiar em cabeçalhos encaminhados somente pelo proxy.
- Preservar autorização atual das imagens e suportar uploads.
- Não publicar 3000, 8000, 5432 ou a API administrativa do Caddy (2019).

### Portas para INFRA-06

| Porta/protocolo | Origem | Finalidade |
| --- | --- | --- |
| 80/TCP | Internet | Redirect HTTP e desafio ACME HTTP-01 |
| 443/TCP | Internet | HTTPS da aplicação |
| 22/TCP | Somente IPs autorizados do time, se SSH for adotado | Administração; dispensável se houver SSM |
| 3000, 8000 e 5432/TCP | Rede Docker interna; sem publicação no host e sem ingresso público | Frontend, API e Postgres |

Não exigir 443/UDP neste MVP: operar com HTTPS sobre TCP e desabilitar HTTP/3 na configuração. Garantir saída para DNS e HTTPS/ACME. Se houver EC2 separada para o modelo, sua porta privada é decisão da INFRA-01, sem exposição pública por esta task.

### Operação e implementação posterior
Em INFRA-08, fixar versão/digest do Caddy, configurar explicitamente Let's Encrypt como emissor e persistir o diretório de dados de certificados/conta ACME em volume gravável. Caddy gerencia emissão, renovação e redirects, desde que DNS, portas e armazenamento persistente estejam corretos. Não usar tls internal em produção. [Documentação Caddy](https://caddyserver.com/docs/automatic-https).

O sslip.io resolve hostnames com IP embutido e admite emissão por HTTP-01; o serviço registra a possibilidade de rate limits. nip.io e sslip.io compartilham atualmente operação, portanto trocar entre eles não representa redundância independente. [Documentação do serviço](https://sslip.io/).

Antes da primeira emissão pública: conferir DNS para o Elastic IP e testar ACME staging; depois trocar para produção. Evitar recriar volumes ou repetir emissão desnecessariamente. Em falha de DNS/CA, investigar e manter certificados válidos; não recorrer a HTTP para login. Mudança de hostname requer novo certificado, rebuild do frontend e ajuste de CORS.

Na INFRA-08 validar redirects, cadeia confiável, roteamento, assets, login/refresh, uploads e persistência do certificado após recriação. A emissão pública depende do IP/portas provisionados; testes em dispositivos continuam fora do spike. HTTPS habilita o contexto seguro da câmera, mas não substitui consentimento do usuário ou compatibilidade do navegador. [MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

### Evidência dos critérios

- [x] AC-I02-01: quatro alternativas comparadas com vantagens, limitações e esforço.
- [x] AC-I02-02: abordagem escolhida e justificativa registradas.
- [x] AC-I02-03: proxy, roteamento e portas definidos para INFRA-06/08.
- [ ] DoD comum: revisão da entrega por outra pessoa.

Este spike não cria recursos AWS, não emite certificados e não implementa o compose. Essas ações pertencem às tasks posteriores.
