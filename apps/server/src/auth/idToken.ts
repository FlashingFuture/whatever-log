import type { KeyProvider } from "./jwks.ts";

/** 검증을 통과한 ID 토큰에서 우리가 쓰는 값. */
export interface GoogleClaims {
  sub: string;
  email: string;
}

/**
 * invalid_token은 서명·형식·만료·대상이 맞지 않는 경우, email_not_verified는 Google이 이메일을 검증하지 않은
 * 계정이다.
 */
export class IdTokenError extends Error {
  kind: "invalid_token" | "email_not_verified";

  constructor(kind: "invalid_token" | "email_not_verified", message: string) {
    super(message);
    this.name = "IdTokenError";
    this.kind = kind;
  }
}

const ISSUERS = new Set(["https://accounts.google.com", "accounts.google.com"]);

function invalid(message: string): IdTokenError {
  return new IdTokenError("invalid_token", message);
}

function base64UrlToBytes(text: string): Uint8Array<ArrayBuffer> {
  const base64 = text.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function decodeJson(segment: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(
      new TextDecoder().decode(base64UrlToBytes(segment)),
    );
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // 아래에서 같은 오류로 처리한다.
  }
  throw invalid("토큰 형식이 올바르지 않습니다.");
}

/**
 * Google ID 토큰(JWT)을 검증하고 사용자 정보를 꺼낸다. 서명(RS256, Google 공개키)을 먼저 확인한 뒤 발급자·
 * 대상(우리 클라이언트 ID)·만료·이메일 검증 여부를 본다. 서명 알고리즘은 RS256만 받는다(`none` 등으로 서명을
 * 건너뛰는 토큰을 막는다).
 */
export async function verifyIdToken(
  idToken: string,
  options: { clientId: string; now: Date; keys: KeyProvider },
): Promise<GoogleClaims> {
  const parts = idToken.split(".");
  if (parts.length !== 3 || parts.some((part) => part.length === 0)) {
    throw invalid("토큰 형식이 올바르지 않습니다.");
  }
  const [headerPart, payloadPart, signaturePart] = parts as [
    string,
    string,
    string,
  ];
  const header = decodeJson(headerPart);
  if (header.alg !== "RS256" || typeof header.kid !== "string") {
    throw invalid("지원하지 않는 서명 방식입니다.");
  }

  const jwk = await options.keys.get(header.kid);
  if (jwk === undefined) {
    throw invalid("서명 키를 찾을 수 없습니다.");
  }
  let signatureOk = false;
  try {
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    signatureOk = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      base64UrlToBytes(signaturePart),
      new TextEncoder().encode(`${headerPart}.${payloadPart}`),
    );
  } catch {
    signatureOk = false;
  }
  if (!signatureOk) {
    throw invalid("서명이 올바르지 않습니다.");
  }

  const claims = decodeJson(payloadPart);
  if (typeof claims.iss !== "string" || !ISSUERS.has(claims.iss)) {
    throw invalid("발급자가 올바르지 않습니다.");
  }
  if (claims.aud !== options.clientId) {
    throw invalid("이 앱을 위한 토큰이 아닙니다.");
  }
  if (
    typeof claims.exp !== "number" ||
    !Number.isFinite(claims.exp) ||
    claims.exp * 1000 <= options.now.getTime()
  ) {
    throw invalid("토큰이 만료됐습니다.");
  }
  const { sub, email } = claims;
  if (typeof sub !== "string" || sub.length === 0 || sub.length > 255) {
    throw invalid("사용자 식별 값이 올바르지 않습니다.");
  }
  if (
    typeof email !== "string" ||
    email.length === 0 ||
    email.length > 254 ||
    !email.includes("@") ||
    /[\s\p{C}]/u.test(email)
  ) {
    throw invalid("이메일이 올바르지 않습니다.");
  }
  if (claims.email_verified !== true) {
    throw new IdTokenError(
      "email_not_verified",
      "이메일이 검증되지 않은 계정입니다.",
    );
  }
  return { sub, email };
}
