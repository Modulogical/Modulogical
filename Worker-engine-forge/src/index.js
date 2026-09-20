
const ITEM_TYPES = new Set(["module", "personality", "workflow", "webvector"]);

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function cors(response) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  return new Response(response.body, { status: response.status, headers });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization"
        }
      });
    }

    const url = new URL(request.url);

    if (url.pathname === "/health" && request.method === "GET") {
      let inference = "offline";
      try {
        const r = await fetch(`${env.INFERENCE_URL}/health`, {
          signal: AbortSignal.timeout(5000)
        });
        if (r.ok) inference = "online";
      } catch (_) {}

      return cors(json({
        status: "ok",
        service: "engine-forge",
        inference
      }));
    }

    if (url.pathname === "/produce" && request.method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch (_) {
        return cors(json({ error: "Request body must be valid JSON." }, 400));
      }

      const type = String(body.item_type || "").toLowerCase();
      if (!ITEM_TYPES.has(type)) {
        return cors(json({ error: "Invalid item_type." }, 400));
      }

      const required = [
        "title", "developer_id", "developer_tier", "item_id",
        "schema", "item_version", "item_price", "item_dependencies"
      ];
      for (const field of required) {
        if (body[field] === undefined || body[field] === null || body[field] === "") {
          return cors(json({ error: `Missing field: ${field}` }, 400));
        }
      }

      // Table names cannot be parameterized, so they are selected only
      // from the fixed whitelist above.
      const table = `${type}_queue`;

      const schema = typeof body.schema === "string"
        ? body.schema
        : JSON.stringify(body.schema);

      const display = typeof body.display === "string"
        ? body.display
        : JSON.stringify(body.display ?? {});

      const dependencies = typeof body.item_dependencies === "string"
        ? body.item_dependencies
        : JSON.stringify(body.item_dependencies);

      // The current queue schema has no code column, so /produce stores
      // exactly the fields defined by that schema. Code is intentionally
      // not returned by the website.
      const sql = `
        INSERT INTO ${table}
        (title, developer_id, developer_tier, ${type}_id, schema,
         description, display, ${type}_version, ${type}_price, ${type}_dependencies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `;

      try {
        await env.DB.prepare(sql).bind(
          String(body.title),
          String(body.developer_id),
          String(body.developer_tier),
          String(body.item_id),
          schema,
          String(body.description ?? ""),
          display,
          String(body.item_version),
          String(body.item_price),
          dependencies
        ).run();

        return cors(json({
          success: true,
          item_type: type,
          item_id: body.item_id,
          message: "Item queued successfully."
        }, 201));
      } catch (error) {
        return cors(json({
          error: "Could not queue item.",
          detail: error instanceof Error ? error.message : String(error)
        }, 500));
      }
    }

    return cors(json({ error: "Not found." }, 404));
  }
};
