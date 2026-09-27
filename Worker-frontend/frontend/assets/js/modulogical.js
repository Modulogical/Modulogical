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
    sessionStorage.removeItem(AUTH_CHECKED_AT_KEY);
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

  // ---- Session authentication -----------------------------------------
  // The token itself remains the API credential. Page navigation does not
  // block on /auth/check; validation happens in the background. This keeps
  // an already-signed-in session responsive while API endpoints remain the
  // authoritative security boundary.
  const AUTH_CHECKED_AT_KEY = "modulogical_auth_checked_at";
  const AUTH_CHECK_TTL = 5 * 60 * 1000;
  let authValidationPromise = null;

  function markAuthChecked(){
    sessionStorage.setItem(AUTH_CHECKED_AT_KEY, String(Date.now()));
  }

  function authCheckIsFresh(){
    const checkedAt = Number(sessionStorage.getItem(AUTH_CHECKED_AT_KEY) || 0);
    return checkedAt > 0 && (Date.now() - checkedAt) < AUTH_CHECK_TTL;
  }

  async function validateAuthToken(token){
    if (!token) return false;

    try {
      const res = await fetch(API + "/auth/check?token=" + encodeURIComponent(token), {
        headers: headers(false),
        cache: "no-store"
      });
      const result = await res.json();

      if (!result.valid) {
        clearSession();
        sessionStorage.removeItem(AUTH_CHECKED_AT_KEY);
        goToEntry();
        return false;
      }

      markAuthChecked();
      return true;
    } catch (e) {
      // A network failure is not proof that the session is invalid.
      console.error("Auth check failed:", e);
      return true;
    } finally {
      authValidationPromise = null;
    }
  }

  function validateAuthInBackground(token){
    if (!token || authValidationPromise) return;
    authValidationPromise = validateAuthToken(token);
  }

  async function requireAuth(options = {}){
    const token = getToken();
    if (!token) {
      goToEntry();
      return null;
    }

    // A recently validated session needs no network round-trip.
    if (authCheckIsFresh()) return token;

    // Normal page startup/navigation is optimistic: render immediately and
    // validate in the background. Callers that truly need a blocking check
    // can pass { block: true }.
    if (!options.block) {
      validateAuthInBackground(token);
      return token;
    }

    const valid = await validateAuthToken(token);
    return valid ? token : null;
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

  // ---- Shared navigation ---------------------------------------------
  const SHARED_NAV = [
    { key: "dashboard", label: "Dashboard", href: "/dashboard.html", icon: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>' },
    { key: "chat", label: "Chat", href: "/chat", icon: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>' },
    { key: "marketplace", label: "Marketplace", href: "/marketplace", icon: '<path d="M3 9h18l-1.5 11h-15z"/><path d="M5 9l2-5h10l2 5M9 13h6"/>' },
    { key: "engine-forge", label: "Engine Forge", href: "/engine-forge", icon: '<path d="M14.7 6.3a4.5 4.5 0 0 0-5.9 5.9L4 17v3h3l4.8-4.8a4.5 4.5 0 0 0 5.9-5.9l-2.4 2.4-2.1-2.1z"/>' },
    { key: "settings", label: "Settings", href: "/settings", icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9c.2.4.6.8 1.5 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.4 1z"/>' }
  ];

  function renderSharedDesktopSidebar(sidebar, activePage, displayName){
    if (!sidebar) return;

    const items = SHARED_NAV.map(item => `
      <a class="sidebar-link sidebar-button${item.key === activePage ? " active" : ""}" data-nav="${item.key}" href="${item.href}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${item.icon}</svg>
        <span>${item.label}</span>
      </a>`).join("");

    sidebar.innerHTML = `
      <div class="sidebar-brand">
        <span class="brand-mark" aria-hidden="true"></span>
        MODULOGICAL
      </div>
      <button class="new-chat-btn sidebar-button" id="new-chat-btn" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
        <span>New chat</span>
      </button>
      <nav class="sidebar-nav" aria-label="Main navigation">${items}</nav>
      <div class="sidebar-foot">
        <a class="sidebar-account" href="/settings">
          <span class="account-avatar" id="nav-avatar">${initials(displayName)}</span>
          <span class="account-name" id="nav-name">${displayName}</span>
        </a>
        <button class="sidebar-logout sidebar-button" data-logout type="button">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>
          <span>Log out</span>
        </button>
      </div>`;

    sidebar.querySelectorAll("[data-nav]").forEach(link => {
      if (link.getAttribute("data-nav") === activePage) link.classList.add("active");
    });
  }

  function renderSharedMobileNav(drawer, activePage, displayName){
    if (!drawer || !drawer.classList.contains("appnav-links")) return;

    const items = SHARED_NAV.map(item => `
      <a class="appnav-link shared-mobile-nav-link" data-nav="${item.key}" href="${item.href}">
        <svg class="shared-mobile-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${item.icon}</svg>
        <span>${item.label}</span>
      </a>`).join("");

    drawer.innerHTML = `
      <div class="shared-mobile-nav-brand">
        <span class="brand-mark" aria-hidden="true"></span>
        MODULOGICAL
      </div>
      <a class="shared-mobile-new-chat sidebar-button" href="/chat">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
        <span>New chat</span>
      </a>
      <div class="shared-mobile-nav-links">${items}</div>
      <div class="shared-mobile-nav-account">
        <a class="shared-mobile-nav-account-link" href="/settings">
          <span class="account-avatar" aria-hidden="true">${initials(displayName)}</span>
          <span class="account-name">${displayName}</span>
        </a>
        <button class="shared-mobile-nav-logout sidebar-button" data-logout>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>
          <span>Log out</span>
        </button>
      </div>`;

    drawer.querySelectorAll("[data-nav]").forEach(link => {
      if (link.getAttribute("data-nav") === activePage) link.classList.add("active");
    });
  }

  // ---- Client-side navigation / persistent app shell ------------------
  // The global stylesheet, theme, sidebar, and mobile navigation belong to
  // the application shell and are loaded once on the initial document.
  // Internal page navigation replaces only [data-page-root].
  let navigationBound = false;
  let navigationRequest = null;

  function routeKeyFromPath(pathname){
    const path = pathname.replace(/\/+$/, "") || "/";
    if (path === "/dashboard" || path === "/dashboard.html") return "dashboard";
    if (path === "/chat" || path === "/chat.html") return "chat";
    if (path === "/marketplace" || path === "/marketplace.html") return "marketplace";
    if (path === "/engine-forge" || path === "/engine-forge.html") return "engine-forge";
    if (path === "/settings" || path === "/settings.html") return "settings";
    return null;
  }

  function isInternalAppRoute(url){
    return url.origin === window.location.origin && !!routeKeyFromPath(url.pathname);
  }

  function closeMobileNavigation(){
    const drawer = document.querySelector("[data-nav-drawer]");
    const toggle = document.querySelector("[data-nav-toggle]");
    const scrim = document.querySelector("[data-scrim]");
    drawer?.classList.remove("open");
    toggle?.setAttribute("aria-expanded", "false");
    scrim?.classList.remove("show");
  }

  function setPageStyle(cssText){
    document.querySelectorAll("style[data-page-style]").forEach(style => style.remove());
    if (!cssText) return;
    const style = document.createElement("style");
    style.setAttribute("data-page-style", "");
    style.textContent = cssText;
    document.head.appendChild(style);
  }

  async function executePageScript(scriptText){
    if (!scriptText) return;
    // Page scripts are the scripts from our own authenticated frontend pages;
    // they are deliberately executed after the new page DOM is mounted.
    const run = new Function(scriptText);
    await run();
  }

  async function navigate(url, {replace = false, popstate = false} = {}){
    if (navigationRequest) return navigationRequest;

    const target = new URL(url, window.location.href);
    if (!isInternalAppRoute(target)) {
      window.location.href = target.href;
      return;
    }

    const root = document.querySelector("[data-page-root]");
    if (!root) {
      window.location.href = target.href;
      return;
    }

    navigationRequest = (async () => {
      const response = await fetch(target.href, {
        headers: { "X-Modulogical-Navigation": "client" },
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error(`Navigation failed: ${response.status}`);

      const html = await response.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const nextRoot = doc.querySelector("[data-page-root]");
      if (!nextRoot) throw new Error("Destination page has no app root.");

      const nextStyle = doc.querySelector("style[data-page-style]");
      const nextScript = doc.querySelector("script[data-page-script]");

      // Global <link rel="stylesheet" href="/assets/css/modulogical.css">
      // is intentionally NOT copied from the destination document.
      root.innerHTML = nextRoot.innerHTML;
      setPageStyle(nextStyle ? nextStyle.textContent : "");

      if (doc.title) document.title = doc.title;

      if (!popstate) {
        const state = { modulogical: true, path: target.pathname };
        if (replace) history.replaceState(state, "", target.href);
        else history.pushState(state, "", target.href);
      }

      closeMobileNavigation();

      const activePage = routeKeyFromPath(target.pathname);
      if (activePage) setActiveNav(activePage);
      await executePageScript(nextScript ? nextScript.textContent : "");
    })().catch(error => {
      console.error("Client-side navigation failed:", error);
      // Fall back to normal browser navigation rather than leaving the user
      // on a partially changed page.
      window.location.href = target.href;
    }).finally(() => {
      navigationRequest = null;
    });

    return navigationRequest;
  }

  function bindNavigation(){
    if (navigationBound) return;
    navigationBound = true;

    document.addEventListener("click", event => {
      const link = event.target.closest("a[href]");
      if (!link || event.defaultPrevented) return;
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (link.target && link.target !== "_self") return;
      if (link.hasAttribute("download")) return;

      const url = new URL(link.href, window.location.href);
      if (!isInternalAppRoute(url)) return;

      event.preventDefault();
      navigate(url.href);
    });

    window.addEventListener("popstate", () => {
      const active = routeKeyFromPath(window.location.pathname);
      if (active) navigate(window.location.href, {popstate: true});
    });
  }

  // ---- Nav wiring ------------------------------------------------------
  function initNav(activePage){
    const sidebar = document.querySelector("[data-shared-sidebar]");
    const drawer = document.querySelector("[data-nav-drawer]");
    const toggle = document.querySelector("[data-nav-toggle]");
    const scrim = document.querySelector("[data-scrim]");
    const displayName = localStorage.getItem(NAME_KEY) || localStorage.getItem(USERNAME_KEY) || "Account";

    // The shell survives client-side navigation. Render it only once.
    if (sidebar && !sidebar.dataset.rendered) {
      renderSharedDesktopSidebar(sidebar, activePage, displayName);
      sidebar.dataset.rendered = "true";
    }

    if (drawer && !drawer.dataset.rendered) {
      renderSharedMobileNav(drawer, activePage, displayName);
      drawer.dataset.rendered = "true";
    }

    setActiveNav(activePage);

    const navName = document.getElementById("nav-name");
    const navAvatar = document.getElementById("nav-avatar");
    if (navName) navName.textContent = displayName;
    if (navAvatar) navAvatar.textContent = initials(displayName);

    if (toggle && drawer && !toggle.dataset.bound) {
      toggle.dataset.bound = "true";

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

      toggle.addEventListener("click", event => {
        event.stopPropagation();
        drawer.classList.contains("open") ? closeDrawer() : openDrawer();
      });

      drawer.addEventListener("click", event => {
        const link = event.target.closest("a, button");
        if (link) closeDrawer();
      });

      scrim?.addEventListener("click", closeDrawer);

      document.addEventListener("click", event => {
        if (!drawer.classList.contains("open")) return;
        if (!drawer.contains(event.target) && !toggle.contains(event.target)) closeDrawer();
      });

      document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeDrawer();
      });

      window.addEventListener("resize", () => {
        if (window.innerWidth > 760) closeDrawer();
      });
    }

    document.querySelectorAll("[data-logout]").forEach(btn => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "true";
      btn.addEventListener("click", e => {
        e.preventDefault();
        logout();
      });
    });

    bindNavigation();
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
