import { getApiBaseUrl, GATEWAY_BASIC_AUTH } from '@/lib/config';
import type {
  ActionBoardItem,
  AppMessage,
  AppUser,
  AuthSession,
  BrainSnapshot,
  ClosedPosition,
  ClosePositionPayload,
  CompositePick,
  CompositeReplayItem,
  FeedbackDecisionPayload,
  FeedbackDecisionResult,
  FeedbackItem,
  FeedbackSubmissionPayload,
  FeedbackSubmissionResult,
  HomeSnapshot,
  IndustryCapitalDirection,
  IndustryResearchPushStatus,
  IndustryCapitalResearchItem,
  IndustryCapitalResearchSubmissionResult,
  KlineBar,
  LearningAdvanceStatus,
  LearningProgress,
  OpenSignalPositionPayload,
  OpsSummary,
  PortfolioHistory,
  PortfolioActionResult,
  Position,
  PositionDetail,
  PositionGuide,
  PositioningPlan,
  PolicyWatchItem,
  PositionRiskUpdatePayload,
  PositionTrade,
  RecommendationCompareDay,
  RecommendationCompareSnapshot,
  RecommendationCompareSummary,
  RecommendationTakeoverReadiness,
  PushDevice,
  PushDispatchResult,
  PushRegistrationPayload,
  PushRegistrationResult,
  PushTakeoverPayload,
  PushTestPayload,
  RiskAlert,
  Signal,
  SignalDetail,
  SignalEntryGuide,
  StockDiagnosis,
  StrongMoveCandidate,
  StrategyPerformance,
  SystemStatus,
  TakeoverPushStatus,
  ThemeFollower,
  ThemeRadarItem,
  ThemeStageItem,
  TradeLedgerEntry,
} from '@/types/trading';

interface RequestOptions {
  token?: string;
  method?: 'GET' | 'POST' | 'PATCH';
  body?: Record<string, unknown>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};

  if (options.body) {
    headers['Content-Type'] = 'application/json';
  }

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  } else if (GATEWAY_BASIC_AUTH) {
    // Nginx gateway requires Basic Auth for unauthenticated requests
    headers.Authorization = `Basic ${GATEWAY_BASIC_AUTH}`;
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    let detail: string | undefined
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (payload.detail) {
        detail =
          typeof payload.detail === 'string'
            ? payload.detail
            : JSON.stringify(payload.detail)
      }
    } catch {
      // ignore json parse failures
    }

    throw new Error(detail ?? `HTTP ${response.status}`)
  }

  return (await response.json()) as T;
}

function appPath(token: string | undefined, path: string) {
  return token ? `/api/app${path}` : `/api${path}`;
}

function normalizeAppUser(payload: {
  username: string;
  display_name: string;
  role: string;
}): AppUser {
  return {
    username: payload.username,
    displayName: payload.display_name,
    role: payload.role,
  };
}

function normalizeAuthSession(payload: {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: {
    username: string;
    display_name: string;
    role: string;
  };
}): AuthSession {
  return {
    accessToken: payload.access_token,
    tokenType: payload.token_type,
    expiresAt: payload.expires_at,
    user: normalizeAppUser(payload.user),
  };
}

function normalizeSystemStatus(payload: {
  status: string;
  uptime_hours: number;
  health_score: number;
  today_signals: number;
  active_strategies: number;
  ooda_cycles: number;
  decision_accuracy: number;
}): SystemStatus {
  return {
    status: payload.status,
    uptimeHours: payload.uptime_hours,
    healthScore: payload.health_score,
    todaySignals: payload.today_signals,
    activeStrategies: payload.active_strategies,
    oodaCycles: payload.ooda_cycles,
    decisionAccuracy: payload.decision_accuracy,
  };
}

function normalizeLearningProgress(payload: {
  today_cycles: number;
  factor_adjustments: number;
  online_updates: number;
  experiments_running: number;
  new_factors_deployed: number;
  decision_accuracy: number;
}): LearningProgress {
  return {
    todayCycles: payload.today_cycles,
    factorAdjustments: payload.factor_adjustments,
    onlineUpdates: payload.online_updates,
    experimentsRunning: payload.experiments_running,
    newFactorsDeployed: payload.new_factors_deployed,
    decisionAccuracy: payload.decision_accuracy,
  };
}

function normalizeLearningAdvanceStatus(payload: {
  status: string;
  in_progress: boolean;
  today_completed: boolean;
  last_started_at: string | null;
  current_run_started_at: string | null;
  last_completed_at: string | null;
  last_requested_by: string | null;
  stale_hours: number | null;
  health_status: string;
  summary: string;
  last_error: string | null;
  last_report_excerpt: string;
  ingested_signals: number;
  verified_signals: number;
  reviewed_decisions: number;
  checks: Array<{
    name: string;
    status: string;
    detail: string;
  }>;
  recommendations: string[];
}): LearningAdvanceStatus {
  return {
    status: payload.status,
    inProgress: payload.in_progress,
    todayCompleted: payload.today_completed,
    lastStartedAt: payload.last_started_at,
    currentRunStartedAt: payload.current_run_started_at,
    lastCompletedAt: payload.last_completed_at,
    lastRequestedBy: payload.last_requested_by,
    staleHours: payload.stale_hours,
    healthStatus: payload.health_status,
    summary: payload.summary,
    lastError: payload.last_error,
    lastReportExcerpt: payload.last_report_excerpt,
    ingestedSignals: payload.ingested_signals,
    verifiedSignals: payload.verified_signals,
    reviewedDecisions: payload.reviewed_decisions,
    checks: payload.checks.map((item) => ({
      name: item.name,
      status: item.status,
      detail: item.detail,
    })),
    recommendations: payload.recommendations,
  };
}

function normalizeSignal(payload: {
  id: string;
  code: string;
  name: string;
  strategy: string;
  score: number;
  price: number;
  change_pct: number;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  risk_reward: number;
  timestamp: string;
  consensus_count: number;
}): Signal {
  return {
    id: payload.id,
    code: payload.code,
    name: payload.name,
    strategy: payload.strategy,
    score: payload.score,
    price: payload.price,
    changePct: payload.change_pct,
    buyPrice: payload.buy_price,
    stopLoss: payload.stop_loss,
    targetPrice: payload.target_price,
    riskReward: payload.risk_reward,
    timestamp: payload.timestamp,
    consensusCount: payload.consensus_count,
  };
}

function normalizeSignalDetail(payload: {
  id: string;
  code: string;
  name: string;
  strategy: string;
  strategies: string[];
  score: number;
  price: number;
  change_pct: number;
  high: number;
  low: number;
  volume: number;
  turnover: number;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  risk_reward: number;
  timestamp: string;
  consensus_count: number;
  factor_scores: Record<string, number>;
  regime: string;
  regime_score: number;
  entry_guide: {
    mode: string;
    summary: string;
    action: string;
    composite_score: number;
    setup_label: string | null;
    theme_sector: string | null;
    sector_bucket: string | null;
    theme_alignment: string;
    event_bias: string;
    event_score: number;
    event_summary: string | null;
    recommended_first_position_pct: number;
    suggested_amount: number;
    suggested_quantity: number;
    total_assets: number;
    max_single_position_pct: number;
    max_theme_exposure_pct: number;
    target_exposure_pct: number;
    deployable_cash: number;
    current_theme_exposure_pct: number;
    projected_theme_exposure_pct: number;
    concentration_summary: string | null;
    warnings: string[];
  };
}): SignalDetail {
  const entryGuide: SignalEntryGuide = {
    mode: payload.entry_guide?.mode ?? '优先观察',
    summary: payload.entry_guide?.summary ?? '先看组合和事件环境，再决定是否要动手。',
    action: payload.entry_guide?.action ?? '先控制总仓和首仓，再谈执行。',
    compositeScore: payload.entry_guide?.composite_score ?? 0,
    setupLabel: payload.entry_guide?.setup_label ?? null,
    themeSector: payload.entry_guide?.theme_sector ?? null,
    sectorBucket: payload.entry_guide?.sector_bucket ?? null,
    themeAlignment: payload.entry_guide?.theme_alignment ?? '主线匹配待观察',
    eventBias: payload.entry_guide?.event_bias ?? '中性',
    eventScore: payload.entry_guide?.event_score ?? 50,
    eventSummary: payload.entry_guide?.event_summary ?? null,
    recommendedFirstPositionPct: payload.entry_guide?.recommended_first_position_pct ?? 0,
    suggestedAmount: payload.entry_guide?.suggested_amount ?? 0,
    suggestedQuantity: payload.entry_guide?.suggested_quantity ?? 0,
    totalAssets: payload.entry_guide?.total_assets ?? 0,
    maxSinglePositionPct: payload.entry_guide?.max_single_position_pct ?? 0,
    maxThemeExposurePct: payload.entry_guide?.max_theme_exposure_pct ?? 0,
    targetExposurePct: payload.entry_guide?.target_exposure_pct ?? 0,
    deployableCash: payload.entry_guide?.deployable_cash ?? 0,
    currentThemeExposurePct: payload.entry_guide?.current_theme_exposure_pct ?? 0,
    projectedThemeExposurePct: payload.entry_guide?.projected_theme_exposure_pct ?? 0,
    concentrationSummary: payload.entry_guide?.concentration_summary ?? null,
    warnings: payload.entry_guide?.warnings ?? [],
  };

  return {
    ...normalizeSignal(payload),
    strategies: payload.strategies,
    high: payload.high,
    low: payload.low,
    volume: payload.volume,
    turnover: payload.turnover,
    factorScores: payload.factor_scores,
    regime: payload.regime,
    regimeScore: payload.regime_score,
    entryGuide,
  };
}

function normalizeStrongMoveCandidate(payload: {
  id: string;
  signal_id: string;
  code: string;
  name: string;
  strategy: string;
  setup_label: string;
  conviction: 'low' | 'medium' | 'high';
  composite_score: number;
  continuation_score: number;
  swing_score: number;
  strategy_win_rate: number;
  price: number;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  risk_reward: number;
  timestamp: string;
  thesis: string;
  next_step: string;
  reasons: string[];
}): StrongMoveCandidate {
  return {
    id: payload.id,
    signalId: payload.signal_id,
    code: payload.code,
    name: payload.name,
    strategy: payload.strategy,
    setupLabel: payload.setup_label,
    conviction: payload.conviction,
    compositeScore: payload.composite_score,
    continuationScore: payload.continuation_score,
    swingScore: payload.swing_score,
    strategyWinRate: payload.strategy_win_rate,
    price: payload.price,
    buyPrice: payload.buy_price,
    stopLoss: payload.stop_loss,
    targetPrice: payload.target_price,
    riskReward: payload.risk_reward,
    timestamp: payload.timestamp,
    thesis: payload.thesis,
    nextStep: payload.next_step,
    reasons: payload.reasons,
  };
}

function normalizeThemeFollower(payload: {
  code: string;
  name: string;
  change_pct: number;
  label: string;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  risk_reward: number;
}): ThemeFollower {
  return {
    code: payload.code,
    name: payload.name,
    changePct: payload.change_pct,
    label: payload.label,
    buyPrice: payload.buy_price,
    stopLoss: payload.stop_loss,
    targetPrice: payload.target_price,
    riskReward: payload.risk_reward,
  };
}

function normalizeThemeRadarItem(payload: {
  id: string;
  sector: string;
  theme_type: string;
  change_pct: number;
  score: number;
  intensity: string;
  timestamp: string;
  narrative: string;
  action: string;
  risk_note: string;
  message_hint: string | null;
  linked_signal_id: string | null;
  linked_code: string | null;
  linked_name: string | null;
  linked_setup_label: string | null;
  followers: Array<{
    code: string;
    name: string;
    change_pct: number;
    label: string;
    buy_price: number;
    stop_loss: number;
    target_price: number;
    risk_reward: number;
  }>;
}): ThemeRadarItem {
  return {
    id: payload.id,
    sector: payload.sector,
    themeType: payload.theme_type,
    changePct: payload.change_pct,
    score: payload.score,
    intensity: payload.intensity,
    timestamp: payload.timestamp,
    narrative: payload.narrative,
    action: payload.action,
    riskNote: payload.risk_note,
    messageHint: payload.message_hint,
    linkedSignalId: payload.linked_signal_id,
    linkedCode: payload.linked_code,
    linkedName: payload.linked_name,
    linkedSetupLabel: payload.linked_setup_label,
    followers: payload.followers.map(normalizeThemeFollower),
  };
}

function normalizeThemeStageItem(payload: {
  id: string;
  sector: string;
  theme_type: string;
  intensity: string;
  stage_label: string;
  participation_label: string;
  direction_score: number;
  policy_event_score: number;
  trend_score: number;
  attention_score: number;
  capital_preference_score: number;
  stage_score: number;
  linked_signal_id: string | null;
  linked_code: string | null;
  linked_name: string | null;
  linked_setup_label: string | null;
  summary: string;
  action: string;
  risk_note: string;
  drivers: string[];
}): ThemeStageItem {
  return {
    id: payload.id,
    sector: payload.sector,
    themeType: payload.theme_type,
    intensity: payload.intensity,
    stageLabel: payload.stage_label,
    participationLabel: payload.participation_label,
    directionScore: payload.direction_score,
    policyEventScore: payload.policy_event_score,
    trendScore: payload.trend_score,
    attentionScore: payload.attention_score,
    capitalPreferenceScore: payload.capital_preference_score,
    stageScore: payload.stage_score,
    linkedSignalId: payload.linked_signal_id,
    linkedCode: payload.linked_code,
    linkedName: payload.linked_name,
    linkedSetupLabel: payload.linked_setup_label,
    summary: payload.summary,
    action: payload.action,
    riskNote: payload.risk_note,
    drivers: payload.drivers,
  };
}

function normalizePolicyWatchItem(payload: {
  id: string;
  direction: string;
  policy_bucket: string;
  focus_sector: string;
  stage_label: string;
  participation_label: string;
  industry_phase: string;
  direction_score: number;
  policy_score: number;
  trend_score: number;
  attention_score: number;
  capital_preference_score: number;
  linked_signal_id: string | null;
  linked_code: string | null;
  linked_name: string | null;
  linked_setup_label: string | null;
  summary: string;
  action: string;
  risk_note: string;
  phase_summary: string;
  demand_drivers: string[];
  supply_drivers: string[];
  upstream: string[];
  midstream: string[];
  downstream: string[];
  milestones: string[];
  transmission_paths: string[];
  drivers: string[];
}): PolicyWatchItem {
  return {
    id: payload.id,
    direction: payload.direction,
    policyBucket: payload.policy_bucket,
    focusSector: payload.focus_sector,
    stageLabel: payload.stage_label,
    participationLabel: payload.participation_label,
    industryPhase: payload.industry_phase,
    directionScore: payload.direction_score,
    policyScore: payload.policy_score,
    trendScore: payload.trend_score,
    attentionScore: payload.attention_score,
    capitalPreferenceScore: payload.capital_preference_score,
    linkedSignalId: payload.linked_signal_id,
    linkedCode: payload.linked_code,
    linkedName: payload.linked_name,
    linkedSetupLabel: payload.linked_setup_label,
    summary: payload.summary,
    action: payload.action,
    riskNote: payload.risk_note,
    phaseSummary: payload.phase_summary,
    demandDrivers: payload.demand_drivers,
    supplyDrivers: payload.supply_drivers,
    upstream: payload.upstream,
    midstream: payload.midstream,
    downstream: payload.downstream,
    milestones: payload.milestones,
    transmissionPaths: payload.transmission_paths,
    drivers: payload.drivers,
  };
}

function normalizeIndustryCapitalDirection(payload: {
  id: string;
  direction: string;
  policy_bucket: string;
  focus_sector: string;
  strategic_label: string;
  industry_phase: string;
  participation_label: string;
  business_horizon: string;
  capital_horizon: string;
  priority_score?: number;
  strategic_score: number;
  policy_score: number;
  demand_score: number;
  supply_score: number;
  capital_preference_score: number;
  research_signal_score?: number;
  research_signal_label?: string;
  official_freshness_score?: number;
  official_freshness_label?: string;
  linked_signal_id: string | null;
  linked_code: string | null;
  linked_name: string | null;
  linked_setup_label: string | null;
  summary: string;
  business_action: string;
  capital_action: string;
  risk_note: string;
  research_summary?: string;
  research_next_action?: string;
  upstream: string[];
  midstream: string[];
  downstream: string[];
  demand_drivers: string[];
  supply_drivers: string[];
  milestones: string[];
  transmission_paths: string[];
  opportunities: string[];
  official_sources: string[];
  official_watchpoints: string[];
  business_checklist: string[];
  capital_checklist: string[];
  official_cards: Array<{
    title: string;
    source: string;
    excerpt: string;
    why_it_matters: string;
    next_watch: string;
  }>;
  official_source_entries?: Array<{
    title: string;
    issuer: string;
    published_at?: string | null;
    source_type?: string;
    excerpt: string;
    reference?: string | null;
    reference_url?: string | null;
    key_points?: string[];
    watch_tags?: string[];
  }>;
  official_documents: string[];
  timeline_checkpoints: string[];
  current_timeline_stage?: string;
  latest_catalyst_title?: string;
  latest_catalyst_summary?: string;
  timeline_events?: Array<{
    id: string;
    lane: string;
    stage: string;
    title: string;
    summary: string;
    source?: string | null;
    signal_label?: string;
    emphasis?: string;
    timestamp?: string | null;
    next_action?: string | null;
  }>;
  cooperation_targets: string[];
  cooperation_modes: string[];
  company_watchlist: Array<{
    code: string;
    name: string;
    role: string;
    chain_position: string;
    tracking_reason: string;
    action: string;
    tracking_score?: number;
    priority_label?: string;
    market_alignment?: string;
    next_check?: string;
    linked_setup_label?: string | null;
    linked_source?: string | null;
    research_signal_score?: number;
    research_signal_label?: string;
    recent_research_note?: string | null;
    timeline_alignment?: string;
    catalyst_hint?: string | null;
  }>;
  research_targets: string[];
  validation_signals: string[];
  drivers: string[];
}): IndustryCapitalDirection {
  return {
    id: payload.id,
    direction: payload.direction,
    policyBucket: payload.policy_bucket,
    focusSector: payload.focus_sector,
    strategicLabel: payload.strategic_label,
    industryPhase: payload.industry_phase,
    participationLabel: payload.participation_label,
    businessHorizon: payload.business_horizon,
    capitalHorizon: payload.capital_horizon,
    priorityScore: payload.priority_score ?? payload.strategic_score,
    strategicScore: payload.strategic_score,
    policyScore: payload.policy_score,
    demandScore: payload.demand_score,
    supplyScore: payload.supply_score,
    capitalPreferenceScore: payload.capital_preference_score,
    researchSignalScore: payload.research_signal_score ?? 50,
    researchSignalLabel: payload.research_signal_label ?? '暂无回写',
    officialFreshnessScore: payload.official_freshness_score ?? 50,
    officialFreshnessLabel: payload.official_freshness_label ?? '待补官方日期',
    linkedSignalId: payload.linked_signal_id,
    linkedCode: payload.linked_code,
    linkedName: payload.linked_name,
    linkedSetupLabel: payload.linked_setup_label,
    summary: payload.summary,
    businessAction: payload.business_action,
    capitalAction: payload.capital_action,
    riskNote: payload.risk_note,
    researchSummary: payload.research_summary ?? '当前还没有调研回写，先补客户、供应链和政策验证。',
    researchNextAction: payload.research_next_action ?? '先补第一次方向调研记录。',
    upstream: payload.upstream,
    midstream: payload.midstream,
    downstream: payload.downstream,
    demandDrivers: payload.demand_drivers,
    supplyDrivers: payload.supply_drivers,
    milestones: payload.milestones,
    transmissionPaths: payload.transmission_paths,
    opportunities: payload.opportunities,
    officialSources: payload.official_sources,
    officialWatchpoints: payload.official_watchpoints,
    businessChecklist: payload.business_checklist,
    capitalChecklist: payload.capital_checklist,
    officialCards: payload.official_cards.map((item) => ({
      title: item.title,
      source: item.source,
      excerpt: item.excerpt,
      whyItMatters: item.why_it_matters,
      nextWatch: item.next_watch,
    })),
    officialSourceEntries: (payload.official_source_entries ?? []).map((item) => ({
      title: item.title,
      issuer: item.issuer,
      publishedAt: item.published_at ?? null,
      sourceType: item.source_type ?? '官方原文',
      excerpt: item.excerpt,
      reference: item.reference ?? null,
      referenceUrl: item.reference_url ?? null,
      keyPoints: item.key_points ?? [],
      watchTags: item.watch_tags ?? [],
    })),
    officialDocuments: payload.official_documents,
    timelineCheckpoints: payload.timeline_checkpoints,
    currentTimelineStage: payload.current_timeline_stage ?? payload.timeline_checkpoints[0] ?? '继续观察',
    latestCatalystTitle: payload.latest_catalyst_title ?? payload.official_cards[0]?.title ?? '等待新的方向催化',
    latestCatalystSummary:
      payload.latest_catalyst_summary ??
      payload.official_cards[0]?.next_watch ??
      '当前先看官方口径、兑现节点和调研回写是否继续强化。',
    timelineEvents: (payload.timeline_events ?? []).map((item) => ({
      id: item.id,
      lane: item.lane,
      stage: item.stage,
      title: item.title,
      summary: item.summary,
      source: item.source ?? null,
      signalLabel: item.signal_label ?? '观察中',
      emphasis: item.emphasis ?? 'neutral',
      timestamp: item.timestamp ?? null,
      nextAction: item.next_action ?? null,
    })),
    cooperationTargets: payload.cooperation_targets,
    cooperationModes: payload.cooperation_modes,
    companyWatchlist: payload.company_watchlist.map((item) => ({
      code: item.code,
      name: item.name,
      role: item.role,
      chainPosition: item.chain_position,
      trackingReason: item.tracking_reason,
      action: item.action,
      trackingScore: item.tracking_score ?? 50,
      priorityLabel: item.priority_label ?? '持续跟踪',
      marketAlignment: item.market_alignment ?? '待确认',
      nextCheck: item.next_check ?? '继续跟踪兑现与承接',
      linkedSetupLabel: item.linked_setup_label ?? null,
      linkedSource: item.linked_source ?? null,
      researchSignalScore: item.research_signal_score ?? 50,
      researchSignalLabel: item.research_signal_label ?? '暂无回写',
      recentResearchNote: item.recent_research_note ?? null,
      timelineAlignment: item.timeline_alignment ?? '时间轴待确认',
      catalystHint: item.catalyst_hint ?? null,
    })),
    researchTargets: payload.research_targets,
    validationSignals: payload.validation_signals,
    drivers: payload.drivers,
  };
}

function normalizeIndustryCapitalResearchItem(payload: {
  id: string;
  direction_id: string;
  direction: string;
  title: string;
  note: string;
  source: string;
  status: string;
  company_code: string | null;
  company_name: string | null;
  created_at: string;
  updated_at: string;
  author: string;
}): IndustryCapitalResearchItem {
  return {
    id: payload.id,
    directionId: payload.direction_id,
    direction: payload.direction,
    title: payload.title,
    note: payload.note,
    source: payload.source,
    status: payload.status,
    companyCode: payload.company_code ?? null,
    companyName: payload.company_name ?? null,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
    author: payload.author,
  };
}

function normalizeCompositePick(payload: {
  id: string;
  signal_id: string;
  code: string;
  name: string;
  strategy: string;
  theme_sector: string | null;
  theme_intensity: string | null;
  source_category?: string;
  source_label?: string;
  horizon_label?: string;
  setup_label: string;
  conviction: 'low' | 'medium' | 'high';
  composite_score: number;
  strategy_score: number;
  capital_score: number;
  theme_score: number;
  event_score?: number;
  event_bias?: string;
  event_summary?: string | null;
  event_matched_sector?: string | null;
  execution_score: number;
  first_position_pct: number;
  price: number;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  risk_reward: number;
  timestamp: string;
  thesis: string;
  action: string;
  reasons: string[];
}): CompositePick {
  return {
    id: payload.id,
    signalId: payload.signal_id,
    code: payload.code,
    name: payload.name,
    strategy: payload.strategy,
    themeSector: payload.theme_sector,
    themeIntensity: payload.theme_intensity,
    sourceCategory: payload.source_category ?? 'strategy',
    sourceLabel: payload.source_label ?? '策略候选',
    horizonLabel: payload.horizon_label ?? '短线观察',
    setupLabel: payload.setup_label,
    conviction: payload.conviction,
    compositeScore: payload.composite_score,
    strategyScore: payload.strategy_score,
    capitalScore: payload.capital_score,
    themeScore: payload.theme_score,
    eventScore: payload.event_score ?? 50,
    eventBias: payload.event_bias ?? '中性',
    eventSummary: payload.event_summary ?? null,
    eventMatchedSector: payload.event_matched_sector ?? null,
    executionScore: payload.execution_score,
    firstPositionPct: payload.first_position_pct,
    price: payload.price,
    buyPrice: payload.buy_price,
    stopLoss: payload.stop_loss,
    targetPrice: payload.target_price,
    riskReward: payload.risk_reward,
    timestamp: payload.timestamp,
    thesis: payload.thesis,
    action: payload.action,
    reasons: payload.reasons,
  };
}

function normalizePositioningPlan(payload: {
  mode: string;
  regime: string;
  regime_score: number;
  event_bias?: string;
  event_score?: number;
  event_summary?: string | null;
  event_focus_sector?: string | null;
  current_exposure_pct: number;
  target_exposure_pct: number;
  deployable_exposure_pct: number;
  cash_balance: number;
  total_assets: number;
  deployable_cash: number;
  current_positions: number;
  available_slots: number;
  max_positions: number;
  first_entry_position_pct: number;
  max_single_position_pct: number;
  max_theme_exposure_pct: number;
  top_theme: string | null;
  focus: string;
  reasons: string[];
  actions: string[];
  deployments: Array<{
    code: string;
    name: string;
    setup_label: string;
    suggested_position_pct: number;
    suggested_amount: number;
    theme_sector: string | null;
    reason: string;
  }>;
}): PositioningPlan {
  return {
    mode: payload.mode,
    regime: payload.regime,
    regimeScore: payload.regime_score,
    eventBias: payload.event_bias ?? '中性',
    eventScore: payload.event_score ?? 50,
    eventSummary: payload.event_summary ?? null,
    eventFocusSector: payload.event_focus_sector ?? null,
    currentExposurePct: payload.current_exposure_pct,
    targetExposurePct: payload.target_exposure_pct,
    deployableExposurePct: payload.deployable_exposure_pct,
    cashBalance: payload.cash_balance,
    totalAssets: payload.total_assets,
    deployableCash: payload.deployable_cash,
    currentPositions: payload.current_positions,
    availableSlots: payload.available_slots,
    maxPositions: payload.max_positions,
    firstEntryPositionPct: payload.first_entry_position_pct,
    maxSinglePositionPct: payload.max_single_position_pct,
    maxThemeExposurePct: payload.max_theme_exposure_pct,
    topTheme: payload.top_theme,
    focus: payload.focus,
    reasons: payload.reasons,
    actions: payload.actions,
    deployments: payload.deployments.map((item) => ({
      code: item.code,
      name: item.name,
      setupLabel: item.setup_label,
      suggestedPositionPct: item.suggested_position_pct,
      suggestedAmount: item.suggested_amount,
      themeSector: item.theme_sector,
      reason: item.reason,
    })),
  };
}

function normalizeCompositeReplayItem(payload: {
  id: string;
  trade_date: string;
  signal_id: string;
  code: string;
  name: string;
  strategy: string;
  setup_label: string;
  conviction: 'low' | 'medium' | 'high';
  composite_score: number;
  first_position_pct: number;
  theme_sector: string | null;
  review_label: string;
  verified_days: number;
  t1_return_pct: number | null;
  t3_return_pct: number | null;
  t5_return_pct: number | null;
  outcome_summary: string;
  review: string;
}): CompositeReplayItem {
  return {
    id: payload.id,
    tradeDate: payload.trade_date,
    signalId: payload.signal_id,
    code: payload.code,
    name: payload.name,
    strategy: payload.strategy,
    setupLabel: payload.setup_label,
    conviction: payload.conviction,
    compositeScore: payload.composite_score,
    firstPositionPct: payload.first_position_pct,
    themeSector: payload.theme_sector,
    reviewLabel: payload.review_label,
    verifiedDays: payload.verified_days,
    t1ReturnPct: payload.t1_return_pct,
    t3ReturnPct: payload.t3_return_pct,
    t5ReturnPct: payload.t5_return_pct,
    outcomeSummary: payload.outcome_summary,
    review: payload.review,
  };
}

function normalizeRecommendationCompareSummary(payload: {
  label: string;
  sample_days: number;
  observed_t1_days: number;
  observed_t3_days: number;
  observed_t5_days: number;
  avg_t1_return_pct: number | null;
  avg_t3_return_pct: number | null;
  avg_t5_return_pct: number | null;
  t1_win_rate: number | null;
  t3_win_rate: number | null;
  t5_win_rate: number | null;
}): RecommendationCompareSummary {
  return {
    label: payload.label,
    sampleDays: payload.sample_days,
    observedT1Days: payload.observed_t1_days,
    observedT3Days: payload.observed_t3_days,
    observedT5Days: payload.observed_t5_days,
    avgT1ReturnPct: payload.avg_t1_return_pct,
    avgT3ReturnPct: payload.avg_t3_return_pct,
    avgT5ReturnPct: payload.avg_t5_return_pct,
    t1WinRate: payload.t1_win_rate,
    t3WinRate: payload.t3_win_rate,
    t5WinRate: payload.t5_win_rate,
  };
}

function normalizeRecommendationCompareDay(payload: {
  trade_date: string;
  composite_signal_id: string | null;
  composite_code: string | null;
  composite_name: string | null;
  composite_score: number | null;
  composite_t1_return_pct: number | null;
  composite_t3_return_pct: number | null;
  composite_t5_return_pct: number | null;
  baseline_signal_id: string | null;
  baseline_code: string | null;
  baseline_name: string | null;
  baseline_score: number | null;
  baseline_t1_return_pct: number | null;
  baseline_t3_return_pct: number | null;
  baseline_t5_return_pct: number | null;
  winner_label: string;
  summary: string;
}): RecommendationCompareDay {
  return {
    tradeDate: payload.trade_date,
    compositeSignalId: payload.composite_signal_id,
    compositeCode: payload.composite_code,
    compositeName: payload.composite_name,
    compositeScore: payload.composite_score,
    compositeT1ReturnPct: payload.composite_t1_return_pct,
    compositeT3ReturnPct: payload.composite_t3_return_pct,
    compositeT5ReturnPct: payload.composite_t5_return_pct,
    baselineSignalId: payload.baseline_signal_id,
    baselineCode: payload.baseline_code,
    baselineName: payload.baseline_name,
    baselineScore: payload.baseline_score,
    baselineT1ReturnPct: payload.baseline_t1_return_pct,
    baselineT3ReturnPct: payload.baseline_t3_return_pct,
    baselineT5ReturnPct: payload.baseline_t5_return_pct,
    winnerLabel: payload.winner_label,
    summary: payload.summary,
  };
}

function normalizeRecommendationTakeoverReadiness(payload: {
  status: string;
  label: string;
  confidence_score: number;
  summary: string;
  recommended_action: string;
  conditions: string[];
}): RecommendationTakeoverReadiness {
  return {
    status: payload.status,
    label: payload.label,
    confidenceScore: payload.confidence_score,
    summary: payload.summary,
    recommendedAction: payload.recommended_action,
    conditions: payload.conditions,
  };
}

function normalizeRecommendationCompareSnapshot(payload: {
  composite: {
    label: string;
    sample_days: number;
    observed_t1_days: number;
    observed_t3_days: number;
    observed_t5_days: number;
    avg_t1_return_pct: number | null;
    avg_t3_return_pct: number | null;
    avg_t5_return_pct: number | null;
    t1_win_rate: number | null;
    t3_win_rate: number | null;
    t5_win_rate: number | null;
  };
  baseline: {
    label: string;
    sample_days: number;
    observed_t1_days: number;
    observed_t3_days: number;
    observed_t5_days: number;
    avg_t1_return_pct: number | null;
    avg_t3_return_pct: number | null;
    avg_t5_return_pct: number | null;
    t1_win_rate: number | null;
    t3_win_rate: number | null;
    t5_win_rate: number | null;
  };
  advantage: string[];
  readiness: {
    status: string;
    label: string;
    confidence_score: number;
    summary: string;
    recommended_action: string;
    conditions: string[];
  };
  days: Array<{
    trade_date: string;
    composite_signal_id: string | null;
    composite_code: string | null;
    composite_name: string | null;
    composite_score: number | null;
    composite_t1_return_pct: number | null;
    composite_t3_return_pct: number | null;
    composite_t5_return_pct: number | null;
    baseline_signal_id: string | null;
    baseline_code: string | null;
    baseline_name: string | null;
    baseline_score: number | null;
    baseline_t1_return_pct: number | null;
    baseline_t3_return_pct: number | null;
    baseline_t5_return_pct: number | null;
    winner_label: string;
    summary: string;
  }>;
}): RecommendationCompareSnapshot {
  return {
    composite: normalizeRecommendationCompareSummary(payload.composite),
    baseline: normalizeRecommendationCompareSummary(payload.baseline),
    advantage: payload.advantage,
    readiness: normalizeRecommendationTakeoverReadiness(payload.readiness),
    days: payload.days.map(normalizeRecommendationCompareDay),
  };
}

function normalizePosition(payload: {
  code: string;
  name: string;
  quantity: number;
  cost_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
  stop_loss: number;
  take_profit: number;
  hold_days: number;
  strategy: string;
}): Position {
  return {
    code: payload.code,
    name: payload.name,
    quantity: payload.quantity,
    costPrice: payload.cost_price,
    currentPrice: payload.current_price,
    marketValue: payload.market_value,
    profitLoss: payload.profit_loss,
    profitLossPct: payload.profit_loss_pct,
    stopLoss: payload.stop_loss,
    takeProfit: payload.take_profit,
    holdDays: payload.hold_days,
    strategy: payload.strategy,
  };
}

function normalizePositionTrade(payload: {
  time: string;
  type: string;
  price: number;
  quantity: number;
  reason: string;
}): PositionTrade {
  return {
    time: payload.time,
    type: payload.type,
    price: payload.price,
    quantity: payload.quantity,
    reason: payload.reason,
  };
}

function normalizePositionDetail(payload: {
  code: string;
  name: string;
  quantity: number;
  cost_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
  stop_loss: number;
  take_profit: number;
  hold_days: number;
  strategy: string;
  buy_time: string;
  high_price: number;
  low_price: number;
  trailing_stop: boolean;
  trailing_trigger_price: number;
  trades: Array<{
    time: string;
    type: string;
    price: number;
    quantity: number;
    reason: string;
  }>;
  position_guide: {
    mode: string;
    summary: string;
    next_action: string;
    event_bias: string;
    event_score: number;
    event_summary: string | null;
    top_theme: string | null;
    sector_bucket: string | null;
    theme_alignment: string;
    can_add: boolean;
    current_exposure_pct: number;
    target_exposure_pct: number;
    position_pct: number;
    current_theme_exposure_pct: number;
    max_theme_exposure_pct: number;
    suggested_stop_loss: number;
    suggested_take_profit: number;
    suggested_reduce_pct: number;
    suggested_reduce_quantity: number;
    concentration_summary: string | null;
    warnings: string[];
  };
}): PositionDetail {
  const positionGuide: PositionGuide = {
    mode: payload.position_guide?.mode ?? '继续持有',
    summary: payload.position_guide?.summary ?? '仓位总体仍在可控区间。',
    nextAction: payload.position_guide?.next_action ?? '继续观察',
    eventBias: payload.position_guide?.event_bias ?? '中性',
    eventScore: payload.position_guide?.event_score ?? 50,
    eventSummary: payload.position_guide?.event_summary ?? null,
    topTheme: payload.position_guide?.top_theme ?? null,
    sectorBucket: payload.position_guide?.sector_bucket ?? null,
    themeAlignment: payload.position_guide?.theme_alignment ?? '主线匹配待观察',
    canAdd: payload.position_guide?.can_add ?? false,
    currentExposurePct: payload.position_guide?.current_exposure_pct ?? 0,
    targetExposurePct: payload.position_guide?.target_exposure_pct ?? 0,
    positionPct: payload.position_guide?.position_pct ?? 0,
    currentThemeExposurePct: payload.position_guide?.current_theme_exposure_pct ?? 0,
    maxThemeExposurePct: payload.position_guide?.max_theme_exposure_pct ?? 0,
    suggestedStopLoss: payload.position_guide?.suggested_stop_loss ?? 0,
    suggestedTakeProfit: payload.position_guide?.suggested_take_profit ?? 0,
    suggestedReducePct: payload.position_guide?.suggested_reduce_pct ?? 0,
    suggestedReduceQuantity: payload.position_guide?.suggested_reduce_quantity ?? 0,
    concentrationSummary: payload.position_guide?.concentration_summary ?? null,
    warnings: payload.position_guide?.warnings ?? [],
  };

  return {
    ...normalizePosition(payload),
    buyTime: payload.buy_time,
    highPrice: payload.high_price,
    lowPrice: payload.low_price,
    trailingStop: payload.trailing_stop,
    trailingTriggerPrice: payload.trailing_trigger_price,
    trades: payload.trades.map(normalizePositionTrade),
    positionGuide,
  };
}

function normalizeClosedPosition(payload: {
  code: string;
  name: string;
  quantity: number;
  cost_price: number;
  close_price: number;
  realized_profit_loss: number;
  realized_profit_loss_pct: number;
  hold_days: number;
  strategy: string;
  buy_time: string;
  closed_at: string;
  close_reason: string;
  status: string;
  trades: Array<{
    time: string;
    type: string;
    price: number;
    quantity: number;
    reason: string;
  }>;
}): ClosedPosition {
  return {
    code: payload.code,
    name: payload.name,
    quantity: payload.quantity,
    costPrice: payload.cost_price,
    closePrice: payload.close_price,
    realizedProfitLoss: payload.realized_profit_loss,
    realizedProfitLossPct: payload.realized_profit_loss_pct,
    holdDays: payload.hold_days,
    strategy: payload.strategy,
    buyTime: payload.buy_time,
    closedAt: payload.closed_at,
    closeReason: payload.close_reason,
    status: payload.status,
    trades: payload.trades.map(normalizePositionTrade),
  };
}

function normalizeTradeLedgerEntry(payload: {
  id: string;
  code: string;
  name: string;
  strategy: string;
  time: string;
  type: string;
  price: number;
  quantity: number;
  reason: string;
  status: string;
}): TradeLedgerEntry {
  return {
    id: payload.id,
    code: payload.code,
    name: payload.name,
    strategy: payload.strategy,
    time: payload.time,
    type: payload.type,
    price: payload.price,
    quantity: payload.quantity,
    reason: payload.reason,
    status: payload.status,
  };
}

function normalizeFeedbackItem(payload: {
  id: string;
  username: string;
  title: string;
  message: string;
  category: string;
  priority: string;
  decision_status: string;
  owner_note: string;
  source_type: string;
  source_id: string;
  source_route: string;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  decided_by: string | null;
}): FeedbackItem {
  return {
    id: payload.id,
    username: payload.username,
    title: payload.title,
    message: payload.message,
    category: payload.category,
    priority: payload.priority,
    decisionStatus: payload.decision_status,
    ownerNote: payload.owner_note,
    sourceType: payload.source_type,
    sourceId: payload.source_id,
    sourceRoute: payload.source_route,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
    decidedAt: payload.decided_at,
    decidedBy: payload.decided_by,
  };
}

function normalizeFeedbackSubmissionResult(payload: {
  success: boolean;
  message: string;
  item: {
    id: string;
    username: string;
    title: string;
    message: string;
    category: string;
    priority: string;
    decision_status: string;
    owner_note: string;
    source_type: string;
    source_id: string;
    source_route: string;
    created_at: string;
    updated_at: string;
    decided_at: string | null;
    decided_by: string | null;
  };
  pending_count: number;
}): FeedbackSubmissionResult {
  return {
    success: payload.success,
    message: payload.message,
    item: normalizeFeedbackItem(payload.item),
    pendingCount: payload.pending_count,
  };
}

function normalizeFeedbackDecisionResult(payload: {
  success: boolean;
  message: string;
  item: {
    id: string;
    username: string;
    title: string;
    message: string;
    category: string;
    priority: string;
    decision_status: string;
    owner_note: string;
    source_type: string;
    source_id: string;
    source_route: string;
    created_at: string;
    updated_at: string;
    decided_at: string | null;
    decided_by: string | null;
  };
}): FeedbackDecisionResult {
  return {
    success: payload.success,
    message: payload.message,
    item: normalizeFeedbackItem(payload.item),
  };
}

function normalizeOpsRouteStat(payload: {
  method: string;
  path: string;
  count: number;
  error_count: number;
  avg_latency_ms: number;
  max_latency_ms: number;
  last_status: number;
  last_seen_at: string | null;
}) {
  return {
    method: payload.method,
    path: payload.path,
    count: payload.count,
    errorCount: payload.error_count,
    avgLatencyMs: payload.avg_latency_ms,
    maxLatencyMs: payload.max_latency_ms,
    lastStatus: payload.last_status,
    lastSeenAt: payload.last_seen_at,
  };
}

function normalizeOpsSummary(payload: {
  service: string;
  version: string;
  started_at: string;
  uptime_seconds: number;
  ready: boolean;
  readiness_issues: string[];
  request_count: number;
  error_count: number;
  error_rate: number;
  avg_latency_ms: number;
  max_latency_ms: number;
  p95_latency_ms: number;
  last_error_at: string | null;
  last_error_path: string | null;
  websocket_connections: number;
  system_status: string;
  system_health_score: number;
  today_signals: number;
  active_strategies: number;
  data_status: {
    scorecard_records: number;
    trade_journal_records: number;
    signal_count: number;
    active_positions: number;
    feedback_items: number;
    push_devices: number;
  };
  routes: Array<{
    method: string;
    path: string;
    count: number;
    error_count: number;
    avg_latency_ms: number;
    max_latency_ms: number;
    last_status: number;
    last_seen_at: string | null;
  }>;
  recommendations?: Array<{
    level: string;
    title: string;
    message: string;
  }>;
}): OpsSummary {
  return {
    service: payload.service,
    version: payload.version,
    startedAt: payload.started_at,
    uptimeSeconds: payload.uptime_seconds,
    ready: payload.ready,
    readinessIssues: payload.readiness_issues,
    requestCount: payload.request_count,
    errorCount: payload.error_count,
    errorRate: payload.error_rate,
    avgLatencyMs: payload.avg_latency_ms,
    maxLatencyMs: payload.max_latency_ms,
    p95LatencyMs: payload.p95_latency_ms,
    lastErrorAt: payload.last_error_at,
    lastErrorPath: payload.last_error_path,
    websocketConnections: payload.websocket_connections,
    systemStatus: payload.system_status,
    systemHealthScore: payload.system_health_score,
    todaySignals: payload.today_signals,
    activeStrategies: payload.active_strategies,
    dataStatus: {
      scorecardRecords: payload.data_status.scorecard_records,
      tradeJournalRecords: payload.data_status.trade_journal_records,
      signalCount: payload.data_status.signal_count,
      activePositions: payload.data_status.active_positions,
      feedbackItems: payload.data_status.feedback_items,
      pushDevices: payload.data_status.push_devices,
    },
    routes: payload.routes.map(normalizeOpsRouteStat),
    recommendations: (payload.recommendations ?? []).map((item) => ({
      level: item.level,
      title: item.title,
      message: item.message,
    })),
  };
}

function normalizeKlineBar(payload: {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
}): KlineBar {
  return {
    date: payload.date,
    open: payload.open,
    high: payload.high,
    low: payload.low,
    close: payload.close,
    volume: payload.volume,
    turnover: payload.turnover,
  };
}

function normalizeRiskAlert(payload: {
  id: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  message: string;
  source: string;
  source_id: string;
  created_at: string;
  route: string | null;
}): RiskAlert {
  return {
    id: payload.id,
    level: payload.level,
    title: payload.title,
    message: payload.message,
    source: payload.source,
    sourceId: payload.source_id,
    createdAt: payload.created_at,
    route: payload.route,
  };
}

function normalizeAppMessage(payload: {
  id: string;
  title: string;
  body: string;
  preview: string;
  level: string;
  channel: string;
  created_at: string;
  route?: string | null;
}): AppMessage {
  return {
    id: payload.id,
    title: payload.title,
    body: payload.body,
    preview: payload.preview,
    level: payload.level,
    channel: payload.channel,
    createdAt: payload.created_at,
    route: payload.route ?? null,
  };
}

function normalizeActionBoardItem(payload: {
  id: string;
  kind: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  summary: string;
  action_label: string;
  route: string | null;
  source: string;
  source_id: string;
  created_at: string;
}): ActionBoardItem {
  return {
    id: payload.id,
    kind: payload.kind,
    level: payload.level,
    title: payload.title,
    summary: payload.summary,
    actionLabel: payload.action_label,
    route: payload.route,
    source: payload.source,
    sourceId: payload.source_id,
    createdAt: payload.created_at,
  };
}

function normalizeStrategyPerformance(payload: {
  id: string;
  name: string;
  status: string;
  win_rate: number;
  avg_return: number;
  signal_count: number;
  last_signal_time: string | null;
}): StrategyPerformance {
  return {
    id: payload.id,
    name: payload.name,
    status: payload.status,
    winRate: payload.win_rate,
    avgReturn: payload.avg_return,
    signalCount: payload.signal_count,
    lastSignalTime: payload.last_signal_time,
  };
}

function normalizeStockDiagnosis(payload: {
  code: string;
  name: string;
  price: number;
  as_of: string;
  total_score: number;
  verdict: string;
  direction: string;
  signal_direction: string;
  actionable: boolean;
  confidence_label: string;
  advice: string;
  report_text: string;
  stop_loss: number | null;
  take_profit: number | null;
  scores: Record<string, number>;
  details: Record<string, string[]>;
  regime: string;
  regime_score: number;
  regime_summary: string;
  health_bias: string;
  in_portfolio: boolean;
  position_quantity: number;
  position_profit_loss_pct: number | null;
  in_signal_board: boolean;
  top_strategy: string | null;
  top_strategy_win_rate: number | null;
  top_strategy_avg_return: number | null;
  risk_flags: string[];
  next_actions: string[];
}): StockDiagnosis {
  return {
    code: payload.code,
    name: payload.name,
    price: payload.price,
    asOf: payload.as_of,
    totalScore: payload.total_score,
    verdict: payload.verdict,
    direction: payload.direction,
    signalDirection: payload.signal_direction,
    actionable: payload.actionable,
    confidenceLabel: payload.confidence_label,
    advice: payload.advice,
    reportText: payload.report_text,
    stopLoss: payload.stop_loss,
    takeProfit: payload.take_profit,
    scores: payload.scores,
    details: payload.details,
    regime: payload.regime,
    regimeScore: payload.regime_score,
    regimeSummary: payload.regime_summary,
    healthBias: payload.health_bias,
    inPortfolio: payload.in_portfolio,
    positionQuantity: payload.position_quantity,
    positionProfitLossPct: payload.position_profit_loss_pct,
    inSignalBoard: payload.in_signal_board,
    topStrategy: payload.top_strategy,
    topStrategyWinRate: payload.top_strategy_win_rate,
    topStrategyAvgReturn: payload.top_strategy_avg_return,
    riskFlags: payload.risk_flags,
    nextActions: payload.next_actions,
  };
}

function normalizePortfolioActionResult(payload: {
  success: boolean;
  action: 'open' | 'risk_update' | 'close';
  code: string;
  name: string;
  message: string;
  executed_at: string;
  quantity: number;
  execution_price: number;
  cash_balance: number;
  total_assets: number;
  position: {
    code: string;
    name: string;
    quantity: number;
    cost_price: number;
    current_price: number;
    market_value: number;
    profit_loss: number;
    profit_loss_pct: number;
    stop_loss: number;
    take_profit: number;
    hold_days: number;
    strategy: string;
    buy_time: string;
    high_price: number;
    low_price: number;
    trailing_stop: boolean;
    trailing_trigger_price: number;
    trades: Array<{
      time: string;
      type: string;
      price: number;
      quantity: number;
      reason: string;
    }>;
    position_guide: {
      mode: string;
      summary: string;
      next_action: string;
      event_bias: string;
      event_score: number;
      event_summary: string | null;
      top_theme: string | null;
      sector_bucket: string | null;
      theme_alignment: string;
      can_add: boolean;
      current_exposure_pct: number;
      target_exposure_pct: number;
      position_pct: number;
      current_theme_exposure_pct: number;
      max_theme_exposure_pct: number;
      suggested_stop_loss: number;
      suggested_take_profit: number;
      suggested_reduce_pct: number;
      suggested_reduce_quantity: number;
      concentration_summary: string | null;
      warnings: string[];
    };
  } | null;
  realized_profit_loss: number | null;
}): PortfolioActionResult {
  return {
    success: payload.success,
    action: payload.action,
    code: payload.code,
    name: payload.name,
    message: payload.message,
    executedAt: payload.executed_at,
    quantity: payload.quantity,
    executionPrice: payload.execution_price,
    cashBalance: payload.cash_balance,
    totalAssets: payload.total_assets,
    position: payload.position ? normalizePositionDetail(payload.position) : null,
    realizedProfitLoss: payload.realized_profit_loss,
  };
}

function normalizePushDevice(payload: {
  username: string;
  platform: string;
  expo_push_token: string;
  device_name: string;
  app_version: string;
  permission_state: string;
  is_physical_device: boolean | null;
  status: string;
  last_seen_at: string;
  last_push_at: string | null;
  last_push_status: string | null;
  last_error: string | null;
}): PushDevice {
  return {
    username: payload.username,
    platform: payload.platform,
    expoPushToken: payload.expo_push_token,
    deviceName: payload.device_name,
    appVersion: payload.app_version,
    permissionState: payload.permission_state,
    isPhysicalDevice: payload.is_physical_device,
    status: payload.status,
    lastSeenAt: payload.last_seen_at,
    lastPushAt: payload.last_push_at,
    lastPushStatus: payload.last_push_status,
    lastError: payload.last_error,
  };
}

function normalizePushRegistrationResult(payload: {
  success: boolean;
  message: string;
  device: {
    username: string;
    platform: string;
    expo_push_token: string;
    device_name: string;
    app_version: string;
    permission_state: string;
    is_physical_device: boolean | null;
    status: string;
    last_seen_at: string;
    last_push_at: string | null;
    last_push_status: string | null;
    last_error: string | null;
  };
  active_devices: number;
  takeover_dispatch?: {
    success: boolean;
    dry_run: boolean;
    targeted_devices: number;
    sent_devices: number;
    failed_devices: number;
    tickets: Array<{
      expo_push_token: string;
      status: string;
      ticket_id: string | null;
      message: string | null;
      details: string | null;
    }>;
  } | null;
}): PushRegistrationResult {
  return {
    success: payload.success,
    message: payload.message,
    device: normalizePushDevice(payload.device),
    activeDevices: payload.active_devices,
    takeoverDispatch: payload.takeover_dispatch
      ? normalizePushDispatchResult(payload.takeover_dispatch)
      : null,
  };
}

function normalizePushDispatchResult(payload: {
  success: boolean;
  dry_run: boolean;
  targeted_devices: number;
  sent_devices: number;
  failed_devices: number;
  tickets: Array<{
    expo_push_token: string;
    status: string;
    ticket_id: string | null;
    message: string | null;
    details: string | null;
  }>;
}): PushDispatchResult {
  return {
    success: payload.success,
    dryRun: payload.dry_run,
    targetedDevices: payload.targeted_devices,
    sentDevices: payload.sent_devices,
    failedDevices: payload.failed_devices,
    tickets: payload.tickets.map((ticket) => ({
      expoPushToken: ticket.expo_push_token,
      status: ticket.status,
      ticketId: ticket.ticket_id,
      message: ticket.message,
      details: ticket.details,
    })),
  };
}

function normalizeTakeoverPushStatus(payload: {
  title: string;
  body: string;
  readiness_label: string;
  fingerprint: string;
  active_devices: number;
  synced_devices: number;
  pending_devices: number;
  delivery_state: string;
  should_send: boolean;
  summary: string;
  recommended_action: string;
  auto_enabled: boolean;
  auto_ready: boolean;
  auto_cooldown_seconds: number;
  last_sent_at: string | null;
  last_sent_status: string | null;
  last_sent_fingerprint: string | null;
  last_preview_at: string | null;
  last_auto_run_at: string | null;
  last_auto_run_status: string | null;
}): TakeoverPushStatus {
  return {
    title: payload.title,
    body: payload.body,
    readinessLabel: payload.readiness_label,
    fingerprint: payload.fingerprint,
    activeDevices: payload.active_devices,
    syncedDevices: payload.synced_devices,
    pendingDevices: payload.pending_devices,
    deliveryState: payload.delivery_state,
    shouldSend: payload.should_send,
    summary: payload.summary,
    recommendedAction: payload.recommended_action,
    autoEnabled: payload.auto_enabled,
    autoReady: payload.auto_ready,
    autoCooldownSeconds: payload.auto_cooldown_seconds,
    lastSentAt: payload.last_sent_at,
    lastSentStatus: payload.last_sent_status,
    lastSentFingerprint: payload.last_sent_fingerprint,
    lastPreviewAt: payload.last_preview_at,
    lastAutoRunAt: payload.last_auto_run_at,
    lastAutoRunStatus: payload.last_auto_run_status,
  };
}

function normalizeIndustryResearchPushStatus(payload: {
  title: string;
  latest_title: string | null;
  latest_preview: string | null;
  latest_direction?: string | null;
  latest_timeline_stage?: string | null;
  latest_catalyst_title?: string | null;
  active_devices: number;
  delivery_state: string;
  auto_enabled: boolean;
  summary: string;
  recommended_action: string;
  last_sent_at: string | null;
  last_sent_status: string | null;
}): IndustryResearchPushStatus {
  return {
    title: payload.title,
    latestTitle: payload.latest_title,
    latestPreview: payload.latest_preview,
    latestDirection: payload.latest_direction ?? null,
    latestTimelineStage: payload.latest_timeline_stage ?? null,
    latestCatalystTitle: payload.latest_catalyst_title ?? null,
    activeDevices: payload.active_devices,
    deliveryState: payload.delivery_state,
    autoEnabled: payload.auto_enabled,
    summary: payload.summary,
    recommendedAction: payload.recommended_action,
    lastSentAt: payload.last_sent_at,
    lastSentStatus: payload.last_sent_status,
  };
}

function requireToken(token?: string): string {
  if (!token) {
    throw new Error('当前操作需要先登录');
  }

  return token;
}

export async function login(username: string, password: string): Promise<AuthSession> {
  return normalizeAuthSession(
    await request<{
      access_token: string;
      token_type: string;
      expires_at: string;
      user: {
        username: string;
        display_name: string;
        role: string;
      };
    }>('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    })
  );
}

export async function getMe(token: string): Promise<AppUser> {
  return normalizeAppUser(
    await request<{
      username: string;
      display_name: string;
      role: string;
    }>('/api/auth/me', { token })
  );
}

export async function getSystemStatus(token?: string): Promise<SystemStatus> {
  return normalizeSystemStatus(
    await request<{
      status: string;
      uptime_hours: number;
      health_score: number;
      today_signals: number;
      active_strategies: number;
      ooda_cycles: number;
      decision_accuracy: number;
    }>(appPath(token, '/system'), { token })
  );
}

export async function getOpsSummary(token?: string): Promise<OpsSummary> {
  return normalizeOpsSummary(
    await request<{
      service: string;
      version: string;
      started_at: string;
      uptime_seconds: number;
      ready: boolean;
      readiness_issues: string[];
      request_count: number;
      error_count: number;
      error_rate: number;
      avg_latency_ms: number;
      max_latency_ms: number;
      p95_latency_ms: number;
      last_error_at: string | null;
      last_error_path: string | null;
      websocket_connections: number;
      system_status: string;
      system_health_score: number;
      today_signals: number;
      active_strategies: number;
      data_status: {
        scorecard_records: number;
        trade_journal_records: number;
        signal_count: number;
        active_positions: number;
        feedback_items: number;
        push_devices: number;
      };
      routes: Array<{
        method: string;
        path: string;
        count: number;
        error_count: number;
        avg_latency_ms: number;
        max_latency_ms: number;
        last_status: number;
        last_seen_at: string | null;
      }>;
      recommendations: Array<{
        level: string;
        title: string;
        message: string;
      }>;
    }>(token ? '/api/app/ops/summary' : '/api/ops/summary', { token })
  );
}

export async function getLearning(token?: string): Promise<LearningProgress> {
  return normalizeLearningProgress(
    await request<{
      today_cycles: number;
      factor_adjustments: number;
      online_updates: number;
      experiments_running: number;
      new_factors_deployed: number;
      decision_accuracy: number;
    }>(appPath(token, '/learning'), { token })
  );
}

export async function getLearningAdvanceStatus(token?: string): Promise<LearningAdvanceStatus> {
  try {
    return normalizeLearningAdvanceStatus(
      await request<{
        status: string;
        in_progress: boolean;
        today_completed: boolean;
        last_started_at: string | null;
        current_run_started_at: string | null;
        last_completed_at: string | null;
        last_requested_by: string | null;
        stale_hours: number | null;
        health_status: string;
        summary: string;
        last_error: string | null;
        last_report_excerpt: string;
        ingested_signals: number;
        verified_signals: number;
        reviewed_decisions: number;
        checks: Array<{
          name: string;
          status: string;
          detail: string;
        }>;
        recommendations: string[];
      }>(appPath(token, '/learning/daily-advance'), { token })
    );
  } catch (error) {
    if (error instanceof Error && error.message.includes('404')) {
      return {
        status: 'pending',
        inProgress: false,
        todayCompleted: false,
        lastStartedAt: null,
        currentRunStartedAt: null,
        lastCompletedAt: null,
        lastRequestedBy: null,
        staleHours: null,
        healthStatus: 'unknown',
        summary: '当前服务还没加载日日精进接口，先保持现有链路可用。',
        lastError: null,
        lastReportExcerpt: '',
        ingestedSignals: 0,
        verifiedSignals: 0,
        reviewedDecisions: 0,
        checks: [],
        recommendations: ['服务端升级后，这里会显示每日学习的完整闭环状态。'],
      };
    }

    throw error;
  }
}

export async function runLearningAdvance(token?: string): Promise<LearningAdvanceStatus> {
  const authToken = requireToken(token);

  return normalizeLearningAdvanceStatus(
    await request<{
      status: string;
      in_progress: boolean;
      today_completed: boolean;
      last_started_at: string | null;
      current_run_started_at: string | null;
      last_completed_at: string | null;
      last_requested_by: string | null;
      stale_hours: number | null;
      health_status: string;
      summary: string;
      last_error: string | null;
      last_report_excerpt: string;
      ingested_signals: number;
      verified_signals: number;
      reviewed_decisions: number;
      checks: Array<{
        name: string;
        status: string;
        detail: string;
      }>;
      recommendations: string[];
    }>('/api/app/learning/daily-advance', {
      method: 'POST',
      token: authToken,
    })
  );
}

export async function getSignals(token?: string): Promise<Signal[]> {
  const payload = await request<
    Array<{
      id: string;
      code: string;
      name: string;
      strategy: string;
      score: number;
      price: number;
      change_pct: number;
      buy_price: number;
      stop_loss: number;
      target_price: number;
      risk_reward: number;
      timestamp: string;
      consensus_count: number;
    }>
  >(appPath(token, '/signals?days=1'), { token });

  return payload.map(normalizeSignal);
}

export async function getStrongMoves(token?: string): Promise<StrongMoveCandidate[]> {
  const payload = await request<
    Array<{
      id: string;
      signal_id: string;
      code: string;
      name: string;
      strategy: string;
      setup_label: string;
      conviction: 'low' | 'medium' | 'high';
      composite_score: number;
      continuation_score: number;
      swing_score: number;
      strategy_win_rate: number;
      price: number;
      buy_price: number;
      stop_loss: number;
      target_price: number;
      risk_reward: number;
      timestamp: string;
      thesis: string;
      next_step: string;
      reasons: string[];
    }>
  >(appPath(token, '/strong-moves?days=1&limit=5'), { token });

  return payload.map(normalizeStrongMoveCandidate);
}

export async function getThemeRadar(token?: string): Promise<ThemeRadarItem[]> {
  const payload = await request<
    Array<{
      id: string;
      sector: string;
      theme_type: string;
      change_pct: number;
      score: number;
      intensity: string;
      timestamp: string;
      narrative: string;
      action: string;
      risk_note: string;
      message_hint: string | null;
      linked_signal_id: string | null;
      linked_code: string | null;
      linked_name: string | null;
      linked_setup_label: string | null;
      followers: Array<{
        code: string;
        name: string;
        change_pct: number;
        label: string;
        buy_price: number;
        stop_loss: number;
        target_price: number;
        risk_reward: number;
      }>;
    }>
  >(appPath(token, '/theme-radar?limit=3'), { token });

  return payload.map(normalizeThemeRadarItem);
}

export async function getThemeStage(token?: string): Promise<ThemeStageItem[]> {
  const payload = await request<
    Array<{
      id: string;
      sector: string;
      theme_type: string;
      intensity: string;
      stage_label: string;
      participation_label: string;
      direction_score: number;
      policy_event_score: number;
      trend_score: number;
      attention_score: number;
      capital_preference_score: number;
      stage_score: number;
      linked_signal_id: string | null;
      linked_code: string | null;
      linked_name: string | null;
      linked_setup_label: string | null;
      summary: string;
      action: string;
      risk_note: string;
      drivers: string[];
    }>
  >(appPath(token, '/theme-stage?limit=3'), { token });

  return payload.map(normalizeThemeStageItem);
}

export async function getPolicyWatch(token?: string): Promise<PolicyWatchItem[]> {
  const payload = await request<
    Array<{
      id: string;
      direction: string;
      policy_bucket: string;
      focus_sector: string;
      stage_label: string;
      participation_label: string;
      industry_phase: string;
      direction_score: number;
      policy_score: number;
      trend_score: number;
      attention_score: number;
      capital_preference_score: number;
      linked_signal_id: string | null;
      linked_code: string | null;
      linked_name: string | null;
      linked_setup_label: string | null;
      summary: string;
      action: string;
      risk_note: string;
      phase_summary: string;
      demand_drivers: string[];
      supply_drivers: string[];
      upstream: string[];
      midstream: string[];
      downstream: string[];
      milestones: string[];
      transmission_paths: string[];
      drivers: string[];
    }>
  >(appPath(token, '/policy-watch?limit=3'), {
    token,
  });

  return payload.map(normalizePolicyWatchItem);
}

export async function getIndustryCapital(token?: string): Promise<IndustryCapitalDirection[]> {
  const payload = await request<
    Array<{
      id: string;
      direction: string;
      policy_bucket: string;
      focus_sector: string;
      strategic_label: string;
      industry_phase: string;
      participation_label: string;
      business_horizon: string;
      capital_horizon: string;
      strategic_score: number;
      policy_score: number;
      demand_score: number;
      supply_score: number;
      capital_preference_score: number;
      linked_signal_id: string | null;
      linked_code: string | null;
      linked_name: string | null;
      linked_setup_label: string | null;
      summary: string;
      business_action: string;
      capital_action: string;
      risk_note: string;
      upstream: string[];
      midstream: string[];
      downstream: string[];
      demand_drivers: string[];
      supply_drivers: string[];
      milestones: string[];
      transmission_paths: string[];
      opportunities: string[];
      official_sources: string[];
      official_watchpoints: string[];
      business_checklist: string[];
      capital_checklist: string[];
      official_cards: Array<{
        title: string;
        source: string;
        excerpt: string;
        why_it_matters: string;
        next_watch: string;
      }>;
      official_documents: string[];
      timeline_checkpoints: string[];
      cooperation_targets: string[];
      cooperation_modes: string[];
      company_watchlist: Array<{
        code: string;
        name: string;
        role: string;
        chain_position: string;
        tracking_reason: string;
        action: string;
        tracking_score?: number;
        priority_label?: string;
        market_alignment?: string;
        next_check?: string;
        linked_setup_label?: string | null;
        linked_source?: string | null;
      }>;
      research_targets: string[];
      validation_signals: string[];
      drivers: string[];
    }>
  >(appPath(token, '/industry-capital?limit=3'), {
    token,
  });

  return payload.map(normalizeIndustryCapitalDirection);
}

export async function getIndustryCapitalDetail(
  directionId: string,
  token?: string
): Promise<IndustryCapitalDirection> {
  const payload = await request<{
    id: string;
    direction: string;
    policy_bucket: string;
    focus_sector: string;
    strategic_label: string;
    industry_phase: string;
    participation_label: string;
    business_horizon: string;
    capital_horizon: string;
    strategic_score: number;
    policy_score: number;
    demand_score: number;
    supply_score: number;
    capital_preference_score: number;
    linked_signal_id: string | null;
    linked_code: string | null;
    linked_name: string | null;
    linked_setup_label: string | null;
    summary: string;
    business_action: string;
    capital_action: string;
    risk_note: string;
    upstream: string[];
    midstream: string[];
    downstream: string[];
    demand_drivers: string[];
    supply_drivers: string[];
    milestones: string[];
    transmission_paths: string[];
    opportunities: string[];
    official_sources: string[];
    official_watchpoints: string[];
    business_checklist: string[];
    capital_checklist: string[];
    official_cards: Array<{
      title: string;
      source: string;
      excerpt: string;
      why_it_matters: string;
      next_watch: string;
    }>;
    official_documents: string[];
    timeline_checkpoints: string[];
    cooperation_targets: string[];
    cooperation_modes: string[];
    company_watchlist: Array<{
      code: string;
      name: string;
      role: string;
      chain_position: string;
      tracking_reason: string;
      action: string;
      tracking_score?: number;
      priority_label?: string;
      market_alignment?: string;
      next_check?: string;
      linked_setup_label?: string | null;
      linked_source?: string | null;
    }>;
    research_targets: string[];
    validation_signals: string[];
    drivers: string[];
  }>(appPath(token, `/industry-capital/${encodeURIComponent(directionId)}`), {
    token,
  });

  return normalizeIndustryCapitalDirection(payload);
}

export async function getIndustryCapitalResearchLog(
  directionId: string,
  token?: string
): Promise<IndustryCapitalResearchItem[]> {
  const payload = await request<
    Array<{
      id: string;
      direction_id: string;
      direction: string;
      title: string;
      note: string;
      source: string;
      status: string;
      company_code: string | null;
      company_name: string | null;
      created_at: string;
      updated_at: string;
      author: string;
    }>
  >(appPath(token, `/industry-capital/${encodeURIComponent(directionId)}/research-log`), {
    token,
  });

  return payload.map(normalizeIndustryCapitalResearchItem);
}

export async function submitIndustryCapitalResearchLog(
  directionId: string,
  input: {
    title: string;
    note: string;
    source: string;
    status: string;
    companyCode?: string | null;
    companyName?: string | null;
  },
  token?: string
): Promise<IndustryCapitalResearchSubmissionResult> {
  const payload = await request<{
    success: boolean;
    message: string;
    total_items: number;
    item: {
      id: string;
      direction_id: string;
      direction: string;
      title: string;
      note: string;
      source: string;
      status: string;
      company_code: string | null;
      company_name: string | null;
      created_at: string;
      updated_at: string;
      author: string;
    };
  }>(appPath(token, `/industry-capital/${encodeURIComponent(directionId)}/research-log`), {
    method: 'POST',
    token,
    body: {
      title: input.title,
      note: input.note,
      source: input.source,
      status: input.status,
      company_code: input.companyCode ?? null,
      company_name: input.companyName ?? null,
    },
  });

  return {
    success: payload.success,
    message: payload.message,
    totalItems: payload.total_items,
    item: normalizeIndustryCapitalResearchItem(payload.item),
  };
}

export async function getCompositePicks(token?: string): Promise<CompositePick[]> {
  const payload = await request<
    Array<{
      id: string;
      signal_id: string;
      code: string;
      name: string;
      strategy: string;
      theme_sector: string | null;
      theme_intensity: string | null;
      setup_label: string;
      conviction: 'low' | 'medium' | 'high';
      composite_score: number;
      strategy_score: number;
      capital_score: number;
      theme_score: number;
      event_score?: number;
      event_bias?: string;
      event_summary?: string | null;
      event_matched_sector?: string | null;
      execution_score: number;
      first_position_pct: number;
      price: number;
      buy_price: number;
      stop_loss: number;
      target_price: number;
      risk_reward: number;
      timestamp: string;
      thesis: string;
      action: string;
      reasons: string[];
    }>
  >(appPath(token, '/composite-picks?days=1&limit=5'), { token });

  return payload.map(normalizeCompositePick);
}

export async function getPositioningPlan(token?: string): Promise<PositioningPlan> {
  return normalizePositioningPlan(
    await request<{
      mode: string;
      regime: string;
      regime_score: number;
      event_bias?: string;
      event_score?: number;
      event_summary?: string | null;
      event_focus_sector?: string | null;
      current_exposure_pct: number;
      target_exposure_pct: number;
      deployable_exposure_pct: number;
      cash_balance: number;
      total_assets: number;
      deployable_cash: number;
      current_positions: number;
      available_slots: number;
      max_positions: number;
      first_entry_position_pct: number;
      max_single_position_pct: number;
      max_theme_exposure_pct: number;
      top_theme: string | null;
      focus: string;
      reasons: string[];
      actions: string[];
      deployments: Array<{
        code: string;
        name: string;
        setup_label: string;
        suggested_position_pct: number;
        suggested_amount: number;
        theme_sector: string | null;
        reason: string;
      }>;
    }>(appPath(token, '/positioning-plan?days=1'), { token })
  );
}

export async function getCompositeReplay(token?: string): Promise<CompositeReplayItem[]> {
  const payload = await request<
    Array<{
      id: string;
      trade_date: string;
      signal_id: string;
      code: string;
      name: string;
      strategy: string;
      setup_label: string;
      conviction: 'low' | 'medium' | 'high';
      composite_score: number;
      first_position_pct: number;
      theme_sector: string | null;
      review_label: string;
      verified_days: number;
      t1_return_pct: number | null;
      t3_return_pct: number | null;
      t5_return_pct: number | null;
      outcome_summary: string;
      review: string;
    }>
  >(appPath(token, '/composite-replay?days=5&per_day=1'), { token });

  return payload.map(normalizeCompositeReplayItem);
}

export async function getCompositeCompare(token?: string, days = 5): Promise<RecommendationCompareSnapshot> {
  return normalizeRecommendationCompareSnapshot(
    await request<{
      composite: {
        label: string;
        sample_days: number;
        observed_t1_days: number;
        observed_t3_days: number;
        observed_t5_days: number;
        avg_t1_return_pct: number | null;
        avg_t3_return_pct: number | null;
        avg_t5_return_pct: number | null;
        t1_win_rate: number | null;
        t3_win_rate: number | null;
        t5_win_rate: number | null;
      };
      baseline: {
        label: string;
        sample_days: number;
        observed_t1_days: number;
        observed_t3_days: number;
        observed_t5_days: number;
        avg_t1_return_pct: number | null;
        avg_t3_return_pct: number | null;
        avg_t5_return_pct: number | null;
        t1_win_rate: number | null;
        t3_win_rate: number | null;
        t5_win_rate: number | null;
      };
      advantage: string[];
      readiness: {
        status: string;
        label: string;
        confidence_score: number;
        summary: string;
        recommended_action: string;
        conditions: string[];
      };
      days: Array<{
        trade_date: string;
        composite_signal_id: string | null;
        composite_code: string | null;
        composite_name: string | null;
        composite_score: number | null;
        composite_t1_return_pct: number | null;
        composite_t3_return_pct: number | null;
        composite_t5_return_pct: number | null;
        baseline_signal_id: string | null;
        baseline_code: string | null;
        baseline_name: string | null;
        baseline_score: number | null;
        baseline_t1_return_pct: number | null;
        baseline_t3_return_pct: number | null;
        baseline_t5_return_pct: number | null;
        winner_label: string;
        summary: string;
      }>;
    }>(appPath(token, `/composite-compare?days=${days}`), { token })
  );
}

export async function getSignalDetail(id: string, token?: string): Promise<SignalDetail> {
  return normalizeSignalDetail(
    await request<{
      id: string;
      code: string;
      name: string;
      strategy: string;
      strategies: string[];
      score: number;
      price: number;
      change_pct: number;
      high: number;
      low: number;
      volume: number;
      turnover: number;
      buy_price: number;
      stop_loss: number;
      target_price: number;
      risk_reward: number;
      timestamp: string;
      consensus_count: number;
      factor_scores: Record<string, number>;
      regime: string;
      regime_score: number;
      entry_guide: {
        mode: string;
        summary: string;
        action: string;
        composite_score: number;
        setup_label: string | null;
        theme_sector: string | null;
        sector_bucket: string | null;
        theme_alignment: string;
        event_bias: string;
        event_score: number;
        event_summary: string | null;
        recommended_first_position_pct: number;
        suggested_amount: number;
        suggested_quantity: number;
        total_assets: number;
        max_single_position_pct: number;
        max_theme_exposure_pct: number;
        target_exposure_pct: number;
        deployable_cash: number;
        current_theme_exposure_pct: number;
        projected_theme_exposure_pct: number;
        concentration_summary: string | null;
        warnings: string[];
      };
    }>(appPath(token, `/signals/${id}`), { token })
  );
}

export async function getPositions(token?: string): Promise<Position[]> {
  const payload = await request<
    Array<{
      code: string;
      name: string;
      quantity: number;
      cost_price: number;
      current_price: number;
      market_value: number;
      profit_loss: number;
      profit_loss_pct: number;
      stop_loss: number;
      take_profit: number;
      hold_days: number;
      strategy: string;
    }>
  >(appPath(token, '/positions'), { token });

  return payload.map(normalizePosition);
}

export async function getPositionDetail(code: string, token?: string): Promise<PositionDetail> {
  return normalizePositionDetail(
    await request<{
      code: string;
      name: string;
      quantity: number;
      cost_price: number;
      current_price: number;
      market_value: number;
      profit_loss: number;
      profit_loss_pct: number;
      stop_loss: number;
      take_profit: number;
      hold_days: number;
      strategy: string;
      buy_time: string;
      high_price: number;
      low_price: number;
      trailing_stop: boolean;
      trailing_trigger_price: number;
      trades: Array<{
        time: string;
        type: string;
        price: number;
        quantity: number;
        reason: string;
      }>;
      position_guide: {
        mode: string;
        summary: string;
        next_action: string;
        event_bias: string;
        event_score: number;
        event_summary: string | null;
        top_theme: string | null;
        sector_bucket: string | null;
        theme_alignment: string;
        can_add: boolean;
        current_exposure_pct: number;
        target_exposure_pct: number;
        position_pct: number;
        current_theme_exposure_pct: number;
        max_theme_exposure_pct: number;
        suggested_stop_loss: number;
        suggested_take_profit: number;
        suggested_reduce_pct: number;
        suggested_reduce_quantity: number;
        concentration_summary: string | null;
        warnings: string[];
      };
    }>(appPath(token, `/positions/${code}`), { token })
  );
}

export async function getKlineBars(code: string, days = 60, token?: string): Promise<KlineBar[]> {
  const payload = await request<
    Array<{
      date: string;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
      turnover: number;
    }>
  >(appPath(token, `/market/${code}/kline?days=${days}`), { token });

  return payload.map(normalizeKlineBar);
}

export async function getAlerts(token?: string): Promise<RiskAlert[]> {
  const payload = await request<
    Array<{
      id: string;
      level: 'critical' | 'warning' | 'info';
      title: string;
      message: string;
      source: string;
      source_id: string;
      created_at: string;
      route: string | null;
    }>
  >(appPath(token, '/alerts'), { token });

  return payload.map(normalizeRiskAlert);
}

export async function getAppMessages(token?: string, limit = 30): Promise<AppMessage[]> {
  const payload = await request<
    Array<{
      id: string;
      title: string;
      body: string;
      preview: string;
      level: string;
      channel: string;
      created_at: string;
      route?: string | null;
    }>
  >(appPath(token, `/messages?limit=${limit}`), { token });

  return payload.map(normalizeAppMessage);
}

export async function getActionBoard(token?: string, limit = 6): Promise<ActionBoardItem[]> {
  const payload = await request<
    Array<{
      id: string;
      kind: string;
      level: 'critical' | 'warning' | 'info';
      title: string;
      summary: string;
      action_label: string;
      route: string | null;
      source: string;
      source_id: string;
      created_at: string;
    }>
  >(appPath(token, `/action-board?limit=${limit}`), { token });

  return payload.map(normalizeActionBoardItem);
}

export async function getStrategies(token?: string): Promise<StrategyPerformance[]> {
  const payload = await request<
    Array<{
      id: string;
      name: string;
      status: string;
      win_rate: number;
      avg_return: number;
      signal_count: number;
      last_signal_time: string | null;
    }>
  >(appPath(token, '/strategies'), { token });

  return payload.map(normalizeStrategyPerformance);
}

export async function getStockDiagnosis(code: string, token?: string): Promise<StockDiagnosis> {
  return normalizeStockDiagnosis(
    await request<{
      code: string;
      name: string;
      price: number;
      as_of: string;
      total_score: number;
      verdict: string;
      direction: string;
      signal_direction: string;
      actionable: boolean;
      confidence_label: string;
      advice: string;
      report_text: string;
      stop_loss: number | null;
      take_profit: number | null;
      scores: Record<string, number>;
      details: Record<string, string[]>;
      regime: string;
      regime_score: number;
      regime_summary: string;
      health_bias: string;
      in_portfolio: boolean;
      position_quantity: number;
      position_profit_loss_pct: number | null;
      in_signal_board: boolean;
      top_strategy: string | null;
      top_strategy_win_rate: number | null;
      top_strategy_avg_return: number | null;
      risk_flags: string[];
      next_actions: string[];
    }>(appPath(token, `/diagnosis/${code}`), { token })
  );
}

export async function getPortfolioHistory(token?: string): Promise<PortfolioHistory> {
  const payload = await request<{
    realized_profit_loss: number;
    closed_positions: Array<{
      code: string;
      name: string;
      quantity: number;
      cost_price: number;
      close_price: number;
      realized_profit_loss: number;
      realized_profit_loss_pct: number;
      hold_days: number;
      strategy: string;
      buy_time: string;
      closed_at: string;
      close_reason: string;
      status: string;
      trades: Array<{
        time: string;
        type: string;
        price: number;
        quantity: number;
        reason: string;
      }>;
    }>;
    recent_trades: Array<{
      id: string;
      code: string;
      name: string;
      strategy: string;
      time: string;
      type: string;
      price: number;
      quantity: number;
      reason: string;
      status: string;
    }>;
  }>(appPath(token, '/portfolio/history'), { token });

  return {
    realizedProfitLoss: payload.realized_profit_loss,
    closedPositions: payload.closed_positions.map(normalizeClosedPosition),
    recentTrades: payload.recent_trades.map(normalizeTradeLedgerEntry),
  };
}

export async function getFeedbackItems(token?: string): Promise<FeedbackItem[]> {
  const authToken = requireToken(token);
  const payload = await request<
    Array<{
      id: string;
      username: string;
      title: string;
      message: string;
      category: string;
      priority: string;
      decision_status: string;
      owner_note: string;
      source_type: string;
      source_id: string;
      source_route: string;
      created_at: string;
      updated_at: string;
      decided_at: string | null;
      decided_by: string | null;
    }>
  >('/api/app/feedback', { token: authToken });

  return payload.map(normalizeFeedbackItem);
}

export async function submitFeedback(
  payload: FeedbackSubmissionPayload,
  token?: string
): Promise<FeedbackSubmissionResult> {
  const authToken = requireToken(token);
  return normalizeFeedbackSubmissionResult(
    await request<{
      success: boolean;
      message: string;
      item: {
        id: string;
        username: string;
        title: string;
        message: string;
        category: string;
        priority: string;
        decision_status: string;
        owner_note: string;
        source_type: string;
        source_id: string;
        source_route: string;
        created_at: string;
        updated_at: string;
        decided_at: string | null;
        decided_by: string | null;
      };
      pending_count: number;
    }>('/api/app/feedback', {
      token: authToken,
      method: 'POST',
      body: {
        title: payload.title,
        message: payload.message,
        category: payload.category,
        priority: payload.priority,
        source_type: payload.sourceType,
        source_id: payload.sourceId,
        source_route: payload.sourceRoute,
      },
    })
  );
}

export async function decideFeedback(
  feedbackId: string,
  payload: FeedbackDecisionPayload,
  token?: string
): Promise<FeedbackDecisionResult> {
  const authToken = requireToken(token);
  return normalizeFeedbackDecisionResult(
    await request<{
      success: boolean;
      message: string;
      item: {
        id: string;
        username: string;
        title: string;
        message: string;
        category: string;
        priority: string;
        decision_status: string;
        owner_note: string;
        source_type: string;
        source_id: string;
        source_route: string;
        created_at: string;
        updated_at: string;
        decided_at: string | null;
        decided_by: string | null;
      };
    }>(`/api/app/feedback/${feedbackId}/decision`, {
      token: authToken,
      method: 'PATCH',
      body: {
        decision: payload.decision,
        owner_note: payload.ownerNote,
      },
    })
  );
}

export async function getHomeSnapshot(token?: string): Promise<HomeSnapshot> {
  const [system, learning, dailyAdvance, positioningPlan, positions, strategies, signals, compositePicks, compositeCompare, policyWatch, industryCapital, themeStages, strongMoves, alerts, messages, actionBoard] = await Promise.all([
    getSystemStatus(token),
    getLearning(token),
    getLearningAdvanceStatus(token),
    getPositioningPlan(token),
    getPositions(token),
    getStrategies(token),
    getSignals(token),
    getCompositePicks(token),
    getCompositeCompare(token),
    getPolicyWatch(token),
    getIndustryCapital(token),
    getThemeStage(token),
    getStrongMoves(token),
    getAlerts(token),
    getAppMessages(token, 10),
    getActionBoard(token, 6),
  ]);

  return {
    system,
    learning,
    dailyAdvance,
    positioningPlan,
    positions,
    strategies: strategies.sort((a, b) => b.signalCount - a.signalCount),
    signals,
    compositePicks,
    compositeCompare,
    policyWatch,
    industryCapital,
    themeStages,
    strongMoves,
    alerts,
    messages,
    actionBoard,
  };
}

export async function getBrainSnapshot(token?: string): Promise<BrainSnapshot> {
  const [system, learning, strategies, signals, compositePicks, compositeCompare, themeRadar, policyWatch, industryCapital, themeStages, ops, dailyAdvance] = await Promise.all([
    getSystemStatus(token),
    getLearning(token),
    getStrategies(token),
    getSignals(token),
    getCompositePicks(token),
    getCompositeCompare(token),
    getThemeRadar(token),
    getPolicyWatch(token),
    getIndustryCapital(token),
    getThemeStage(token),
    getOpsSummary(token),
    getLearningAdvanceStatus(token),
  ]);

  return {
    system,
    learning,
    strategies: strategies.filter((item) => item.signalCount > 0).slice(0, 8),
    signals,
    compositePicks,
    compositeCompare,
    themeRadar,
    policyWatch,
    industryCapital,
    themeStages,
    ops,
    dailyAdvance,
  };
}

export async function openSignalPosition(
  signalId: string,
  payload: OpenSignalPositionPayload,
  token?: string
): Promise<PortfolioActionResult> {
  const authToken = requireToken(token);

  return normalizePortfolioActionResult(
    await request<{
      success: boolean;
      action: 'open' | 'risk_update' | 'close';
      code: string;
      name: string;
      message: string;
      executed_at: string;
      quantity: number;
      execution_price: number;
      cash_balance: number;
      total_assets: number;
      position: {
        code: string;
        name: string;
        quantity: number;
        cost_price: number;
        current_price: number;
        market_value: number;
        profit_loss: number;
        profit_loss_pct: number;
        stop_loss: number;
        take_profit: number;
        hold_days: number;
        strategy: string;
        buy_time: string;
        high_price: number;
        low_price: number;
        trailing_stop: boolean;
        trailing_trigger_price: number;
        trades: Array<{
          time: string;
          type: string;
          price: number;
          quantity: number;
          reason: string;
        }>;
        position_guide: {
          mode: string;
          summary: string;
          next_action: string;
          event_bias: string;
          event_score: number;
          event_summary: string | null;
          top_theme: string | null;
          sector_bucket: string | null;
          theme_alignment: string;
          can_add: boolean;
          current_exposure_pct: number;
          target_exposure_pct: number;
          position_pct: number;
          current_theme_exposure_pct: number;
          max_theme_exposure_pct: number;
          suggested_stop_loss: number;
          suggested_take_profit: number;
          suggested_reduce_pct: number;
          suggested_reduce_quantity: number;
          concentration_summary: string | null;
          warnings: string[];
        };
      } | null;
      realized_profit_loss: number | null;
    }>(`/api/app/signals/${signalId}/open`, {
      token: authToken,
      method: 'POST',
      body: {
        quantity: payload.quantity,
        price: payload.price,
        stop_loss: payload.stopLoss,
        take_profit: payload.takeProfit,
      },
    })
  );
}

export async function updatePositionRisk(
  code: string,
  payload: PositionRiskUpdatePayload,
  token?: string
): Promise<PortfolioActionResult> {
  const authToken = requireToken(token);

  return normalizePortfolioActionResult(
    await request<{
      success: boolean;
      action: 'open' | 'risk_update' | 'close';
      code: string;
      name: string;
      message: string;
      executed_at: string;
      quantity: number;
      execution_price: number;
      cash_balance: number;
      total_assets: number;
      position: {
        code: string;
        name: string;
        quantity: number;
        cost_price: number;
        current_price: number;
        market_value: number;
        profit_loss: number;
        profit_loss_pct: number;
        stop_loss: number;
        take_profit: number;
        hold_days: number;
        strategy: string;
        buy_time: string;
        high_price: number;
        low_price: number;
        trailing_stop: boolean;
        trailing_trigger_price: number;
        trades: Array<{
          time: string;
          type: string;
          price: number;
          quantity: number;
          reason: string;
        }>;
        position_guide: {
          mode: string;
          summary: string;
          next_action: string;
          event_bias: string;
          event_score: number;
          event_summary: string | null;
          top_theme: string | null;
          sector_bucket: string | null;
          theme_alignment: string;
          can_add: boolean;
          current_exposure_pct: number;
          target_exposure_pct: number;
          position_pct: number;
          current_theme_exposure_pct: number;
          max_theme_exposure_pct: number;
          suggested_stop_loss: number;
          suggested_take_profit: number;
          suggested_reduce_pct: number;
          suggested_reduce_quantity: number;
          concentration_summary: string | null;
          warnings: string[];
        };
      } | null;
      realized_profit_loss: number | null;
    }>(`/api/app/positions/${code}/risk`, {
      token: authToken,
      method: 'PATCH',
      body: {
        stop_loss: payload.stopLoss,
        take_profit: payload.takeProfit,
        trailing_stop: payload.trailingStop,
        trailing_trigger_price: payload.trailingTriggerPrice,
      },
    })
  );
}

export async function closePosition(
  code: string,
  payload: ClosePositionPayload = {},
  token?: string
): Promise<PortfolioActionResult> {
  const authToken = requireToken(token);

  return normalizePortfolioActionResult(
    await request<{
      success: boolean;
      action: 'open' | 'risk_update' | 'close';
      code: string;
      name: string;
      message: string;
      executed_at: string;
      quantity: number;
      execution_price: number;
      cash_balance: number;
      total_assets: number;
      position: {
        code: string;
        name: string;
        quantity: number;
        cost_price: number;
        current_price: number;
        market_value: number;
        profit_loss: number;
        profit_loss_pct: number;
        stop_loss: number;
        take_profit: number;
        hold_days: number;
        strategy: string;
        buy_time: string;
        high_price: number;
        low_price: number;
        trailing_stop: boolean;
        trailing_trigger_price: number;
        trades: Array<{
          time: string;
          type: string;
          price: number;
          quantity: number;
          reason: string;
        }>;
        position_guide: {
          mode: string;
          summary: string;
          next_action: string;
          event_bias: string;
          event_score: number;
          event_summary: string | null;
          top_theme: string | null;
          sector_bucket: string | null;
          theme_alignment: string;
          can_add: boolean;
          current_exposure_pct: number;
          target_exposure_pct: number;
          position_pct: number;
          current_theme_exposure_pct: number;
          max_theme_exposure_pct: number;
          suggested_stop_loss: number;
          suggested_take_profit: number;
          suggested_reduce_pct: number;
          suggested_reduce_quantity: number;
          concentration_summary: string | null;
          warnings: string[];
        };
      } | null;
      realized_profit_loss: number | null;
    }>(`/api/app/positions/${code}/close`, {
      token: authToken,
      method: 'POST',
      body: {
        price: payload.price,
        reason: payload.reason,
        quantity: payload.quantity,
      },
    })
  );
}

export async function getPushDevices(token?: string): Promise<PushDevice[]> {
  const authToken = requireToken(token);
  const payload = await request<
    Array<{
      username: string;
      platform: string;
      expo_push_token: string;
      device_name: string;
      app_version: string;
      permission_state: string;
      is_physical_device: boolean | null;
      status: string;
      last_seen_at: string;
      last_push_at: string | null;
      last_push_status: string | null;
      last_error: string | null;
    }>
  >('/api/app/push/devices', { token: authToken });

  return payload.map(normalizePushDevice);
}

export async function getTakeoverPushStatus(token?: string): Promise<TakeoverPushStatus> {
  const authToken = requireToken(token);
  const payload = await request<{
    title: string;
    body: string;
    readiness_label: string;
    fingerprint: string;
    active_devices: number;
    synced_devices: number;
    pending_devices: number;
    delivery_state: string;
    should_send: boolean;
    summary: string;
    recommended_action: string;
    auto_enabled: boolean;
    auto_ready: boolean;
    auto_cooldown_seconds: number;
    last_sent_at: string | null;
    last_sent_status: string | null;
    last_sent_fingerprint: string | null;
    last_preview_at: string | null;
    last_auto_run_at: string | null;
    last_auto_run_status: string | null;
  }>('/api/app/push/takeover/status', { token: authToken });

  return normalizeTakeoverPushStatus(payload);
}

export async function getIndustryResearchPushStatus(
  token?: string
): Promise<IndustryResearchPushStatus> {
  const authToken = requireToken(token);
  const payload = await request<{
    title: string;
    latest_title: string | null;
    latest_preview: string | null;
    active_devices: number;
    delivery_state: string;
    auto_enabled: boolean;
    summary: string;
    recommended_action: string;
    last_sent_at: string | null;
    last_sent_status: string | null;
  }>('/api/app/push/industry-research/status', { token: authToken });

  return normalizeIndustryResearchPushStatus(payload);
}

export async function registerPushDevice(
  payload: PushRegistrationPayload,
  token?: string
): Promise<PushRegistrationResult> {
  const authToken = requireToken(token);

  return normalizePushRegistrationResult(
    await request<{
      success: boolean;
      message: string;
      device: {
        username: string;
        platform: string;
        expo_push_token: string;
        device_name: string;
        app_version: string;
        permission_state: string;
        is_physical_device: boolean | null;
        status: string;
        last_seen_at: string;
        last_push_at: string | null;
        last_push_status: string | null;
        last_error: string | null;
      };
      active_devices: number;
      takeover_dispatch: {
        success: boolean;
        dry_run: boolean;
        targeted_devices: number;
        sent_devices: number;
        failed_devices: number;
        tickets: Array<{
          expo_push_token: string;
          status: string;
          ticket_id: string | null;
          message: string | null;
          details: string | null;
        }>;
      } | null;
    }>('/api/app/push/register', {
      token: authToken,
      method: 'POST',
      body: {
        expo_push_token: payload.expoPushToken,
        platform: payload.platform,
        device_name: payload.deviceName,
        app_version: payload.appVersion,
        permission_state: payload.permissionState,
        is_physical_device: payload.isPhysicalDevice,
      },
    })
  );
}

export async function sendPushTest(
  payload: PushTestPayload = {},
  token?: string
): Promise<PushDispatchResult> {
  const authToken = requireToken(token);

  return normalizePushDispatchResult(
    await request<{
      success: boolean;
      dry_run: boolean;
      targeted_devices: number;
      sent_devices: number;
      failed_devices: number;
      tickets: Array<{
        expo_push_token: string;
        status: string;
        ticket_id: string | null;
        message: string | null;
        details: string | null;
      }>;
    }>('/api/app/push/test', {
      token: authToken,
      method: 'POST',
      body: {
        title: payload.title,
        body: payload.body,
        route: payload.route,
        dry_run: payload.dryRun,
        target_token: payload.targetToken,
      },
    })
  );
}

export async function sendTakeoverPush(
  payload: PushTakeoverPayload = {},
  token?: string
): Promise<PushDispatchResult> {
  const authToken = requireToken(token);

  return normalizePushDispatchResult(
    await request<{
      success: boolean;
      dry_run: boolean;
      targeted_devices: number;
      sent_devices: number;
      failed_devices: number;
      tickets: Array<{
        expo_push_token: string;
        status: string;
        ticket_id: string | null;
        message: string | null;
        details: string | null;
      }>;
    }>('/api/app/push/takeover', {
      token: authToken,
      method: 'POST',
      body: {
        dry_run: payload.dryRun,
        target_token: payload.targetToken,
        force: payload.force,
      },
    })
  );
}

export async function updateTakeoverPushSettings(
  autoEnabled: boolean,
  token?: string
): Promise<TakeoverPushStatus> {
  const authToken = requireToken(token);
  const payload = await request<{
    title: string;
    body: string;
    readiness_label: string;
    fingerprint: string;
    active_devices: number;
    synced_devices: number;
    pending_devices: number;
    delivery_state: string;
    should_send: boolean;
    summary: string;
    recommended_action: string;
    auto_enabled: boolean;
    auto_ready: boolean;
    auto_cooldown_seconds: number;
    last_sent_at: string | null;
    last_sent_status: string | null;
    last_sent_fingerprint: string | null;
    last_preview_at: string | null;
    last_auto_run_at: string | null;
    last_auto_run_status: string | null;
  }>('/api/app/push/takeover/settings', {
    token: authToken,
    method: 'PATCH',
    body: { auto_enabled: autoEnabled },
  });

  return normalizeTakeoverPushStatus(payload);
}

export async function runTakeoverPushAuto(
  payload: PushTakeoverPayload = {},
  token?: string
): Promise<PushDispatchResult> {
  const authToken = requireToken(token);

  return normalizePushDispatchResult(
    await request<{
      success: boolean;
      dry_run: boolean;
      targeted_devices: number;
      sent_devices: number;
      failed_devices: number;
      tickets: Array<{
        expo_push_token: string;
        status: string;
        ticket_id: string | null;
        message: string | null;
        details: string | null;
      }>;
    }>('/api/app/push/takeover/auto-run', {
      token: authToken,
      method: 'POST',
      body: {
        force: payload.force,
      },
    })
  );
}
