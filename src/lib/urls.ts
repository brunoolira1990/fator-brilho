/**
 * Guarda de URL de imagem. Mora num arquivo sem dependência de node:fs para que
 * o endpoint e o formulário do painel possam importar a mesma regra — site.ts
 * fala com o disco e, por isso, não pode entrar no bundle do navegador.
 */
export function urlDeImagem(valor: unknown): string | null {
  if (typeof valor !== 'string') return null;

  const bruto = valor.trim();

  if (bruto === '') return null;

  // Só http(s) ou caminho do próprio site. Um javascript: ou data:text/html
  // escrito direto na coluna viraria payload na página pública do cliente.
  if (/^https?:\/\//i.test(bruto)) return bruto;
  if (bruto.startsWith('/') && !bruto.startsWith('//')) return bruto;

  return null;
}
