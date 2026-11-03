import type { APIRoute } from 'astro';
import { createSupabaseServerClient, json, readCredentials } from '../../../lib/supabase-ssr';

export const POST: APIRoute = async (context) => {
  const credentials = await readCredentials(context.request);

  if (!credentials) {
    return json(400, { ok: false, error: 'Informe e-mail e senha.' });
  }

  const supabase = createSupabaseServerClient(context);
  const { error } = await supabase.auth.signInWithPassword(credentials);

  if (error) {
    return json(401, { ok: false, error: error.message });
  }

  return json(200, { ok: true });
};
