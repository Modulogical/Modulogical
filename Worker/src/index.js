export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      // API handling later
    }

    return env.ASSETS.fetch(request);
  }
};