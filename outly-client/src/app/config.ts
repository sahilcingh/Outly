// Same-origin by default: next.config.ts proxies /backend/* to the real API,
// so the browser never makes a cross-origin request and session cookies just
// work. Set NEXT_PUBLIC_API_URL to bypass the proxy (e.g. a separately-hosted
// backend with its own CORS/cookie policy already handled server-side).
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/backend";
