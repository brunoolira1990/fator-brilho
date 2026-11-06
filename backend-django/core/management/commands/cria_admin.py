"""
Cria o primeiro superusuário do /admin a partir de variáveis de ambiente.

Existe por um motivo medido, não por conveniência: o `createsuperuser --noinput` oficial
quebra o deploy. Ele devolve `Error: That username is already taken.` quando a conta já
existe (django/contrib/auth/management/commands/createsuperuser.py), e um CMD que falha
a cada deploy depois do primeiro não é um CMD. Este comando é idempotente: sem as
variáveis ele avisa e sai com código 0; com elas, cria uma vez e nas outras apenas
constata.

A identidade é o e-mail, como no resto do produto: `RegistroView` (core/views.py) grava
`username=email` e o `RegistroSerializer` minúsculiza antes. Por isso o `.lower()` aqui
não é capricho -- é o que impede "Admin@x.com" no ambiente virar uma segunda conta ao
lado de "admin@x.com" criada pelo painel.

Regra dura, a mesma do `importa_supabase`: **não mexe no que já existe**. Se o e-mail já
tem uma conta, o comando não cria e não promove ninguém a staff em silêncio. Administrar
o sistema é decisão de quem escreve a variável, não efeito colateral de um deploy.
"""

from __future__ import annotations

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

VARIAVEL_EMAIL = "DJANGO_SUPERUSER_EMAIL"
VARIAVEL_SENHA = "DJANGO_SUPERUSER_PASSWORD"


class Command(BaseCommand):
    help = (
        f"Cria o superusuário do /admin a partir de {VARIAVEL_EMAIL} e "
        f"{VARIAVEL_SENHA}. Não faz nada (e não falha) se elas não estiverem definidas."
    )

    def handle(self, *args, **options):
        email = (os.getenv(VARIAVEL_EMAIL) or "").strip().lower()
        senha = os.getenv(VARIAVEL_SENHA) or ""

        if not email or not senha:
            # Ausência não é erro: é o estado normal de 99% dos deploys. Quebrar aqui
            # faria o container inteiro não subir por causa de uma variável opcional.
            self.stdout.write(
                f"cria_admin: {VARIAVEL_EMAIL}/{VARIAVEL_SENHA} não definidas — nenhum "
                f"superusuário criado. Defina as duas em Settings → Environment "
                f"Variables (escopo Production) e redeploye para criar o acesso ao /admin."
            )
            return

        existente = User.objects.filter(username=email).first()
        if existente is not None:
            if existente.is_superuser:
                self.stdout.write(f"cria_admin: {email} já é superusuário, nada a fazer.")
            else:
                # A conta veio do /api/auth/registro/, ou alguém usou o e-mail antes. O
                # deploy não resolve isso sozinho, mas também não deixa de avisar: sem
                # staff o /admin fica inacessível e o sintoma seria "a variável está lá e
                # mesmo assim não entra".
                self.stderr.write(
                    f"cria_admin: {email} já existe como conta comum e NÃO foi promovida. "
                    f"Promova no /admin de outra conta staff, ou use outro e-mail na "
                    f"{VARIAVEL_EMAIL}."
                )
            return

        # create_superuser já liga is_staff, is_superuser e is_active (é o que o método
        # oficial faz); nomear as flags aqui de novo só criaria um segundo caminho para
        # esquecer uma delas no futuro.
        User.objects.create_superuser(username=email, email=email, password=senha)
        # A senha nunca é impressa: o log da Vercel fica retido e consultável.
        self.stdout.write(f"cria_admin: superusuário {email} criado.")
