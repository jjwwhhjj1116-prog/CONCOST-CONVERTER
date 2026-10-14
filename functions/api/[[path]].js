// /api/* 요청을 클라우드 변환 엔진(Render Docker)으로 깨끗한 헤더로 프록시 및 자동 재시도
import { json, verifyToken } from "../_shared.js";

const DEFAULT_CLOUD_ENGINE = "https://concost-converter-engine.onrender.com";

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Engine-Key",
      },
    });
  }

  let user = "anonymous";
  if (url.pathname !== "/api/health") {
    const auth = request.headers.get("Authorization") || "";
    const token = auth.startsWith("Bearer ") ? auth.slice(7) : url.searchParams.get("t");
    user = await verifyToken(env, token);
    if (!user) return json({ detail: "로그인이 필요합니다. 다시 로그인해주세요." }, 401);
  }

  const row = await env.DB.prepare("SELECT value FROM engine_registry WHERE key = 'url'").first().catch(() => null);
  const candidates = [];
  if (row && row.value && !row.value.includes("trycloudflare.com")) {
    candidates.push(row.value.replace(/\/+$/, ""));
  }
  if (!candidates.includes(DEFAULT_CLOUD_ENGINE)) {
    candidates.push(DEFAULT_CLOUD_ENGINE);
  }

  url.searchParams.delete("t");

  // Cloudflare-to-Cloudflare (pages.dev -> onrender.com) 서브요청 시 cf-*, cdn-loop, origin 헤더 충돌을 방지하기 위해 필수 헤더만 전달
  const cleanHeaders = new Headers();
  const contentType = request.headers.get("Content-Type");
  if (contentType) cleanHeaders.set("Content-Type", contentType);
  cleanHeaders.set("Accept", request.headers.get("Accept") || "application/json, */*");
  cleanHeaders.set("User-Agent", "CONCOST-Pages-Proxy/1.10.2");
  if (env.ENGINE_KEY) cleanHeaders.set("X-Engine-Key", env.ENGINE_KEY);
  cleanHeaders.set("X-Concost-User", user);

  const reqBody = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();

  let lastError = null;
  for (const base of candidates) {
    const target = `${base}${url.pathname}${url.search}`;
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const resp = await fetch(target, {
          method: request.method,
          headers: cleanHeaders,
          body: reqBody,
        });
        if (resp.status !== 530 && resp.status !== 502 && resp.status !== 503 && resp.status !== 504) {
          const respHeaders = new Headers(resp.headers);
          respHeaders.set("Cache-Control", "no-store");
          return new Response(resp.body, { status: resp.status, headers: respHeaders });
        }
        lastError = `HTTP ${resp.status} from ${base} (attempt ${attempt})`;
      } catch (err) {
        lastError = String(err);
      }
      if (attempt < 2) {
        await new Promise((r) => setTimeout(r, 2500));
      }
    }
  }

  return json({
    detail: "클라우드 변환 엔진이 절전 모드에서 깨어나는 중입니다. 자동으로 재연결합니다.",
    retryable: true,
    cloud_engine: DEFAULT_CLOUD_ENGINE,
    error: lastError,
  }, 503);
}
