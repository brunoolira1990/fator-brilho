-- Tabela "estetica": um registro por usuario autenticado.
-- O proprio id e a chave do usuario, entao um upsert nunca colide com dados de terceiros.

create table if not exists public.estetica (
  id uuid primary key default auth.uid(),
  nome_negocio text,
  whatsapp text,
  instagram text,
  endereco text,
  cor_principal text default '#075E54',
  created_at timestamptz not null default now()
);

alter table public.estetica enable row level security;

-- drop antes de create para o script ser reexecutavel
drop policy if exists "estetica_select_own" on public.estetica;
drop policy if exists "estetica_insert_own" on public.estetica;
drop policy if exists "estetica_update_own" on public.estetica;

create policy "estetica_select_own"
  on public.estetica
  for select
  using (auth.uid() = id);

-- O upsert do PostgREST envia INSERT ... ON CONFLICT DO UPDATE, entao precisa das duas
-- policies abaixo: sem a de insert o pedido e negado mesmo quando a linha ja existe.
create policy "estetica_insert_own"
  on public.estetica
  for insert
  with check (auth.uid() = id);

create policy "estetica_update_own"
  on public.estetica
  for update
  using (auth.uid() = id)
  with check (auth.uid() = id);
