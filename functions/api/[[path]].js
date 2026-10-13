// /api/* 중 auth/engine 외 나머지(convert, download, cad/zwcad-status, health)를
// Cloudflare Tunnel 뒤의 사내 PC 변환 엔진(FastAPI)으로 프록시
import { json, verifyToken } from "../_shared.js";

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // 직원 로그인 토큰 검사 (헤더 또는 다운로드 링크용 ?t= 쿼리)
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : url.searchParams.get("t");
  const user = await verifyToken(env, token);
  if (!user) return json({ detail: "로그인이 필요합니다. 다시 로그인해주세요." }, 401);

  // 사내 PC가 기동 시 등록한 터널 주소 조회
  const row = await env.DB.prepare("SELECT value, updated_at FROM engine_registry WHERE key = 'url'").first();
  if (!row) return json({ detail: "변환 엔진(사내 PC)이 등록되지 않았습니다. start_engine.bat 실행 여부를 확인하세요." }, 503);

  url.searchParams.delete("t");
  const target = `${row.value.replace(/\/+$/, "")}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  headers.delete("Authorization");
  headers.delete("host");
  headers.set("X-Engine-Key", env.ENGINE_KEY);
  headers.set("X-Concost-User", user);

  try {
    const resp = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    });
    return new Response(resp.body, { status: resp.status, headers: resp.headers });
  } catch (err) {
    return json({
      detail: "사내 변환 엔진에 연결할 수 없습니다. 엔진 PC가 켜져 있고 start_engine.bat이 실행 중인지 확인하세요.",
      engine_registered_at: row.updated_at,
      error: String(err),
    }, 502);
  }
}
