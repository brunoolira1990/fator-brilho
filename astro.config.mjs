// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

import react from '@astrojs/react';

import vercel from '@astrojs/vercel';

import dotenv from 'dotenv';

// O Astro não joga o `.env` no `process.env` do dev server, e o caminho do Vite
// (`import.meta.env`) expande o `$` da chave do Asaas como se fosse outra variável
// — a chave chega vazia. Carregar o arquivo aqui, com o dotenv puro e sem expansão,
// devolve o valor intacto no `process.env` do processo que serve o site. Não
// sobrescreve nada que já exista: no deploy é a Vercel quem fornece as variáveis,
// e ali o arquivo `.env` nem está (gitignored).
dotenv.config();

// https://astro.build/config
export default defineConfig({
  output: 'server',
  vite: {
    plugins: [tailwindcss()]
  },

  integrations: [react()],
  adapter: vercel()
});