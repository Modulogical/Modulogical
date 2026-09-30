/**
 * Modulogical — Admin Dashboard Worker
 *
 * This Worker:
 *   1. Serves the admin dashboard/login assets.
 *   2. Validates existing Modulogical session tokens against ATLAS D1.
 *   3. Proxies admin login to the main Modulogical API so the existing
 *      Argon2 password system remains the single source of truth.
 *   4. Restricts moderation endpoints to ADMIN_ACCOUNT_ID.
 *   5. Reads and moderates Engine Forge metadata.
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
};

const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...JSON_HEADERS, ...CORS },
  });
}

function tokenFrom(request) {
  const auth = request.headers.get("Authorization") || "";
  if (auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  return new URL(request.url).searchParams.get("token") || "";
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

async function authenticateToken(request, env) {
  const token = tokenFrom(request);
  if (!token) return null;

  const hash = await sha256(token);

  return env.ATLAS.prepare(`
    SELECT a.id, a.username, a.name, a.account_subscription_status
    FROM sessions s
    JOIN accounts a ON a.id = s.account_id
    WHERE s.token_hash = ?
    LIMIT 1
  `).bind(hash).first();
}

async function requireAdmin(request, env) {
  const account = await authenticateToken(request, env);

  if (!account) {
    return { ok: false, response: json({ valid: false, error: "Unauthorized" }, 401) };
  }

  if (!env.ADMIN_ACCOUNT_ID || account.id !== env.ADMIN_ACCOUNT_ID) {
    return { ok: false, response: json({ valid: false, error: "Forbidden" }, 403) };
  }

  return { ok: true, account };
}

function validStatus(value) {
  return ["pending", "approved", "rejected"].includes(String(value || "").toLowerCase())
    ? String(value).toLowerCase()
    : "pending";
}

async function counts(env) {
  const row = await env.DB.prepare(`
    SELECT
      SUM(CASE WHEN marketplace_status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
      SUM(CASE WHEN marketplace_status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
      SUM(CASE WHEN marketplace_status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count
    FROM metadata
  `).first();

  return {
    pending_count: Number(row?.pending_count || 0),
    approved_count: Number(row?.approved_count || 0),
    rejected_count: Number(row?.rejected_count || 0),
  };
}

async function listItems(request, env) {
  const url = new URL(request.url);
  const status = validStatus(url.searchParams.get("status"));
  const search = (url.searchParams.get("search") || "").trim();
  const type = (url.searchParams.get("type") || "").trim();

  let sql = `
    SELECT item_id, item_type, developer_id, developer_tier,
           item_name, item_description, marketplace_status,
           submitted_at, moderated_at, moderated_by, rejection_reason
    FROM metadata
    WHERE marketplace_status = ?
  `;
  const params = [status];

  if (type) {
    sql += " AND item_type = ?";
    params.push(type);
  }

  if (search) {
    sql += " AND (item_name LIKE ? OR item_description LIKE ?)";
    const pattern = `%${search}%`;
    params.push(pattern, pattern);
  }

  sql += " ORDER BY submitted_at DESC, item_name ASC LIMIT 100";

  const result = await env.DB.prepare(sql).bind(...params).all();
  const rows = result.results || [];

  const developerIds = [...new Set(rows.map(x => x.developer_id).filter(Boolean))];
  const developers = new Map();

  for (const id of developerIds) {
    const developer = await env.ATLAS.prepare(
      "SELECT id, username, name FROM accounts WHERE id = ? LIMIT 1"
    ).bind(id).first();

    if (developer) developers.set(id, developer);
  }

  const items = rows.map(row => {
    const developer = developers.get(row.developer_id);
    return {
      ...row,
      developer_username: developer?.username || null,
      developer_name: developer?.name || null,
    };
  });

  return json({
    items,
    approved_count: (await counts(env)).approved_count,
    rejected_count: (await counts(env)).rejected_count,
  });
}

async function moderate(request, env, itemId, action, adminAccountId) {
  if (!itemId) return json({ error: "Missing item ID" }, 400);
  if (!["approve", "reject"].includes(action)) {
    return json({ error: "Invalid moderation action" }, 400);
  }

  const existing = await env.DB.prepare(
    "SELECT item_id, marketplace_status FROM metadata WHERE item_id = ? LIMIT 1"
  ).bind(itemId).first();

  if (!existing) return json({ error: "Item not found" }, 404);

  if (existing.marketplace_status !== "pending") {
    return json({
      error: "Item has already been moderated",
      marketplace_status: existing.marketplace_status,
    }, 409);
  }

  const body = await request.json().catch(() => ({}));
  const reason = String(body?.rejection_reason || "").trim();
  const status = action === "approve" ? "approved" : "rejected";
  const now = new Date().toISOString();

  await env.DB.prepare(`
    UPDATE metadata
    SET marketplace_status = ?,
        moderated_at = ?,
        moderated_by = ?,
        rejection_reason = ?
    WHERE item_id = ?
  `).bind(
    status,
    now,
    adminAccountId,
    status === "rejected" ? reason : "",
    itemId
  ).run();

  const item = await env.DB.prepare(`
    SELECT item_id, item_type, developer_id, developer_tier,
           item_name, item_description, marketplace_status,
           submitted_at, moderated_at, moderated_by, rejection_reason
    FROM metadata
    WHERE item_id = ?
    LIMIT 1
  `).bind(itemId).first();

  return json({ success: true, item });
}

async function proxyLogin(request, env) {
  if (!env.MODULOLOGICAL_API_URL) {
    return json({ message: "MODULOLOGICAL_API_URL is not configured." }, 500);
  }

  const incoming = await request.json().catch(() => null);
  if (!incoming || typeof incoming.username !== "string" || typeof incoming.password !== "string") {
    return json({ message: "Username and password are required." }, 400);
  }

  // The main Modulogical API remains responsible for Argon2 password
  // verification and session creation.
  const target = env.MODULOLOGICAL_API_URL.replace(/\/+$/, "") + "/login";

  const response = await fetch(target, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: incoming.username.trim(),
      password: incoming.password,
    }),
  });

  const text = await response.text();

  return new Response(text, {
    status: response.status,
    headers: { ...JSON_HEADERS, ...CORS },
  });
}

async function adminRoutes(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  // The login endpoint intentionally does not require an existing session.
  if (request.method === "POST" && path === "/login") {
    return proxyLogin(request, env);
  }

  // The dashboard's existing Modulogical.requireAuth() calls this endpoint.
  if (request.method === "GET" && path === "/api/auth/check") {
    const account = await authenticateToken(request, env);
    return json({ valid: !!account });
  }

  if (request.method === "GET" && path === "/auth/check") {
    const account = await authenticateToken(request, env);
    return json({ valid: !!account });
  }

  if (request.method === "GET" && path === "/admin/me") {
    const auth = await requireAdmin(request, env);
    if (!auth.ok) return auth.response;

    return json({
      valid: true,
      account_id: auth.account.id,
      username: auth.account.username,
      name: auth.account.name,
    });
  }

  const auth = await requireAdmin(request, env);
  if (!auth.ok) return auth.response;

  if (request.method === "GET" && path === "/admin/items") {
    return listItems(request, env);
  }

  const match = path.match(/^\/admin\/items\/([^/]+)\/(approve|reject)$/);
  if (request.method === "POST" && match) {
    return moderate(
      request,
      env,
      decodeURIComponent(match[1]),
      match[2],
      auth.account.id
    );
  }

  return json({ error: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(request.url);

    try {
      if (request.method === "GET" && url.pathname === "/health") {
        return json({ ok: true, service: "modulogical-admin-dashboard" });
      }

      // API routes are handled before static assets.
      if (
        url.pathname === "/login" ||
        url.pathname === "/auth/check" ||
        url.pathname === "/api/auth/check" ||
        url.pathname === "/admin" ||
        url.pathname.startsWith("/admin/")
      ) {
        return adminRoutes(request, env);
      }

      // Root is the dedicated admin login page.
      if (url.pathname === "/" || url.pathname === "") {
        const loginUrl = new URL("/login.html", request.url);
        return env.ASSETS.fetch(new Request(loginUrl, request));
      }

      return env.ASSETS.fetch(request);
    } catch (error) {
      console.error("Admin Worker error:", error);
      return json({ error: "Internal server error" }, 500);
    }
  },
};
