/** Worker가 받는 환경: wrangler.toml의 [vars]와 비밀 값(.dev.vars / wrangler secret). */
export interface Env {
  GOOGLE_CLIENT_ID: string;
  GOOGLE_CLIENT_SECRET: string;
}

/**
 * 설정이 들어왔는지만 알려 주는 확인용 응답이다(값은 돌려주지 않는다). 로그인(`POST /auth/google`)을 만들면
 * 이 응답은 지운다.
 */
export default {
  async fetch(_request: Request, env: Env): Promise<Response> {
    return Response.json({
      ok: true,
      configured: {
        googleClientId: Boolean(env.GOOGLE_CLIENT_ID),
        googleClientSecret: Boolean(env.GOOGLE_CLIENT_SECRET),
      },
    });
  },
} satisfies ExportedHandler<Env>;
