export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname !== env.PUBLIC_HOST) return new Response('Not found', { status: 404 });
    if (!env.ORIGIN_AUTH) return new Response('Service unavailable', { status: 503 });
    const origin = new URL(env.ORIGIN_URL);
    origin.pathname = url.pathname;
    origin.search = url.search;
    const headers = new Headers(request.headers);
    headers.delete('Host');
    headers.set('X-Origin-Authorization', env.ORIGIN_AUTH);
    headers.set('X-Forwarded-Host', env.PUBLIC_HOST);
    headers.set('X-Forwarded-Proto', 'https');
    headers.set('Cache-Control', 'no-store');
    try {
      const response = await fetch(new Request(origin, {
        method: request.method, headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        redirect: 'manual',
      }), { cache: 'no-store' });
      const result = new Response(response.body, response);
      result.headers.set('Cache-Control', 'no-store');
      result.headers.delete('X-Origin-Authorization');
      return result;
    } catch {
      console.error(JSON.stringify({ event: 'origin_unavailable' }));
      return new Response('Service unavailable', { status: 502, headers: { 'Cache-Control': 'no-store' } });
    }
  },
};
