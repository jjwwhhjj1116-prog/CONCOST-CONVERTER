// Cloudflare Pages Functions - /api/auth/change-password
export async function onRequestPost(context) {
  const { request, env } = context;

  try {
    const { login_id, old_password, new_password } = await request.json();

    const hashOld = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(old_password))))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const hashNew = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(new_password))))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

    if (env.DB) {
      const user = await env.DB.prepare("SELECT password_hash FROM users WHERE LOWER(login_id) = LOWER(?)")
        .bind(login_id)
        .first();

      if (!user || user.password_hash !== hashOld) {
        return new Response(JSON.stringify({ detail: "현재 비밀번호가 일치하지 않습니다." }), {
          status: 400,
          headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" },
        });
      }

      await env.DB.prepare("UPDATE users SET password_hash = ? WHERE LOWER(login_id) = LOWER(?)")
        .bind(hashNew, login_id)
        .run();

      return new Response(JSON.stringify({ success: true, message: "비밀번호가 성공적으로 변경되었습니다." }), {
        headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" },
      });
    }

    return new Response(JSON.stringify({ detail: "D1 데이터베이스가 없습니다." }), { status: 500 });
  } catch (err) {
    return new Response(JSON.stringify({ detail: err.message }), { status: 500 });
  }
}
