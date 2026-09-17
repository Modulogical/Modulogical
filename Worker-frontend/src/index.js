export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      const backendURL = new URL(request.url);
      backendURL.pathname = backendURL.pathname.replace(/^\/api/, "") || "/";

      const backendRequest = new Request(backendURL.toString(), request);
      return env.BACKEND.fetch(backendRequest);
    }

    return env.ASSETS.fetch(request);
  },
};
