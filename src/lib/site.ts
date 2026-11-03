import type { ClientData } from './schema';

/**
 * O que as partes visuais do site precisam saber sobre um cliente.
 *
 * É um subconjunto de ClientData (data.json) e, ao mesmo tempo, o que a tabela
 * "estetica" consegue entregar hoje. Assim o mesmo Hero.astro serve a página
 * institucional e a página pública de cada cliente.
 *
 * Campo obrigatório é só o que a página não tem como desenhar sem: nome, cor e
 * mensagem do WhatsApp. O resto some da tela quando estiver vazio.
 */
export type SiteData = {
  slug: string;
  business: {
    name: string;
    description?: string | null;
    tagline?: string | null;
    neighborhood?: string | null;
    address?: string | null;
    mapsUrl?: string | null;
    whatsapp?: string | null;
    whatsappMessage: string;
    instagramUrl?: string | null;
    hours?: string | null;
  };
  branding: {
    accentColor: string;
    heroImage?: string | null;
  };
  legal: {
    privacyPolicyUrl: string;
  };
};

/** Linha como chega do banco. Nada aqui é confiável até passar pelos adaptadores. */
export type EsteticaRow = {
  slug_estetica?: string | null;
  nome_negocio?: string | null;
  whatsapp?: string | null;
  instagram?: string | null;
  endereco?: string | null;
  cor_principal?: string | null;
};

export const COR_ACENTO_PADRAO = '#075E54';

/** Mesmo texto usado no data.json de exemplo: é o CTA, não um dado do cliente. */
export const MENSAGEM_WHATSAPP_PADRAO = 'Olá! Vim pelo site e quero um orçamento.';

const HEX = /^#[\da-f]{6}$/i;

/**
 * cor_principal vira valor de CSS dentro de um atributo style. Sem este filtro,
 * algo como "#fff; }body{display:none" escrito direto no banco injetaria regras.
 */
function corSegura(valor: string | null | undefined): string {
  return typeof valor === 'string' && HEX.test(valor.trim()) ? valor.trim().toLowerCase() : COR_ACENTO_PADRAO;
}

/** "hero.jpg" no data.json é relativo à raiz; em /site/<slug> o navegador erro a path. */
function caminhoAbsoluto(valor: string | null | undefined): string | null {
  if (!valor) return null;
  const limpo = valor.trim();
  if (limpo === '') return null;
  if (/^(https?:)?\/\//i.test(limpo) || limpo.startsWith('/') || limpo.startsWith('data:')) return limpo;
  return `/${limpo}`;
}

function texto(valor: string | null | undefined): string | null {
  const limpo = (valor ?? '').trim();
  return limpo === '' ? null : limpo;
}

/** Página institucional, alimentada pelo clients/<slug>/data.json. */
export function siteDeClientData(client: ClientData): SiteData {
  return {
    slug: client.slug,
    business: {
      name: client.business.name,
      description: client.business.description,
      tagline: client.business.tagline,
      neighborhood: client.business.neighborhood,
      address: client.business.address,
      mapsUrl: client.business.mapsUrl,
      whatsapp: client.business.whatsapp,
      whatsappMessage: client.business.whatsappMessage,
      instagramUrl: client.business.instagram,
      hours: client.business.hours,
    },
    branding: {
      accentColor: corSegura(client.branding.accentColor),
      heroImage: caminhoAbsoluto(client.branding.heroImage),
    },
    legal: {
      privacyPolicyUrl: client.legal.privacyPolicyUrl,
    },
  };
}

/** Página pública do cliente, alimentada pela linha da tabela "estetica". */
export function siteDaLinhaEstetica(row: EsteticaRow): SiteData {
  const nome = texto(row.nome_negocio) ?? 'Estética';
  const endereco = texto(row.endereco);
  // A API já grava o @ removido; refazer aqui cobre linha escrita direto no SQL.
  const instagram = (texto(row.instagram) ?? '').replace(/^@/, '');
  const whatsapp = texto(row.whatsapp);

  return {
    slug: texto(row.slug_estetica) ?? '',
    business: {
      name: nome,
      // A tabela ainda não tem coluna para esses textos, então a página não os mostra.
      description: null,
      tagline: null,
      neighborhood: null,
      address: endereco,
      mapsUrl: endereco ? `https://www.google.com/maps?q=${encodeURIComponent(endereco)}` : null,
      whatsapp,
      whatsappMessage: MENSAGEM_WHATSAPP_PADRAO,
      instagramUrl: instagram ? `https://instagram.com/${instagram}` : null,
      hours: null,
    },
    branding: {
      accentColor: corSegura(row.cor_principal),
      // Sem coluna de imagem no banco: o Hero usa só o degradê sobre o slate-950.
      heroImage: null,
    },
    legal: {
      privacyPolicyUrl: '/privacidade',
    },
  };
}

/** href wa.me — o mesmo formato usado hoje por Hero, Footer e WhatsAppFloat. */
export function waHref(site: SiteData): string | null {
  if (!site.business.whatsapp) return null;
  return `https://wa.me/${site.business.whatsapp}?text=${encodeURIComponent(site.business.whatsappMessage)}`;
}
