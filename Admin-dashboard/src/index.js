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

function unauthorized(message = "Authentication required.") {
  return cors(json({ error: message }, 401));
}

function forbidden(message = "Admin access required.") {
  return cors(json({ error: message }, 403));
}

function getBearerToken(request) {
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Bearer ")) return null;
  const token = header.slice(7).trim();
  return token || null;
}

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

/*
 * Authenticate the request directly against the same ATLAS D1 database
 * used by Modulogical's main authentication system.
 *
 * Admin status is determined solely by:
 *
 *   accounts.account_subscription_status = "admin"
 *
 * No hard-coded admin account ID is required.
 */
async function getAdminAccount(request, env) {
  const token = getBearerToken(request);

  if (!token) {
    return { error: unauthorized() };
  }

  try {
    const tokenHash = await sha256Hex(token);

    const account = await env.ATLAS.prepare(`
      SELECT
        a.id,
        a.username,
        a.name,
        a.account_subscription_status
      FROM sessions s
      JOIN accounts a ON a.id = s.account_id
      WHERE s.token_hash = ?
        AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
      LIMIT 1
    `).bind(tokenHash).first();

    if (!account) {
      return {
        error: unauthorized("Invalid or expired session."),
      };
    }

    if (account.account_subscription_status !== "admin") {
      return {
        error: forbidden(),
      };
    }

    return { account };
  } catch (error) {
    return {
      error: cors(json({
        error: "Could not verify admin account.",
        detail: error instanceof Error ? error.message : String(error),
      }, 500)),
    };
  }
}

async function listItems(request, env) {
  const auth = await getAdminAccount(request, env);
  if (auth.error) return auth.error;

  const url = new URL(request.url);
  const status = (url.searchParams.get("status") || "pending").trim();
  const search = (url.searchParams.get("search") || "").trim();
  const type = (url.searchParams.get("type") || "").trim();

  const allowedStatuses = new Set(["pending", "approved", "rejected", "all"]);
  if (!allowedStatuses.has(status)) {
    return cors(json({ error: "Invalid status." }, 400));
  }

  let query = `
    SELECT
      m.item_id,
      m.item_type,
      m.developer_id,
      m.developer_tier,
      m.item_name,
      m.item_description,
      m.marketplace_status,
      m.submitted_at,
      m.moderated_at,
      m.moderated_by,
      m.rejection_reason,
      a.username AS developer_username,
      a.name AS developer_name
    FROM metadata m
    LEFT JOIN accounts a ON a.id = m.developer_id
    WHERE 1 = 1
  `;

  const params = [];

  if (status !== "all") {
    query += ` AND m.marketplace_status = ?`;
    params.push(status);
  }

  if (type) {
    query += ` AND m.item_type = ?`;
    params.push(type);
  }

  if (search) {
    query += ` AND (
      LOWER(m.item_name) LIKE LOWER(?) OR
      LOWER(m.item_description) LIKE LOWER(?) OR
      LOWER(a.username) LIKE LOWER(?) OR
      LOWER(a.name) LIKE LOWER(?)
    )`;
    const pattern = `%${search}%`;
    params.push(pattern, pattern, pattern, pattern);
  }

  query += ` ORDER BY COALESCE(m.submitted_at, '') DESC, m.item_name ASC LIMIT 100`;

  try {
    const result = await env.DB.prepare(query).bind(...params).all();

    const counts = await env.DB.prepare(`
      SELECT marketplace_status, COUNT(*) AS count
      FROM metadata
      GROUP BY marketplace_status
    `).all();

    const countMap = {};
    for (const row of counts.results || []) {
      countMap[row.marketplace_status] = Number(row.count);
    }

    return cors(json({
      admin: true,
      items: result.results || [],
      pending_count: countMap.pending || 0,
      approved_count: countMap.approved || 0,
      rejected_count: countMap.rejected || 0,
    }));
  } catch (error) {
    return cors(json({
      error: "Could not load marketplace submissions.",
      detail: error instanceof Error ? error.message : String(error),
    }, 500));
  }
}

async function getItem(request, env, itemId) {
  const auth = await getAdminAccount(request, env);
  if (auth.error) return auth.error;

  try {
    const item = await env.DB.prepare(`
      SELECT
        m.*,
        a.username AS developer_username,
        a.name AS developer_name
      FROM metadata m
      LEFT JOIN accounts a ON a.id = m.developer_id
      WHERE m.item_id = ?
      LIMIT 1
    `).bind(itemId).first();

    if (!item) {
      return cors(json({ error: "Item not found." }, 404));
    }

    return cors(json({ item }));
  } catch (error) {
    return cors(json({
      error: "Could not load item.",
      detail: error instanceof Error ? error.message : String(error),
    }, 500));
  }
}

async function moderateItem(request, env, itemId, action) {
  const auth = await getAdminAccount(request, env);
  if (auth.error) return auth.error;

  if (action !== "approve" && action !== "reject") {
    return cors(json({ error: "Invalid moderation action." }, 400));
  }

  let body = {};
  if (request.method === "POST") {
    try {
      body = await request.json();
    } catch {
      body = {};
    }
  }

  const rejectionReason =
    typeof body.rejection_reason === "string"
      ? body.rejection_reason.trim()
      : "";

  if (action === "reject" && rejectionReason.length > 2000) {
    return cors(json({
      error: "Rejection reason is too long."
    }, 400));
  }

  const newStatus = action === "approve" ? "approved" : "rejected";
  const moderatedBy = auth.account.id;
  const moderatedAt = new Date().toISOString();

  try {
    const item = await env.DB.prepare(`
      SELECT item_id, marketplace_status
      FROM metadata
      WHERE item_id = ?
      LIMIT 1
    `).bind(itemId).first();

    if (!item) {
      return cors(json({ error: "Item not found." }, 404));
    }

    if (item.marketplace_status !== "pending") {
      return cors(json({
        error: "Item has already been moderated.",
        marketplace_status: item.marketplace_status,
      }, 409));
    }

    await env.DB.prepare(`
      UPDATE metadata
      SET
        marketplace_status = ?,
        moderated_at = ?,
        moderated_by = ?,
        rejection_reason = ?
      WHERE item_id = ?
        AND marketplace_status = 'pending'
    `).bind(
      newStatus,
      moderatedAt,
      moderatedBy,
      action === "reject" ? rejectionReason : "",
      itemId
    ).run();

    return cors(json({
      success: true,
      item_id: itemId,
      marketplace_status: newStatus,
      moderated_at: moderatedAt,
      moderated_by: moderatedBy,
      rejection_reason: action === "reject" ? rejectionReason : "",
    }));
  } catch (error) {
    return cors(json({
      error: "Could not moderate item.",
      detail: error instanceof Error ? error.message : String(error),
    }, 500));
  }
}

async function health(env) {
  const databases = {
    metadata: false,
    accounts: false,
  };

  try {
    await env.DB.prepare("SELECT 1").first();
    databases.metadata = true;
  } catch {}

  try {
    await env.ATLAS.prepare("SELECT 1").first();
    databases.accounts = true;
  } catch {}

  const online = databases.metadata && databases.accounts;

  return {
    status: online ? "ok" : "degraded",
    service: "admin",
    databases,
    admin_auth: "account_subscription_status=admin",
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

    if (url.pathname === "/admin/me" && request.method === "GET") {
      const auth = await getAdminAccount(request, env);
      if (auth.error) return auth.error;

      return cors(json({
        admin: true,
        account: auth.account,
      }));
    }

    if (url.pathname === "/api/auth/check" && request.method === "GET") {
      const auth = await getAdminAccount(request, env);
      if (auth.error) return auth.error;

      return cors(json({
        valid: true,
        admin: true,
        account_id: auth.account.id,
        username: auth.account.username,
        name: auth.account.name,
        account_subscription_status:
          auth.account.account_subscription_status,
      }));
    }

    if (url.pathname === "/admin/items" && request.method === "GET") {
      return listItems(request, env);
    }

    const itemMatch = url.pathname.match(
      /^\/admin\/items\/([^/]+)$/
    );

    if (itemMatch && request.method === "GET") {
      return getItem(request, env, decodeURIComponent(itemMatch[1]));
    }

    const moderationMatch = url.pathname.match(
      /^\/admin\/items\/([^/]+)\/(approve|reject)$/
    );

    if (
      moderationMatch &&
      request.method === "POST"
    ) {
      return moderateItem(
        request,
        env,
        decodeURIComponent(moderationMatch[1]),
        moderationMatch[2]
      );
    }

    return cors(json({ error: "Not found." }, 404));
  },
};
