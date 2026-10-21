# Contributing

## 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/)를 따릅니다.

```
<type>: <description>

<본문 (선택) — 무엇을 왜 바꿨는지>
```

**type**

- `feat`: 새 기능
- `fix`: 버그 수정
- `chore`: 빌드/설정/도구 변경 (코드 동작에 영향 없음)
- `docs`: 문서만 변경
- `refactor`: 동작은 그대로, 구조만 변경
- `test`: 테스트 추가/수정

예: `feat: 프로세스 기록 수집기 추가`, `chore: biome 설정 추가`

## 브랜치 이름

`<type>/<짧은-설명>` 형식입니다. 위 커밋 type과 동일한 접두어를 씁니다.

예: `chore/project-setting`, `feat/process-collector`

## PR 올리기 전

- `pnpm lint` 통과 확인 (커밋 시점에 pre-commit hook이 자동 검사하지만, PR 올리기 전 한 번 더 확인하는 걸 권장)
- PR 템플릿의 체크리스트를 채웁니다.
