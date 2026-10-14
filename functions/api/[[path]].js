// /api/* 요청을 클라우드 변환 엔진(Render Docker)으로 프록시 (사내 PC 실행 불필요)
import { json, verifyToken } from "../_shared.js";

const DEFAULT_CLOUD_ENGINE = "https://concost-converter-engine.onrender.com";

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // 헬스체크(/api/health)는 로그인 없이도 컨테이너 워밍업(Pre-warm) 허용
  let user = "anonymous";
  if (url.pathname !== "/api/health") {
    const auth = request.headers.get("Authorization") || "";
    const token = auth.startsWith("Bearer ") ? auth.slice(7) : url.searchParams.get("t");
    user = await verifyToken(env, token);
    if (!user) return json({ detail: "로그인이 필요합니다. 다시 로그인해주세요." }, 401);
  }

  // D1 레지스트리 조회 후, 없거나 죽은 터널이면 항상 클라우드 엔진(DEFAULT_CLOUD_ENGINE) 사용
  const row = await env.DB.prepare("SELECT value FROM engine_registry WHERE key = 'url'").first().catch(() => null);
  const candidates = [];
  if (row && row.value && !row.value.includes("trycloudflare.com")) {
    candidates.push(row.value.replace(/\/+$/, ""));
  }
  if (!candidates.includes(DEFAULT_CLOUD_ENGINE)) {
    candidates.push(DEFAULT_CLOUD_ENGINE);
  }

  url.searchParams.delete("t");
  const headers = new Headers(request.headers);
  headers.delete("Authorization");
  headers.delete("host");
  headers.set("X-Engine-Key", env.ENGINE_KEY);
  headers.set("X-Concost-User", user);

  const reqBody = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();

  let lastError = null;
  for (const base of candidates) {
    const target = `${base}${url.pathname}${url.search}`;
    try {
      const resp = await fetch(target, {
        method: request.method,
        headers,
        body: reqBody,
      });
      if (resp.status !== 530 && resp.status !== 502) {
        return new Response(resp.body, { status: resp.status, headers: resp.headers });
      }
      lastError = `HTTP ${resp.status} from ${base}`;
    } catch (err) {
      lastError = String(err);
    }
  }

  return json({
    detail: "클라우드 변환 엔진이 절전 모드에서 깨어나는 중입니다(약 20초 소요). 잠시 후 다시 시도해주세요.",
    error: lastError,
  }, 503);
}
