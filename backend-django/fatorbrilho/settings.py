"""
Configurações do projeto Fator Brilho (backend Django).

Tudo que é segredo ou escolha de ambiente vem de variável de ambiente. Na Vercel
isso é injetado pelo painel/integração do banco; localmente o `vercel pull` salva
em `.env.local` e o `load_dotenv` abaixo lê esse arquivo no `manage.py`.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Ordem importa: .env.local é o que o `vercel pull` escreve, e ele precisa vencer o
# .env genérico caso os dois existam na mesma máquina.
load_dotenv(BASE_DIR / ".env.local")
load_dotenv(BASE_DIR / ".env")


def _bool(nome: str, padrao: bool = False) -> bool:
    return os.getenv(nome, str(padrao)).strip().lower() in {"1", "true", "yes", "on"}


def _lista(nome: str, padrao: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(nome, padrao).split(",") if item.strip()]


# SECURITY WARNING: a chave de produção vem do painel da Vercel (DJANGO_SECRET_KEY).
# O literal abaixo é marcador de desenvolvimento e não serve para nada além de fazer
# `manage.py runserver` subir sem configuração.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-not-a-secret-change-me")

DEBUG = _bool("DJANGO_DEBUG")

# Em produção o Django não aceita Host vazio: sem esta lista o domínio da Vercel
# devolve 400. O nome do host do projeto entra por DJANGO_ALLOWED_HOSTS.
ALLOWED_HOSTS = _lista(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,testserver",
)

INSTALLED_APPS = [
    # Jazzmin ANTES do contrib.admin: é assim que ele substitui os templates do
    # admin (ordem de INSTALLED_APPS define qual template wina).
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise imediatamente após o SecurityMiddleware, como manda a doc
    # oficial: é o posição mais alta possível que ainda vem antes de qualquer
    # middleware que possa reescrever a URL. No runtime de container da Vercel
    # nada mais serve /static (o CDN do modelo serverless antigo não existe
    # aqui), então é ele que responde o CSS/JS do admin a partir do STATIC_ROOT.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # O mais alto possível, antes do CommonMiddleware, como manda a doc do
    # django-cors-headers: é o que responde o preflight OPTIONS sem tocar na view.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fatorbrilho.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fatorbrilho.wsgi.application"

# Banco. Sem variável de conexão (desenvolvimento no notebook, sem Docker de propósito)
# cai em SQLite, que é arquivo local e some com o `db.sqlite3` no .gitignore.
#
# A integração do Neon no Marketplace injeta duas strings para o mesmo banco:
# `DATABASE_URL` (pool PgBouncer em modo transação) e `DATABASE_URL_UNPOOLED`
# (conexão direta). Preferimos a direta por motivo medido, não por hábito: ao abrir
# uma conexão o Django executa `SELECT set_config('TimeZone', %s, false)`
# (django/db/backends/postgresql/operations.py, set_time_zone_sql) e a documentação
# do Neon lista "SET / RESET (session variables)" como não suportado no pool
# transacional. Com TIME_ZONE="America/Sao_Paulo" + USE_TZ=True aqui embaixo, isso
# significa que o fuso da sessão não persistiria de uma transação para a outra.
# Conexão direta tem limite de clientes por plano — que `conn_max_age=0` ajuda: cada
# invocação abre e fecha a própria conexão em vez de segurá-la entre execuções.
_URL_DO_BANCO = "DATABASE_URL_UNPOOLED" if os.getenv("DATABASE_URL_UNPOOLED") else "DATABASE_URL"

DATABASES = {
    "default": dj_database_url.config(
        env=_URL_DO_BANCO,
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Lista explícita por um motivo só: o `BCryptPasswordHasher` (o `$2a$10$` que o
# Supabase guardava em auth.users.encrypted_password) não está no padrão do Django 6,
# que traz PBKDF2, Argon2, BCryptSHA256 e Scrypt. Sem esta linha, o hash importado de
# b.liraa@gmail.com não é reconhecido por ninguém e a conta dele não consegue entrar
# com a senha que já existe.
#
# A ordem importa: o primeiro é o algoritmo das senhas NOVAS (PBKDF2, padrão do
# Django, sem dependência extra). O hash $2a$ importado continua sendo verificado pelo
# BCryptPasswordHasher, que está mais abaixo na lista — é isso que mantém a senha que
# já existe funcionando no primeiro login depois da migração.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LANGUAGE_CODE = "pt-br"

TIME_ZONE = "America/Sao_Paulo"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

# Realidade atual (runtime de container na Vercel): a imagem roda
# `python manage.py collectstatic --noinput` na construção (Dockerfile.vercel)
# e o WhiteNoise serve o resultado em /static a cada requisição. O comentário
# antigo dizia que "a Vercel roda o collectstatic sozinha e serve do CDN" --
# isso era do modelo serverless e não vale mais; sem o collectstatic na imagem
# o /admin renderiza sem CSS (404 em /static/admin/css/base.css).
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # A ordem é a ordem de tentativa. Primeiro o cookie (navegador do painel), depois
    # o header Authorization (curl, testes, chamadas de servidor para servidor).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.authentication.TokenCookieAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Erro em JSON sempre: estas rotas só falam com o frontend Astro, nunca com um
    # formulário HTML do Django.
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    # 401/403/404 e ValidationError lançado dentro de perform_create passam por aqui,
    # para que toda resposta de erro tenha o mesmo `{ok: false, error}` que o painel lê.
    "EXCEPTION_HANDLER": "core.excecoes.tratar_excecao",
}

# Cookie que carrega o token de API para o painel. Nome próprio em vez de "token"
# para não colidir com cookie de outro sistema no mesmo domínio.
TOKEN_COOKIE = os.getenv("TOKEN_COOKIE", "fb_token")
TOKEN_COOKIE_AGE = int(os.getenv("TOKEN_COOKIE_AGE", 60 * 60 * 24 * 30))

# CORS: necessário no DESENVOLVIMENTO, onde o `astro dev` chama o runserver direto
# (localhost:4321 → 127.0.0.1:8010 é cross-origin por porta) e a reescrita do
# vercel.json não existe. Em produção o navegador chama a mesma origem do painel e a
# Vercel encaminha para cá, então nada do tráfego real passa por aqui — mas deixar a
# lista não custa nada e mantém o dev funcionando. Origens explícitas, nunca "*": com
# credencial liberada o "*" é rejeitado pelo navegador de qualquer jeito.
CORS_ALLOWED_ORIGINS = _lista(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:4321,https://fator-brilho.vercel.app",
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    # O cabeçalho que o frontend manda em todo método não-seguro; é ele que prova que
    # a requisição saiu do nosso JS e não de um <form> de outro site.
    "x-fator-brilho",
]

# Cookies do próprio Django (sessão e CSRF, usados pelo /admin). O cookie que autentica
# o painel é o `fb_token`, gravado em `core.views._grava_cookie`, e não depende destas
# linhas. Mesma regra dos dois lados: em produção None + Secure, porque o admin pode ser
# aberto a partir de outro site (a API tem seu próprio host); em http local o navegador
# recusaria None + Secure, então fica Lax sem Secure.
SESSION_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"
CSRF_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True

# A Vercel termina o TLS e chama a função por HTTP; sem isto o Django não sabe que a
# requisição original foi HTTPS e o is_secure() mente.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Asaas. A regra do `$` na chave é a mesma que já morou no .env do Astro: só leitura
# crua, sem expensão — por isso dotenv e não export shell.
ASAAS_API_KEY = os.getenv("ASAAS_API_KEY", "")
ASAAS_WEBHOOK_TOKEN = os.getenv("ASAAS_WEBHOOK_TOKEN", "")

# Base dos links de retorno do checkout (successUrl/cancelUrl do Asaas), que apontam
# para o PAINEL, não para este backend. Em produção a variável é obrigatória: o Host da
# request é o domínio da API, e o fallback que existe em `_base_do_site` é o cabeçalho
# `Origin` — que sob a reescrita do vercel.json chega certo por acidente de desenho, e
# link de dinheiro não se apoia em acidente.
SITE_URL = os.getenv("SITE_URL", "")

JAZZMIN_SETTINGS = {
    "site_title": "Fator Brilho - Admin",
    "site_header": "Fator Brilho",
    "site_brand": "Fator Brilho",
    "welcome_sign": "Painel administrativo",
    "copyright": "Fator Brilho SaaS",
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "core": "fas fa-car-wash",
        "core.Estetica": "fas fa-store",
        "core.Servico": "fas fa-list",
        "core.Galeria": "fas fa-images",
    },
    # O caminho é relativo ao static dos apps; o arquivo está em
    # core/static/core/admin/theme.css.
    "custom_css": "core/admin/theme.css",
    "show_ui_builder": False,
}

# Tema escuro de verdade: no jazzmin 3 isso é o modo dark do Bootstrap 5.3, e não
# mais as classes de cor da linha AdminLTE (a chave "colors" que existia antes não é
# mais lida por ninguém — por isso ela não está aqui).
JAZZMIN_UI_TWEAKS = {
    "theme": "default",
    "default_theme_mode": "dark",
    "navbar_small_text": False,
    "body_small_text": False,
    "sidebar_small_text": False,
    "navbar_fixed": True,
    "sidebar_fixed": True,
}

# Email: nada de SMTP ainda. Console evita que um cadastro de admin tente entregar
# mensagem e trave a request.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
