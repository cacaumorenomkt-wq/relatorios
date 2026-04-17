# Guia de Setup — Meta API para o Dashboard

## Visão geral do que vamos fazer

1. Criar um App no Meta for Developers
2. Conseguir os tokens de acesso de longa duração de cada cliente
3. Pegar os IDs das páginas e contas de anúncio
4. Preencher o `meta_config.json`
5. Rodar o script e popular o dashboard

---

## PARTE 1 — Criar o App no Meta for Developers

### Passo 1
Acesse: https://developers.facebook.com/apps  
Clique em **"Criar app"**

### Passo 2 — Tipo do app
Selecione **"Business"** e clique em Avançar.

### Passo 3 — Detalhes do app
- **Nome:** `Dashboard Agência` (ou o nome da sua agência)
- **E-mail de contato:** seu e-mail
- **Business Manager:** selecione o BM da sua agência
- Clique em **"Criar app"**

### Passo 4 — Adicionar produtos
No painel do app, clique em **"Adicionar produto"** e adicione:
- **Facebook Login** → clique em Configurar
- **Instagram Graph API** → clique em Configurar
- **Marketing API** → clique em Configurar

---

## PARTE 2 — Configurar permissões (Scopes)

No menu lateral, vá em **Facebook Login > Configurações**.

Na seção **"Client OAuth Settings"**, adicione estas permissões:
```
pages_read_engagement
pages_show_list
read_insights
instagram_basic
instagram_manage_insights
ads_read
ads_management
business_management
```

Salve as alterações.

---

## PARTE 3 — Gerar Tokens de Acesso

### Para cada cliente, você precisará de um Token de Longa Duração.

**Passo 1 — Obter token de curta duração**

Acesse o **Graph API Explorer**:  
https://developers.facebook.com/tools/explorer/

- Selecione seu app no canto superior direito
- Clique em **"Gerar token de acesso"**
- Marque as permissões listadas acima
- Autorize com a conta do cliente (ou peça que o cliente autorize)
- Copie o token gerado

**Passo 2 — Converter para token de longa duração (60 dias)**

No mesmo Graph API Explorer, faça esta chamada:

```
GET /oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id=SEU_APP_ID
  &client_secret=SEU_APP_SECRET
  &fb_exchange_token=TOKEN_CURTA_DURACAO
```

> App ID e App Secret ficam em: **Configurações do App > Básico**

O token retornado dura 60 dias. Salve em `meta_config.json`.

**Passo 3 — Obter token permanente da Página**

Com o token de longa duração do usuário, faça:

```
GET /me/accounts?access_token=TOKEN_LONGA_DURACAO
```

Isso retorna todas as páginas com seus tokens permanentes (não expiram enquanto o admin não revogar).

---

## PARTE 4 — Pegar os IDs necessários

### ID da Página do Facebook
```
GET /me/accounts?access_token=TOKEN_USUARIO
```
Procure o campo `"id"` da página desejada.

### ID da Conta do Instagram Business
```
GET /{page_id}?fields=instagram_business_account&access_token=TOKEN_DA_PAGINA
```
O valor em `instagram_business_account.id` é o Instagram Business ID.

### ID da Conta de Anúncios (Ad Account)
No Meta Business Manager:
- Acesse: https://business.facebook.com/settings/ad-accounts
- Clique na conta de anúncios do cliente
- O ID aparece no formato: `act_XXXXXXXXXX`

---

## PARTE 5 — Preencher o meta_config.json

Abra o arquivo `meta_config.json` e substitua os valores:

```json
{
  "clientes": [
    {
      "nome": "Nome Real do Cliente",
      "ativo": true,
      "instagram": {
        "page_id": "123456789",
        "instagram_business_id": "987654321",
        "access_token": "EAABsbCS..."
      },
      "facebook": {
        "page_id": "123456789",
        "access_token": "EAABsbCS..."
      },
      "ads": {
        "ad_account_id": "act_123456789",
        "access_token": "EAABsbCS..."
      }
    }
  ]
}
```

> ⚠️ **Atenção:** A página do Facebook e o Instagram Business geralmente compartilham o mesmo `page_id` e `access_token`.

---

## PARTE 6 — Instalar dependências e rodar

### Instalar bibliotecas necessárias
```bash
pip install requests
```

### Rodar o script
```bash
# Últimos 30 dias de todos os clientes
python fetch_meta.py

# Apenas um cliente
python fetch_meta.py --cliente "Nome do Cliente"

# Período específico
python fetch_meta.py --inicio 2026-03-01 --fim 2026-03-31

# Últimos 60 dias
python fetch_meta.py --dias 60
```

### O que acontece
O script cria uma pasta `dados_meta/` com um CSV por cliente.  
Exemplo: `dados_meta/cliente_nome_2026-03-01_a_2026-03-31.csv`

### Carregar no Dashboard
1. Abra o `dashboard-campanhas.html` no navegador
2. Clique em **"Upload CSV / Excel"**
3. Selecione o CSV gerado
4. O dashboard popula automaticamente com os dados reais

---

## PARTE 7 — Automação (rodar todo dia/semana)

### No Windows — Agendador de Tarefas
1. Abra o **Agendador de Tarefas** (Task Scheduler)
2. Clique em **Criar Tarefa Básica**
3. Nome: `Dashboard Meta - Coleta Diária`
4. Gatilho: **Diariamente** (sugestão: 7h da manhã)
5. Ação: **Iniciar programa**
   - Programa: `python`
   - Argumentos: `fetch_meta.py --dias 30`
   - Pasta: caminho completo onde você salvou os arquivos

### No Mac/Linux — Cron
```bash
# Editar crontab
crontab -e

# Adicionar esta linha (roda todo dia às 7h)
0 7 * * * cd /caminho/para/pasta && python fetch_meta.py --dias 30
```

---

## Renovação dos Tokens

| Tipo | Duração | Como renovar |
|------|---------|--------------|
| Token de página | Permanente | Não precisa renovar |
| Token de usuário longa duração | 60 dias | Repetir o Passo 2 da Parte 3 |
| Token de sistema (Business) | 60 dias ou permanente | Via Business Manager |

> **Dica:** Configure um lembrete no calendário para renovar os tokens de usuário a cada 50 dias.

---

## Problemas comuns

**Erro: "OAuthException: Invalid OAuth access token"**  
→ Token expirado. Gere um novo token de longa duração.

**Erro: "PermissionError: (#10) Not enough permission"**  
→ A permissão necessária não foi autorizada. Repita o processo de geração de token marcando todas as permissões.

**Nenhum dado de Ads retornado**  
→ Verifique se o `ad_account_id` começa com `act_` e se a conta está ativa.

**Dados de Instagram não aparecem**  
→ Confirme que a conta do Instagram está configurada como **Business** ou **Creator** e vinculada à Página do Facebook.

---

*Dúvidas? Compartilhe a mensagem de erro e eu ajudo a resolver.*
