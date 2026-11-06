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

Corrida entre instâncias: o `CMD` roda em **toda** instância que nasce, e o deploy de
verificação sobe duas em paralelo (medido em produção: wh4wl e g2j5k aos 02:08:54). As
duas passam pela checagem de existência e uma delas apanha do índice único de
`auth_user.username`. Isso é tratado, não improvisado: `IntegrityError` nunca vira
traceback no log, porque um traceback que não quebra nada ensina todo mundo a ignorar
log vermelho.
"""

from __future__ import annotations

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

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
            self._relatar_existente(existente)
            return

        try:
            # create_superuser liga is_staff e is_superuser sozinho e devolve ValueError
            # se alguém passar o contrário (django/contrib/auth/models.py:191-200); por
            # isso as flags não são repetidas aqui.
            #
            # O atomic é o que torna a corrida recuperável: dentro do bloco o INSERT
            # rejeitado desfaz apenas este trabalho, e a releitura abaixo encontra a
            # linha que a outra instância gravou. Hoje o create_superuser escreve numa
            # tabela só, então ele também é a garantia de que um futuro AUTH_USER_MODEL
            # com escrita dupla não deixa um meio-administrador no banco.
            with transaction.atomic():
                User.objects.create_superuser(username=email, email=email, password=senha)
        except IntegrityError as erro:
            competidora = User.objects.filter(username=email).first()
            if competidora is None:
                # Não foi a corrida de username: é um problema novo, e a resposta certa
                # é dizer isso e sair com código 1 -- não um traceback (o CMD usa ";",
                # então o container continua servindo de qualquer jeito) nem uma
                # mensagem tranquilizadora sobre uma conta que não existe.
                raise CommandError(
                    f"cria_admin: a criação de {email} foi rejeitada pelo banco e não há "
                    f"nenhuma conta com esse nome para relatar. Isso não é a corrida do "
                    f"autoscale. Rode `python manage.py cria_admin --traceback` para ver "
                    f"a causa original."
                ) from erro
            self._relatar_existente(competidora)
            return

        # A senha nunca é impressa: o log da Vercel fica retido e consultável.
        self.stdout.write(f"cria_admin: superusuário {email} criado.")

    def _relatar_existente(self, usuario: User) -> None:
        """O que dizer quando a conta já estava lá -- criada antes ou por outra instância."""
        if usuario.is_superuser:
            self.stdout.write(
                f"cria_admin: {usuario.username} já é superusuário, nada a fazer."
            )
        else:
            # A conta veio do /api/auth/registro/, ou alguém usou o e-mail antes. O
            # deploy não resolve isso sozinho, mas também não deixa de avisar: sem
            # staff o /admin fica inacessível e o sintoma seria "a variável está lá e
            # mesmo assim não entra".
            self.stderr.write(
                f"cria_admin: {usuario.username} já existe como conta comum e NÃO foi "
                f"promovida. Promova no /admin de outra conta staff, ou use outro e-mail "
                f"na {VARIAVEL_EMAIL}."
            )
