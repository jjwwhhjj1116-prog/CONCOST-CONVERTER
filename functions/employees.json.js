// 예전 배포의 /employees.json 엣지 캐시를 덮어쓰기 위한 차단 라우트 (명단은 D1 /api/auth/employees 로만 제공)
export function onRequest() {
  return new Response("Not Found", {
    status: 404,
    headers: { "Cache-Control": "no-store", "Content-Type": "text/plain" },
  });
}
