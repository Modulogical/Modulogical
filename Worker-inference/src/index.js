/**
 * Modulogical / Atlas — Worker Inference
 *
 * Cloudflare Worker inference gateway.
 *
 * This worker does NOT run Ollama.
 * It forwards inference requests to the machine/server running
 * the actual Python inference service.
 *
 * Set:
 *   INFERENCE_ORIGIN = https://<your-inference-host>
 *
 * The Python inference service should expose:
 *   POST /generate
 *
 * Expected request body:
 *   {
 *     "prompt": "...",
 *     "model": "gemma3:latest",
 *     "temperature": 0.2,
 *     "stream": true
 *   }
 */

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(request),
      });
    }

    const incoming = new URL(request.url);

    if (incoming.pathname !== "/generate") {
      return json({ error: "Not found" }, 404, request);
    }

    if (request.method !== "POST") {
      return json({ error: "Method not allowed" }, 405, request);
    }

    if (!env.INFERENCE_ORIGIN) {
      return json(
        { error: "INFERENCE_ORIGIN is not configured." },
        500,
        request
      );
    }

    try {
      const base = env.INFERENCE_ORIGIN.endsWith("/")
        ? env.INFERENCE_ORIGIN.slice(0, -1)
        : env.INFERENCE_ORIGIN;

      const target = `${base}/generate`;

      const headers = new Headers(request.headers);
      headers.delete("host");

      const upstream = await fetch(target, {
        method: "POST",
        headers,
        body: request.body,
        redirect: "manual",
      });

      const responseHeaders = new Headers(upstream.headers);
      addCors(responseHeaders, request);

      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: responseHeaders,
      });
    } catch (error) {
      return json(
        {
          error: "Inference gateway error",
          detail: error instanceof Error ? error.message : String(error),
        },
        502,
        request
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
  headers.set(
    "Access-Control-Allow-Origin",
    request.headers.get("Origin") || "*"
  );
  headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
}

function json(data, status, request) {
  const headers = corsHeaders(request);
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(data), { status, headers });
}
