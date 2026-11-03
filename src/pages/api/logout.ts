import type { APIRoute } from 'astro';
import { createSupabaseServerClient } from '../../lib/supabase-ssr';

export const POST: APIRoute = async (context) => {
  const supabase = createSupabaseServerClient(context);
  await supabase.auth.signOut();

  return context.redirect('/', 303);
};
