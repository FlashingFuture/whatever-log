/** 프로세스를 고르는 화면의 순수 로직(DOM 없음). 한 프로세스는 하나의 목표에만 연결된다. */

/** 이 모듈이 필요한 목표의 모양(Goal의 일부). */
export interface GoalLike {
  id: number;
  name: string;
  processes: readonly string[];
}

export interface ProcessSplit {
  /** 이 목표에 연결된 프로세스. */
  linked: string[];
  /** 추적된 프로세스 중 아직 어느 목표에도 연결되지 않은 것 — 이 목표에 추가할 수 있다. */
  available: string[];
  /** 다른 목표에 이미 연결돼 있어 이 목표에는 추가할 수 없는 것(어느 목표인지 함께). */
  takenByOthers: { process: string; goalName: string }[];
}

/** 프로세스 이름의 비교 키. Windows 파일 이름은 대소문자를 구분하지 않아 같은 프로세스로 본다. */
export function processKey(name: string): string {
  return name.toLowerCase();
}

function byKey(a: string, b: string): number {
  return processKey(a).localeCompare(processKey(b), "en");
}

/**
 * 연결 화면의 세 목록을 나눈다. tracked는 추적된 프로세스 이름들, goals는 모든 목표, goalId는 지금
 * 보는 목표다. 각 목록은 이름(대소문자 무시) 순이다.
 */
export function splitProcesses(
  tracked: readonly string[],
  goals: readonly GoalLike[],
  goalId: number,
): ProcessSplit {
  const current = goals.find((goal) => goal.id === goalId);
  const linked = [...(current?.processes ?? [])].sort(byKey);
  const linkedKeys = new Set(linked.map(processKey));

  const owner = new Map<string, string>();
  for (const goal of goals) {
    if (goal.id !== goalId) {
      for (const process of goal.processes) {
        owner.set(processKey(process), goal.name);
      }
    }
  }

  const available = tracked
    .filter(
      (process) =>
        !linkedKeys.has(processKey(process)) && !owner.has(processKey(process)),
    )
    .sort(byKey);

  const takenByOthers = goals
    .filter((goal) => goal.id !== goalId)
    .flatMap((goal) =>
      goal.processes.map((process) => ({ process, goalName: goal.name })),
    )
    .sort((a, b) => byKey(a.process, b.process));

  return { linked, available, takenByOthers };
}

/** 목록에 프로세스를 더한 새 목록(이미 있으면 그대로). 이름 순으로 돌려준다. */
export function addProcess(list: readonly string[], name: string): string[] {
  if (list.some((item) => processKey(item) === processKey(name))) {
    return [...list].sort(byKey);
  }
  return [...list, name].sort(byKey);
}

/** 목록에서 프로세스를 뺀 새 목록. */
export function removeProcess(list: readonly string[], name: string): string[] {
  return list.filter((item) => processKey(item) !== processKey(name));
}
