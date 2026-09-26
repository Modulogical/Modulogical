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
  const API = "/api";
  const TOKEN_KEY = "atlas_token";
  const MODEL_KEY = "model";
  const MODULE_KEY = "Module";
  const NAME_KEY = "atlas_name";
  const USERNAME_KEY = "atlas_username";
  const THEME_KEY = "modulogical_theme";
  const DEFAULT_THEME = "holographic";

  // Theme definitions live in the shared CSS. The frontend accepts a theme key
  // when it is a safe CSS identifier; settings.html discovers the actual theme
  // selectors from that stylesheet and renders them automatically.
  const THEMES = [
    { key: "holographic", label: "Holographic dark" },
  ];

  function themeByKey(key){
    if (THEMES.some(theme => theme.key === key)) return { key };
    return typeof key === "string" && /^[a-z0-9_-]+$/i.test(key) ? { key } : null;
  }

  function getTheme(){
    const stored = localStorage.getItem(THEME_KEY);
    return themeByKey(stored) ? stored : DEFAULT_THEME;
  }

  function applyTheme(theme){
    const selected = themeByKey(theme) ? theme : DEFAULT_THEME;
    document.documentElement.dataset.theme = selected === DEFAULT_THEME ? "" : selected;
    localStorage.setItem(THEME_KEY, selected);
    return selected;
  }

  async function loadTheme(){
    // Apply the last known value immediately to avoid a flash on navigation.
    applyTheme(getTheme());

    const token = getToken();
    if (!token) return getTheme();

    try {
      const response = await fetch(API + "/settings/theme?token=" + encodeURIComponent(token), {
        headers: headers(false)
      });
      if (!response.ok) return getTheme();

      const data = await response.json();
      if (data.theme) return applyTheme(data.theme);
    } catch (error) {
      console.error("Theme load failed:", error);
    }
    return getTheme();
  }

  // Model registry — IDs are exactly what the backend already expects.
  // "auto" has no backend ID: it is sent as the literal string "auto" so the
  // backend can implement real automatic routing. Until it does, treat any
  // non-auto response model as the definitive "actually used" model.
  const MODELS = [
    { key: "auto",      id: "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E", label: "Auto",      blurb: "Best model for this request",  description: "Automatically selecting the best model" },
    { key: "efficient", id: "YCaXXcxd9qg_TbaC0WXHpbMsBMgwZOaIX9pIjeP-W-E", label: "Efficient", blurb: "Fast everyday responses",       description: "Fast everyday responses" },
    { key: "lightweight",     id: "nFOin8rHgAul9HWygNv4semqq9MNx71NEBpMMNrVYXY", label: "Lightweight",     blurb: "General reasoning",              description: "General reasoning" },
    { key: "advanced", id: "Af3hf8E0SbC0_o44yQnhvFtpMtjOq73wU_iKquZL2AA", label: "Advanced", blurb: "Powerful responses", description: "Advanced reasoning"},
    { key: "powerful", id: "Ik0LpuQXHGpAsl6EtTJDzq09SyTAxBh9rdZvQ4UZkpU", label: "Powerful", blurb: "Most capable model", description: "Most capable model"}
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
    localStorage.removeItem(THEME_KEY);
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
    const scrim = document.querySelector("[data-scrim]");

    const displayName = localStorage.getItem(NAME_KEY) || localStorage.getItem(USERNAME_KEY) || "Account";
    document.querySelectorAll(".mobile-nav-account .account-name").forEach(el => { el.textContent = displayName; });
    document.querySelectorAll(".mobile-nav-account .account-avatar").forEach(el => { el.textContent = initials(displayName); });

    if (toggle && drawer) {
      const closeDrawer = () => {
        drawer.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        scrim?.classList.remove("show");
      };
      const openDrawer = () => {
        drawer.classList.add("open");
        toggle.setAttribute("aria-expanded", "true");
        scrim?.classList.add("show");
      };

      toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        drawer.classList.contains("open") ? closeDrawer() : openDrawer();
      });

      drawer.querySelectorAll("a, button").forEach(el => {
        el.addEventListener("click", () => closeDrawer());
      });

      scrim?.addEventListener("click", closeDrawer);

      document.addEventListener("click", (event) => {
        if (!drawer.classList.contains("open")) return;
        if (!drawer.contains(event.target) && !toggle.contains(event.target)) closeDrawer();
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeDrawer();
      });

      window.addEventListener("resize", () => {
        if (window.innerWidth > 760) closeDrawer();
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

  // Every authenticated page includes this shared file, so themes persist
  // across navigation without requiring each page to implement theme loading.
  applyTheme(getTheme());
  if (getToken()) loadTheme();

  return {
    API, TOKEN_KEY, MODEL_KEY, MODULE_KEY, NAME_KEY, USERNAME_KEY, THEME_KEY, DEFAULT_THEME, THEMES,
    MODELS, modelByKey, modelById,
    getToken, setToken, clearSession,
    getModelKey, setModelKey, themeByKey, getTheme, applyTheme, loadTheme,
    headers, requireAuth, logout, goToEntry,
    toast, initNav, initials,
  };
})();
