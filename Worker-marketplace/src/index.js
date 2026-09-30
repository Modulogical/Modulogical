function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {"Content-Type": "application/json; charset=utf-8"},
  });
}
//
function cors(response) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  return new Response(response.body, {status: response.status, headers});
}

const TYPES = new Set(["module", "personality", "workflow", "webvector"]);

function normalizeType(value) {
  if (!value) return null;
  const type = value.trim().toLowerCase();
  return TYPES.has(type) ? type : null;
}

async function listItems(request, env) {
  const url = new URL(request.url);
  const search = (url.searchParams.get("search") || "").trim();
  const requestedType = url.searchParams.get("type");
  const type = normalizeType(requestedType);

  if (requestedType && !type) {
    return cors(json({
      error: "Invalid item type. Use module, personality, workflow, or webvector."
    }, 400));
  }

  const rawLimit = Number.parseInt(url.searchParams.get("limit") || "50", 10);
  const limit = Math.min(Math.max(Number.isFinite(rawLimit) ? rawLimit : 50, 1), 100);

  const conditions = [];
  const values = [];

  if (type) {
    conditions.push("item_type = ?");
    values.push(type);
  }

  if (search) {
    conditions.push("(LOWER(item_name) LIKE ? OR LOWER(item_description) LIKE ?)");
    const pattern = `%${search.toLowerCase()}%`;
    values.push(pattern, pattern);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";

  const result = await env.DB.prepare(`
    SELECT item_id, item_type, developer_id, developer_tier,
           item_name, item_description
    FROM metadata
    ${where}
    ORDER BY item_name COLLATE NOCASE ASC
    LIMIT ?
  `).bind(...values, limit).all();

  return cors(json({
    success: true,
    items: result.results || [],
    count: (result.results || []).length
  }));
}

async function getItem(env, itemId) {
  if (!itemId) return cors(json({error: "Item ID is required."}, 400));

  const item = await env.DB.prepare(`
    SELECT item_id, item_type, developer_id, developer_tier,
           item_name, item_description
    FROM metadata
    WHERE item_id = ?
    LIMIT 1
  `).bind(itemId).first();

  if (!item) return cors(json({error: "Item not found."}, 404));

  let developer = null;
  try {
    developer = await env.ATLAS.prepare(`
      SELECT id, username, name
      FROM accounts
      WHERE id = ?
      LIMIT 1
    `).bind(item.developer_id).first();
  } catch {}

  return cors(json({
    success: true,
    item: {
      ...item,
      developer: developer ? {
        id: developer.id,
        username: developer.username,
        name: developer.name
      } : null
    }
  }));
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization"
        }
      });
    }

    const url = new URL(request.url);

    if (url.pathname === "/health" && request.method === "GET") {
      try {
        await env.DB.prepare("SELECT 1").first();
        await env.ATLAS.prepare("SELECT 1").first();
        return cors(json({status: "ok", service: "marketplace"}));
      } catch (error) {
        return cors(json({
          status: "degraded",
          service: "marketplace",
          detail: error instanceof Error ? error.message : String(error)
        }, 500));
      }
    }

    try {
      if (url.pathname === "/items" && request.method === "GET") {
        return await listItems(request, env);
      }

      if (url.pathname.startsWith("/items/") && request.method === "GET") {
        const itemId = decodeURIComponent(url.pathname.slice("/items/".length));
        return await getItem(env, itemId);
      }
    } catch (error) {
      return cors(json({
        error: "Marketplace request failed.",
        detail: error instanceof Error ? error.message : String(error)
      }, 500));
    }

    return cors(json({error: "Not found."}, 404));
  }
};
