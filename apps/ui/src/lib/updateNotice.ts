// 새 버전 알림의 순수 로직: 알림 줄을 보일지, 무엇이라고 쓸지. DOM·hub를 모른다(lib 층).

export interface UpdateLike {
  supported: boolean;
  enabled: boolean;
  current: string;
  latest: { version: string } | null;
  available: boolean;
  error: string | null;
}

/** 알림 줄을 보이는가: 확인이 켜져 있고 새 버전이 있으며, 사용자가 그 버전을 "나중에"로 넘기지 않았다(다음 버전은 다시 알린다). */
export function shouldShowBanner(
  state: UpdateLike | null,
  dismissedVersion: string | null,
): boolean {
  return (
    state?.supported === true &&
    state.enabled &&
    state.available &&
    state.latest !== null &&
    state.latest.version !== dismissedVersion
  );
}

/** "새 버전 v1.0.0이 나왔어요 (지금 v1.0.0-beta.2)". */
export function bannerText(state: UpdateLike): string {
  const latest = state.latest?.version ?? "?";
  return `새 버전 v${latest}이 나왔어요 (지금 v${currentVersion(state)})`;
}

/** 지금 버전에서 개발 표시를 뺀 것. */
export function currentVersion(state: UpdateLike): string {
  return state.current.replace(/ \(개발\)$/, "");
}

/** 화면 아래 줄: 버전과 확인 상태. */
export function footerText(state: UpdateLike): string {
  const version = `whatever.log ${state.current}`;
  if (!state.supported) return version;
  if (!state.enabled) return `${version} · 새 버전 알림 꺼짐`;
  if (state.available && state.latest) {
    return `${version} · 새 버전 v${state.latest.version}`;
  }
  return state.error ? `${version} · ${state.error}` : `${version} · 최신 버전`;
}
