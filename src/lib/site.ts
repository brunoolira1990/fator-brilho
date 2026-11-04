import fs from 'node:fs';
import path from 'node:path';
import type { ClientData } from './schema';
import { urlDeImagem } from './urls';

/**
 * O que as partes visuais do site precisam saber sobre um cliente.
 *
 * É um subconjunto de ClientData (data.json) e, ao mesmo tempo, o shape que a página
 * pública monta a partir da linha de `/api/publico/<slug>/` do Django. Assim os mesmos
 * componentes servem a página institucional e a página pública de cada cliente.
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
  services: ServiceItem[];
  gallery: GalleryItem[];
  legal: {
    privacyPolicyUrl: string;
  };
};

export type ServiceItem = {
  name: string;
  priceFrom: string | null;
  description: string | null;
};

export type GalleryItem = {
  caption: string;
  /** src já resolvido, ou null quando não há imagem para mostrar. */
  before: string | null;
  after: string | null;
};

/**
 * Linha como sai de `/api/publico/<slug>/` do Django (core/serializers.py,
 * PublicoSerializer). Os nomes são os da API, não os do banco antigo: o que o Supabase
 * chamava `slug_estetica` é `slug`, e a lista de fotos é `galerias`.
 *
 * Tudo opcional e `unknown` nas listas de propósito: esta é a borda do sistema, e o
 * que a tela faz com o que vier é decidido campo a campo abaixo, nunca no pressuposto
 * de que o servidor sempre manda a mesma shape.
 */
export type EsteticaRow = {
  slug?: string | null;
  nome_negocio?: string | null;
  whatsapp?: string | null;
  instagram?: string | null;
  endereco?: string | null;
  cor_principal?: string | null;
  servicos?: unknown;
  galerias?: unknown;
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

function texto(valor: unknown): string | null {
  if (typeof valor !== 'string') return null;
  const limpo = valor.trim();
  return limpo === '' ? null : limpo;
}

/** "hero.jpg" no data.json é relativo à raiz; em /site/<slug> o navegador erro a path. */
function caminhoAbsoluto(valor: string | null | undefined): string | null {
  if (!valor) return null;
  const limpo = valor.trim();
  if (limpo === '') return null;
  if (/^(https?:)?\/\//i.test(limpo) || limpo.startsWith('/') || limpo.startsWith('data:')) return limpo;
  return `/${limpo}`;
}

/** Mesma checagem que Gallery.astro fazia: o asset do data.json existe em public/? */
function assetPublicoExiste(arquivo: string): boolean {
  return fs.existsSync(path.resolve(process.cwd(), 'public', arquivo));
}

/** data.json não trava se vier sem as listas; nada aqui é confiável às cegas. */
function servicesDoClient(client: ClientData): ServiceItem[] {
  if (!Array.isArray(client.services)) return [];

  return client.services
    .map((service) => ({
      name: service.name,
      priceFrom: texto(service.priceFrom),
      description: texto(service.description),
    }))
    .filter((service) => service.name !== '');
}

function galeriaDoClient(client: ClientData): GalleryItem[] {
  if (!Array.isArray(client.gallery)) return [];

  return client.gallery
    .filter((item) => typeof item.before === 'string' && typeof item.after === 'string')
    .map((item) => ({
      caption: item.caption,
      before: assetPublicoExiste(item.before) ? `/${item.before}` : null,
      after: assetPublicoExiste(item.after) ? `/${item.after}` : null,
    }));
}

/** jsonb do banco -> lista de serviços, item a item, sem confiar em nada. */
function servicesDaLinha(valor: unknown): ServiceItem[] {
  if (!Array.isArray(valor)) return [];

  return valor
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      name: texto(item.nome) ?? '',
      priceFrom: texto(item.preco),
      description: texto(item.descricao),
    }))
    .filter((service) => service.name !== '');
}

function galeriaDaLinha(valor: unknown): GalleryItem[] {
  if (!Array.isArray(valor)) return [];

  return valor
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      caption: texto(item.legenda) ?? '',
      before: urlDeImagem(item.antes_url),
      after: urlDeImagem(item.depois_url),
    }));
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
    services: servicesDoClient(client),
    gallery: galeriaDoClient(client),
    legal: {
      privacyPolicyUrl: client.legal.privacyPolicyUrl,
    },
  };
}

/** Página pública do cliente, alimentada pela linha de `/api/publico/<slug>/`. */
export function siteDaLinhaEstetica(row: EsteticaRow): SiteData {
  const nome = texto(row.nome_negocio) ?? 'Estética';
  const endereco = texto(row.endereco);
  // A API já grava o @ removido; refazer aqui cobre linha escrita direto no SQL.
  const instagram = (texto(row.instagram) ?? '').replace(/^@/, '');
  const whatsapp = texto(row.whatsapp);

  return {
    slug: texto(row.slug) ?? '',
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
    services: servicesDaLinha(row.servicos),
    gallery: galeriaDaLinha(row.galerias),
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

/** href de orçamento de um serviço específico, usado pelos cards de Services.astro. */
export function quoteHref(site: SiteData, serviceName: string): string | null {
  if (!site.business.whatsapp) return null;
  return `https://wa.me/${site.business.whatsapp}?text=${encodeURIComponent(`Olá! Quero solicitar um orçamento para ${serviceName}.`)}`;
}
