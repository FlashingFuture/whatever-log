/**
 * hub API의 단일 진입점. 화면 코드는 이 폴더 바깥에서 `../api`만 가져다 쓴다 — 안쪽이
 * 어떻게 나뉘어 있는지(client: 공통 통신, usage: 사용량 조회, goals: 목표 CRUD·수행 시간, browsers: 사이트를 기록하는 브라우저,
 * icons: 아이콘 주소, account: 로그인 상태·로그인·로그아웃, types: 응답 모양)는 숨긴다.
 */
export {
  cancelLogin,
  fetchAccount,
  logout,
  openExternalLink,
  startLogin,
} from "./account";
export { isSiteTrackingBrowser } from "./browsers";
export { ApiError, requestTimeoutMs } from "./client";
export {
  createGoal,
  deleteGoal,
  fetchGoalProgress,
  fetchGoals,
  fetchTrackedProcesses,
  fetchTrackedSites,
  updateGoal,
} from "./goals";
export { iconUrl, siteIconUrl } from "./icons";
export {
  applySync,
  deleteAccount,
  deleteDevice,
  fetchDevices,
  fetchSyncPlan,
  fetchSyncStatus,
} from "./sync";
export type {
  AccountSnapshot,
  BucketUsage,
  DeleteAccountResult,
  DeviceRow,
  ExternalLink,
  FieldError,
  Goal,
  GoalInput,
  GoalProgress,
  GoalProgressResponse,
  LoginProvider,
  LogoutResponse,
  ProcessSeries,
  ProcessTime,
  ProcessUsage,
  RangeSummary,
  RangeUsage,
  SiteLink,
  SiteRangeUsage,
  SiteTime,
  SiteUsage,
  SyncItem,
  SyncPlan,
  SyncResult,
  SyncStatus,
  TopTarget,
} from "./types";
export { fetchProcessUsage, fetchSiteUsage, fetchUsage } from "./usage";
