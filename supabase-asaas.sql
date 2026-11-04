-- Migração da integração de cobrança (Asaas).
--
-- Reexecutável: add column if not exists + drop constraint antes de recriar, do
-- mesmo jeito que os outros scripts deste projeto. Rode com `npm run db:migrate
-- supabase-asaas.sql`.
--
-- O que cada coluna resolve:
--   asaas_customer_id  -> id do cliente no Asaas. Criamos uma vez e guardamos; é
--                          por ele que o webhook encontra a linha do dono.
--   cpf_cnpj           -> obrigatório na API do Asaas para criar cliente (e para
--                          cobrar no cartão). Sem isso não há checkout possível.
--   plano_ativo        -> o plano pago. Null = assinatura ainda não paga; é o
--                          estado que o banner do painel passa a ler, em vez do
--                          "pendente" fixo de hoje.

alter table public.estetica add column if not exists asaas_customer_id text;
alter table public.estetica add column if not exists cpf_cnpj text;
alter table public.estetica add column if not exists plano_ativo text;

-- Trava os valores de plano no próprio banco: um webhook malformado ou um bug no
-- painel não conseguem gravar "gold" e sumir com a contabilidade. A whitelist do
-- código (src/lib/planos.ts) e esta lista têm de bater.
alter table public.estetica drop constraint if exists estetica_plano_ativo_check;
alter table public.estetica
  add constraint estetica_plano_ativo_check
  check (plano_ativo is null or plano_ativo in ('essencial', 'profissional', 'premium'));

-- O webhook recebe o evento com o id do cliente no Asaas e precisa achar a linha
-- dele sem varrer a tabela inteira.
create index if not exists estetica_asaas_customer_id_idx
  on public.estetica (asaas_customer_id);

-- Nada de policy nova aqui: o webhook escreve com a service role key, que por
-- definição atravessa o RLS. O acesso do dono continua sendo o que já está no
-- supabase-schema.sql (auth.uid() = id).
