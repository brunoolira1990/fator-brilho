# Astro Starter Kit: Minimal

```sh
npm create astro@latest -- --template minimal
```

> 🧑‍🚀 **Seasoned astronaut?** Delete this file. Have fun!

## 🚀 Project Structure

Inside of your Astro project, you'll see the following folders and files:

```text
/
├── public/
├── src/
│   └── pages/
│       └── index.astro
└── package.json
```

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

Any static assets, like images, can be placed in the `public/` directory.

## Backend

A API é um projeto Django separado que mora em [`backend-django/`](backend-django/README.md)
e roda na porta **8010** (a 8000 está ocupada pelo Docker nesta máquina). Do diretório da
raiz:

```sh
npm run api:dev    # python manage.py runserver 8010
```

E no `.env` da raiz, para o `astro dev` saber onde chamar:

```
PUBLIC_API_URL=http://127.0.0.1:8010
```

Em produção não há `PUBLIC_API_URL`: o [`vercel.json`](vercel.json) deste projeto reescreve
`/api/*` para o domínio do Django, e é isso que faz o cookie de sessão nascer no host do
frontend e o SSR do painel conseguir lê-lo. O passo a passo do deploy está no
[README do backend](backend-django/README.md).

## 🧞 Commands

All commands are run from the root of the project, from a terminal:

| Command                   | Action                                           |
| :------------------------ | :----------------------------------------------- |
| `npm install`             | Installs dependencies                            |
| `npm run dev`             | Starts local dev server at `localhost:4321`      |
| `npm run api:dev`         | Starts the Django API at `127.0.0.1:8010`        |
| `npm run build`           | Build your production site to `./dist/`          |
| `npm run preview`         | Preview your build locally, before deploying     |
| `npm run astro ...`       | Run CLI commands like `astro add`, `astro check` |
| `npm run astro -- --help` | Get help using the Astro CLI                     |

## 👀 Want to learn more?

Feel free to check [our documentation](https://docs.astro.build) or jump into our [Discord server](https://astro.build/chat).
