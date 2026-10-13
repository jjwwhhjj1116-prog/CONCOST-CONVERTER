// 공용 헬퍼 (파일명이 _ 로 시작하므로 라우트로 노출되지 않음)

export const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

export function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function b64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  return b64url(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg)));
}

// 로그인 토큰 발급: "<login_id>.<만료epoch>.<서명>" (12시간)
export async function issueToken(env, loginId) {
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600;
  const payload = `${loginId}.${exp}`;
  return `${payload}.${await hmac(env.ENGINE_KEY, payload)}`;
}

// 토큰 검증 → 유효하면 login_id, 아니면 null
export async function verifyToken(env, token) {
  if (!token || !env.ENGINE_KEY) return null;
  const idx = token.lastIndexOf(".");
  if (idx < 0) return null;
  const payload = token.slice(0, idx);
  const sig = token.slice(idx + 1);
  if ((await hmac(env.ENGINE_KEY, payload)) !== sig) return null;
  const dot = payload.lastIndexOf(".");
  const exp = parseInt(payload.slice(dot + 1), 10);
  if (!exp || exp < Date.now() / 1000) return null;
  return payload.slice(0, dot);
}

export async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
