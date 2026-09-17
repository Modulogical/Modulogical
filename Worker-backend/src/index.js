export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Forward every backend request to the Python FastAPI backend.
    // Set BACKEND_ORIGIN to your Cloudflare Tunnel/ngrok HTTPS URL.
    const origin = env.BACKEND_ORIGIN.replace(/\/+$/, "");
    const target = origin + url.pathname + url.search;

    const headers = new Headers(request.headers);
    headers.set("X-Atlas-From", "modulogical-backend-worker");

    const proxied = new Request(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
      redirect: "manual",
    });

    return fetch(proxied);
  },
};
