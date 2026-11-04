/**
 * Leitura única de variáveis de ambiente do servidor.
 *
 * Só `process.env`. A tentação de cair em `import.meta.env` como fallback existe, e
 * ela foi medida antes de ser descartada — duas razões:
 *
 *  1. No build, o Vite serializa o objeto `import.meta.env` inteiro como literal.
 *     No bundle do servidor isso significa a chave do Asaas escrita no artefato
 *     implantado (verificado: `.vercel/output/_functions/chunks/asaas_*.mjs`
 *     continha os 166 caracteres da chave real). O bundle do navegador fica limpo,
 *     mas artefato de função também é cópia de segredo — e não precisa existir.
 *  2. Valor inlinado é valor congelado no momento do build: uma variável trocada no
 *     painel da Vercel sem rebuild não teria efeito nenhum.
 *
 * O que fez o `process.env` funcionar em desenvolvimento é o `dotenv.config()` do
 * `astro.config.mjs`. Sem ele o dev server não vê o `.env` (medição: rotas que
 * liam `process.env` recebiam `undefined` e o webhook respondia 500 "falta token"
 * com o token no arquivo). E o `dotenv` puro é escolhido de propósito em vez do
 * caminho do Vite, que expande `$`: `ASAAS_API_KEY=$aact_prod_...` chegava como
 * string vazia por `import.meta.env`, com aspas ou sem aspas, e só voltava inteiro
 * escapando o `$` como `\$`. No deploy não há `.env` (gitignored) — lá quem preenche
 * o `process.env` é a própria Vercel, com o valor cru.
 *
 * Vazio conta como ausente: chave vazia passa pelo `||` e morre na API remota.
 */
export function variavel(chave: string): string | null {
  const bruto = (process.env[chave] ?? '').trim();

  return bruto || null;
}
