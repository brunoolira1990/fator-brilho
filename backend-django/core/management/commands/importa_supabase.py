"""
Importa o dump do Supabase (dump/supabase.json) para o banco do Django.

Idempotente por construção: rodar duas vezes não duplica nada, e a segunda rodada
não reescreve senha de quem já mudou a senha depois da migração.

Uso:
    python manage.py importa_supabase --apenas-relatorio
    python manage.py importa_supabase
    python manage.py importa_supabase --importar-orfas=donodepoxis@exemplo.com
    python manage.py importa_supabase --importar-orfas=EMAIL --orfa=ID_DA_ORFA

As estéticas órfãs (linha em public.estetica sem login correspondente em auth.users —
no banco antigo a PK da estética É o auth.uid(), então "órfã" quer dizer "criada direto
no SQL Editor") não têm dono. Não adivinhamos um: ficam paradas até alguém dizer de
verdade para quem elas pertencem, e é para isso que existe --importar-orfas.

A regra dura do import é "não destrói o que já existe", porque é exatamente assim que
o modelo é: **uma estética por conta** (ver core/views.py, `EsteticaView` pega
`filter(user=...).first()`). Receber duas linhas do dump para a mesma conta, ou dar a
mesma conta como destino de duas órfãs, reescreveria o site que já está no banco novo.
O comando recusa antes de escrever, e diz o motivo com o `id_supabase` da linha — nunca
resolve sozinho escolhendo um dos lados no sorteio.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from core.limpeza import gerar_slug, validar_slug
from core.models import Estetica, Galeria, Servico

COLUNAS_TEXTO = ("nome_negocio", "whatsapp", "instagram", "cpf_cnpj", "asaas_customer_id")


def hash_de_senha(bruto: str | None) -> str | None:
    """
    Converte o hash do Supabase para o formato que o Django entende.

    O Supabase guarda a string bcrypt crua ($2a$10$..., 60 caracteres). O Django
    identifica o algoritmo pelo prefixo antes do primeiro `$`: sem `bcrypt$` na frente,
    `check_password` devolve False e a conta importada não loga — sem aviso nenhum.
    Medido: `check_password('x', '$2a$10$...')` é False; com o prefixo é True.
    """
    if not bruto:
        return None

    bruto = bruto.strip()

    if bruto.startswith("bcrypt$") or bruto.startswith("bcrypt_sha256$"):
        return bruto

    if not bruto.startswith("$2"):
        # pbkdf2_, argon2, scrypt: vieram do Django ou de outro sistema que já fala a
        # língua dele. Tentamos identificar; se não der, é melhor parar do que gravar
        # uma senha que ninguém consegue usar.
        try:
            identify_hasher(bruto)
        except Exception as erro:  # noqa: BLE001 - o erro é a mensagem que o usuário lê
            raise CommandError(f"hash de senha em formato inesperado: {erro}") from erro

        return bruto

    return f"bcrypt${bruto}"


class Command(BaseCommand):
    help = "Importa estéticas, serviços e galerias do dump do Supabase."

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", default="dump/supabase.json", help="caminho do JSON gerado por scripts/exporta_supabase.py")
        parser.add_argument("--apenas-relatorio", action="store_true", help="não escreve nada, só diz o que faria")
        parser.add_argument(
            "--importar-orfas",
            default="",
            metavar="EMAIL",
            help="e-mail da conta que vai receber as estéticas sem login no dump",
        )
        parser.add_argument(
            "--orfa",
            action="append",
            default=[],
            metavar="ID",
            dest="orfas",
            help="id_supabase da órfã a importar (uma por rodada: o destino é uma conta só)",
        )

    def handle(self, *args, **opcoes):
        caminho = Path(opcoes["arquivo"])

        if not caminho.is_absolute():
            caminho = Path.cwd() / caminho

        if not caminho.exists():
            raise CommandError(f"não achei {caminho}. Rode antes: python scripts/exporta_supabase.py")

        dump = json.loads(caminho.read_text(encoding="utf-8"))
        relatorio = Relatorio()
        com_dono = dump.get("esteticas_com_dono", [])

        # Uma estética por conta: se o dump trouxer duas linhas para o mesmo e-mail, a
        # segunda reescreveria a primeira. Paramos as duas antes de qualquer INSERT e
        # deixamos a decisão para quem conhece os dados.
        donos_repetidos = self.donos_repetidos(com_dono)

        for registro in com_dono:
            dono_email = (registro["usuario"]["email"] or "").strip().lower()

            if dono_email in donos_repetidos:
                relatorio.pular(registro, f"mais de uma estética no dump para {dono_email}; o modelo tem uma por conta — importe uma e repita")

                continue

            self.importa_um(registro, dono_email=dono_email, relatorio=relatorio, seco=opcoes["apenas_relatorio"])

        orfas = dump.get("esteticas_orfas") or []

        if orfas:
            alvo = (opcoes["importar_orfas"] or "").strip().lower()
            decisoes = self.ordena_orfas(orfas, alvo=alvo, escolhidas=opcoes["orfas"])

            for registro, motivo in decisoes:
                if motivo is None:
                    self.importa_um(registro, dono_email=alvo, relatorio=relatorio, seco=opcoes["apenas_relatorio"])
                else:
                    relatorio.pular(registro, motivo)

        self.echo(relatorio, seco=opcoes["apenas_relatorio"])

    # -- decisões de segurança -----------------------------------------------------

    @staticmethod
    def donos_repetidos(com_dono: list[dict]) -> set[str]:
        vistos, repetidos = set(), set()

        for registro in com_dono:
            email = (registro["usuario"]["email"] or "").strip().lower()

            if email in vistos:
                repetidos.add(email)

            vistos.add(email)

        return repetidos

    def ordena_orfas(self, orfas: list[dict], alvo: str, escolhidas: list[str]) -> list[tuple[dict, str | None]]:
        """
        Devolve (registro, motivo) — `motivo=None` significa "importa".

        Toda recusa acontece aqui, antes de abrir transação: é mais seguro do que
        parar no meio e deixar metade do dump escrita.
        """
        alvo = (alvo or "").strip().lower()
        ids = [str(id_ or "").strip() for id_ in escolhidas if str(id_ or "").strip()]

        if not alvo and not ids:
            return [(o, "sem login no dump; use --importar-orfas=EMAIL para dar um dono") for o in orfas]

        if not alvo:
            raise CommandError("--orfa=ID escolhe QUAL órfã, mas não diz DE QUEM ela é: use junto com --importar-orfas=EMAIL.")

        if not User.objects.filter(email__iexact=alvo).exists():
            raise CommandError(f"--importar-orfas={alvo or '(vazio)'}: não existe conta com esse e-mail. Cadastre antes.")

        # A conta destino precisa estar livre. Se ela já tem estética neste banco, a
        # importação por cima reescreveria o site publicado do dono dela.
        if Estetica.objects.filter(user__email__iexact=alvo).exists():
            raise CommandError(
                f"--importar-orfas={alvo}: esta conta já tem uma estética neste banco, e o painel só mostra uma por conta. "
                "Importar órfã por cima apagaria o site dela. Use outra conta, ou libere/migre pelo admin."
            )

        if ids:
            disponiveis = {str(o.get("id_supabase")): o for o in orfas}
            desconhecidos = [i for i in ids if i not in disponiveis]

            if desconhecidos:
                raise CommandError(
                    f"--orfa={desconhecidos[0]} não é uma órfã deste dump. Opções: "
                    + ", ".join(f"{i} ({d['nome_negocio']!r})" for i, d in disponiveis.items())
                )

            if len(ids) > 1:
                raise CommandError(
                    f"--orfa foi passado {len(ids)} vezes, e todas iriam para {alvo}: uma estética por conta. "
                    "Rode uma vez por órfã (com uma conta destino diferente em cada rodada)."
                )

        elif len(orfas) > 1:
            lista = "; ".join(f"{o.get('id_supabase')} = {o['nome_negocio']!r} (slug={o.get('slug_estetica')!r}, "
                              f"{len(o.get('servicos') or [])} serviços, {len(o.get('galeria') or [])} fotos)" for o in orfas)

            raise CommandError(
                f"há {len(orfas)} estéticas órfãs e o destino é um só: {alvo}. Escolha uma com --orfa=ID. Opções: {lista}"
            )

        selecionadas = set(ids) or {str(orfas[0].get("id_supabase"))}

        return [
            (o, None) if str(o.get("id_supabase")) in selecionadas
            else (o, "ficou fora do --orfa escolhido" if ids else "sem login no dump")
            for o in orfas
        ]

    # -- núcleo -------------------------------------------------------------------

    def importa_um(self, registro: dict, dono_email: str, relatorio: "Relatorio", seco: bool) -> None:
        dono_email = (dono_email or "").strip().lower()

        if not dono_email:
            relatorio.pular(registro, "linha sem e-mail de dono no dump")

            return

        slug = gerar_slug(registro.get("slug_estetica") or "")
        erro_slug = validar_slug(slug)

        if erro_slug:
            relatorio.pular(registro, f"slug inválido: {erro_slug}")

            return

        # Slug ocupado por outra conta neste banco = colisão de link público. Não
        # roubamos o endereço de ninguém: a linha fica para trás e o relatório diz por quê.
        dono = User.objects.filter(email__iexact=dono_email).first()
        ocupado = Estetica.objects.filter(slug=slug or None).exclude(user=dono).exists() if slug else False

        if ocupado:
            relatorio.pular(registro, f"o link /{slug}/ já pertence a outra conta deste banco")

            return

        if seco:
            relatorio.simular(registro, dono_email, slug)

            return

        with transaction.atomic():
            usuario = self._usuario(dono_email, registro, relatorio)
            estetica = self._estetica(usuario, registro, slug, relatorio)
            self._listas(estetica, registro, relatorio)

        relatorio.importado(registro, usuario.email, slug)

    def _usuario(self, email: str, registro: dict, relatorio: "Relatorio") -> User:
        usuario = User.objects.filter(username__iexact=email).first() or User.objects.filter(email__iexact=email).first()

        if usuario is None:
            usuario = User.objects.create_user(username=email, email=email, password=None)

            hash_bruto = (registro.get("usuario") or {}).get("hash")
            convertido = hash_de_senha(hash_bruto)

            if convertido:
                # `set_password` re-hasharia; aqui a intenção é exatamente levar o hash
                # que já existe, então a atribuição é direta.
                usuario.password = convertido
                usuario.save(update_fields=["password"])
            else:
                relatorio.aviso(f"{email}: sem hash no dump, conta criada sem senha (defina uma antes de usar)")

            return usuario

        # Conta já existia aqui. Não tocamos na senha dela: se o dono já trocou a senha
        # depois da migração, reimportar o hash velho a jogaria de volta anos no tempo.
        if not (usuario.email or "").strip():
            usuario.email = email
            usuario.save(update_fields=["email"])

        return usuario

    def _estetica(self, usuario: User, registro: dict, slug: str, relatorio: "Relatorio") -> Estetica:
        estetica = Estetica.objects.filter(user=usuario).first()

        if estetica is None:
            estetica = Estetica(user=usuario)

        for campo in COLUNAS_TEXTO:
            valor = (registro.get(campo) or "").strip()

            if valor:
                setattr(estetica, campo, valor)

        endereco = (registro.get("endereco") or "").strip()

        if endereco:
            estetica.endereco = endereco

        cor = (registro.get("cor_principal") or "").strip().lower()

        if cor:
            estetica.cor_principal = cor

        if slug:
            estetica.slug = slug

        plano = (registro.get("plano_ativo") or "").strip()

        if plano:
            estetica.plano_ativo = plano

        # `full_clean` antes de salvar: a migration de dados não tem serializer por
        # cima, e é exatamente aqui que um CPF de 13 dígitos ou uma cor fora do hex
        # entrariam no banco novo sem ninguém ver.
        estetica.full_clean(exclude=["user", "criado_em", "atualizado_em"])
        estetica.save()

        # auto_now_add não aceita valor da migration: o update é depois do insert, e só
        # quando o dump trouxe a data. Sem isso toda conta importada nasceria "hoje".
        criado_em = parse_datetime(registro.get("created_at") or "")

        if criado_em:
            Estetica.objects.filter(pk=estetica.pk).update(criado_em=criado_em)
            relatorio.aviso(f"{usuario.email}: criado_em preservado como {criado_em:%d/%m/%Y}")

        return estetica

    def _listas(self, estetica: Estetica, registro: dict, relatorio: "Relatorio") -> None:
        """Repondo as listas pelo nome+ordem: reimportar não pode duplicar card."""
        for linha in registro.get("servicos") or []:
            nome = (linha.get("nome") or "").strip()

            if not nome:
                relatorio.aviso(f"serviço sem nome na estética {estetica.pk}, ignorado")

                continue

            Servico.objects.update_or_create(
                estetica=estetica,
                nome=nome,
                defaults={"preco": (linha.get("preco") or "").strip(), "ordem": linha.get("ordem") or 0},
            )

        for linha in registro.get("galeria") or []:
            antes = (linha.get("antes_url") or "").strip()
            depois = (linha.get("depois_url") or "").strip()

            if not antes and not depois:
                relatorio.aviso(f"par de fotos vazio na estética {estetica.pk}, ignorado")

                continue

            Galeria.objects.update_or_create(
                estetica=estetica,
                antes_url=antes,
                defaults={"depois_url": depois, "legenda": (linha.get("legenda") or "").strip(), "ordem": linha.get("ordem") or 0},
            )

    def echo(self, relatorio: "Relatorio", seco: bool) -> None:
        titulo = "RELATÓRIO (nada foi escrito)" if seco else "IMPORTAÇÃO"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {titulo} ==="))
        self.stdout.write(f"  importadas: {len(relatorio.importadas)}")

        for linha in relatorio.importadas:
            self.stdout.write(f"    + {linha}")

        self.stdout.write(f"  puladas: {len(relatorio.puladas)}")

        for registro, motivo in relatorio.puladas:
            origem = f"[{registro.get('id_supabase') or '-'}] "
            self.stdout.write(self.style.WARNING(f"    - {origem}{registro.get('nome_negocio')!r}: {motivo}"))

        for aviso in relatorio.avisos:
            self.stdout.write(self.style.WARNING(f"    ! {aviso}"))

        if not seco and relatorio.importadas:
            self.stdout.write("\n    próximo passo: python manage.py createsuperuser (o dump não cria staff)\n")


class Relatorio:
    def __init__(self):
        self.importadas: list[str] = []
        self.puladas: list[tuple[dict, str]] = []
        self.avisos: list[str] = []

    def importado(self, registro: dict, email: str, slug: str) -> None:
        self.importadas.append(
            f"{registro.get('nome_negocio')!r} -> {email} /site/{slug or '(sem link)'} "
            f"({len(registro.get('servicos') or [])} serviços, {len(registro.get('galeria') or [])} fotos)"
        )

    def simular(self, registro: dict, email: str, slug: str) -> None:
        self.importado({**registro, "nome_negocio": f"[simulado] {registro.get('nome_negocio')}"}, email, slug)

    def pular(self, registro: dict, motivo: str) -> None:
        self.puladas.append((registro, motivo))

    def aviso(self, texto: str) -> None:
        self.avisos.append(texto)
