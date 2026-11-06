# Backend Django — Fator Brilho SaaS

API REST (Django 6 + DRF) que é a única fonte de verdade do produto: contas, dados da
estética, serviços, galeria, checkout e webhook do Asaas. O frontend Astro é camada de
apresentação e consome só estes endpoints.

## Como o deploy é desenhado

```
navegador do dono
   └─ https://fator-brilho.vercel.app  (Astro, SSR)
         │
         │  todo pedido em /api/* (menos /api/webhooks/*)
         └─ rewrite da Vercel ──► https://api-fator-brilho.vercel.app/api/*  (este Django)
```

A reescrita existe por um motivo concreto: o cookie do token (`fb_token`) é gravado sem
atributo `Domain=`, então ele nasce no host que a requisição pediu. Pedindo
`/api/...` no próprio host do frontend, o cookie fica em `fator-brilho.vercel.app` e o
SSR do Astro consegue repassá-lo no cabeçalho `cookie` — que é o que faz `/dashboard`
saber "está logado?" antes de devolver o HTML. Chamando o subdomínio `api-` direto, o
cookie seria host-only lá, o SSR nunca o veria, e todo painel logado cairia em
`/login`.

Duas consequências que valem como regra:

- **Em produção não existe `PUBLIC_API_URL` no frontend.** `src/lib/api.ts` devolve
  origem vazia (mesma origem) quando `import.meta.env.PROD`, de propósito. Definir a
  variável no projeto da Vercel não teria efeito nenhum, e é melhor assim do que ter um
  endereço que recria o bug.
- **No desenvolvimento local a reescrita não acontece.** O `astro dev` não lê
  `vercel.json`; o navegador chama `http://127.0.0.1:8010` direto, que é cross-origin
  por porta (daí o CORS do Django continuar servindo) mas mesmo host para cookie (porta
  não separa cookie, então a sessão local funciona do mesmo jeito).

## Rodando local

O ambiente é Python puro, sem Docker. Na sua máquina o `.env` da raiz do repositório não
é lido por este projeto — quem lê é `settings.py`, a partir de `backend-django/.env` ou
`backend-django/.env.local` (este vence, porque é o que o `vercel pull` escreve). Sem CLI
logada, o `.env.local` é só um arquivo que você cria na mão quando precisar rodar algo
contra o banco de produção (colar a string do Neon, por exemplo) — o dia a dia local roda
em SQLite e não precisa dele.

```bash
cd backend-django
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt
venv/Scripts/python.exe manage.py migrate
venv/Scripts/python.exe manage.py createsuperuser
venv/Scripts/python.exe manage.py runserver 8010
```

**Porta 8010, não 8000.** Medido nesta máquina: a 8000 está ocupada pelo Docker
(`com.docker.backend.exe`) respondendo Django de outro projeto, e o fallback do
`astro dev` não ia achar esta API. O valor está em três lugares que precisam bater:
o comando acima, `PUBLIC_API_URL=http://127.0.0.1:8010` no `.env` da raiz, e o padrão
em `src/lib/api.ts`. Há também `npm run api:dev` na raiz do repositório, que sobe isto
aqui.

Sem `DATABASE_URL_UNPOOLED` nem `DATABASE_URL` o projeto cai em SQLite (`db.sqlite3`,
gitignored). É o ambiente de dev esperado. Em produção isso está **bloqueado por código**:
o `settings.py` levanta `ImproperlyConfigured` quando `DJANGO_SECRET_KEY` existe (o sinal
de deploy) e nenhuma string de banco chegou, porque o filesystem do container é descartável
e os dados somem com a instância — foi exatamente o que aconteceu antes do bloqueio (a seção
"Migrações" acima e os testes em `GarantiaDeBancoEmDeploy`).

## Deploy na Vercel (pelo painel, sem CLI)

São dois projetos no mesmo repositório. O que separa um do outro é só o Root Directory.

### 1. Projeto do backend

1. Vercel → **Add New → Project** → conecte o repositório do GitHub (o mesmo do Astro).
2. **Settings → General → Root Directory = `backend-django`**. Isso é o que faz a Vercel
   ver `manage.py` e `requirements.txt` em vez do `package.json` da raiz.
3. Nome do projeto: `api-fator-brilho`, para o host sair `api-fator-brilho.vercel.app`.
   Se a Vercel der outro sufixo (algo como `api-fator-brilho-seunome.vercel.app`),
   **leia o domínio real** em Settings → Domain Names e ajuste a `destination` do
   `vercel.json` do Astro — a linha é aquela, não existe variável que alimente ela.
4. **Framework.** Não é mais detecção: o `Dockerfile.vercel` deste diretório vence a
   detecção automática de framework (a Vercel preferiria Django pelo `manage.py` e o
   entrypoint `WSGI_APPLICATION`), e o `vercel.json` declara `{"framework": "container"}`
   os dois juntos. O que mudou em relação a esta seção, que descrevia o modo serverless:
   não há mais preset de Python, nem `buildCommand`, nem `functions`.
5. **Python 3.13** vem de `.python-version`, que é o que a base da imagem usa
   (`FROM python:3.13-slim`). Localmente seu 3.15 continua igual: o arquivo só é lido pelo
   build da Vercel — e por `pyenv`/`uv`, se você recriar um ambiente dentro de
   `backend-django`.
6. **Estáticos.** Em container a Vercel **não** roda `collectstatic` nem serve do CDN —
   isso era comportamento do modo serverless. Hoje o `RUN collectstatic --noinput` do
   `Dockerfile.vercel` embute os arquivos na imagem e o **WhiteNoise** serve `/static` em
   tempo de execução (com `whitenoise.middleware.WhiteNoiseMiddleware` logo depois do
   `SecurityMiddleware`, como manda a doc). Foi medido: antes disso o `/admin` subia sem
   CSS, com 404 em `/static/admin/css/base.css`. `staticfiles/` continua gitignored.
7. **Processo.** Não há mais `functions`/`maxDuration` no `vercel.json`: o Gunicorn
   (`gunicorn==26.2.0`, pinado no `requirements.txt`) escuta na porta 80 e o tempo de
   resposta é o do container, não o limite de uma Serverless Function. O `idle timeout` de
   produção é ~5 minutos: depois disso a instância morre e o próximo pedido paga o cold
   start (~5s medidos).

### 2. Banco Postgres pelo Marketplace

1. No projeto do backend: **Storage → Create Database → Neon (Storage for Postgres)**.
   O botão muda de nome com o tempo — o que importa é escolher um provedor Postgres do
   Marketplace; o Neon é a opção recomendada hoje pela própria Vercel (a nota oficial:
   *"Vercel Postgres is no longer available ... For new projects, install a Postgres
   integration from the Marketplace"*).
2. Selecione a região mais perto dos teus clientes (o produto é Brasil; o Asaas também).
3. Ao terminar, a integração escreve sozinha as variáveis no projeto. Nomes que ela
   injeta, conforme a doc do Neon:

   | Variável | O que é |
   | --- | --- |
   | `DATABASE_URL` | string **pooled** (PgBouncer em modo transação) |
   | `DATABASE_URL_UNPOOLED` | string **direta** |
   | `PGHOST`, `PGHOST_UNPOOLED`, `PGUSER`, `PGDATABASE`, `PGPASSWORD` | pedaços soltos |
   | `POSTGRES_*` | legado, compatibilidade com templates do antigo Vercel Postgres |

4. **Este projeto usa a direta**, e isso é decisão tomada, não detalhe esquecido: ao abrir
   conexão o Django executa `SELECT set_config('TimeZone', %s, false)`
   (`django/db/backends/postgresql/operations.py`, `set_time_zone_sql`) com
   `TIME_ZONE = "America/Sao_Paulo"` + `USE_TZ = True`, e a doc do Neon lista
   *"`SET` / `RESET` (session variables)"* como **não suportado** na conexão pooled — o
   ajuste não sobreviveria à volta do server connection para o pool. O código lê
   `DATABASE_URL_UNPOOLED` quando ela existe e só cai em `DATABASE_URL`/SQLite quando não
   existe (`settings.py`, bloco `_URL_DO_BANCO`). Então **não edite nem apague** a variável
   da integração; ela já vem certa.
   - Consequência que você precisa ter em mente: conexão direta tem teto de clientes por
     plano. `CONN_MAX_AGE=0` está lá de propósito — cada invocação abre e fecha a própria
     conexão em vez de segurá-la entre execuções.
   - Preview: a integração cria um **branch** do Neon por deployment de preview, com
     valores próprios. Um banco de teste à parte, sem risco de escrever no dado dos
     clientes — mas também sem os dados: o login de teste no preview é outro cadastro.
5. Não misture: a doc diz que a integração "Vercel-managed" do Neon não pode coexistir
   com a "Neon-managed" no mesmo projeto. Instale uma.

### 3. Variáveis antes do primeiro build

Preencha tudo em **Settings → Environment Variables** antes do primeiro build (tabela e
motivos na seção seguinte). Não existe `PUBLIC_API_URL` aqui nem no projeto Astro — em
produção a chamada é same-origin por causa da reescrita.

### 4. Migrações: no boot do container

**Esta seção descrevia o modo serverless (`buildCommand`) e foi reescida.** No runtime de
container não existe Build Command: o `vercel.json` deste diretório só declara
`{"framework": "container"}`, e quem manda na subida é o `CMD` do `Dockerfile.vercel`.

A ordem do `CMD` é `aviso → migrate → cria_admin → gunicorn`. O `migrate` roda com
`;` e não com `&&`: se ele falhar, o servidor sobe mesmo assim e o erro fica legível no
log em vez de o container entrar em loop de reinício. (Com uma exceção que é bom saber:
sem `DATABASE_URL` o `settings.py` levanta `ImproperlyConfigured` antes de qualquer
coisa, e aí o container **não** sobe. É intenção, porque a alternativa medida foi o
deploy escrever clientes num SQLite que morria a cada instância.)

Idempotência confirmada em produção, não só local: a primeira instância de um banco novo
loga `Applying ... OK` para todas as migrações; toda instância seguinte, em qualquer
deploy, loga `No migrations to apply.`.

O preço de rodar no boot e não no build: **cada** instância nova executa o `migrate`, e no
autoscale duas podem executar juntas. O Postgres serializa pelo lock da tabela
`django_migrations`, então a segunda fica esperando (segundos) em vez de corromper nada.

### 5. O primeiro superusuário do /admin

Não dá para usar o `createsuperuser --noinput` oficial dentro do `CMD`: a partir do
segundo deploy ele devolve `Error: That username is already taken.` e derrubaria a
subida. Por isso existe `core/management/commands/cria_admin.py`, que o `CMD` chama em
todo boot e que é **silenciosamente inofensivo** quando não tem nada a fazer.

**Você não precisa de `venv` na sua máquina.** O superusuário é criado em produção, pelo
container:

1. **Settings → Environment Variables** do projeto `api-fator-brilho`, escopo
   **Production**, tipo **Secret**:

   | Variável | O que colocar |
   | --- | --- |
   | `DJANGO_SUPERUSER_EMAIL` | o e-mail com que você vai entrar no `/admin` |
   | `DJANGO_SUPERUSER_PASSWORD` | a senha (mínimo 8 caracteres; ela nunca aparece no log) |

2. **Deploy** (commit qualquer, ou Redeploy no painel). O `CMD` roda o comando sozinho.

3. **Leia o resultado** em **Observability → Runtime Logs**, filtrando por `cria_admin:`:

   | Linha no log | O que aconteceu |
   | --- | --- |
   | `superusuário dono@exemplo.com criado` | pronto — entre em `https://api-fator-brilho.vercel.app/admin` |
   | `dono@exemplo.com já é superusuário, nada a fazer` | deploy idempotente, está tudo certo |
   | `DJANGO_SUPERUSER_EMAIL/DJANGO_SUPERUSER_PASSWORD não definidas` | as variáveis não estão no escopo **Production** |
   | `já existe como conta comum e NÃO foi promovida` | o e-mail já tem conta do painel; veja logo abaixo |

4. Depois do primeiro acesso, **troque a senha no `/admin`** (Users → você → Change
   password) e pode apagar `DJANGO_SUPERUSER_PASSWORD` do painel. O comando não reescreve
   a senha de quem já existe, então nada quebrará nos deploys seguintes.

Três decisões de projeto, para não parecerem acidente:

- **A identidade é o e-mail minúsculizado.** `DJANGO_SUPERUSER_EMAIL=Dono@Exemplo.com`
  cria a conta `dono@exemplo.com` — a mesma regra do `/api/auth/registro/`, que grava
  `username=email`. Sem isso coexistiriam duas contas do mesmo dono, uma com staff e
  outra sem.
- **Deploy não promove ninguém.** Se o e-mail já tem conta comum criada pelo painel, o
  comando grava um aviso no **stderr** e não toca em `is_staff`/`is_superuser`. Dar
  acesso de administrador é decisão de quem escreve a variável, não efeito colateral de
  um push. A saída é usar outro e-mail na `DJANGO_SUPERUSER_EMAIL`.
- **Sem variável não é erro.** O comando sai com código 0. Um deploy sem `DJANGO_*` no
  ambiente não pode deixar de subir por causa de uma variável opcional.

### 6. Variáveis no projeto do Astro

Nada de segredo novo: o frontend em produção não lê chave de API nenhuma. As variáveis do
Supabase (`PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`)
continuam necessárias no projeto Astro até o webhook `/api/webhooks/asaas` ser aposentado —
é o handler que ainda escreve no banco antigo.

## Variáveis de ambiente

Nomes como estão em `fatorbrilho/settings.py`. Não coloque segredo neste repositório —
`.env` e `.env.local` de `backend-django` estão no `.gitignore`.

| Variável | Em produção | Valor |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | obrigatória | gerada; sem ela o `SECRET_KEY` cai no literal de dev |
| `DJANGO_DEBUG` | não defina (ou `false`) | é o que liga `Secure`/`SameSite=None` no cookie e o `ALLOWED_HOSTS` rígido |
| `DJANGO_ALLOWED_HOSTS` | obrigatória | `api-fator-brilho.vercel.app,fator-brilho.vercel.app` — os dois, por motivo explicado logo abaixo |
| `DATABASE_URL` | **cria sozinha** | string pooled do Postgres do Marketplace — o projeto não lê esta quando existe a de baixo |
| `DATABASE_URL_UNPOOLED` | **cria sozinha** | string direta; é a que `settings.py` prefere, e é por isso que a integração não deve ser substituída por uma `DATABASE_URL` colada à mão |
| `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` | opcional | usadas pelo `cria_admin` da seção 5, que o `CMD` roda em todo boot. Sem elas o comando só imprime um aviso e sai com 0. O `createsuperuser` oficial **não** serve aqui: dá erro no segundo deploy e derrubaria o container |
| `SITE_URL` | obrigatória | `https://fator-brilho.vercel.app` — é a base dos links `?pagamento=sucesso/cancelado` do checkout |
| `ASAAS_API_KEY` | obrigatória | começa com `$`: leia cru, sem `export` de shell (dotenv resolve isso) |
| `ASAAS_WEBHOOK_TOKEN` | obrigatória | o mesmo token configurado no painel do Asaas |
| `CORS_ALLOWED_ORIGINS` | opcional | o padrão (`http://localhost:4321,https://fator-brilho.vercel.app`) já serve; em produção o navegador é same-origin e não passa por aqui |
| `TOKEN_COOKIE` / `TOKEN_COOKIE_AGE` | opcional | padrão `fb_token` / 30 dias |

Sobre `DJANGO_ALLOWED_HOSTS`: o valor mínimo é o host do próprio backend
(`api-fator-brilho.vercel.app`), porque é ele que aparece quando o Asaas chama o webhook
direto. Para as chamadas que vêm pela reescrita do Astro, no entanto, **não medimos** qual
`Host` chega na função — depende de como a Vercel reescreve para outro projeto, e isso
só é verificável no primeiro deploy (o log da função mostra). O conselho prático é
colocar os dois: `api-fator-brilho.vercel.app,fator-brilho.vercel.app`. Se der 400
`DisallowedHost`, a lista é o lugar de corrigir — não o `DEBUG`.

Se você quiser que os **preview** da Vercel chamem esta API, o único jeito prático é um
sufixo (`.vercel.app`), porque o hostname de preview é gerado. Aceitar `.vercel.app` abre
qualquer projeto da Vercel como Host válido para esta API — a API já é pública por natureza
e o `/admin` continua protegido por login Django + `SECRET_KEY`, mas é um troca-valores
seu, não uma economia invisível.

`SITE_URL` existe porque painel e API são domínios diferentes. Sem ela o código tenta o
cabeçalho `Origin` da request, que a reescrita tende a repassar — mas depender de um header
para montar o link de pagamento é arriscado demais para não ter variável, e é por isso que a
resposta sem base é um 500 com instrução (`core/views.py:399`).

## O que fica no projeto Astro

`vercel.json` na raiz do frontend:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "rewrites": [
    {
      "source": "/api/:path((?!webhooks/).*)",
      "destination": "https://api-fator-brilho.vercel.app/api/:path*"
    }
  ],
  "headers": [
    {
      "source": "/api/publico/:path*",
      "headers": [{ "key": "x-vercel-enable-rewrite-caching", "value": "1" }]
    }
  ]
}
```

- O lookahead `(?!webhooks/)` não é enfeite: `/api/webhooks/asaas` ainda é uma rota do
  Astro (veja "Ordem de troca do webhook" abaixo) e precisa continuar sendo servido por
  ele. Quando aquela rota for apagada, a exclusão pode ir junto.
- Trocar o domínio do backend é editar **esta** linha. Não há variável de ambiente que
  alimente `destination`.
- O header `x-vercel-enable-rewrite-caching` vale só para `/api/publico/*`: é o que faz
  o `Cache-Control: public, max-age=60, s-maxage=300` que a `PublicoView` manda ser
  respeitado pelo CDN. Os endpoints autenticados ficam de fora de propósito — nada de
  cache de CDN em resposta que depende de cookie.

### O que já foi medido e o que só o deploy mede

O `astro build` **não** copia esse `vercel.json` para a saída: depois de rodar o build,
`.vercel/output/config.json` tem só as rotas que o `@astrojs/vercel` gera (o `/_astro`,
`handle: filesystem`, `^/api/webhooks/asaas`, as páginas e o catch-all), e o `rewrite` não
aparece. Isso é comportamento do adaptador, confirmado no código dele — ele escreve o
`config.json` a partir das próprias rotas e chama `getTransformedRoutes` com
`rewrites: []` fixo (`node_modules/@astrojs/vercel/dist/index.js`, bloco que gera o
`config.json`).

Quem aplica o `vercel.json` é a plataforma, na hora do build a partir do repositório:
*"The routing configuration ... captures the rewrites, redirects, and headers from your
framework configuration or `vercel.json` file"* (Vercel, *How Vercel builds your
application*, atualizado 2026-09-03). Ou seja, o rewrite existe no deploy feito pelo Git —
mas essa é justamente a parte que não dá para provar localmente: `vercel build` recusa
rodar sem Project Settings (`Error: [BUILD_PROJECT_SETTINGS_REQUIRED] No Project Settings
found locally`), e obtê-las exige `vercel pull` com o teu token. Não fiz isso.

Consequência prática: o `curl` do checklist que verifica o rewrite é obrigatório, não
opcional. Se ele devolver HTML do Astro em vez do JSON do Django, o plano B é o mesmo
mecanismo por outra porta — Settings → Routing → Rewrite no painel do projeto Astro, com
`Source` `/api/:path((?!webhooks/).*)` e `Destination` a URL do backend — que alimenta a
mesma configuração de roteamento e não depende do arquivo.

## Ordem de troca do webhook do Asaas

O painel do Asaas ainda aponta para o handler do Astro
(`src/pages/api/webhooks/asaas.ts`), que hoje é o único código do frontend que ainda fala
com o Supabase — ele é autossuficiente exatamente para os três arquivos antigos do
Supabase terem podido ser apagados. A sequência segura:

1. Backend Django no ar com `ASAAS_WEBHOOK_TOKEN` igual ao do painel.
2. No painel do Asaas, trocar a URL para `https://api-fator-brilho.vercel.app/api/webhooks/asaas/`.
3. Validar com uma assinatura de teste que o plano ativa no Django (o handler é o mesmo
   raciocínio: confere `GET /payments?checkoutSession=` antes de escrever).
4. Só então apagar `src/pages/api/webhooks/asaas.ts`, desinstalar `@supabase/ssr` e
   `@supabase/supabase-js` e remover `PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` do `.env` e do projeto Astro na Vercel.

Até o passo 2, os dois canais de ativação estão vivos. Os dois são idempotentes (escrevem
o mesmo `plano_ativo` / `asaas_customer_id`), mas escrevem em bancos diferentes — é mais um
motivo para não deixar essa janela aberta mais do que o necessário.

## Migração de dados (como repetir)

```bash
python scripts/exporta_supabase.py            # lê SUPABASE_DB_URL do .env da raiz, escreve dump/supabase.json
venv/Scripts/python.exe manage.py importa_supabase --apenas-relatorio
venv/Scripts/python.exe manage.py importa_supabase
```

`dump/` é gitignored porque contém CPF, e-mail e id de cliente do Asaas — e hoje ele nem
existe na máquina: o `dump/supabase.json` que sobrou da primeira importação foi apagado,
então o `exporta_supabase.py` precisa rodar antes do importador. O importador não destrói
nada que já existe: recusa slug ocupado, dono com duas estéticas e órfã sem destino
explícito (`--importar-orfas <e-mail> [--orfa <id>]`). Hash `$2a$` do Supabase ganha o
prefixo `bcrypt$` para o Django reconhecer; senha nova é PBKDF2.

Para importar no banco de **produção** em vez do SQLite local, aponte a conexão direta do
Neon para uma variável chamada `DATABASE_URL_UNPOOLED` no ambiente antes de rodar os dois
últimos comandos — é exatamente a mesma variável que o `settings.py` prefere na Vercel. Se
você rodar com `DATABASE_URL` apenas, vai escrever no banco da mesma forma, mas aí a
conexão passa pelo pool transacional e os `SET` de sessão da ferramenta não se sustentam.

## Gates

```bash
venv/Scripts/python.exe manage.py test core   # 90 testes
venv/Scripts/python.exe manage.py check
venv/Scripts/python.exe scripts/contraste.py  # contraste WCAG do admin
```

A escolha entre as duas strings do banco é coberta por `GarantiaDeBancoEmDeploy`, que roda
cada caso em `subprocess` (recarregar `settings` dentro da suíte derrubaria o banco de
teste). A tabela abaixo é a medição histórica, feita na mão antes desses testes existirem,
e continua valendo:

| Ambiente | `_URL_DO_BANCO` | `DATABASES["default"]["ENGINE"]` |
| --- | --- | --- |
| sem nenhuma das duas | `DATABASE_URL` | `django.db.backends.sqlite3` |
| com as duas (é o que a integração do Neon entrega) | `DATABASE_URL_UNPOOLED` | `django.db.backends.postgresql`, host = endpoint **direto** |
| só com `DATABASE_URL` | `DATABASE_URL` | `django.db.backends.postgresql` |

## Checklist do primeiro deploy

Na ordem, porque cada item assume o anterior.

**Backend (projeto `api-fator-brilho`)**

1. Root Directory `backend-django`. O Framework Preset não decide mais nada: a presença
   do `Dockerfile.vercel` vence a detecção (item 4 da seção 1).
2. Banco do Marketplace criado **e vinculado ao projeto**, com `DATABASE_URL` **e**
   `DATABASE_URL_UNPOOLED` aparecendo em Settings → Environment Variables (criadas pela
   integração; não coladas por você). *Vinculado* é a palavra: a integração instalada no
   time sem projeto selecionado não injeta nada, e o sintoma medido foi o banco voltar a
   zero a cada instância. Confira com `curl` + dois registros seguidos: os `id` têm de
   incrementar entre deploys e depois de 6 minutos parado.
3. Variáveis da tabela preenchidas em Production. `DJANGO_ALLOWED_HOSTS` com os dois hosts.
4. Deploy. O `migrate` **não** aparece no Build Output Log — ele roda no boot, então vá em
   **Observability → Runtime Logs** do deployment e procure `Applying ... OK` (banco novo)
   ou `No migrations to apply.` (todo boot seguinte, inclusive em instância diferente).
   Se o container não subir com `ImproperlyConfigured`, falta uma das duas strings.
5. Superusuário pelas duas variáveis da seção 5, com o resultado lido no mesmo
   Runtime Logs filtrando por `cria_admin:`. Não há mais Build Command temporário para
   reverter.

```bash
curl -s https://api-fator-brilho.vercel.app/api/planos/   # {"ok":true,"planos":[...]}
```

6. Este `curl` é o único teste do backend puro. Se ele responder `DisallowedHost`, some com
   a variável `DJANGO_ALLOWED_HOSTS` errada; se responder 500 com "Falta SITE_URL", a
   variável não está no escopo Production.

**Frontend (projeto Astro)**

7. Deploy com Root Directory na raiz. Sem `PUBLIC_API_URL` — em produção a origem é vazia
   de propósito.

```bash
curl -s https://fator-brilho.vercel.app/api/planos/          # mesma resposta => rewrite ativo
curl -s https://fator-brilho.vercel.app/api/webhooks/asaas/  # resposta do Astro, não do Django
```

8. O primeiro `curl` é o que fecha a dúvida documentada em "O que já foi medido e o que só
   o deploy mede". Se vier HTML do Astro (404), registre o rewrite em Settings → Routing →
   Rewrite e faça um novo deploy.
9. No navegador: logar, e no DevTools confirmar que o cookie `fb_token` está gravado em
   `fator-brilho.vercel.app` (não no subdomínio `api-`), e que `/dashboard` abre logado na
   primeira. As duas últimas são as que importam, e nenhuma delas é verificável antes de
   estar na Vercel: rewrite de origem externa e escopo de cookie são comportamento da
   plataforma e do navegador, não do `astro dev`.
10. Site público de um cliente: abra `/site/<slug>` e confirme no DevTools que a resposta de
    `/api/publico/<slug>/` traz `cache-control: public, max-age=60, s-maxage=300` **e** um
    `x-vercel-cache: HIT` na segunda visita. Sem o header `x-vercel-enable-rewrite-caching`
    o CDN guarda a resposta de um rewrite externo só se o projeto for novo — se der sempre
    `MISS`, é esse o motivo.

Nenhum desses passos toca no Asaas. A troca da URL do webhook continua sendo a sequência
própria da seção "Ordem de troca do webhook do Asaas", e é ela que libera a remoção do
Supabase.
