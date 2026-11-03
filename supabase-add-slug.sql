-- Adiciona o slug (link publico) na tabela "estetica" e libera a leitura anonima.
-- Rode este arquivo no SQL Editor do Supabase depois do supabase-schema.sql.

-- 1) Coluna nova: texto livre, com formato validado pela API (/api/estetica.ts).
alter table public.estetica
  add column if not exists slug_estetica text;

-- 2) Unicidade. Um index unico equivale a uma constraint e pode ser recriado
--    sem erro caso o script rode duas vezes. Valores NULL ficam de fora da
--    unicidade, entao varios clientes ainda sem link podem coexistir.
create unique index if not exists estetica_slug_estetica_unique
  on public.estetica (slug_estetica);

comment on column public.estetica.slug_estetica is
  'Identificador do site publico: /site/<slug>. minusculo, letras, numeros e hifen.';

-- 3) Leitura publica.
-- As policies atuais so deixam o dono ver a propria linha (auth.uid() = id), o que
-- faz uma visita anonima receber zero linhas. Uma function "security definer" roda
-- como dueno da tabela, furando o RLS de proposito, e devolve somente as colunas
-- que o site publico precisa. Nada de e-mail, nada de id.
create or replace function public.estetica_publica_por_slug(p_slug text)
returns table (
  slug_estetica text,
  nome_negocio text,
  whatsapp text,
  instagram text,
  endereco text,
  cor_principal text
)
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
begin
  return query
    select
      e.slug_estetica,
      e.nome_negocio,
      e.whatsapp,
      e.instagram,
      e.endereco,
      e.cor_principal
    from public.estetica e
    where e.slug_estetica = p_slug
    limit 1;
end;
$$;

-- Supabase ja cria functions com privilegios amplios; revoke antes de grant explicito.
revoke all on function public.estetica_publica_por_slug(text) from public;
grant execute on function public.estetica_publica_por_slug(text) to anon, authenticated;
