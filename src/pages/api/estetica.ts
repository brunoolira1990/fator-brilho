import type { APIRoute } from 'astro';
import { createSupabaseServerClient, json } from '../../lib/supabase-ssr';
import { gerarSlug, validarSlug } from '../../lib/slug';
import { normalizarListas, type LinhaGaleria, type LinhaServico } from '../../lib/listas';

const CAMPOS_TEXTO = [
  { chave: 'nome_negocio', rotulo: 'Nome do negócio', max: 120 },
  { chave: 'whatsapp', rotulo: 'WhatsApp', max: 20 },
  { chave: 'instagram', rotulo: 'Instagram', max: 64 },
  { chave: 'endereco', rotulo: 'Endereço', max: 300 },
] as const;

type Validação = { campos: Record<string, string | null> } | { erro: string };

function normalizar(body: Record<string, unknown>): Validação {
  const campos: Record<string, string | null> = {};

  for (const { chave, rotulo, max } of CAMPOS_TEXTO) {
    const valor = body[chave];

    if (valor !== undefined && typeof valor !== 'string') {
      return { erro: `${rotulo}: envie um texto.` };
    }

    const limpo = (valor ?? '').trim();

    if (limpo.length > max) {
      return { erro: `${rotulo}: use no máximo ${max} caracteres.` };
    }

    campos[chave] = limpo === '' ? null : limpo;
  }

  // Vira sufixo de wa.me em outros componentes: só dígitos e sinais de formatação.
  if (campos.whatsapp && !/^\+?[\d\s().-]+$/.test(campos.whatsapp)) {
    return { erro: 'WhatsApp: use apenas números, com opcional + no início.' };
  }

  if (campos.instagram) {
    campos.instagram = campos.instagram.replace(/^@/, '');
    if (!/^[\w.]+$/.test(campos.instagram)) {
      return { erro: 'Instagram: use apenas letras, números, ponto e underscore.' };
    }
  }

  const cor = body.cor_principal;
  if (typeof cor !== 'string' || !/^#[\da-f]{6}$/i.test(cor)) {
    return { erro: 'Cor principal inválida: use o formato #RRGGBB.' };
  }
  campos.cor_principal = cor.toLowerCase();

  const slugBruto = body.slug_estetica;

  if (slugBruto !== undefined && typeof slugBruto !== 'string') {
    return { erro: 'Link do site: envie um texto.' };
  }

  const slug = gerarSlug(slugBruto ?? '');
  const erroSlug = validarSlug(slug);

  if (erroSlug) {
    return { erro: erroSlug };
  }

  campos.slug_estetica = slug === '' ? null : slug;

  return { campos };
}

type SupabaseServer = ReturnType<typeof createSupabaseServerClient>;

/**
 * Alguma coisa deu errado porque a tabela ainda não existe no banco — o estado de
 * quem subiu o código e ainda não rodou o supabase-services-gallery.sql. Não é
 * erro do cliente, então merece instrução e não uma stack trace.
 */
function tabelaFaltando(message: string): boolean {
  return /does not exist|schema cache|relation .* not found/i.test(message);
}

const PENDENCIA_SQL =
  'As tabelas de serviços e galeria ainda não existem no banco. Rode o arquivo supabase-services-gallery.sql no SQL Editor do Supabase.';

type ListasDoPainel = {
  servicos: Record<string, unknown>[];
  galeria: Record<string, unknown>[];
  pendencia: string | null;
  erro: string | null;
};

async function leiaListas(supabase: SupabaseServer, userId: string): Promise<ListasDoPainel> {
  const [servicos, galeria] = await Promise.all([
    supabase.from('servicos').select('id, nome, preco, descricao, ordem').eq('estetica_id', userId).order('ordem'),
    supabase
      .from('galeria')
      .select('id, antes_url, depois_url, legenda, ordem')
      .eq('estetica_id', userId)
      .order('ordem'),
  ]);

  if (servicos.error && tabelaFaltando(servicos.error.message)) {
    return { servicos: [], galeria: [], pendencia: PENDENCIA_SQL, erro: null };
  }

  if (servicos.error) {
    return { servicos: [], galeria: [], pendencia: null, erro: servicos.error.message };
  }

  if (galeria.error && tabelaFaltando(galeria.error.message)) {
    return { servicos: [], galeria: [], pendencia: PENDENCIA_SQL, erro: null };
  }

  if (galeria.error) {
    return { servicos: [], galeria: [], pendencia: null, erro: galeria.error.message };
  }

  return {
    servicos: servicos.data ?? [],
    galeria: galeria.data ?? [],
    pendencia: null,
    erro: null,
  };
}

/**
 * Troca a lista inteira: apaga as linhas do dono e insere as novas na ordem da
 * tela. Os dois passos são pedidos separados ao PostgREST, então não são
 * atômicos — por isso toda validação acontece antes de qualquer escrita. Um
 * banco cair no meio do caminho deixaria a lista vazia, e isso está declarado.
 */
async function substituirLista(
  supabase: SupabaseServer,
  tabela: 'servicos' | 'galeria',
  userId: string,
  linhas: (LinhaServico | LinhaGaleria)[]
): Promise<string | null> {
  const { error: erroDelete } = await supabase.from(tabela).delete().eq('estetica_id', userId);

  if (erroDelete) {
    return tabelaFaltando(erroDelete.message) ? PENDENCIA_SQL : erroDelete.message;
  }

  if (linhas.length === 0) {
    return null;
  }

  const { error: erroInsert } = await supabase
    .from(tabela)
    .insert(linhas.map((linha) => ({ ...linha, estetica_id: userId })));

  if (erroInsert) {
    return tabelaFaltando(erroInsert.message) ? PENDENCIA_SQL : erroInsert.message;
  }

  return null;
}

export const GET: APIRoute = async (context) => {
  const supabase = createSupabaseServerClient(context);
  const { data: authData } = await supabase.auth.getUser();

  if (!authData.user) {
    return json(401, { ok: false, error: 'Sessão expirada. Entre novamente.' });
  }

  const { data, error } = await supabase.from('estetica').select('*').maybeSingle();

  if (error) {
    return json(500, { ok: false, error: error.message });
  }

  const listas = await leiaListas(supabase, authData.user.id);

  if (listas.erro) {
    return json(500, { ok: false, error: listas.erro });
  }

  return json(200, { ok: true, data, servicos: listas.servicos, galeria: listas.galeria, pendencia: listas.pendencia });
};

export const PUT: APIRoute = async (context) => {
  const supabase = createSupabaseServerClient(context);
  const { data: authData } = await supabase.auth.getUser();

  if (!authData.user) {
    return json(401, { ok: false, error: 'Sessão expirada. Entre novamente.' });
  }

  let body: unknown;

  try {
    body = await context.request.json();
  } catch {
    return json(400, { ok: false, error: 'Corpo da requisição não é JSON válido.' });
  }

  if (!body || typeof body !== 'object') {
    return json(400, { ok: false, error: 'Corpo da requisição não é JSON válido.' });
  }

  const bruto = body as Record<string, unknown>;

  // Nada toca o banco antes das duas validações passarem. É isso que impede um
  // body malformado de apagar a galeria de quem só quis trocar o telefone.
  const resultado = normalizar(bruto);

  if ('erro' in resultado) {
    return json(400, { ok: false, error: resultado.erro });
  }

  const listas = normalizarListas(bruto);

  if ('erro' in listas) {
    return json(400, { ok: false, error: listas.erro });
  }

  const { data, error } = await supabase
    .from('estetica')
    .upsert({ id: authData.user.id, ...resultado.campos }, { onConflict: 'id' })
    .select()
    .single();

  if (error) {
    // Estado entre subir este código e rodar o supabase-add-slug.sql no painel:
    // a coluna ainda não existe. Merece instrução, não a mensagem do PostgREST.
    if (error.message.includes('slug_estetica') && /column|schema cache/i.test(error.message)) {
      return json(500, { ok: false, error: 'O banco ainda não tem a coluna do link. Rode o arquivo supabase-add-slug.sql no SQL Editor do Supabase e salve novamente.' });
    }

    // 23505 = unique_violation. O index único do slug devolve a mensagem crua do
    // Postgres; o cliente não precisa ler "estetica_slug_estetica_unique_key".
    if (error.code === '23505' && error.message.includes('slug_estetica')) {
      return json(409, { ok: false, error: 'Esse link já pertence a outra estética. Escolha outro e salve novamente.' });
    }

    return json(500, { ok: false, error: error.message });
  }

  // null = a chave nem veio no body; a lista do banco fica intocada.
  if (listas.servicos !== null) {
    const falha = await substituirLista(supabase, 'servicos', authData.user.id, listas.servicos);

    if (falha) {
      // O cadastro principal já foi gravado nesta mesma request; dizer isso evita
      // que o cliente reescreva nome, WhatsApp e endereço achando que nada entrou.
      return json(500, { ok: false, error: `${falha} Seus dados principais foram salvos; só as listas ficaram de fora.` });
    }
  }

  if (listas.galeria !== null) {
    const falha = await substituirLista(supabase, 'galeria', authData.user.id, listas.galeria);

    if (falha) {
      return json(500, { ok: false, error: `${falha} Seus dados principais foram salvos; só as listas ficaram de fora.` });
    }
  }

  const atual = await leiaListas(supabase, authData.user.id);

  return json(200, {
    ok: true,
    data,
    servicos: atual.servicos,
    galeria: atual.galeria,
    pendencia: atual.pendencia,
  });
};
