
const ITEM_TYPES = ["module", "personality", "workflow", "webvector"];

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function cors(response) {
  const h = new Headers(response.headers);
  h.set("Access-Control-Allow-Origin", "*");
  h.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  h.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  return new Response(response.body, { status: response.status, headers: h });
}

function parseJSON(value, fallback) {
  if (typeof value !== "string") return value ?? fallback;
  try { return JSON.parse(value); } catch { return null; }
}

async function produce(type, request, env) {
  let body;
  try { body = await request.json(); }
  catch { return cors(json({ error: "Request body must be valid JSON." }, 400)); }

  const required = [
    "title", "developer_id", "developer_tier", "item_id",
    "item_version", "item_price", "item_dependencies", "code"
  ];
  for (const field of required) {
    if (body[field] === undefined || body[field] === null || body[field] === "") {
      return cors(json({ error: `Missing field: ${field}` }, 400));
    }
  }

  const schema = parseJSON(body.schema, {});
  const display = parseJSON(body.display, {});
  const dependencies = parseJSON(body.item_dependencies, []);
  const information = parseJSON(body.information, {});

  if (schema === null) return cors(json({ error: "schema must be valid JSON." }, 400));
  if (display === null) return cors(json({ error: "display must be valid JSON." }, 400));
  if (dependencies === null) return cors(json({ error: "item_dependencies must be valid JSON." }, 400));
  if (type === "webvector" && information === null) {
    return cors(json({ error: "information must be valid JSON." }, 400));
  }

  const table = `${type}_queue`;
  const itemIdColumn = `${type}_id`;
  const versionColumn = `${type}_version`;
  const priceColumn = `${type}_price`;
  const depsColumn = `${type}_dependencies`;

  // The code field is intentionally submitted by the Forge UI.
  // If the queue schema has not yet been given a code column, the query
  // returns a clear schema error rather than silently dropping the code.
  const sql = `
    INSERT INTO ${table}
    (title, developer_id, developer_tier, ${itemIdColumn}, schema,
     description, display, ${versionColumn}, ${priceColumn}, ${depsColumn}, code)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `;

  try {
    await env.DB.prepare(sql).bind(
      String(body.title),
      String(body.developer_id),
      String(body.developer_tier),
      String(body.item_id),
      JSON.stringify(type === "webvector" ? information : schema),
      String(body.description ?? ""),
      JSON.stringify(display),
      String(body.item_version),
      String(body.item_price),
      JSON.stringify(dependencies),
      String(body.code)
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

    if (request.method === "POST") {
      const match = url.pathname.match(/^\/produce\/(module|personality|workflow|webvector)$/);
      if (match) return produce(match[1], request, env);
    }

    return cors(json({ error: "Not found." }, 404));
  }
};
