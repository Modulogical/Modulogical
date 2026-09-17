export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname !== "/generate") {
      return new Response("Not found", { status: 404 });
    }

    const origin = env.INFERENCE_ORIGIN.replace(/\/+$/, "");
    const target = origin + "/generate";

    const headers = new Headers(request.headers);
    headers.set("X-Atlas-From", "modulogical-inference-worker");

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
