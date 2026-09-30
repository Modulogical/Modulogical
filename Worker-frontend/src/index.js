export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      const backendURL = new URL(request.url);
      backendURL.pathname = backendURL.pathname.replace(/^\/api/, "") || "/";

      const backendRequest = new Request(backendURL.toString(), request);
      return env.BACKEND.fetch(backendRequest);
    }

    // Engine Forge routes
    const forgePages = {
      "/engine-forge/personality": "/personality-forge.html",
      "/engine-forge/module": "/module-forge.html",
      "/engine-forge/workflow": "/workflow-forge.html",
      "/engine-forge/database": "/database-forge.html",
      "/engine-forge/theme": "/theme-forge.html",
      "/engine-forge/agent": "/agent-forge.html"
    };

    const forgePage = forgePages[url.pathname];

    if (forgePage) {
      return env.ASSETS.fetch(
        new Request(new URL(forgePage, request.url))
      );
    }

    return env.ASSETS.fetch(request);
  },
};