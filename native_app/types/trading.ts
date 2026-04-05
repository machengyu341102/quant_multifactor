export interface AppUser {
  username: string;
  displayName: string;
  role: string;
}

export interface AuthSession {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
  user: AppUser;
}

export interface SystemStatus {
  status: string;
  uptimeHours: number;
  healthScore: number;
  todaySignals: number;
  activeStrategies: number;
  oodaCycles: number;
  decisionAccuracy: number;
}

export interface StrategyPerformance {
  id: string;
  name: string;
  status: string;
  winRate: number;
  avgReturn: number;
  signalCount: number;
  lastSignalTime: string | null;
}

export interface Signal {
  id: string;
  code: string;
  name: string;
  strategy: string;
  score: number;
  price: number;
  changePct: number;
  buyPrice: number;
  stopLoss: number;
  targetPrice: number;
  riskReward: number;
  timestamp: string;
  consensusCount: number;
}

export interface SignalEntryGuide {
  mode: string;
  summary: string;
  action: string;
  compositeScore: number;
  setupLabel: string | null;
  themeSector: string | null;
  sectorBucket: string | null;
  themeAlignment: string;
  eventBias: string;
  eventScore: number;
  eventSummary: string | null;
  recommendedFirstPositionPct: number;
  suggestedAmount: number;
  suggestedQuantity: number;
  totalAssets: number;
  maxSinglePositionPct: number;
  maxThemeExposurePct: number;
  targetExposurePct: number;
  deployableCash: number;
  currentThemeExposurePct: number;
  projectedThemeExposurePct: number;
  concentrationSummary: string | null;
  warnings: string[];
}

export interface SignalDetail extends Signal {
  strategies: string[];
  high: number;
  low: number;
  volume: number;
  turnover: number;
  factorScores: Record<string, number>;
  regime: string;
  regimeScore: number;
  entryGuide: SignalEntryGuide;
}

export interface StrongMoveCandidate {
  id: string;
  signalId: string;
  code: string;
  name: string;
  strategy: string;
  setupLabel: string;
  conviction: 'low' | 'medium' | 'high';
  compositeScore: number;
  continuationScore: number;
  swingScore: number;
  strategyWinRate: number;
  price: number;
  buyPrice: number;
  stopLoss: number;
  targetPrice: number;
  riskReward: number;
  timestamp: string;
  thesis: string;
  nextStep: string;
  reasons: string[];
}

export interface HiddenAccumulationOpportunity {
  id: string;
  code: string;
  name: string;
  marketPhase: string;
  marketPhaseLabel: string;
  floatMvYi: number;
  streakDays: number;
  consolidationWidthPct: number;
  streakGainPct: number;
  setupLabel: string;
  tradabilityLabel: string;
  accumulationScore: number;
  holdingWindow: string;
  action: string;
  thesis: string;
  reasons: string[];
  recentCloses: number[];
  tailPcts: number[];
}

export interface ThemeFollower {
  code: string;
  name: string;
  changePct: number;
  label: string;
  buyPrice: number;
  stopLoss: number;
  targetPrice: number;
  riskReward: number;
}

export interface ThemeRadarItem {
  id: string;
  sector: string;
  themeType: string;
  changePct: number;
  score: number;
  intensity: string;
  timestamp: string;
  narrative: string;
  action: string;
  riskNote: string;
  messageHint: string | null;
  linkedSignalId: string | null;
  linkedCode: string | null;
  linkedName: string | null;
  linkedSetupLabel: string | null;
  followers: ThemeFollower[];
}

export interface ThemeStageItem {
  id: string;
  sector: string;
  themeType: string;
  intensity: string;
  stageLabel: string;
  participationLabel: string;
  directionScore: number;
  policyEventScore: number;
  trendScore: number;
  attentionScore: number;
  capitalPreferenceScore: number;
  stageScore: number;
  linkedSignalId: string | null;
  linkedCode: string | null;
  linkedName: string | null;
  linkedSetupLabel: string | null;
  summary: string;
  action: string;
  riskNote: string;
  drivers: string[];
}

export interface PolicyWatchItem {
  id: string;
  direction: string;
  policyBucket: string;
  focusSector: string;
  stageLabel: string;
  participationLabel: string;
  industryPhase: string;
  directionScore: number;
  policyScore: number;
  trendScore: number;
  attentionScore: number;
  capitalPreferenceScore: number;
  linkedSignalId: string | null;
  linkedCode: string | null;
  linkedName: string | null;
  linkedSetupLabel: string | null;
  summary: string;
  action: string;
  riskNote: string;
  phaseSummary: string;
  demandDrivers: string[];
  supplyDrivers: string[];
  upstream: string[];
  midstream: string[];
  downstream: string[];
  milestones: string[];
  transmissionPaths: string[];
  drivers: string[];
}

export interface IndustryCapitalDirection {
  id: string;
  direction: string;
  policyBucket: string;
  focusSector: string;
  strategicLabel: string;
  industryPhase: string;
  participationLabel: string;
  businessHorizon: string;
  capitalHorizon: string;
  priorityScore: number;
  strategicScore: number;
  policyScore: number;
  demandScore: number;
  supplyScore: number;
  capitalPreferenceScore: number;
  researchSignalScore: number;
  researchSignalLabel: string;
  officialFreshnessScore: number;
  officialFreshnessLabel: string;
  linkedSignalId: string | null;
  linkedCode: string | null;
  linkedName: string | null;
  linkedSetupLabel: string | null;
  summary: string;
  businessAction: string;
  capitalAction: string;
  riskNote: string;
  researchSummary: string;
  researchNextAction: string;
  upstream: string[];
  midstream: string[];
  downstream: string[];
  demandDrivers: string[];
  supplyDrivers: string[];
  milestones: string[];
  transmissionPaths: string[];
  opportunities: string[];
  officialSources: string[];
  officialWatchpoints: string[];
  businessChecklist: string[];
  capitalChecklist: string[];
  officialCards: Array<{
    title: string;
    source: string;
    excerpt: string;
    whyItMatters: string;
    nextWatch: string;
  }>;
  officialSourceEntries: Array<{
    title: string;
    issuer: string;
    publishedAt: string | null;
    sourceType: string;
    excerpt: string;
    reference: string | null;
    referenceUrl: string | null;
    keyPoints: string[];
    watchTags: string[];
  }>;
  officialDocuments: string[];
  timelineCheckpoints: string[];
  currentTimelineStage: string;
  latestCatalystTitle: string;
  latestCatalystSummary: string;
  timelineEvents: Array<{
    id: string;
    lane: string;
    stage: string;
    title: string;
    summary: string;
    source: string | null;
    signalLabel: string;
    emphasis: string;
    timestamp: string | null;
    nextAction: string | null;
  }>;
  cooperationTargets: string[];
  cooperationModes: string[];
  companyWatchlist: Array<{
    code: string;
    name: string;
    role: string;
    chainPosition: string;
    trackingReason: string;
    action: string;
    trackingScore: number;
    priorityLabel: string;
    marketAlignment: string;
    nextCheck: string;
    linkedSetupLabel: string | null;
    linkedSource: string | null;
    researchSignalScore: number;
    researchSignalLabel: string;
    recentResearchNote: string | null;
    timelineAlignment: string;
    catalystHint: string | null;
  }>;
  researchTargets: string[];
  validationSignals: string[];
  drivers: string[];
}

export interface IndustryCapitalResearchItem {
  id: string;
  directionId: string;
  direction: string;
  title: string;
  note: string;
  source: string;
  status: string;
  companyCode: string | null;
  companyName: string | null;
  createdAt: string;
  updatedAt: string;
  author: string;
}

export interface IndustryCapitalResearchSubmissionResult {
  success: boolean;
  message: string;
  item: IndustryCapitalResearchItem;
  totalItems: number;
}

export interface CompositePick {
  id: string;
  signalId: string;
  code: string;
  name: string;
  strategy: string;
  themeSector: string | null;
  themeIntensity: string | null;
  sourceCategory: string;
  sourceLabel: string;
  horizonLabel: string;
  setupLabel: string;
  conviction: 'low' | 'medium' | 'high';
  compositeScore: number;
  strategyScore: number;
  capitalScore: number;
  themeScore: number;
  eventScore: number;
  eventBias: string;
  eventSummary: string | null;
  eventMatchedSector: string | null;
  executionScore: number;
  firstPositionPct: number;
  price: number;
  buyPrice: number;
  stopLoss: number;
  targetPrice: number;
  riskReward: number;
  timestamp: string;
  thesis: string;
  action: string;
  reasons: string[];
}

export interface PositioningDeployment {
  code: string;
  name: string;
  setupLabel: string;
  suggestedPositionPct: number;
  suggestedAmount: number;
  themeSector: string | null;
  reason: string;
}

export interface PositioningPlan {
  mode: string;
  regime: string;
  regimeScore: number;
  eventBias: string;
  eventScore: number;
  eventSummary: string | null;
  eventFocusSector: string | null;
  currentExposurePct: number;
  targetExposurePct: number;
  deployableExposurePct: number;
  cashBalance: number;
  totalAssets: number;
  deployableCash: number;
  currentPositions: number;
  availableSlots: number;
  maxPositions: number;
  firstEntryPositionPct: number;
  maxSinglePositionPct: number;
  maxThemeExposurePct: number;
  topTheme: string | null;
  focus: string;
  reasons: string[];
  actions: string[];
  deployments: PositioningDeployment[];
}

export interface CompositeReplayItem {
  id: string;
  tradeDate: string;
  signalId: string;
  code: string;
  name: string;
  strategy: string;
  setupLabel: string;
  conviction: 'low' | 'medium' | 'high';
  compositeScore: number;
  firstPositionPct: number;
  themeSector: string | null;
  reviewLabel: string;
  verifiedDays: number;
  t1ReturnPct: number | null;
  t3ReturnPct: number | null;
  t5ReturnPct: number | null;
  outcomeSummary: string;
  review: string;
}

export interface RecommendationCompareSummary {
  label: string;
  sampleDays: number;
  observedT1Days: number;
  observedT3Days: number;
  observedT5Days: number;
  avgT1ReturnPct: number | null;
  avgT3ReturnPct: number | null;
  avgT5ReturnPct: number | null;
  t1WinRate: number | null;
  t3WinRate: number | null;
  t5WinRate: number | null;
}

export interface RecommendationCompareDay {
  tradeDate: string;
  compositeSignalId: string | null;
  compositeCode: string | null;
  compositeName: string | null;
  compositeScore: number | null;
  compositeT1ReturnPct: number | null;
  compositeT3ReturnPct: number | null;
  compositeT5ReturnPct: number | null;
  baselineSignalId: string | null;
  baselineCode: string | null;
  baselineName: string | null;
  baselineScore: number | null;
  baselineT1ReturnPct: number | null;
  baselineT3ReturnPct: number | null;
  baselineT5ReturnPct: number | null;
  winnerLabel: string;
  summary: string;
}

export interface RecommendationTakeoverReadiness {
  status: string;
  label: string;
  confidenceScore: number;
  summary: string;
  recommendedAction: string;
  conditions: string[];
}

export interface RecommendationCompareSnapshot {
  composite: RecommendationCompareSummary;
  baseline: RecommendationCompareSummary;
  advantage: string[];
  readiness: RecommendationTakeoverReadiness;
  days: RecommendationCompareDay[];
}

export interface Position {
  code: string;
  name: string;
  quantity: number;
  costPrice: number;
  currentPrice: number;
  marketValue: number;
  profitLoss: number;
  profitLossPct: number;
  stopLoss: number;
  takeProfit: number;
  holdDays: number;
  strategy: string;
}

export interface PositionTrade {
  time: string;
  type: string;
  price: number;
  quantity: number;
  reason: string;
}

export interface PositionGuide {
  mode: string;
  summary: string;
  nextAction: string;
  eventBias: string;
  eventScore: number;
  eventSummary: string | null;
  topTheme: string | null;
  sectorBucket: string | null;
  themeAlignment: string;
  canAdd: boolean;
  currentExposurePct: number;
  targetExposurePct: number;
  positionPct: number;
  currentThemeExposurePct: number;
  maxThemeExposurePct: number;
  suggestedStopLoss: number;
  suggestedTakeProfit: number;
  suggestedReducePct: number;
  suggestedReduceQuantity: number;
  concentrationSummary: string | null;
  warnings: string[];
}

export interface PositionDetail extends Position {
  buyTime: string;
  highPrice: number;
  lowPrice: number;
  trailingStop: boolean;
  trailingTriggerPrice: number;
  trades: PositionTrade[];
  positionGuide: PositionGuide;
}

export interface ClosedPosition {
  code: string;
  name: string;
  quantity: number;
  costPrice: number;
  closePrice: number;
  realizedProfitLoss: number;
  realizedProfitLossPct: number;
  holdDays: number;
  strategy: string;
  buyTime: string;
  closedAt: string;
  closeReason: string;
  status: string;
  trades: PositionTrade[];
}

export interface TradeLedgerEntry {
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
}

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
}

export interface RiskAlert {
  id: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  message: string;
  source: string;
  sourceId: string;
  createdAt: string;
  route: string | null;
}

export interface AppMessage {
  id: string;
  title: string;
  body: string;
  preview: string;
  level: string;
  channel: string;
  createdAt: string;
  route?: string | null;
}

export interface ActionBoardItem {
  id: string;
  kind: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  summary: string;
  actionLabel: string;
  route: string | null;
  source: string;
  sourceId: string;
  createdAt: string;
}

export interface LearningProgress {
  todayCycles: number;
  factorAdjustments: number;
  onlineUpdates: number;
  experimentsRunning: number;
  newFactorsDeployed: number;
  decisionAccuracy: number;
}

export interface HomeSnapshot {
  system: SystemStatus;
  learning: LearningProgress;
  dailyAdvance: LearningAdvanceStatus;
  worldState: WorldStateSnapshot | null;
  hiddenAccumulationOpportunities: HiddenAccumulationOpportunity[];
  productionGuard: ProductionGuardSnapshot | null;
  positioningPlan: PositioningPlan;
  positions: Position[];
  strategies: StrategyPerformance[];
  signals: Signal[];
  compositePicks: CompositePick[];
  compositeCompare: RecommendationCompareSnapshot;
  policyWatch: PolicyWatchItem[];
  industryCapital: IndustryCapitalDirection[];
  themeStages: ThemeStageItem[];
  strongMoves: StrongMoveCandidate[];
  alerts: RiskAlert[];
  messages: AppMessage[];
  actionBoard: ActionBoardItem[];
}

export interface BrainSnapshot {
  system: SystemStatus;
  learning: LearningProgress;
  strategies: StrategyPerformance[];
  signals: Signal[];
  compositePicks: CompositePick[];
  compositeCompare: RecommendationCompareSnapshot;
  themeRadar: ThemeRadarItem[];
  policyWatch: PolicyWatchItem[];
  industryCapital: IndustryCapitalDirection[];
  themeStages: ThemeStageItem[];
  ops: OpsSummary;
  dailyAdvance: LearningAdvanceStatus;
}

export interface PortfolioHistory {
  realizedProfitLoss: number;
  closedPositions: ClosedPosition[];
  recentTrades: TradeLedgerEntry[];
}

export interface FeedbackItem {
  id: string;
  username: string;
  title: string;
  message: string;
  category: string;
  priority: string;
  decisionStatus: string;
  ownerNote: string;
  sourceType: string;
  sourceId: string;
  sourceRoute: string;
  createdAt: string;
  updatedAt: string;
  decidedAt: string | null;
  decidedBy: string | null;
}

export interface FeedbackSubmissionPayload {
  title: string;
  message: string;
  category: string;
  priority: string;
  sourceType?: string;
  sourceId?: string;
  sourceRoute?: string;
}

export interface FeedbackSubmissionResult {
  success: boolean;
  message: string;
  item: FeedbackItem;
  pendingCount: number;
}

export interface FeedbackDecisionPayload {
  decision: 'pending' | 'watchlist' | 'accepted' | 'rejected';
  ownerNote?: string;
}

export interface FeedbackDecisionResult {
  success: boolean;
  message: string;
  item: FeedbackItem;
}

export interface OpenSignalPositionPayload {
  quantity: number;
  price?: number;
  stopLoss?: number;
  takeProfit?: number;
}

export interface PositionRiskUpdatePayload {
  stopLoss?: number;
  takeProfit?: number;
  trailingStop?: boolean;
  trailingTriggerPrice?: number;
}

export interface ClosePositionPayload {
  price?: number;
  reason?: string;
  quantity?: number;
}

export interface PortfolioActionResult {
  success: boolean;
  action: 'open' | 'risk_update' | 'close';
  code: string;
  name: string;
  message: string;
  executedAt: string;
  quantity: number;
  executionPrice: number;
  cashBalance: number;
  totalAssets: number;
  position: PositionDetail | null;
  realizedProfitLoss: number | null;
}

export interface OpsRouteStat {
  method: string;
  path: string;
  count: number;
  errorCount: number;
  avgLatencyMs: number;
  maxLatencyMs: number;
  lastStatus: number;
  lastSeenAt: string | null;
}

export interface OpsDataStatus {
  scorecardRecords: number;
  tradeJournalRecords: number;
  signalCount: number;
  activePositions: number;
  feedbackItems: number;
  pushDevices: number;
}

export interface OpsRecommendation {
  level: string;
  title: string;
  message: string;
}

export interface ExecutionPolicyExportStatus {
  period: string;
  latestExportAt: string | null;
  latestExportId: string | null;
  latestManifestRoute: string | null;
  latestReportRoute: string | null;
  latestBundleRoute: string | null;
  latestAssetCount: number;
  historyCount: number;
  stale: boolean;
}

export interface WorldStateExportStatus {
  period: string;
  latestExportAt: string | null;
  latestExportId: string | null;
  latestManifestRoute: string | null;
  latestReportRoute: string | null;
  latestBundleRoute: string | null;
  latestAssetCount: number;
  historyCount: number;
  stale: boolean;
}

export interface ProductionGuardSnapshot {
  marketPhase: string;
  marketPhaseLabel: string;
  hardRiskGate: boolean;
  blockedAdditions: boolean;
  autoReducePositions: boolean;
  autoExitLosers: boolean;
  currentDrawdownPct: number;
  maxDrawdownPct: number;
  drawdownDays: number;
  walkForwardRisk: string;
  walkForwardEfficiency: number | null;
  walkForwardDegradation: number | null;
  unstableStrategies: string[];
  summary: string;
  actions: string[];
}

export interface WorldStateComponent {
  key: string;
  label: string;
  score: number;
  bias: string;
  summary: string;
  drivers: string[];
}

export interface WorldEventCascade {
  themeKey: string;
  eventId: string;
  title: string;
  triggerType: string;
  severity: string;
  peakSeverity: string;
  tradeBias: string;
  immediateAction: string;
  continuityFocus: string;
  transportFocus: string;
  followUpSignal: string;
  confidenceScore: number;
  restrictionScope: string;
  estimatedFlowImpactPct: number;
  affectedCountries: string[];
  affectedRoutes: string[];
  directBeneficiaries: string[];
  directLosers: string[];
  exposedIndustries: string[];
  secondOrderImpacts: string[];
  commodityLinks: string[];
  evidenceCount: number;
  sourceTimestamp: string | null;
}

export interface OperatingProfile {
  companyName: string;
  primaryIndustries: string[];
  operatingMode: string;
  orderVisibilityMonths: number;
  capacityUtilizationPct: number;
  inventoryDays: number;
  supplierConcentrationPct: number;
  customerConcentrationPct: number;
  overseasRevenuePct: number;
  sensitiveRegionExposurePct: number;
  cashBufferMonths: number;
  capexFlexibility: string;
  inventoryStrategy: string;
  keyInputs: string[];
  keyRoutes: string[];
  strategicProjects: string[];
  completenessScore: number;
  completenessLabel: string;
  profileStatus: string;
  freshnessLabel: string;
  stale: boolean;
  missingFields: string[];
  recommendedActions: string[];
  summary: string | null;
  updatedAt: string | null;
}

export interface OperatingProfileUpdatePayload {
  companyName?: string;
  primaryIndustries?: string[];
  operatingMode?: string;
  orderVisibilityMonths?: number;
  capacityUtilizationPct?: number;
  inventoryDays?: number;
  supplierConcentrationPct?: number;
  customerConcentrationPct?: number;
  overseasRevenuePct?: number;
  sensitiveRegionExposurePct?: number;
  cashBufferMonths?: number;
  capexFlexibility?: string;
  inventoryStrategy?: string;
  keyInputs?: string[];
  keyRoutes?: string[];
  strategicProjects?: string[];
}

export interface WorldStateSnapshot {
  regime: string;
  regimeScore: number;
  marketPhase: string;
  marketPhaseLabel: string;
  valuationRegime: string;
  capitalStyle: string;
  strategicDirection: string | null;
  technologyFocus: string | null;
  geopoliticsBias: string;
  supplyChainMode: string;
  technologyBreakthroughScore: number;
  technologyBreakthroughSummary: string | null;
  phaseConfidence: number;
  styleBias: string;
  horizonHint: string;
  limitUpMode: string;
  limitUpAllowed: boolean;
  shouldTrade: boolean;
  summary: string;
  structuralSummary: string | null;
  dominantComponent: string | null;
  components: WorldStateComponent[];
  sourceStatuses: Array<{
    key: string;
    label: string;
    updatedAt: string | null;
    freshnessScore: number;
    freshnessLabel: string;
    reliabilityScore: number;
    authorityScore: number;
    timelinessScore: number;
    signalCount: number;
    summary: string;
    category: string;
    external: boolean;
    required: boolean;
    fetchMode: string;
    remoteConfigured: boolean;
    degradedToDerived: boolean;
    originMode: string;
    available: boolean;
    stale: boolean;
    dataQualityScore: number;
    blockReason?: string | null;
    liveProbeSummary?: string | null;
  }>;
  topDirections: Array<{
    directionId: string;
    direction: string;
    focusSector: string | null;
    policyBucket: string | null;
    totalScore: number;
    eventScore: number;
    officialScore: number;
    chainControlScore: number;
    researchScore: number;
    timelineScore: number;
    hardSourceScore: number;
    technologyBreakthroughScore: number;
    technologyFocus: string | null;
    summary: string;
  }>;
  crossAssetSignals: Array<{
    key: string;
    label: string;
    level: string;
    score: number;
    bias: string;
    summary: string;
    actionType: string;
    targets: string[];
    sourceKeys: string[];
  }>;
  regionalPressures: Array<{
    region: string;
    level: string;
    score: number;
    summary: string;
    affectedCountries: string[];
    affectedRoutes: string[];
    exposedIndustries: string[];
  }>;
  eventCascades: WorldEventCascade[];
  refreshPlan: {
    mode: string;
    modeLabel: string;
    activeWindow: string;
    activeWindowLabel: string;
    escalationActive: boolean;
    topTrigger: string | null;
    triggerType: string | null;
    newsIntervalMinutes: number;
    feedsIntervalMinutes: number;
    hardSourceIntervalMinutes: number;
    policyIntervalMinutes: number;
    overnightWatch: boolean;
    summary: string;
    nextFocus: string[];
    nextNewsDueAt: string | null;
    nextFeedsDueAt: string | null;
    nextHardSourcesDueAt: string | null;
    nextPolicyDueAt: string | null;
    overdueSources: string[];
    generatedAt: string | null;
  } | null;
  actions: Array<{
    key: string;
    level: string;
    actionType: string;
    priority: number;
    title: string;
    summary: string;
    horizon: string;
    sourceKeys: string[];
    targets: string[];
  }>;
  operatingActions: Array<{
    key: string;
    level: string;
    actionType: string;
    priority: number;
    title: string;
    summary: string;
    horizon: string;
    targets: string[];
  }>;
  operatingProfile: OperatingProfile | null;
  checks: Array<{
    key: string;
    level: string;
    title: string;
    message: string;
    suggestion: string | null;
    sourceKeys: string[];
  }>;
}

export interface OpsSummary {
  service: string;
  version: string;
  startedAt: string;
  uptimeSeconds: number;
  ready: boolean;
  readinessIssues: string[];
  requestCount: number;
  errorCount: number;
  errorRate: number;
  avgLatencyMs: number;
  maxLatencyMs: number;
  p95LatencyMs: number;
  lastErrorAt: string | null;
  lastErrorPath: string | null;
  websocketConnections: number;
  systemStatus: string;
  systemHealthScore: number;
  todaySignals: number;
  activeStrategies: number;
  dataStatus: OpsDataStatus;
  routes: OpsRouteStat[];
  worldState: WorldStateSnapshot | null;
  worldStateExport: WorldStateExportStatus | null;
  executionPolicyExport: ExecutionPolicyExportStatus | null;
  productionGuard: ProductionGuardSnapshot | null;
  recommendations: OpsRecommendation[];
}

export interface StockDiagnosis {
  code: string;
  name: string;
  price: number;
  asOf: string;
  totalScore: number;
  verdict: string;
  direction: string;
  signalDirection: string;
  actionable: boolean;
  confidenceLabel: string;
  advice: string;
  reportText: string;
  stopLoss: number | null;
  takeProfit: number | null;
  scores: Record<string, number>;
  details: Record<string, string[]>;
  regime: string;
  regimeScore: number;
  regimeSummary: string;
  healthBias: string;
  inPortfolio: boolean;
  positionQuantity: number;
  positionProfitLossPct: number | null;
  inSignalBoard: boolean;
  topStrategy: string | null;
  topStrategyWinRate: number | null;
  topStrategyAvgReturn: number | null;
  riskFlags: string[];
  nextActions: string[];
}

export interface LearningAdvanceCheck {
  name: string;
  status: string;
  detail: string;
}

export interface LearningAdvanceStatus {
  status: string;
  inProgress: boolean;
  todayCompleted: boolean;
  lastStartedAt: string | null;
  currentRunStartedAt: string | null;
  lastCompletedAt: string | null;
  lastRequestedBy: string | null;
  staleHours: number | null;
  healthStatus: string;
  summary: string;
  lastError: string | null;
  lastReportExcerpt: string;
  ingestedSignals: number;
  verifiedSignals: number;
  reviewedDecisions: number;
  checks: LearningAdvanceCheck[];
  recommendations: string[];
}

export interface PushDevice {
  username: string;
  platform: string;
  expoPushToken: string;
  deviceName: string;
  appVersion: string;
  permissionState: string;
  isPhysicalDevice: boolean | null;
  status: string;
  lastSeenAt: string;
  lastPushAt: string | null;
  lastPushStatus: string | null;
  lastError: string | null;
}

export interface PushRegistrationPayload {
  expoPushToken: string;
  platform: string;
  deviceName?: string;
  appVersion?: string;
  permissionState?: string;
  isPhysicalDevice?: boolean;
}

export interface PushRegistrationResult {
  success: boolean;
  message: string;
  device: PushDevice;
  activeDevices: number;
  takeoverDispatch: PushDispatchResult | null;
}

export interface PushTestPayload {
  title?: string;
  body?: string;
  route?: string;
  dryRun?: boolean;
  targetToken?: string;
}

export interface PushTakeoverPayload {
  dryRun?: boolean;
  targetToken?: string;
  force?: boolean;
}

export interface PushDispatchTicket {
  expoPushToken: string;
  status: string;
  ticketId: string | null;
  message: string | null;
  details: string | null;
}

export interface PushDispatchResult {
  success: boolean;
  dryRun: boolean;
  targetedDevices: number;
  sentDevices: number;
  failedDevices: number;
  tickets: PushDispatchTicket[];
}

export interface TakeoverPushStatus {
  title: string;
  body: string;
  readinessLabel: string;
  fingerprint: string;
  activeDevices: number;
  syncedDevices: number;
  pendingDevices: number;
  deliveryState: string;
  shouldSend: boolean;
  summary: string;
  recommendedAction: string;
  autoEnabled: boolean;
  autoReady: boolean;
  autoCooldownSeconds: number;
  lastSentAt: string | null;
  lastSentStatus: string | null;
  lastSentFingerprint: string | null;
  lastPreviewAt: string | null;
  lastAutoRunAt: string | null;
  lastAutoRunStatus: string | null;
}

export interface IndustryResearchPushStatus {
  title: string;
  latestTitle: string | null;
  latestPreview: string | null;
  latestDirection: string | null;
  latestTimelineStage: string | null;
  latestCatalystTitle: string | null;
  activeDevices: number;
  deliveryState: string;
  autoEnabled: boolean;
  summary: string;
  recommendedAction: string;
  lastSentAt: string | null;
  lastSentStatus: string | null;
}
