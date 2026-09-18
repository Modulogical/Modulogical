/**
 * Modulogical / Atlas — Inference gateway
 *
 * This Worker ONLY forwards requests. Ollama runs on the machine/server
 * behind INFERENCE_ORIGIN.
 *
 * INFERENCE_ORIGIN must be the public origin of the Python inference server,
 * NOT inference.modulogical.com itself.
 */

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(request),
      });
    }

    if (!env.INFERENCE_ORIGIN) {
      return json({ error: "INFERENCE_ORIGIN is not configured" }, 500, request);
    }

    const incoming = new URL(request.url);

    // Only expose the inference endpoint through this gateway.
    if (incoming.pathname !== "/generate") {
      return json({ error: "Not found" }, 404, request);
    }

    if (request.method !== "POST") {
      return json({ error: "Method not allowed" }, 405, request);
    }

    try {
      const origin = env.INFERENCE_ORIGIN.replace(/\/+$/, "");
      const target = `${origin}/generate`;

      console.log(`[Inference] forwarding POST /generate -> ${target}`);

      // Clone only the headers that should be sent upstream.
      const headers = new Headers();
      const contentType = request.headers.get("content-type");
      if (contentType) headers.set("content-type", contentType);
      const authorization = request.headers.get("authorization");
      if (authorization) headers.set("authorization", authorization);

      const upstream = await fetch(target, {
        method: "POST",
        headers,
        body: request.body,
      });

      console.log(`[Inference] upstream status: ${upstream.status}`);

      const responseHeaders = new Headers(upstream.headers);
      addCors(responseHeaders, request);

      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: responseHeaders,
      });
    } catch (error) {
      console.error("[Inference] upstream fetch failed:", error);

      return json(
        {
          error: "Inference gateway error",
          detail: error instanceof Error ? error.message : String(error),
          target: env.INFERENCE_ORIGIN,
        },
        502,
        request,
      );
    }
  },
};

function corsHeaders(request) {
  const headers = new Headers();
  headers.set("Access-Control-Allow-Origin", request.headers.get("Origin") || "*");
  headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  return headers;
}

function addCors(headers, request) {
  const cors = corsHeaders(request);
  for (const [key, value] of cors) headers.set(key, value);
}

function json(data, status, request) {
  const headers = corsHeaders(request);
  headers.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(data), { status, headers });
}
