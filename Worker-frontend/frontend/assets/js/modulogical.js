/* ==========================================================================
   MODULOGICAL — SHARED APPLICATION LAYER
   Backend contracts (endpoints, storage keys, model IDs) live here ONCE so
   every page calls them the same way. Nothing in this file changes what the
   backend receives — it only centralizes the existing behavior.
   ========================================================================== */

const Modulogical = (() => {

  // NOTE ON API HOST: the original pages pointed at two different ngrok
  // hosts (index.html used a different tunnel than landing.html / chat.html).
  // That was almost certainly drift between pages rather than intentional —
  // a frontend can only point at one backend. This build standardizes on the
  // host used by landing + chat (the auth entry point and the chat surface),
  // since those are the two pages a real session actually depends on.
  // If your backend actually lives at the other tunnel, change API below —
  // every page reads from this single constant.
  const API = window.location.protocol === "file:"
    ? "http://localhost:81"
    : "https://unlaced-spruce-husked.ngrok-free.dev";

  const TOKEN_KEY = "atlas_token";
  const MODEL_KEY = "model";
  const MODULE_KEY = "Module";
  const NAME_KEY = "atlas_name";
  const USERNAME_KEY = "atlas_username";

  // Model registry — IDs are exactly what the backend already expects.
  // "auto" has no backend ID: it is sent as the literal string "auto" so the
  // backend can implement real automatic routing. Until it does, treat any
  // non-auto response model as the definitive "actually used" model.
  const MODELS = [
    { key: "auto",      id: "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E", label: "Auto",      blurb: "Best model for this request",  description: "Automatically selecting the best model" },
    { key: "efficient", id: "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E", label: "Efficient", blurb: "Fast everyday responses",       description: "Fast everyday responses" },
    { key: "llama",     id: "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY", label: "Llama",     blurb: "General reasoning",              description: "General reasoning" },
    { key: "phi",       id: "U611jj6ZcghehmIrLKCoFmShaUwt--4LWBoee5d7bHc", label: "Phi",       blurb: "Lightweight reasoning",           description: "Lightweight reasoning" },
    { key: "qwen",      id: "OD4TbKRobbGDtYWVPciloUYR6PPT1f4gKwTqx4jX6eE", label: "Qwen",      blurb: "Reasoning / technical tasks",     description: "Reasoning / technical tasks" },
    { key: "mistral",   id: "B2_9IU7LiIh0hkeiLMqXxAcKn5NcwWYTqMZe4Q9-bZM", label: "Mistral",   blurb: "General-purpose tasks",           description: "General-purpose tasks" },
  ];

  function modelByKey(key){ return MODELS.find(m => m.key === key); }
  function modelById(id){ return MODELS.find(m => m.id === id); }

  function getToken(){ return localStorage.getItem(TOKEN_KEY); }
  function setToken(t){ localStorage.setItem(TOKEN_KEY, t); }
  function clearSession(){
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(MODEL_KEY);
    localStorage.removeItem(MODULE_KEY);
    localStorage.removeItem(NAME_KEY);
    localStorage.removeItem(USERNAME_KEY);
  }

  function getModelKey(){ return localStorage.getItem(MODEL_KEY) || "auto"; }
  function setModelKey(key){ localStorage.setItem(MODEL_KEY, key); }

  function headers(json = true){
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  // Redirect helper — landing.html is the entry point for unauthenticated users.
  function goToEntry(){ window.location.href = "/"; }

  async function requireAuth(){
    const token = getToken();
    if (!token) { goToEntry(); return null; }
    try {
      const res = await fetch(API + "/auth/check?token=" + encodeURIComponent(token), {
        headers: headers(false)
      });
      const result = await res.json();
      if (!result.valid) { clearSession(); goToEntry(); return null; }
      return token;
    } catch (e) {
      // Network hiccup shouldn't force a logout — let the page continue,
      // individual requests will surface their own errors.
      console.error("Auth check failed:", e);
      return token;
    }
  }

  async function logout(){
    const token = getToken();
    try {
      await fetch(API + "/logout", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ token })
      });
    } catch (e) {
      console.error("Logout request failed:", e);
    } finally {
      clearSession();
      goToEntry();
    }
  }

  // ---- Toast ---------------------------------------------------------
  let toastTimer = null;
  function toast(message, kind = "default"){
    let el = document.getElementById("mod-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "mod-toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.className = "toast show" + (kind === "error" ? " is-error" : kind === "success" ? " is-success" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = "toast"; }, 3200);
  }

  // ---- Nav wiring ------------------------------------------------------
  function initNav(activePage){
    document.querySelectorAll("[data-nav]").forEach(link => {
      if (link.getAttribute("data-nav") === activePage) link.classList.add("active");
    });
    const toggle = document.querySelector("[data-nav-toggle]");
    const drawer = document.querySelector("[data-nav-drawer]");
    if (toggle && drawer) {
      toggle.addEventListener("click", () => {
        const open = drawer.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
      drawer.querySelectorAll("a, button").forEach(el => {
        el.addEventListener("click", () => drawer.classList.remove("open"));
      });
    }
    document.querySelectorAll("[data-logout]").forEach(btn => {
      btn.addEventListener("click", (e) => { e.preventDefault(); logout(); });
    });
  }

  function initials(name){
    if (!name) return "?";
    const parts = String(name).trim().split(/\s+/);
    return (parts[0]?.[0] || "").toUpperCase() + (parts[1]?.[0] || "").toUpperCase() || parts[0]?.[0]?.toUpperCase() || "?";
  }

  return {
    API, TOKEN_KEY, MODEL_KEY, MODULE_KEY, NAME_KEY, USERNAME_KEY,
    MODELS, modelByKey, modelById,
    getToken, setToken, clearSession,
    getModelKey, setModelKey,
    headers, requireAuth, logout, goToEntry,
    toast, initNav, initials,
  };
})();
