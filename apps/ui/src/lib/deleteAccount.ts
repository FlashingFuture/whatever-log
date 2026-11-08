// 계정 삭제 확인 창의 순수 규칙: 언제 "삭제" 버튼이 눌리는지, 삭제 뒤 무엇을 알릴지. DOM·hub를 모른다(lib 층).

/**
 * 삭제 버튼을 누를 수 있는 조건. 되돌릴 수 없는 일이라 두 가지를 모두 요구한다:
 * 1) "되돌릴 수 없다는 것을 이해했다"에 체크하고, 2) 지울 계정의 이메일을 직접 입력한다(대소문자·앞뒤 공백은 무시).
 * 이메일을 알 수 없는 로그인(환경 변수 토큰 등)은 입력할 수 없으니 체크만 요구한다.
 */
export function canConfirmDelete(
  understood: boolean,
  typed: string,
  email: string | null,
): boolean {
  if (!understood) {
    return false;
  }
  if (email === null) {
    return true;
  }
  return typed.trim().toLowerCase() === email.trim().toLowerCase();
}

export interface DeleteOutcome {
  deleted_on_server: boolean;
  signed_out: boolean;
  connections_cleared: boolean;
}

/**
 * 삭제가 끝난 뒤 보여 줄 문장들. 서버에서 지워진 것은 되돌릴 수 없으므로, 이 PC의 정리가 일부 실패했더라도 "서버 계정은 삭제됐다"는
 * 사실을 먼저 말하고, 남은 일(로그아웃)을 알린다.
 */
export function outcomeLines(outcome: DeleteOutcome): string[] {
  const lines = ["서버의 계정과 목표·달성 기록·로그인 토큰을 모두 지웠어요."];
  if (outcome.signed_out) {
    lines.push("이 PC의 로그인 정보도 지웠어요.");
  } else {
    lines.push(
      "다만 이 PC의 로그인 정보를 지우지 못했어요. 상단 막대의 '로그아웃'을 눌러 주세요.",
    );
  }
  if (!outcome.connections_cleared) {
    lines.push(
      "이 PC 목표의 서버 연결 표시를 정리하지 못했어요. 다시 로그인하면 다시 확인받아요.",
    );
  }
  lines.push("이 PC의 기록과 목표, 연결한 프로세스는 그대로 남아 있어요.");
  return lines;
}
