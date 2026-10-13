// /api/auth/login — D1 임직원 인증 후 서명 토큰 발급
import { json, issueToken, sha256Hex } from "../../_shared.js";

export async function onRequestPost({ request, env }) {
  try {
    const { login_id, password } = await request.json();
    if (!login_id || !password) return json({ detail: "아이디와 비밀번호를 입력해주세요." }, 400);

    const user = await env.DB.prepare(
      "SELECT login_id, name, department, rank, password_hash FROM users WHERE LOWER(login_id) = LOWER(?)"
    ).bind(login_id).first();

    if (!user || user.password_hash !== (await sha256Hex(password))) {
      return json({ detail: "아이디 또는 비밀번호가 올바르지 않습니다." }, 401);
    }

    return json({
      success: true,
      token: await issueToken(env, user.login_id),
      user: { login_id: user.login_id, name: user.name, department: user.department, rank: user.rank },
    });
  } catch (err) {
    return json({ detail: `로그인 처리 오류: ${err.message}` }, 500);
  }
}
