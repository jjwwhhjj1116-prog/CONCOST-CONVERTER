// Cloudflare Pages Functions - /api/auth/employees
export async function onRequestGet(context) {
  const { env } = context;

  try {
    if (env.DB) {
      const { results } = await env.DB.prepare(
        "SELECT login_id, name, department, rank FROM users ORDER BY department, name"
      ).all();

      return new Response(JSON.stringify({ employees: results, total: results.length, source: "Cloudflare D1" }), {
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }
  } catch (err) {
    console.error("D1 Query Error:", err);
  }

  // 폴백: 정적 데이터 반환
  return new Response(JSON.stringify({ error: "D1 DB 연결 대기", employees: [] }), {
    status: 200,
    headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" },
  });
}
