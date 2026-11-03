import type { APIRoute } from 'astro';
import { createSupabaseServerClient, json, readCredentials } from '../../../lib/supabase-ssr';

export const POST: APIRoute = async (context) => {
  const credentials = await readCredentials(context.request);

  if (!credentials) {
    return json(400, { ok: false, error: 'Informe e-mail e senha.' });
  }

  if (credentials.password.length < 6) {
    return json(400, { ok: false, error: 'A senha deve ter pelo menos 6 caracteres.' });
  }

  const supabase = createSupabaseServerClient(context);
  const { data, error } = await supabase.auth.signUp(credentials);

  if (error) {
    return json(400, { ok: false, error: error.message });
  }

  return json(200, { ok: true, needsConfirmation: !data.session });
};
