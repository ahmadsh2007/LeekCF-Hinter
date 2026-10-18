// The public API only ever needs the publishable (anon) key: the database view is the one door that key can open.
// Starting with a privileged key would make a bug in this service a full database leak, so refuse it.
export function assertPublicKey(key: string | undefined): void {
  if (!key?.trim()) {
    throw new Error('SUPABASE_PUBLISHABLE_KEY is not set (use the publishable / anon key, never the secret key).')
  }
  if (key.startsWith('sb_secret_')) {
    throw new Error('SUPABASE_PUBLISHABLE_KEY holds a secret key. The public API must use the publishable (anon) key.')
  }
  const payload = key.split('.')[1]
  if (key.split('.').length === 3 && payload) {
    try {
      const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'))
      if (claims?.role === 'service_role') {
        throw new Error('SUPABASE_PUBLISHABLE_KEY holds a service_role key. The public API must use the anon key.')
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes('service_role')) throw error
      // not a readable JWT: nothing more to check
    }
  }
}
