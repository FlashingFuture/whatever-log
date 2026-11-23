import type { Db } from "../db.ts";
import { verifyUnsubscribe } from "./links.ts";
import { findSubscriptionById, unsubscribeById } from "./subscriptions.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

/** 작은 HTML 페이지. 스크립트·외부 자원 없이, 폼은 이 주소로만 보낼 수 있게 막는다. */
function page(status: number, title: string, body: string): Response {
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>${escapeHtml(title)}</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;color:#222}button{font:inherit;padding:.5rem 1rem;cursor:pointer}</style>
</head><body><h1>${escapeHtml(title)}</h1>${body}</body></html>`;
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy":
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

const invalid = () =>
  page(
    400,
    "링크가 올바르지 않아요",
    "<p>메일에 있던 링크를 그대로 열어 주세요. 앱의 목표 화면에서도 보고서 메일을 끌 수 있어요.</p>",
  );

/**
 * 메일의 수신 거부 링크(`/mail/unsubscribe?s=<구독 id>&t=<서명>`). 로그인 없이 동작한다 — 서명이 이 구독의 것인지로만 판단한다.
 * - GET: 확인 페이지만 보인다(바꾸지 않는다). 메일 보안 검사기가 링크를 미리 열어 보는 일이 흔해서, 여는 것만으로 끊지 않는다.
 * - POST: 구독을 끝낸다(`unsubscribed`). 메일 앱의 원클릭 수신 거부(RFC 8058, 본문 `List-Unsubscribe=One-Click`)도 이 요청이다.
 *   여러 번 보내도 같다. 이미 지워진 구독이어도 "거부됨"으로 답한다(더 보낼 것이 없다).
 */
export async function handleUnsubscribe(
  request: Request,
  url: URL,
  deps: { db: Db; secret: string | undefined; now: () => Date },
): Promise<Response> {
  if (request.method !== "GET" && request.method !== "POST") {
    return new Response(null, { status: 405, headers: { Allow: "GET, POST" } });
  }
  const id = url.searchParams.get("s") ?? "";
  const signature = url.searchParams.get("t") ?? "";
  if (!deps.secret) {
    console.warn("mail config: MAIL_LINK_SECRET이 설정되지 않았습니다.");
    return page(
      503,
      "잠시 뒤 다시 시도해 주세요",
      "<p>지금은 처리할 수 없어요. 앱의 목표 화면에서 보고서 메일을 끌 수 있어요.</p>",
    );
  }
  if (
    !UUID.test(id) ||
    !(await verifyUnsubscribe(deps.secret, id, signature))
  ) {
    return invalid();
  }

  if (request.method === "GET") {
    const row = await findSubscriptionById(deps.db, id);
    if (!row || row.status === "ended") {
      return page(
        200,
        "보고서 메일을 더 보내지 않아요",
        "<p>이미 받지 않도록 되어 있어요.</p>",
      );
    }
    const action = `/mail/unsubscribe?${new URLSearchParams({ s: id, t: signature })}`;
    return page(
      200,
      "보고서 메일을 그만 받을까요?",
      `<p>이 목표의 보고서 메일을 더 보내지 않아요. 다시 받으려면 앱에서 새로 신청하면 돼요.</p>
<form method="post" action="${escapeHtml(action)}"><button type="submit">그만 받기</button></form>`,
    );
  }

  await unsubscribeById(deps.db, id, deps.now());
  return page(
    200,
    "보고서 메일을 더 보내지 않아요",
    "<p>수신을 거부했어요. 다시 받으려면 앱의 목표 화면에서 새로 신청해 주세요.</p>",
  );
}
