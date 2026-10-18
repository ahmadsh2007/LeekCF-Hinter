// Cloud Run appends the address it saw to X-Forwarded-For, so the right-most entry is the one to trust;
// anything to its left was sent by the client and can be forged.
export function clientIp(forwardedFor: string | undefined, socketAddress: string | undefined): string {
  const last = forwardedFor?.split(',').pop()?.trim()
  return last || socketAddress || 'unknown'
}
