// /api/engine/register — 사내 PC가 기동할 때 자신의 터널 URL을 등록 (ENGINE_KEY 필요)
import { json } from "../../_shared.js";

export async function onRequestPost({ request, env }) {
  if (request.headers.get("X-Engine-Key") !== env.ENGINE_KEY) {
    return json({ detail: "forbidden" }, 403);
  }
  const { url } = await request.json();
  if (!url || !/^https:\/\/[a-z0-9.-]+$/i.test(url)) {
    return json({ detail: "올바른 https 터널 URL이 아닙니다." }, 400);
  }
  await env.DB.prepare(
    "INSERT INTO engine_registry (key, value, updated_at) VALUES ('url', ?, CURRENT_TIMESTAMP) " +
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP"
  ).bind(url).run();
  return json({ success: true, url });
}
