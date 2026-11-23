/**
 * 메일에 넣는 수신 거부 링크. 로그인 없이 누를 수 있어야 하므로(메일 앱에서 바로) 구독 id에 서버의 비밀로 **서명**한다 — 서명이 없으면 남의 구독 id를
 * 짐작해 끊을 수 있다. 서명은 HMAC-SHA256(`MAIL_LINK_SECRET`, "unsubscribe:" + 구독 id)의 base64url(43자)이고 만료가 없다(오래된 메일의 링크도 동작해야 한다).
 */

export interface LinkConfig {
  /** 서명 비밀(`wrangler secret put MAIL_LINK_SECRET`). */
  secret: string;
  /** 링크가 가리킬 이 서버의 주소(`SERVER_PUBLIC_URL`, 끝에 `/` 없이). */
  baseUrl: string;
}

const encoder = new TextEncoder();

function base64url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function fromBase64url(text: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]{43}$/.test(text)) return null;
  const binary = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=");
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function key(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function signUnsubscribe(
  secret: string,
  subscriptionId: string,
): Promise<string> {
  return base64url(
    await crypto.subtle.sign(
      "HMAC",
      await key(secret),
      encoder.encode(`unsubscribe:${subscriptionId}`),
    ),
  );
}

/** 서명이 이 구독 id의 것인가. 비교는 `crypto.subtle.verify`가 한다(시간 차이로 서명을 알아내지 못하게). */
export async function verifyUnsubscribe(
  secret: string,
  subscriptionId: string,
  signature: string,
): Promise<boolean> {
  const bytes = fromBase64url(signature);
  if (bytes === null) return false;
  return crypto.subtle.verify(
    "HMAC",
    await key(secret),
    bytes,
    encoder.encode(`unsubscribe:${subscriptionId}`),
  );
}

/** 메일에 넣을 수신 거부 주소. */
export async function unsubscribeUrl(
  links: LinkConfig,
  subscriptionId: string,
): Promise<string> {
  const params = new URLSearchParams({
    s: subscriptionId,
    t: await signUnsubscribe(links.secret, subscriptionId),
  });
  return `${links.baseUrl}/mail/unsubscribe?${params}`;
}

/**
 * 수신 거부 헤더(RFC 2369·8058). 메일 앱의 "구독 취소" 버튼이 이 주소로 POST(`List-Unsubscribe=One-Click`)를 보낸다 — 대량 발신자 요건(Gmail·Yahoo)이기도 하다.
 */
export function unsubscribeHeaders(url: string): Record<string, string> {
  return {
    "List-Unsubscribe": `<${url}>`,
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
  };
}
