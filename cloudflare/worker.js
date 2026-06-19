export default {
  async scheduled(controller, env, ctx) {
    const slot = new Date(controller.scheduledTime).getUTCMinutes();
    ctx.waitUntil(dispatchWorkflow(env, `cron:${controller.cron}`, slot));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, scheduler: "*/15 * * * *" });
    }
    return new Response("USDJPY scheduler is active", { status: 200 });
  },
};

async function dispatchWorkflow(env, source, slot) {
  const endpoint = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "usd-jpy-cloudflare-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { source, slot: String(slot), mode: "auto" } }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub dispatch failed: ${response.status} ${body}`);
  }
}
