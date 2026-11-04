"""
Exporta os dados do Supabase para dump/supabase.json.

Por que um script e não um `pg_dump`: o banco antigo é o do Supabase e a tabela de
logins (`auth.users`) fica num schema separado, com hash de senha em bcrypt. Um
pg_dump inteiro traria 12 logins e 4 estéticas de teste de fases anteriores; aqui a
escolha do que atravessa para o Django é explícita e o relatório sai junto, para o
Bruno decidir antes de importar.

A conexão é a mesma que o painel Astro já usava: SUPABASE_DB_URL do .env da raiz do
projeto (o pooler do Supabase), lida com `sslmode=require`.

Uso:
    cd backend-django
    ../venv.../python scripts/exporta_supabase.py        # escreve dump/supabase.json
    ../venv.../python scripts/exporta_supabase.py --apenas-relatorio

Nada aqui escreve no Supabase: é SELECT, e só.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

BASE = Path(__file__).resolve().parent.parent
ENV_RAIZ = BASE.parent / ".env"
DIRETORIO_DUMP = BASE / "dump"

# O que atravessa: as três tabelas do site + os logins donos de uma estética.
# `auth.users` sem estética ligada é conta de teste de fase anterior: fica de fora do
# JSON e aparece no relatório como descartada, com o e-mail, para decisão humana.
#
# A amarra NÃO é `user_id`: conferido em information_schema, public.estetica tem
# `id uuid` e nenhuma coluna de usuário. A RLS do banco antigo era `id = auth.uid()`,
# ou seja, a PK da estética é o próprio id do login. É por isso que `estetica.id` e
# `users.id` são comparados direto abaixo.
COISA_IMPORTAR = {
    "usuarios": """
        select id, email, encrypted_password, raw_user_meta_data, created_at
        from auth.users
        where deleted_at is null and is_anonymous = false
    """,
    "estetica": """
        select id, nome_negocio, whatsapp, instagram, endereco, cor_principal,
               created_at, slug_estetica, asaas_customer_id, cpf_cnpj, plano_ativo
        from public.estetica
    """,
    "servicos": """
        select id, nome, preco, descricao, ordem, estetica_id
        from public.servicos
    """,
    "galeria": """
        select id, antes_url, depois_url, legenda, ordem, estetica_id
        from public.galeria
    """,
}


def _json(valor):
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()

    return valor


def conecta() -> str:
    load_dotenv(ENV_RAIZ)

    url = (os.getenv("SUPABASE_DB_URL") or "").strip()

    if not url:
        raise SystemExit(f"Falta SUPABASE_DB_URL em {ENV_RAIZ}.")

    return url


def exporta(relatorio_only: bool = False) -> dict:
    import psycopg2.extensions as ext  # noqa: F401  (garante driver certo antes do connect)

    conn = psycopg2.connect(conecta(), cursor_factory=RealDictCursor)
    conn.set_session(readonly=True, autocommit=True)

    dados = {}

    try:
        with conn.cursor() as cur:
            for nome, sql in COISA_IMPORTAR.items():
                cur.execute(sql)
                linhas = [dict((k, _json(v)) for k, v in linha.items()) for linha in cur.fetchall()]
                dados[nome] = linhas
    finally:
        conn.close()

    return amarra(dados)


def amarra(dados: dict) -> dict:
    """Liga estética -> usuário pelo id (a PK da estética É o auth.uid()) e separa órfãs."""
    usuarios = {str(linha["id"]): linha for linha in dados["usuarios"]}
    esteticas = []
    orfas = []
    servicos_por_estetica = {}
    galeria_por_estetica = {}

    for linha in dados["servicos"]:
        servicos_por_estetica.setdefault(str(linha["estetica_id"]), []).append(linha)

    for linha in dados["galeria"]:
        galeria_por_estetica.setdefault(str(linha["estetica_id"]), []).append(linha)

    for estetica in dados["estetica"]:
        chave = str(estetica["id"])
        dono = usuarios.get(chave)

        registro = dict(estetica)
        registro["id_supabase"] = chave
        registro["servicos"] = sorted(servicos_por_estetica.get(chave, []), key=lambda s: (s["ordem"], str(s["id"])))
        registro["galeria"] = sorted(galeria_por_estetica.get(chave, []), key=lambda g: (g["ordem"], str(g["id"])))

        if dono is None:
            # Sem login não há como criar o User do Django, e sem User não há dono para
            # o painel. Não "adivinhamos" um e-mail: vai para a lista de órfãs.
            orfas.append(registro)

            continue

        meta = dono.get("raw_user_meta_data") if isinstance(dono.get("raw_user_meta_data"), dict) else {}

        registro["usuario"] = {
            "email": dono["email"],
            "hash": dono["encrypted_password"],
            "criado_em": dono["created_at"],
            # Nome que o Supabase guardava em raw_user_meta_data; no Django o username
            # é o próprio e-mail, então isto só vai para first_name.
            "apelido": meta.get("full_name") or meta.get("nome"),
        }
        esteticas.append(registro)

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "origem": "supabase (SELECT only)",
        "total_linhas": {chave: len(valor) for chave, valor in dados.items()},
        "esteticas_com_dono": esteticas,
        "esteticas_orfas": orfas,
        "usuarios_descartados": sorted(
            {u["email"] for u in dados["usuarios"]} - {e["usuario"]["email"] for e in esteticas}
        ),
    }


def imprime_relatorio(saida: dict) -> None:
    print("=== relatório do dump ===")
    print(f"gerado em {saida['gerado_em']}")
    print("linhas no banco antigo:", saida["total_linhas"])
    print()

    for estetica in saida["esteticas_com_dono"]:
        print(
            f"  vai importar: {estetica['nome_negocio']!r} ({estetica['usuario']['email']}) "
            f"slug={estetica['slug_estetica']!r} plano={estetica['plano_ativo'] or '-'} "
            f"servicos={len(estetica['servicos'])} galeria={len(estetica['galeria'])}"
        )

    for estetica in saida["esteticas_orfas"]:
        print(
            f"  ÓRFÃ (sem login): {estetica['nome_negocio']!r} slug={estetica['slug_estetica']!r} "
            f"servicos={len(estetica['servicos'])} galeria={len(estetica['galeria'])}"
        )

    if saida["usuarios_descartados"]:
        print(f"  logins descartados ({len(saida['usuarios_descartados'])}):")

        for email in saida["usuarios_descartados"]:
            print("    -", email)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apenas-relatorio", action="store_true", help="não escreve o JSON")
    args = parser.parse_args()

    saida = exporta()
    imprime_relatorio(saida)

    if args.apenas_relatorio:
        return 0

    DIRETORIO_DUMP.mkdir(exist_ok=True)
    destino = DIRETORIO_DUMP / "supabase.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=_json), encoding="utf-8")
    print(f"\nescrito em {destino} (gitignored: tem CPF e e-mail de cliente)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
