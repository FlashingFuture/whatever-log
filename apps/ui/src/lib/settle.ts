/**
 * promise가 정해진 시간 안에 끝나면 그 값을, 아니면 undefined를 돌려준다(promise는 계속 진행되고
 * 버려지지 않는다 — 호출부가 따로 이어서 쓴다).
 *
 * 화면의 덤 조각(예: 사이트 목록)이 보통은 주 내용과 같이 바로 그려지되, 느리면 주 내용을 먼저
 * 보여 주고 나중에 채우고 싶을 때 쓴다. 주기 갱신마다 "불러오는 중" 자리가 깜빡이지 않게 하려는
 * 것이다. promise는 거부되지 않는 것이어야 한다(거부되면 이 함수도 거부된다).
 */
export async function settleWithin<T>(
  promise: Promise<T>,
  ms: number,
): Promise<T | undefined> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<undefined>((resolve) => {
    timer = setTimeout(() => resolve(undefined), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}
