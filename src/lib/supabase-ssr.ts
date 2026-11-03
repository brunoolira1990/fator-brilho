import { createServerClient } from '@supabase/ssr';
import type { APIContext } from 'astro';

function readCookies(header: string | null) {
  if (!header) return [];

  return header
    .split(';')
    .map((pair) => pair.trim())
    .filter((pair) => pair.includes('='))
    .map((pair) => {
      const separator = pair.indexOf('=');
      return {
        name: pair.slice(0, separator),
        value: decodeURIComponent(pair.slice(separator + 1)),
      };
    });
}

export function createSupabaseServerClient(context: APIContext) {
  return createServerClient(
    import.meta.env.PUBLIC_SUPABASE_URL,
    import.meta.env.PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll() {
          return readCookies(context.request.headers.get('cookie'));
        },
        setAll(cookiesToSet) {
          for (const { name, value, options } of cookiesToSet) {
            context.cookies.set(name, value, {
              ...options,
              path: '/',
              httpOnly: true,
              sameSite: 'lax',
              secure: import.meta.env.PROD,
            });
          }
        },
      },
    }
  );
}

export function json(status: number, payload: Record<string, unknown>) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

export async function readCredentials(
  request: Request
): Promise<{ email: string; password: string } | null> {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return null;
  }

  if (!body || typeof body !== 'object') return null;

  const { email, password } = body as Record<string, unknown>;
  if (typeof email !== 'string' || typeof password !== 'string') return null;

  const trimmedEmail = email.trim();
  if (!trimmedEmail || !password) return null;

  return { email: trimmedEmail, password };
}
