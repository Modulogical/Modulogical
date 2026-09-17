const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "Content-Type, Authorization",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: jsonHeaders,
  });
}

function getToken(request) {
  const auth = request.headers.get("Authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) return null;
  return auth.slice(7).trim() || null;
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function randomToken() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function bodyJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function authenticate(request, env) {
  const token = getToken(request);
  if (!token) return null;

  const tokenHash = await sha256(token);
  return await env.DB.prepare(`
    SELECT a.id, a.username, a.name
    FROM sessions s
    JOIN accounts a ON a.id = s.account_id
    WHERE s.token_hash = ?
  `).bind(tokenHash).first();
}

function newAccountId() {
  const bytes = new Uint8Array(25);
  crypto.getRandomValues(bytes);
  const raw = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${raw.slice(0, 4)}-${raw.slice(4, 8)}-${raw.slice(8, 13)}-${raw.slice(13, 18)}-${raw.slice(18)}`;
}

async function handleRegister(request, env) {
  const body = await bodyJson(request);
  if (!body || !body.username || !body.name || !body.password) {
    return json({ error: "username, name and password are required" }, 400);
  }

  const username = String(body.username).trim();
  const name = String(body.name).trim();
  const passwordHash = String(body.password);

  const existing = await env.DB.prepare(
    "SELECT id FROM accounts WHERE username = ?"
  ).bind(username).first();

  if (existing) return json({ error: "Username already exists" }, 409);

  const accountId = newAccountId();

  // The existing Atlas client/backend is expected to send a password hash.
  // Plaintext password hashing is intentionally not performed in this Worker.
  await env.DB.prepare(`
    INSERT INTO accounts (id, username, name, password_hash)
    VALUES (?, ?, ?, ?)
  `).bind(accountId, username, name, passwordHash).run();

  await env.DB.prepare(`
    INSERT INTO account_config (account_id, model, personality, system_instructions)
    VALUES (?, 'gemma3:latest', '', '')
  `).bind(accountId).run();

  return json({ success: true, account: { id: accountId, username, name } }, 201);
}

async function handleLogin(request, env) {
  const body = await bodyJson(request);
  if (!body || !body.username || !body.password) {
    return json({ error: "username and password are required" }, 400);
  }

  const account = await env.DB.prepare(`
    SELECT id, username, name, password_hash
    FROM accounts
    WHERE username = ?
  `).bind(String(body.username).trim()).first();

  if (!account) return json({ error: "Invalid credentials" }, 401);

  // Password verification is delegated to the existing client/backend hash
  // contract. If the caller supplies a hash, compare it to the stored hash.
  if (String(body.password) !== String(account.password_hash)) {
    return json({ error: "Invalid credentials" }, 401);
  }

  const token = randomToken();
  const tokenHash = await sha256(token);

  await env.DB.prepare(`
    INSERT INTO sessions (token_hash, account_id)
    VALUES (?, ?)
  `).bind(tokenHash, account.id).run();

  return json({
    success: true,
    token,
    account: {
      id: account.id,
      username: account.username,
      name: account.name,
    },
  });
}

async function handleAuthCheck(request, env) {
  const account = await authenticate(request, env);
  if (!account) return json({ authenticated: false }, 401);
  return json({ authenticated: true, account });
}

async function handleLogout(request, env) {
  const token = getToken(request);
  if (!token) return json({ success: true });

  const tokenHash = await sha256(token);
  await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?")
    .bind(tokenHash)
    .run();

  return json({ success: true });
}

async function handleContext(request, env) {
  const account = await authenticate(request, env);
  if (!account) return json({ error: "Unauthorized" }, 401);

  const config = await env.DB.prepare(`
    SELECT model, personality, system_instructions
    FROM account_config
    WHERE account_id = ?
  `).bind(account.id).first();

  const memories = await env.DB.prepare(`
    SELECT id, content, category, confidence, created_at
    FROM memories
    WHERE account_id = ?
    ORDER BY id ASC
  `).bind(account.id).all();

  const conversations = await env.DB.prepare(`
    SELECT id, message, response, model, temperature, created_at
    FROM conversations
    WHERE account_id = ?
    ORDER BY id ASC
  `).bind(account.id).all();

  const modules = await env.DB.prepare(`
    SELECT module_name, module_data, created_at
    FROM account_modules
    WHERE account_id = ?
    ORDER BY id ASC
  `).bind(account.id).all();

  return json({
    account,
    config: config || {
      model: "gemma3:latest",
      personality: "",
      system_instructions: "",
    },
    memories: memories.results || [],
    conversations: conversations.results || [],
    modules: modules.results || [],
  });
}

async function handleModules(request, env) {
  const account = await authenticate(request, env);
  if (!account) return json({ error: "Unauthorized" }, 401);

  if (request.method === "GET") {
    const rows = await env.DB.prepare(`
      SELECT module_name, module_data, created_at
      FROM account_modules
      WHERE account_id = ?
      ORDER BY id ASC
    `).bind(account.id).all();

    return json({ modules: rows.results || [] });
  }

  const body = await bodyJson(request);
  if (!body || !body.module_name) {
    return json({ error: "module_name is required" }, 400);
  }

  const moduleName = String(body.module_name);
  const moduleData = JSON.stringify(body.module_data ?? {});

  await env.DB.prepare(`
    INSERT INTO account_modules (account_id, module_name, module_data)
    VALUES (?, ?, ?)
    ON CONFLICT(account_id, module_name)
    DO UPDATE SET module_data = excluded.module_data
  `).bind(account.id, moduleName, moduleData).run();

  return json({ success: true });
}

async function handleChat(request, env) {
  const account = await authenticate(request, env);
  if (!account) return json({ error: "Unauthorized" }, 401);

  const body = await bodyJson(request);
  if (!body || body.message == null) {
    return json({ error: "message is required" }, 400);
  }

  const config = await env.DB.prepare(`
    SELECT model, personality, system_instructions
    FROM account_config
    WHERE account_id = ?
  `).bind(account.id).first();

  const model = body.model || config?.model || "gemma3:latest";
  const temperature = Number(body.temperature ?? 0.5);

  const inferenceUrl = env.INFERENCE_URL;
  if (!inferenceUrl) {
    return json({ error: "INFERENCE_URL is not configured" }, 500);
  }

  const inferenceResponse = await fetch(new URL("/generate", inferenceUrl), {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({
      prompt: String(body.message),
      model,
      temperature,
      stream: false,
      personality: config?.personality || "",
      system_instructions: config?.system_instructions || "",
    }),
  });

  if (!inferenceResponse.ok) {
    const text = await inferenceResponse.text();
    return json({ error: "Inference service failed", detail: text }, 502);
  }

  const result = await inferenceResponse.json();
  const responseText =
    result.response ?? result.text ?? result.output ?? "";

  await env.DB.prepare(`
    INSERT INTO conversations (account_id, message, response, model, temperature)
    VALUES (?, ?, ?, ?, ?)
  `).bind(
    account.id,
    String(body.message),
    String(responseText),
    model,
    temperature
  ).run();

  return json({
    success: true,
    response: responseText,
    model,
    temperature,
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: jsonHeaders });
    }

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    try {
      switch (path) {
        case "/register":
          return request.method === "POST"
            ? await handleRegister(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/login":
          return request.method === "POST"
            ? await handleLogin(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/auth/check":
          return request.method === "POST" || request.method === "GET"
            ? await handleAuthCheck(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/logout":
          return request.method === "POST"
            ? await handleLogout(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/context":
          return request.method === "GET" || request.method === "POST"
            ? await handleContext(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/chat":
          return request.method === "POST"
            ? await handleChat(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/modules":
          return request.method === "GET" || request.method === "POST"
            ? await handleModules(request, env)
            : json({ error: "Method not allowed" }, 405);

        case "/":
          return json({
            service: "modulogical-backend",
            status: "ok",
            database: "D1",
          });

        default:
          return json({ error: "Not found" }, 404);
      }
    } catch (error) {
      console.error(error);
      return json({
        error: "Internal server error",
        detail: String(error?.message || error),
      }, 500);
    }
  },
};
