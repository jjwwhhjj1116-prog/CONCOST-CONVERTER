// Cloudflare Pages Functions - /api/* 프록시 라우터
export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // 환경 변수에 설정된 실제 백엔드 주소 (Cloudflare Tunnel 또는 사내 서버 주소)
  // 환경변수가 없을 경우의 기본 폴백 주소
  const backendBase = env.BACKEND_URL || "http://127.0.0.1:8000";

  const targetUrl = `${backendBase.replace(/\/+$/, "")}${url.pathname}${url.search}`;

  try {
    const backendRequest = new Request(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "follow",
    });

    const response = await fetch(backendRequest);
    const newHeaders = new Headers(response.headers);
    newHeaders.set("Access-Control-Allow-Origin", "*");
    newHeaders.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    newHeaders.set("Access-Control-Allow-Headers", "*");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });
  } catch (err) {
    return new Response(
      JSON.stringify({
        error: "백엔드 변환 엔진 서버에 연결할 수 없습니다.",
        detail: "사내 PC 또는 서버에서 start_server.bat 및 start_cloudflare_tunnel.bat을 가동해주세요.",
        target_attempted: targetUrl,
        message: err.message,
      }),
      {
        status: 502,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  }
}
