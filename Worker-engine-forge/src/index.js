const ITEM_TYPES = ["module", "personality", "workflow", "webvector"];

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}

function cors(response) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  return new Response(response.body, {
    status: response.status,
    headers,
  });
}

function parseJSON(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function typeConfig(type) {
  return {
    table: `${type}_queue`,
    idColumn: `${type}_id`,
    versionColumn: `${type}_version`,
    priceColumn: `${type}_price`,
    dependenciesColumn: `${type}_dependencies`,
    codeColumn: `${type}_code`,
  };
}

async function produce(type, request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return cors(json({ error: "Request body must be valid JSON." }, 400));
  }

  const required = [
    "title",
    "developer_id",
    "developer_tier",
    "item_id",
    "item_version",
    "item_price",
    "item_dependencies",
    "code",
  ];

  const missing = required.filter(
    (field) => body[field] === undefined || body[field] === null || body[field] === ""
  );

  if (missing.length) {
    return cors(json({
      error: "Missing required fields.",
      fields: missing,
    }, 400));
  }

  let schema = parseJSON(body.schema, {});
  const display = parseJSON(body.display, {});
  const dependencies = parseJSON(body.item_dependencies, []);

  if (schema === null) {
    return cors(json({ error: "schema must contain valid JSON." }, 400));
  }
  if (display === null) {
    return cors(json({ error: "display must contain valid JSON." }, 400));
  }
  if (dependencies === null) {
    return cors(json({ error: "item_dependencies must contain valid JSON." }, 400));
  }

  // WebVector's "Information" field is the stored schema payload.
  if (type === "webvector") {
    const information = parseJSON(body.information, {});
    if (information === null) {
      return cors(json({ error: "information must contain valid JSON." }, 400));
    }
    schema = information;
  }

  // Workflow flowchart data is stored alongside the workflow schema.
  if (type === "workflow" && body.flow !== undefined) {
    const flow = parseJSON(body.flow, null);
    if (flow === null) {
      return cors(json({ error: "flow must contain valid JSON." }, 400));
    }
    if (typeof schema !== "object" || Array.isArray(schema) || schema === null) {
      schema = { schema };
    }
    schema.flow = flow;
  }

  const cfg = typeConfig(type);

  const sql = `
    INSERT INTO ${cfg.table}
      (
        title,
        developer_id,
        developer_tier,
        ${cfg.idColumn},
        schema,
        description,
        display,
        ${cfg.versionColumn},
        ${cfg.priceColumn},
        ${cfg.dependenciesColumn},
        ${cfg.codeColumn}
      )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `;

  try {
    await env.DB.prepare(sql).bind(
      String(body.title),
      String(body.developer_id),
      String(body.developer_tier),
      String(body.item_id),
      JSON.stringify(schema),
      String(body.description ?? ""),
      JSON.stringify(display),
      String(body.item_version),
      String(body.item_price),
      JSON.stringify(dependencies),
      String(body.code),
    ).run();

    return cors(json({
      success: true,
      item_type: type,
      item_id: body.item_id,
      message: "Item queued successfully.",
    }, 201));
  } catch (error) {
    return cors(json({
      error: "Could not queue item.",
      detail: error instanceof Error ? error.message : String(error),
    }, 500));
  }
}

async function health(env) {
  let database = "offline";
  try {
    await env.DB.prepare("SELECT 1").first();
    database = "online";
  } catch {}

  return {
    status: database === "online" ? "ok" : "degraded",
    service: "engine-forge",
    database,
    // Engine Forge itself does not depend on the inference PC.
    inference_dependency: "none",
  };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
      });
    }

    const url = new URL(request.url);

    if (url.pathname === "/health" && request.method === "GET") {
      return cors(json(await health(env)));
    }

    if (request.method === "POST") {
      const match = url.pathname.match(
        /^\/produce\/(module|personality|workflow|webvector)$/
      );
      if (match) {
        return produce(match[1], request, env);
      }
    }

    return cors(json({ error: "Not found." }, 404));
  },
};
