-- Servicos e galeria por estética + leitura pública em uma chamada só.
-- Rode no SQL Editor do Supabase. O arquivo é reexecutável.

-- ============================================================================
-- 1) TABELA public.servicos
-- ============================================================================
create table if not exists public.servicos (
  id uuid primary key default gen_random_uuid(),
  estetica_id uuid not null references public.estetica (id) on delete cascade,
  nome text not null,
  preco text,
  descricao text,
  -- A API grava a ordem que o cliente montou no painel. Sem esta coluna a
  -- listagem viria em ordem indefinida e os cards embaralhariam a cada save.
  ordem integer not null default 0,
  created_at timestamptz not null default now()
);

-- Sobe a coluna em tabelas já criadas por uma execução anterior deste script.
alter table public.servicos add column if not exists ordem integer not null default 0;

create index if not exists servicos_estetica_id_ordem
  on public.servicos (estetica_id, ordem);

alter table public.servicos enable row level security;

drop policy if exists "servicos_select_own" on public.servicos;
drop policy if exists "servicos_insert_own" on public.servicos;
drop policy if exists "servicos_update_own" on public.servicos;
drop policy if exists "servicos_delete_own" on public.servicos;

-- Só o dono da estética enxerga os próprios serviços. Como estetica.id é o
-- auth.uid() do dono, "auth.uid() = estetica_id" também impede que alguém
-- insira linhas apontando para a estética de outra pessoa.
create policy "servicos_select_own" on public.servicos
  for select using (auth.uid() = estetica_id);

create policy "servicos_insert_own" on public.servicos
  for insert with check (auth.uid() = estetica_id);

create policy "servicos_update_own" on public.servicos
  for update using (auth.uid() = estetica_id) with check (auth.uid() = estetica_id);

create policy "servicos_delete_own" on public.servicos
  for delete using (auth.uid() = estetica_id);

-- ============================================================================
-- 2) TABELA public.galeria
-- ============================================================================
create table if not exists public.galeria (
  id uuid primary key default gen_random_uuid(),
  estetica_id uuid not null references public.estetica (id) on delete cascade,
  antes_url text,
  depois_url text,
  legenda text,
  ordem integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.galeria add column if not exists ordem integer not null default 0;

create index if not exists galeria_estetica_id_ordem
  on public.galeria (estetica_id, ordem);

alter table public.galeria enable row level security;

drop policy if exists "galeria_select_own" on public.galeria;
drop policy if exists "galeria_insert_own" on public.galeria;
drop policy if exists "galeria_update_own" on public.galeria;
drop policy if exists "galeria_delete_own" on public.galeria;

create policy "galeria_select_own" on public.galeria
  for select using (auth.uid() = estetica_id);

create policy "galeria_insert_own" on public.galeria
  for insert with check (auth.uid() = estetica_id);

create policy "galeria_update_own" on public.galeria
  for update using (auth.uid() = estetica_id) with check (auth.uid() = estetica_id);

create policy "galeria_delete_own" on public.galeria
  for delete using (auth.uid() = estetica_id);

-- ============================================================================
-- 3) Função pública atualizada
-- ============================================================================
-- create or replace NÃO muda o tipo de retorno de uma função já existente
-- (erro "cannot change return type"), então o drop antes do create é obrigatório
-- aqui: ela foi criada com seis colunas e passa a devolver oito.
-- O retorno das duas colunas é jsonb (veja o returns table acima), então as duas
-- peças têm de ser jsonb: json_agg devolve json e '[]'::jsonb não é conversível
-- implicitamente — coalesce(json, jsonb) morre em 42846 "COALESCE could not
-- convert type jsonb to json". jsonb_agg + '[]'::jsonb é o par consistente.
-- ============================================================================
drop function if exists public.estetica_publica_por_slug(text);

create function public.estetica_publica_por_slug(p_slug text)
returns table (
  slug_estetica text,
  nome_negocio text,
  whatsapp text,
  instagram text,
  endereco text,
  cor_principal text,
  servicos jsonb,
  galeria jsonb
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select
    e.slug_estetica,
    e.nome_negocio,
    e.whatsapp,
    e.instagram,
    e.endereco,
    e.cor_principal,
    -- coalesce com '[]' para a página receber array vazio em vez de null:
    -- o componente não precisa saber se o cliente tem zero ou trezentos serviços.
    coalesce(
      (
        select jsonb_agg(
                 json_build_object(
                   'id', s.id,
                   'nome', s.nome,
                   'preco', s.preco,
                   'descricao', s.descricao
                 )
                 order by s.ordem, s.id
               )
        from public.servicos s
        where s.estetica_id = e.id
      ),
      '[]'::jsonb
    ),
    coalesce(
      (
        select jsonb_agg(
                 json_build_object(
                   'id', g.id,
                   'antes_url', g.antes_url,
                   'depois_url', g.depois_url,
                   'legenda', g.legenda
                 )
                 order by g.ordem, g.id
               )
        from public.galeria g
        where g.estetica_id = e.id
      ),
      '[]'::jsonb
    )
  from public.estetica e
  where e.slug_estetica = p_slug
  limit 1;
$$;

revoke all on function public.estetica_publica_por_slug(text) from public;
grant execute on function public.estetica_publica_por_slug(text) to anon, authenticated;
