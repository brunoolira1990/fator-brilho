import type { APIRoute } from 'astro';
import { createSupabaseServerClient, json } from '../../lib/supabase-ssr';
import { gerarSlug, validarSlug } from '../../lib/slug';

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

  return json(200, { ok: true, data });
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

  const resultado = normalizar(body as Record<string, unknown>);

  if ('erro' in resultado) {
    return json(400, { ok: false, error: resultado.erro });
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

  return json(200, { ok: true, data });
};
