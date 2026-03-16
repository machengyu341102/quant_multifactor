import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useDeferredValue, useEffect } from 'react';
import { useRouter, type Href } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { resolveAppHref } from '@/lib/app-routes';
import { formatCurrency, formatPercent, formatTimestamp } from '@/lib/format';
import { getHomeSnapshot } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useNotifications } from '@/providers/notification-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type {
  ActionBoardItem,
  AppMessage,
  CompositePick,
  IndustryCapitalDirection,
  PolicyWatchItem,
  Position,
  RecommendationCompareSnapshot,
  RiskAlert,
  Signal,
  StrongMoveCandidate,
  ThemeStageItem,
} from '@/types/trading';

type PillTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function getStopBufferPct(position: Position): number | null {
  if (position.currentPrice <= 0 || position.stopLoss <= 0) {
    return null;
  }

  return ((position.currentPrice - position.stopLoss) / position.currentPrice) * 100;
}

function getPositionRiskScore(position: Position): number {
  const stopBufferPct = getStopBufferPct(position);
  const stopRisk = stopBufferPct === null ? 0 : Math.max(0, 12 - stopBufferPct) * 8;
  const pnlRisk = position.profitLossPct < 0 ? Math.abs(position.profitLossPct) * 2.4 : 0;
  const holdRisk = Math.min(position.holdDays, 15) * 0.6;

  return stopRisk + pnlRisk + holdRisk;
}

function getPositionRiskTone(position: Position): PillTone {
  const stopBufferPct = getStopBufferPct(position);

  if (stopBufferPct !== null && stopBufferPct <= 2) {
    return 'danger';
  }
  if (stopBufferPct !== null && stopBufferPct <= 5) {
    return 'warning';
  }
  if (position.profitLossPct < 0) {
    return 'warning';
  }

  return 'success';
}

function getPositionRiskLabel(position: Position): string {
  const stopBufferPct = getStopBufferPct(position);

  if (stopBufferPct !== null && stopBufferPct <= 0) {
    return '已跌穿止损';
  }
  if (stopBufferPct !== null && stopBufferPct <= 2) {
    return '接近止损';
  }
  if (stopBufferPct !== null && stopBufferPct <= 5) {
    return '需要盯盘';
  }
  if (position.profitLossPct < 0) {
    return '浮亏观察';
  }

  return '状态稳定';
}

function getStrongMoveTone(candidate: StrongMoveCandidate): PillTone {
  if (candidate.conviction === 'high') {
    return candidate.setupLabel === '连涨候选' ? 'danger' : 'success';
  }
  if (candidate.conviction === 'medium') {
    return 'warning';
  }
  return 'info';
}

function getStrongMoveSummary(candidate: StrongMoveCandidate): string {
  return `${candidate.setupLabel} / 续强 ${candidate.continuationScore.toFixed(0)} / 波段 ${candidate.swingScore.toFixed(0)} / ${candidate.strategy}`;
}

function getReadinessTone(status: string): PillTone {
  if (status === 'ready') {
    return 'success';
  }
  if (status === 'pilot') {
    return 'info';
  }
  if (status === 'hold') {
    return 'warning';
  }
  return 'neutral';
}

function getCompositeSourceTone(category: string): PillTone {
  if (category === 'theme_seed' || category === 'resonance') {
    return 'success';
  }
  if (category === 'strong_move') {
    return 'info';
  }
  return 'neutral';
}

function getPolicyWatchTone(item: PolicyWatchItem): PillTone {
  if (item.stageLabel === '承压观察') {
    return 'warning';
  }
  if (item.stageLabel === '兑现扩散') {
    return 'success';
  }
  if (item.stageLabel === '催化升温') {
    return 'info';
  }
  return 'neutral';
}

function canOpenCompositeDetail(pick: CompositePick | null): boolean {
  return Boolean(pick && pick.sourceCategory !== 'theme_seed' && !pick.signalId.startsWith('theme-seed-'));
}

function getCompositeSummary(pick: CompositePick | null, compare: RecommendationCompareSnapshot | undefined): string {
  if (!pick) {
    return '综合榜还没产出足够强的候选，先继续盯原推荐和强势收益引擎。';
  }

  const takeoverLabel = compare?.readiness.label ?? '继续影子';
  return `${pick.sourceLabel} / ${pick.horizonLabel} / ${pick.setupLabel} / 事件${pick.eventBias} / 首仓 ${pick.firstPositionPct}% / ${takeoverLabel}`;
}

function getActionTone(level: ActionBoardItem['level']): PillTone {
  if (level === 'critical') {
    return 'danger';
  }
  if (level === 'warning') {
    return 'warning';
  }
  return 'info';
}

function getActionKindLabel(kind: string): string {
  if (kind === 'risk_alert' || kind === 'alert') {
    return '风险';
  }
  if (kind === 'position') {
    return '持仓';
  }
  if (kind === 'industry_capital') {
    return '方向';
  }
  if (kind === 'takeover') {
    return '接管';
  }
  if (kind === 'composite_pick') {
    return '推荐';
  }
  if (kind === 'learning') {
    return '学习';
  }
  return '待办';
}

function getThemeStageTone(item: ThemeStageItem): PillTone {
  if (item.participationLabel === '后排回避') {
    return 'danger';
  }
  if (item.stageLabel === '主升波段') {
    return 'success';
  }
  if (item.stageLabel === '中期扩散') {
    return 'info';
  }
  return 'warning';
}

function getIndustryCapitalTone(item: IndustryCapitalDirection): PillTone {
  if (item.strategicLabel === '逆风跟踪') {
    return 'warning';
  }
  if (item.participationLabel === '中期波段' || item.participationLabel === '连涨接力') {
    return 'success';
  }
  return 'info';
}

function getIndustryResearchTone(label: string): PillTone {
  if (label === '验证增强') {
    return 'success';
  }
  if (label === '出现阻力') {
    return 'warning';
  }
  if (label === '继续验证') {
    return 'info';
  }
  return 'neutral';
}

function selectTradingFocusAction(actionBoard: ActionBoardItem[]): ActionBoardItem | null {
  const urgentRisk = actionBoard.find((item) => item.kind === 'alert' || item.kind === 'position');
  if (urgentRisk) {
    return urgentRisk;
  }

  const directionFocus = actionBoard.find((item) => item.kind === 'industry_capital');
  if (directionFocus) {
    return directionFocus;
  }

  const compositeFocus = actionBoard.find((item) => item.kind === 'composite_pick');
  if (compositeFocus) {
    return compositeFocus;
  }

  const signalFocus = actionBoard.find((item) => item.kind === 'signal');
  if (signalFocus) {
    return signalFocus;
  }

  return actionBoard[0] ?? null;
}

function selectGovernanceAction(actionBoard: ActionBoardItem[]): ActionBoardItem | null {
  return actionBoard.find((item) => item.kind === 'takeover') ?? null;
}

function buildHomeVerdict(
  action: ActionBoardItem | null,
  alert: RiskAlert | null,
  riskyPosition: Position | null,
  signal: Signal | null,
  todayCompleted: boolean
): {
  title: string;
  summary: string;
  tone: PillTone;
} {
  if (action) {
    if (action.kind === 'takeover') {
      return {
        title: '先看综合榜接管判断',
        summary: action.summary,
        tone: getActionTone(action.level),
      };
    }

    if (action.kind === 'industry_capital') {
      return {
        title: '先看大方向，再找小机会',
        summary: action.summary,
        tone: getActionTone(action.level),
      };
    }

    return {
      title: '先处理动作看板的第一项',
      summary: `${action.title}。${action.summary}`,
      tone: getActionTone(action.level),
    };
  }

  if (alert) {
    return {
      title: '先处理风险，再谈机会',
      summary: `当前最高优先级是 ${alert.title}。这不是信息展示，而是明确的待处理动作。`,
      tone: alert.level === 'critical' ? 'danger' : 'warning',
    };
  }

  if (riskyPosition) {
    return {
      title: '仓位风险优先于新增推荐',
      summary: `${riskyPosition.code} ${riskyPosition.name} 已经进入重点监控区，先把组合风险压住。`,
      tone: getPositionRiskTone(riskyPosition),
    };
  }

  if (signal) {
    return {
      title: '今天先看推荐，再决定是否出手',
      summary: `${signal.code} ${signal.name} 是当前首推，适合先做一次完整判断。`,
      tone: 'info',
    };
  }

  if (!todayCompleted) {
    return {
      title: '今天先补学习，再看执行',
      summary: '日日精进还没跑完，先让系统完成学习闭环，再看今天的机会质量。',
      tone: 'warning',
    };
  }

  return {
    title: '当前没有强制动作',
    summary: '系统、学习和组合都在可控区间，可以继续深看推荐、诊股和持仓细节。',
    tone: 'success',
  };
}

function getPrimaryTask(
  action: ActionBoardItem | null,
  alert: RiskAlert | null,
  riskyPosition: Position | null,
  signal: Signal | null,
  message: AppMessage | null,
  todayCompleted: boolean
): {
  eyebrow: string;
  title: string;
  summary: string;
  actionLabel: string;
  tone: PillTone;
  route: Href;
} {
  if (action) {
    if (action.kind === 'takeover') {
      return {
        eyebrow: '策略切换',
        title: action.title,
        summary: `${formatTimestamp(action.createdAt)} / ${getActionKindLabel(action.kind)} / ${action.summary}`,
        actionLabel: action.actionLabel,
        tone: getActionTone(action.level),
        route: (action.route as Href | null) ?? ('/(tabs)/signals' as Href),
      };
    }

    if (action.kind === 'industry_capital') {
      return {
        eyebrow: '方向优先',
        title: action.title,
        summary: `${formatTimestamp(action.createdAt)} / ${getActionKindLabel(action.kind)} / ${action.summary}`,
        actionLabel: action.actionLabel,
        tone: getActionTone(action.level),
        route: (action.route as Href | null) ?? ('/(tabs)/brain' as Href),
      };
    }

    return {
      eyebrow: '当前待办',
      title: action.title,
      summary: `${formatTimestamp(action.createdAt)} / ${getActionKindLabel(action.kind)} / ${action.summary}`,
      actionLabel: action.actionLabel,
      tone: getActionTone(action.level),
      route: (action.route as Href | null) ?? ('/(tabs)/index' as Href),
    };
  }

  if (alert) {
    return {
      eyebrow: '今日主任务',
      title: alert.title,
      summary: alert.message,
      actionLabel: '立即处理',
      tone: alert.level === 'critical' ? 'danger' : 'warning',
      route: (alert.route as Href | null) ?? '/alerts',
    };
  }

  if (riskyPosition) {
    const stopBufferPct = getStopBufferPct(riskyPosition);

    return {
      eyebrow: '今日主任务',
      title: `${riskyPosition.code} ${getPositionRiskLabel(riskyPosition)}`,
      summary: `当前价 ${riskyPosition.currentPrice.toFixed(2)} / 止损 ${riskyPosition.stopLoss.toFixed(2)} / 距离止损 ${
        stopBufferPct === null ? '--' : formatPercent(stopBufferPct / 100)
      }`,
      actionLabel: '处理仓位',
      tone: getPositionRiskTone(riskyPosition),
      route: {
        pathname: '/position/[code]',
        params: { code: riskyPosition.code },
      } as Href,
    };
  }

  if (signal) {
    return {
      eyebrow: '今日主任务',
      title: `${signal.code} ${signal.name} 是当前首推`,
      summary: `评分 ${signal.score.toFixed(3)} / 止损 ${signal.stopLoss.toFixed(2)} / 目标 ${signal.targetPrice.toFixed(2)} / ${formatTimestamp(signal.timestamp)}`,
      actionLabel: '看推荐',
      tone: 'info',
      route: {
        pathname: '/signal/[id]',
        params: { id: signal.id },
      } as Href,
    };
  }

  if (!todayCompleted) {
    return {
      eyebrow: '今日主任务',
      title: '日日精进今天还没跑完',
      summary: '先把学习链跑完，再看脑子今天有没有补到位。',
      actionLabel: '去决策台',
      tone: 'warning',
      route: '/(tabs)/brain' as Href,
    };
  }

  if (message) {
    return {
      eyebrow: '今日主任务',
      title: message.title,
      summary: `${message.channel} / ${formatTimestamp(message.createdAt)} / ${message.preview}`,
      actionLabel: '看消息',
      tone: message.level === 'warning' ? 'warning' : 'neutral',
      route: '/messages' as Href,
    };
  }

  return {
    eyebrow: '今日主任务',
    title: '系统当前没有新的强制动作',
    summary: '没有新的风险、推荐和待处理任务，可以继续看诊股和持仓细节。',
    actionLabel: '去决策台',
    tone: 'success',
    route: '/(tabs)/brain' as Href,
  };
}

export default function HomeScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { permissionState, pushRiskAlerts, pushTakeoverAction } = useNotifications();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getHomeSnapshot(token ?? undefined),
    [token, apiBaseUrl]
  );

  const signals = useDeferredValue(data?.signals ?? []);
  const alerts = useDeferredValue(data?.alerts ?? []);
  const messages = useDeferredValue(data?.messages ?? []);
  const actionBoard = useDeferredValue(data?.actionBoard ?? []);
  const positions = useDeferredValue(data?.positions ?? []);
  const compositePicks = useDeferredValue(data?.compositePicks ?? []);
  const policyWatch = useDeferredValue(data?.policyWatch ?? []);
  const industryCapital = useDeferredValue(data?.industryCapital ?? []);
  const themeStages = useDeferredValue(data?.themeStages ?? []);
  const strongMoves = useDeferredValue(data?.strongMoves ?? []);
  const compositeCompare = data?.compositeCompare;
  const positioningPlan = data?.positioningPlan ?? null;
  const urgentAlertCount = alerts.filter((item) => item.level !== 'info').length;
  const latestSignal = signals[0] ?? null;
  const mirrorMessages = messages.filter((item) => item.channel === 'wechat_mirror');
  const liveMessages = messages.filter((item) => item.channel !== 'wechat_mirror');
  const topCompositePick = compositePicks[0] ?? null;
  const topThemeSeedPick = compositePicks.find((item) => item.sourceCategory === 'theme_seed') ?? null;
  const topSwingCompositePick =
    compositePicks.find((item) => item.horizonLabel === '中期波段' || item.horizonLabel === '连涨接力') ?? null;
  const topStrategyCompositePick =
    compositePicks.find((item) => item.sourceCategory !== 'theme_seed') ?? null;
  const topPolicyWatch = policyWatch[0] ?? null;
  const topIndustryCapital = industryCapital[0] ?? null;
  const topStrongMove = strongMoves[0] ?? null;
  const topThemeStage = themeStages[0] ?? null;
  const latestMessage = messages[0] ?? null;
  const latestMirrorMessage = mirrorMessages[0] ?? null;
  const topAction = selectTradingFocusAction(actionBoard);
  const governanceAction = selectGovernanceAction(actionBoard);
  const topAlert = alerts.find((item) => item.level !== 'info') ?? alerts[0] ?? null;
  const riskyPositions = [...positions]
    .sort((left, right) => getPositionRiskScore(right) - getPositionRiskScore(left))
    .slice(0, 2);
  const totalMarketValue = positions.reduce((sum, item) => sum + item.marketValue, 0);
  const totalProfitLoss = positions.reduce((sum, item) => sum + item.profitLoss, 0);
  const homeVerdict = buildHomeVerdict(
    topAction,
    topAlert,
    riskyPositions[0] ?? null,
    latestSignal,
    data?.dailyAdvance.todayCompleted ?? false
  );
  const primaryTask = getPrimaryTask(
    topAction,
    topAlert,
    riskyPositions[0] ?? null,
    latestSignal,
    latestMessage,
    data?.dailyAdvance.todayCompleted ?? false
  );
  const demoFlow: {
    key: string;
    title: string;
    copy: string;
    route: Href;
  }[] = [
    {
      key: 'command',
      title: '先讲总指挥台',
      copy: '用一句话说明今天先做什么，先把场子定住。',
      route: '/(tabs)/index' as Href,
    },
    {
      key: 'signal',
      title: latestSignal ? `再讲 ${latestSignal.code}` : '再看推荐页',
      copy: latestSignal ? '进入焦点推荐详情，讲结论、风险和动作。' : '说明今天推荐池为空时系统怎么处理。',
      route: latestSignal
        ? ({ pathname: '/signal/[id]', params: { id: latestSignal.id } } as Href)
        : ('/(tabs)/signals' as Href),
    },
    {
      key: 'brain',
      title: '现场做一次诊股',
      copy: '输入代码，让系统现场给出解释和下一步。',
      route: '/(tabs)/brain' as Href,
    },
    {
      key: 'position',
      title: riskyPositions[0] ? `回到 ${riskyPositions[0].code} 持仓` : '回到持仓纪律',
      copy: riskyPositions[0] ? '展示风控、减仓和平仓动作链。' : '说明没有风险仓位时系统如何组织信息。',
      route: riskyPositions[0]
        ? ({ pathname: '/position/[code]', params: { code: riskyPositions[0].code } } as Href)
        : ('/(tabs)/positions' as Href),
    },
    {
      key: 'message',
      title: '最后看后备消息',
      copy: '补一句微信与系统通知只是后备触达，主链路已经在 APP 内闭环。',
      route: '/messages' as Href,
    },
  ];

  useEffect(() => {
    if (alerts.length === 0) {
      return;
    }

    void pushRiskAlerts(alerts);
  }, [alerts, pushRiskAlerts]);

  useEffect(() => {
    if (actionBoard.length === 0) {
      return;
    }

    void pushTakeoverAction(actionBoard);
  }, [actionBoard, pushTakeoverAction]);

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading
        eyebrow="Command Center"
        title="首页"
        subtitle="首页只做一件事：告诉你现在先看什么、为什么看、下一步去哪。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>COMMAND CENTER</Text>
        <Text style={styles.heroTitle}>{homeVerdict.title}</Text>
        <Text style={styles.heroCopy}>{homeVerdict.summary}</Text>
        <View style={styles.heroPills}>
          <StatusPill label={`系统 ${data?.system.status ?? '未连接'}`} tone="neutral" />
          <StatusPill label={`健康分 ${data?.system.healthScore ?? '--'}`} tone={homeVerdict.tone} />
          <StatusPill label={`今日推荐 ${data?.system.todaySignals ?? 0}`} tone="info" />
          <StatusPill label={`风险 ${urgentAlertCount}`} tone={urgentAlertCount > 0 ? 'danger' : 'success'} />
          <StatusPill
            label={`总仓建议 ${positioningPlan ? `${positioningPlan.targetExposurePct.toFixed(0)}%` : '--'}`}
            tone={
              positioningPlan?.mode === '防守'
                ? 'warning'
                : positioningPlan?.mode === '进攻'
                  ? 'success'
                  : 'info'
            }
          />
          <StatusPill
            label={`事件 ${positioningPlan?.eventBias ?? '中性'}`}
            tone={
              positioningPlan?.eventBias === '偏空'
                ? 'warning'
                : positioningPlan?.eventBias === '偏多'
                  ? 'success'
                  : 'neutral'
            }
          />
          <StatusPill
            label={data?.dailyAdvance.todayCompleted ? '学习已完成' : '学习待执行'}
            tone={data?.dailyAdvance.todayCompleted ? 'success' : 'warning'}
          />
          <StatusPill
            label={`接管 ${compositeCompare?.readiness.label ?? '继续影子'}`}
            tone={getReadinessTone(compositeCompare?.readiness.status ?? 'shadow')}
          />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取首页驾驶舱" />

      <View style={styles.metricGrid}>
        <MetricCard label="活跃策略" value={`${data?.system.activeStrategies ?? '--'}`} tone="info" />
        <MetricCard
          label="决策准确率"
          value={formatPercent(data?.system.decisionAccuracy ?? 0, 0)}
          tone="success"
        />
        <MetricCard
          label="目标总仓"
          value={positioningPlan ? formatPercent(positioningPlan.targetExposurePct / 100) : '--'}
          tone={positioningPlan?.mode === '防守' ? 'warning' : 'info'}
        />
        <MetricCard label="总市值" value={formatCurrency(totalMarketValue)} tone="neutral" />
        <MetricCard
          label="组合浮盈"
          value={formatCurrency(totalProfitLoss)}
          tone={totalProfitLoss >= 0 ? 'success' : 'danger'}
        />
      </View>

      <SectionHeading
        title="方向与通道"
        subtitle="APP 负责实时判断和深页，微信只做后备提醒，不再承担主操作链路。"
      />
      <SurfaceCard style={styles.channelHub}>
        <View style={styles.channelGrid}>
          <View style={[styles.channelPanel, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.channelTitle, { color: palette.text }]}>APP 主阵地</Text>
            <Text style={[styles.channelCopy, { color: palette.subtext }]}>
              首页、决策台、推荐、持仓都在这里实时更新，先在 APP 完成判断，再决定要不要执行动作。
            </Text>
            <View style={styles.heroPills}>
              <StatusPill label={`实时消息 ${liveMessages.length}`} tone="success" />
              <StatusPill label={`待办 ${actionBoard.length}`} tone={actionBoard.length > 0 ? 'info' : 'neutral'} />
              <StatusPill label={`方向 ${policyWatch.length + industryCapital.length}`} tone="info" />
            </View>
            <Pressable
              onPress={() => {
                router.push('/(tabs)/brain');
              }}
              style={[styles.secondaryAction, { borderColor: palette.border }]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台看实时链路</Text>
            </Pressable>
          </View>

          <View style={[styles.channelPanel, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.channelTitle, { color: palette.text }]}>微信后备</Text>
            <Text style={[styles.channelCopy, { color: palette.subtext }]}>
              {latestMirrorMessage
                ? `最近一次镜像在 ${formatTimestamp(latestMirrorMessage.createdAt)}，适合做兜底触达、留痕和异常补发。`
                : '当前还没有新的微信镜像，说明这段时间应直接以 APP 为准。'}
            </Text>
            <View style={styles.heroPills}>
              <StatusPill label={`镜像 ${mirrorMessages.length}`} tone="warning" />
              <StatusPill label={latestMirrorMessage ? latestMirrorMessage.level : '待同步'} tone="neutral" />
              <StatusPill label="仅做后备" tone="neutral" />
            </View>
            <Pressable
              onPress={() => {
                router.push('/messages');
              }}
              style={[styles.secondaryAction, { borderColor: palette.border }]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看后备消息中心</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.directionSummaryGrid}>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}>
            <View
              style={[
                styles.directionSummaryCard,
                { backgroundColor: palette.surfaceMuted, borderColor: palette.border },
              ]}>
              <View style={styles.directionSummaryHead}>
                <Text style={[styles.directionSummaryEyebrow, { color: palette.subtext }]}>政策方向</Text>
                <StatusPill
                  label={topPolicyWatch ? topPolicyWatch.stageLabel : '读取中'}
                  tone={topPolicyWatch ? getPolicyWatchTone(topPolicyWatch) : 'neutral'}
                />
              </View>
              <Text style={[styles.directionSummaryTitle, { color: palette.text }]}>
                {topPolicyWatch ? topPolicyWatch.direction : '正在归纳政策大方向'}
              </Text>
              <Text style={[styles.directionSummaryCopy, { color: palette.subtext }]}>
                {topPolicyWatch
                  ? `${topPolicyWatch.policyBucket} / ${topPolicyWatch.focusSector} / ${topPolicyWatch.industryPhase}`
                  : '会把政策、地缘、需求和产业链压缩成今天该先看什么。'}
              </Text>
              <Text style={[styles.directionSummaryBody, { color: palette.text }]}>
                {topPolicyWatch?.action ?? '读取完成后可直接跳去决策台看政策方向雷达。'}
              </Text>
            </View>
          </Pressable>

          <Pressable
            onPress={() => {
              if (topIndustryCapital) {
                router.push(resolveAppHref(`/industry-capital/${topIndustryCapital.id}`));
                return;
              }

              router.push('/(tabs)/brain');
            }}>
            <View
              style={[
                styles.directionSummaryCard,
                { backgroundColor: palette.surfaceMuted, borderColor: palette.border },
              ]}>
              <View style={styles.directionSummaryHead}>
                <Text style={[styles.directionSummaryEyebrow, { color: palette.subtext }]}>产业方向</Text>
                <StatusPill
                  label={topIndustryCapital ? topIndustryCapital.capitalHorizon : '读取中'}
                  tone={topIndustryCapital ? getIndustryCapitalTone(topIndustryCapital) : 'neutral'}
                />
              </View>
              <Text style={[styles.directionSummaryTitle, { color: palette.text }]}>
                {topIndustryCapital ? topIndustryCapital.direction : '正在把政策翻译成产业资本动作'}
              </Text>
              <Text style={[styles.directionSummaryCopy, { color: palette.subtext }]}>
                {topIndustryCapital
                  ? `${topIndustryCapital.policyBucket} / ${topIndustryCapital.focusSector} / ${topIndustryCapital.strategicLabel}`
                  : '会把政策方向进一步翻译成事业动作、资本动作和重点跟踪对象。'}
              </Text>
              <Text style={[styles.directionSummaryBody, { color: palette.text }]}>
                {topIndustryCapital?.capitalAction ?? '读取完成后可直接跳去方向深页看催化、时间轴和公司清单。'}
              </Text>
            </View>
          </Pressable>
        </View>
      </SurfaceCard>

      <SectionHeading
        title="今日决策链"
        subtitle="先看政策，再看产业，再定仓位，最后落到标的，不在中间层直接跳。"
      />
      <SurfaceCard style={styles.chainBoard}>
        <Pressable
          onPress={() => {
            router.push('/(tabs)/brain');
          }}>
          <View style={[styles.chainCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.chainStep, { color: palette.tint }]}>01 政策定调</Text>
            <Text style={[styles.chainTitle, { color: palette.text }]}>
              {topPolicyWatch ? topPolicyWatch.direction : '正在归纳政策大方向'}
            </Text>
            <Text style={[styles.chainLabel, { color: palette.subtext }]}>
              {topPolicyWatch
                ? `${topPolicyWatch.policyBucket} / ${topPolicyWatch.industryPhase} / ${topPolicyWatch.stageLabel}`
                : '先判断政策、地缘和需求从哪里真正开始传导。'}
            </Text>
            <Text style={[styles.chainCopy, { color: palette.text }]}>
              {topPolicyWatch?.action ?? '进入决策台看政策方向雷达。'}
            </Text>
          </View>
        </Pressable>

        <Pressable
          onPress={() => {
            if (topIndustryCapital) {
              router.push(resolveAppHref(`/industry-capital/${topIndustryCapital.id}`));
              return;
            }

            router.push('/(tabs)/brain');
          }}>
          <View style={[styles.chainCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.chainStep, { color: palette.tint }]}>02 产业翻译</Text>
            <Text style={[styles.chainTitle, { color: palette.text }]}>
              {topIndustryCapital ? topIndustryCapital.direction : '正在翻译成产业资本动作'}
            </Text>
            <Text style={[styles.chainLabel, { color: palette.subtext }]}>
              {topIndustryCapital
                ? `${topIndustryCapital.strategicLabel} / ${topIndustryCapital.capitalHorizon} / ${topIndustryCapital.participationLabel}`
                : '把政策主线落成事业动作、资本动作和公司清单。'}
            </Text>
            <Text style={[styles.chainCopy, { color: palette.text }]}>
              {topIndustryCapital?.capitalAction ?? '进入方向深页看催化、时间轴和验证清单。'}
            </Text>
          </View>
        </Pressable>

        <Pressable
          onPress={() => {
            router.push('/(tabs)/positions');
          }}>
          <View style={[styles.chainCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.chainStep, { color: palette.tint }]}>03 仓位部署</Text>
            <Text style={[styles.chainTitle, { color: palette.text }]}>
              {positioningPlan ? `${positioningPlan.mode} / 目标总仓 ${positioningPlan.targetExposurePct.toFixed(0)}%` : '正在计算仓位部署'}
            </Text>
            <Text style={[styles.chainLabel, { color: palette.subtext }]}>
              {positioningPlan
                ? `首仓 ${positioningPlan.firstEntryPositionPct}% / 单票 ${positioningPlan.maxSinglePositionPct}% / 主题 ${positioningPlan.maxThemeExposurePct}%`
                : '先确定总仓、首仓和主题暴露，再决定要不要出手。'}
            </Text>
            <Text style={[styles.chainCopy, { color: palette.text }]}>
              {positioningPlan?.eventSummary ?? '进入持仓纪律页看风控和分仓计划。'}
            </Text>
          </View>
        </Pressable>

        <Pressable
          onPress={() => {
            if (latestSignal) {
              router.push({ pathname: '/signal/[id]', params: { id: latestSignal.id } });
              return;
            }
            router.push('/(tabs)/signals');
          }}>
          <View style={[styles.chainCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.chainStep, { color: palette.tint }]}>04 执行焦点</Text>
            <Text style={[styles.chainTitle, { color: palette.text }]}>
              {latestSignal ? `${latestSignal.code} ${latestSignal.name}` : '当前先看综合推荐'}
            </Text>
            <Text style={[styles.chainLabel, { color: palette.subtext }]}>
              {latestSignal
                ? `评分 ${latestSignal.score.toFixed(3)} / 止损 ${latestSignal.stopLoss.toFixed(2)} / 目标 ${latestSignal.targetPrice.toFixed(2)}`
                : topCompositePick
                  ? getCompositeSummary(topCompositePick, compositeCompare)
                  : '没有明确焦点票时，先看综合榜和接管判断。'}
            </Text>
            <Text style={[styles.chainCopy, { color: palette.text }]}>
              {latestSignal ? '确认风险收益比后再执行，不要跳过前面的方向和仓位层。'
                : '进入推荐页看综合榜、主线候选和接管状态。'}
            </Text>
          </View>
        </Pressable>
      </SurfaceCard>

      <SectionHeading title="仓位与防守" subtitle="先把总仓、单票上限和今天还能怎么出手讲清楚。" />
      <SurfaceCard style={styles.decisionCard}>
        <View style={styles.cardHead}>
          <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>仓位与分仓引擎</Text>
          <StatusPill
            label={positioningPlan?.mode ?? '读取中'}
            tone={
              positioningPlan?.mode === '防守'
                ? 'warning'
                : positioningPlan?.mode === '进攻'
                  ? 'success'
                  : 'info'
            }
          />
        </View>
        <Text style={[styles.cardTitle, { color: palette.text }]}>
          {positioningPlan?.focus ?? '正在计算今天的总仓与分仓建议'}
        </Text>
        <Text style={[styles.cardCopy, { color: palette.subtext }]}>
          {positioningPlan
            ? `当前仓位 ${formatPercent(positioningPlan.currentExposurePct / 100)} / 目标总仓 ${formatPercent(positioningPlan.targetExposurePct / 100)} / 还能再部署 ${formatCurrency(positioningPlan.deployableCash)}`
            : '这层会把市场环境、综合推荐和风控提醒统一成仓位语言。'}
        </Text>
        {positioningPlan ? (
          <>
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>首仓</Text>
                <Text style={[styles.metricChipValue, { color: palette.tint }]}>
                  {positioningPlan.firstEntryPositionPct}%
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>单票上限</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {positioningPlan.maxSinglePositionPct}%
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>主题上限</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {positioningPlan.maxThemeExposurePct}%
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>事件分</Text>
                <Text
                  style={[
                    styles.metricChipValue,
                    {
                      color:
                        positioningPlan.eventBias === '偏空'
                          ? palette.danger
                          : positioningPlan.eventBias === '偏多'
                            ? palette.success
                            : palette.text,
                    },
                  ]}>
                  {positioningPlan.eventScore.toFixed(0)}
                </Text>
              </View>
            </View>
            {positioningPlan.eventSummary ? (
              <View style={[styles.eventBox, { borderColor: palette.border, backgroundColor: palette.surfaceMuted }]}>
                <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>事件总控</Text>
                <Text style={[styles.reasonText, { color: palette.text }]}>
                  {positioningPlan.eventSummary}
                </Text>
              </View>
            ) : null}
            <View style={styles.reasonList}>
              {positioningPlan.reasons.slice(0, 3).map((reason) => (
                <View key={reason} style={styles.reasonRow}>
                  <View style={[styles.reasonDot, { backgroundColor: palette.tint }]} />
                  <Text style={[styles.reasonText, { color: palette.subtext }]}>{reason}</Text>
                </View>
              ))}
            </View>
            {positioningPlan.deployments.length > 0 ? (
              <View style={styles.reasonList}>
                {positioningPlan.deployments.map((item) => (
                  <Pressable
                    key={item.code}
                    onPress={() => {
                      router.push('/(tabs)/signals');
                    }}
                    style={[styles.riskRow, { borderColor: palette.border }]}>
                    <View style={styles.riskMain}>
                      <View style={styles.riskHeader}>
                        <Text style={[styles.riskCode, { color: palette.text }]}>
                          {item.code} {item.name}
                        </Text>
                        <StatusPill label={`${item.suggestedPositionPct}%`} tone="info" />
                      </View>
                      <Text style={[styles.riskMeta, { color: palette.subtext }]}>
                        {item.setupLabel}
                        {item.themeSector ? ` / ${item.themeSector}` : ''} / 建议金额 {formatCurrency(item.suggestedAmount)}
                      </Text>
                      <Text style={[styles.riskMeta, { color: palette.subtext }]}>{item.reason}</Text>
                    </View>
                    <Text style={[styles.focusAction, { color: palette.tint }]}>去看</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </>
        ) : null}
        <View style={styles.actionRow}>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/positions');
            }}
            style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryActionText}>看组合纪律</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/signals');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看综合推荐</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <SectionHeading title="总指挥台" subtitle="如果今天只先做一件事，就做这里这件。" />
      <SurfaceCard style={styles.primaryTaskCard}>
        <View style={styles.taskHead}>
          <Text style={[styles.taskEyebrow, { color: palette.subtext }]}>{primaryTask.eyebrow}</Text>
          <StatusPill label={primaryTask.tone === 'danger' ? '高优先级' : '当前建议'} tone={primaryTask.tone} />
        </View>
        <Text style={[styles.taskTitle, { color: palette.text }]}>{primaryTask.title}</Text>
        <Text style={[styles.taskSummary, { color: palette.subtext }]}>{primaryTask.summary}</Text>
          <Pressable
            onPress={() => {
              router.push(resolveAppHref(primaryTask.route));
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
          <Text style={styles.primaryButtonText}>{primaryTask.actionLabel}</Text>
        </Pressable>
      </SurfaceCard>

      {governanceAction && governanceAction.id !== topAction?.id ? (
        <SurfaceCard style={styles.governanceCard}>
          <View style={styles.taskHead}>
            <Text style={[styles.taskEyebrow, { color: palette.subtext }]}>系统治理</Text>
            <StatusPill
              label={getActionKindLabel(governanceAction.kind)}
              tone={getActionTone(governanceAction.level)}
            />
          </View>
          <Text style={[styles.todoTitle, { color: palette.text }]}>{governanceAction.title}</Text>
          <Text style={[styles.taskSummary, { color: palette.subtext }]}>{governanceAction.summary}</Text>
          <Pressable
            onPress={() => {
              router.push(resolveAppHref(governanceAction.route ?? '/(tabs)/signals'));
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>
              {governanceAction.actionLabel}
            </Text>
          </Pressable>
        </SurfaceCard>
      ) : null}

      {actionBoard.length > 0 ? (
        <>
          <SectionHeading title="当前待办" subtitle="系统已经把该处理的动作排好序，不用自己翻。" />
          <View style={styles.todoList}>
            {actionBoard.slice(0, 3).map((item) => (
              <Pressable
                key={item.id}
                onPress={() => {
                  router.push(resolveAppHref(item.route ?? '/(tabs)/index'));
                }}>
                <SurfaceCard style={styles.todoCard}>
                  <View style={styles.todoHead}>
                    <View style={styles.todoTitleWrap}>
                      <Text style={[styles.todoTitle, { color: palette.text }]}>{item.title}</Text>
                      <Text style={[styles.todoMeta, { color: palette.subtext }]}>
                        {formatTimestamp(item.createdAt)} / {getActionKindLabel(item.kind)}
                      </Text>
                    </View>
                    <View style={styles.todoPills}>
                      <StatusPill label={getActionKindLabel(item.kind)} tone="info" />
                      <StatusPill label={item.level} tone={getActionTone(item.level)} />
                    </View>
                  </View>
                  <Text style={[styles.todoSummary, { color: palette.subtext }]}>{item.summary}</Text>
                  <Text style={[styles.todoAction, { color: palette.tint }]}>{item.actionLabel}</Text>
                </SurfaceCard>
              </Pressable>
            ))}
          </View>
        </>
      ) : null}

      <SectionHeading title="外部演示路径" subtitle="给投资人或合作方看时，按这个顺序讲，不容易散，也更像正式产品。" />
      <View style={styles.demoGrid}>
        {demoFlow.map((item, index) => (
          <Pressable
            key={item.key}
            onPress={() => {
              router.push(resolveAppHref(item.route));
            }}>
            <SurfaceCard style={styles.demoCard}>
              <View style={styles.demoHead}>
                <View style={[styles.demoBadge, { backgroundColor: palette.accentSoft }]}>
                  <Text style={[styles.demoBadgeText, { color: palette.tint }]}>{index + 1}</Text>
                </View>
                <Text style={[styles.demoTitle, { color: palette.text }]}>{item.title}</Text>
              </View>
              <Text style={[styles.demoCopy, { color: palette.subtext }]}>{item.copy}</Text>
            </SurfaceCard>
          </Pressable>
        ))}
      </View>

      <SectionHeading title="焦点对象" subtitle="把今天最该讲的推荐、风险和学习放在第一屏，不让你翻找。" />
      <View style={styles.deck}>
        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>政策方向雷达</Text>
            <StatusPill
              label={
                topPolicyWatch
                  ? `${topPolicyWatch.policyBucket} / ${topPolicyWatch.industryPhase}`
                  : '读取中'
              }
              tone={topPolicyWatch ? getPolicyWatchTone(topPolicyWatch) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topPolicyWatch
              ? `${topPolicyWatch.direction} 是今天先看大的起点`
              : '正在归纳当前最值得先看的政策方向'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topPolicyWatch
              ? topPolicyWatch.summary
              : '这层会把政策、需求、地缘政治和产业链线索压成一张方向卡。'}
          </Text>
          {topPolicyWatch ? (
            <Text style={[styles.cardCopy, { color: palette.text }]}>{topPolicyWatch.phaseSummary}</Text>
          ) : null}
          {topPolicyWatch ? (
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>政策</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topPolicyWatch.policyScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>趋势</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topPolicyWatch.trendScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>关注度</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topPolicyWatch.attentionScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>资金偏好</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topPolicyWatch.capitalPreferenceScore.toFixed(1)}
                </Text>
              </View>
            </View>
          ) : null}
          {topPolicyWatch ? (
            <View style={styles.heroPills}>
              {topPolicyWatch.upstream[0] ? (
                <StatusPill label={`上游 ${topPolicyWatch.upstream[0]}`} tone="neutral" />
              ) : null}
              {topPolicyWatch.midstream[0] ? (
                <StatusPill label={`中游 ${topPolicyWatch.midstream[0]}`} tone="info" />
              ) : null}
              {topPolicyWatch.downstream[0] ? (
                <StatusPill label={`下游 ${topPolicyWatch.downstream[0]}`} tone="success" />
              ) : null}
              {topPolicyWatch.transmissionPaths[0] ? (
                <StatusPill label={topPolicyWatch.transmissionPaths[0]} tone="warning" />
              ) : null}
            </View>
          ) : null}
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台看政策方向</Text>
          </Pressable>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>产业资本方向</Text>
            <StatusPill
              label={
                topIndustryCapital
                  ? `${topIndustryCapital.strategicLabel} / ${topIndustryCapital.capitalHorizon}`
                  : '读取中'
              }
              tone={topIndustryCapital ? getIndustryCapitalTone(topIndustryCapital) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topIndustryCapital
              ? `${topIndustryCapital.direction} 现在更像一条可以跟踪的产业资本线`
              : '正在把政策方向翻译成事业和资本动作'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topIndustryCapital
              ? topIndustryCapital.summary
              : '这层会把政策、供需、产业链和资金偏好压成一条可执行的方向建议。'}
          </Text>
          {topIndustryCapital ? (
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>优先级</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topIndustryCapital.priorityScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>战略</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topIndustryCapital.strategicScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>需求</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topIndustryCapital.demandScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>供给</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topIndustryCapital.supplyScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>资金偏好</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topIndustryCapital.capitalPreferenceScore.toFixed(1)}
                </Text>
              </View>
            </View>
          ) : null}
          {topIndustryCapital ? (
            <>
              <Text style={[styles.reasonText, { color: palette.text }]}>{topIndustryCapital.businessAction}</Text>
              <Text style={[styles.reasonText, { color: palette.subtext }]}>{topIndustryCapital.capitalAction}</Text>
              <Text style={[styles.reasonText, { color: palette.text }]}>{topIndustryCapital.researchSummary}</Text>
              <Text style={[styles.reasonText, { color: palette.tint }]}>{topIndustryCapital.researchNextAction}</Text>
              <Text style={[styles.reasonText, { color: palette.text }]}>
                最新催化：{topIndustryCapital.latestCatalystTitle} / {topIndustryCapital.currentTimelineStage}
              </Text>
              <Text style={[styles.reasonText, { color: palette.subtext }]}>
                {topIndustryCapital.latestCatalystSummary}
              </Text>
              {topIndustryCapital.officialSourceEntries[0] ? (
                <Text style={[styles.reasonText, { color: palette.subtext }]}>
                  官方原文：{topIndustryCapital.officialSourceEntries[0].issuer}
                  {topIndustryCapital.officialSourceEntries[0].publishedAt
                    ? ` / ${topIndustryCapital.officialSourceEntries[0].publishedAt}`
                    : ''}
                </Text>
              ) : null}
              {topIndustryCapital.companyWatchlist[0] ? (
                <Text style={[styles.reasonText, { color: palette.text }]}>
                  重点跟踪：{topIndustryCapital.companyWatchlist[0].code ? `${topIndustryCapital.companyWatchlist[0].code} ` : ''}
                  {topIndustryCapital.companyWatchlist[0].name} / {topIndustryCapital.companyWatchlist[0].priorityLabel} /{' '}
                  {topIndustryCapital.companyWatchlist[0].marketAlignment} / {topIndustryCapital.companyWatchlist[0].timelineAlignment}
                </Text>
              ) : null}
              {topIndustryCapital.companyWatchlist[0]?.recentResearchNote ? (
                <Text style={[styles.reasonText, { color: palette.tint }]}>
                  最近调研：{topIndustryCapital.companyWatchlist[0].recentResearchNote}
                </Text>
              ) : null}
            </>
          ) : null}
          {topIndustryCapital ? (
            <View style={styles.heroPills}>
              <StatusPill label={`事业 ${topIndustryCapital.businessHorizon}`} tone="neutral" />
              <StatusPill label={`资本 ${topIndustryCapital.capitalHorizon}`} tone="info" />
              <StatusPill label={`阶段 ${topIndustryCapital.currentTimelineStage}`} tone="neutral" />
              <StatusPill label={topIndustryCapital.officialFreshnessLabel} tone="warning" />
              <StatusPill
                label={topIndustryCapital.researchSignalLabel}
                tone={getIndustryResearchTone(topIndustryCapital.researchSignalLabel)}
              />
              {topIndustryCapital.opportunities[0] ? (
                <StatusPill label={topIndustryCapital.opportunities[0]} tone="success" />
              ) : null}
            </View>
          ) : null}
          <View style={styles.actionRow}>
            <Pressable
              onPress={() => {
                if (topIndustryCapital) {
                  router.push(resolveAppHref(`/industry-capital/${topIndustryCapital.id}`));
                  return;
                }
                router.push('/(tabs)/brain');
              }}
              style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryActionText}>看方向深页</Text>
            </Pressable>
            <Pressable
              onPress={() => {
                router.push('/(tabs)/brain');
              }}
              style={[styles.secondaryAction, { borderColor: palette.border }]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台看产业资本</Text>
            </Pressable>
          </View>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>主线发现与阶段引擎</Text>
            <StatusPill
              label={topThemeStage ? `${topThemeStage.stageLabel} / ${topThemeStage.participationLabel}` : '读取中'}
              tone={topThemeStage ? getThemeStageTone(topThemeStage) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topThemeStage ? `${topThemeStage.sector} 是当前最值得先看的大方向` : '正在计算当前最值得先看的大方向'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topThemeStage
              ? topThemeStage.summary
              : '这层会把政策/事件、趋势、关注度、资金偏好和阶段位置压成同一张主线卡。'}
          </Text>
          {topThemeStage ? (
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>方向</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topThemeStage.directionScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>趋势</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topThemeStage.trendScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>关注度</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topThemeStage.attentionScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>资金偏好</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topThemeStage.capitalPreferenceScore.toFixed(1)}
                </Text>
              </View>
            </View>
          ) : null}
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台看阶段</Text>
          </Pressable>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>综合榜接管预备</Text>
            <StatusPill
              label={compositeCompare?.readiness.label ?? '继续影子'}
              tone={getReadinessTone(compositeCompare?.readiness.status ?? 'shadow')}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topCompositePick ? `${topCompositePick.code} ${topCompositePick.name}` : '综合榜当前没有焦点候选'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {getCompositeSummary(topCompositePick, compositeCompare)}
          </Text>
          {topCompositePick ? (
            <View style={styles.heroPills}>
              <StatusPill
                label={topCompositePick.sourceLabel}
                tone={getCompositeSourceTone(topCompositePick.sourceCategory)}
              />
              <StatusPill label={topCompositePick.horizonLabel} tone="neutral" />
              {topCompositePick.themeSector ? (
                <StatusPill label={topCompositePick.themeSector} tone="info" />
              ) : null}
            </View>
          ) : null}
          {topCompositePick ? (
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>综合分</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {topCompositePick.compositeScore.toFixed(1)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>事件</Text>
                <Text
                  style={[
                    styles.metricChipValue,
                    {
                      color:
                        topCompositePick.eventBias === '偏多'
                          ? palette.success
                          : topCompositePick.eventBias === '偏空'
                            ? palette.danger
                            : palette.text,
                    },
                  ]}>
                  {topCompositePick.eventBias}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>首仓</Text>
                <Text style={[styles.metricChipValue, { color: palette.tint }]}>
                  {topCompositePick.firstPositionPct}%
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>置信</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {compositeCompare?.readiness.confidenceScore.toFixed(0) ?? '--'}
                </Text>
              </View>
            </View>
          ) : null}
          {compositeCompare ? (
            <>
              <View style={[styles.eventBox, { borderColor: palette.border, backgroundColor: palette.surfaceMuted }]}>
                <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>为什么还没切</Text>
                <Text style={[styles.reasonText, { color: palette.text }]}>
                  {compositeCompare.readiness.summary}
                </Text>
                <Text style={[styles.reasonText, { color: palette.subtext }]}>
                  {compositeCompare.readiness.recommendedAction}
                </Text>
              </View>
              <View style={styles.reasonList}>
                {compositeCompare.readiness.conditions.map((item) => (
                  <View key={item} style={styles.reasonRow}>
                    <View style={[styles.reasonDot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.reasonText, { color: palette.subtext }]}>{item}</Text>
                  </View>
                ))}
              </View>
            </>
          ) : null}
          <View style={styles.actionRow}>
            <Pressable
              onPress={() => {
                router.push('/(tabs)/signals');
              }}
              style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryActionText}>看接管判断</Text>
            </Pressable>
            <Pressable
              disabled={!topCompositePick}
              onPress={() => {
                if (!topCompositePick) {
                  return;
                }
                if (canOpenCompositeDetail(topCompositePick)) {
                  router.push({ pathname: '/signal/[id]', params: { id: topCompositePick.signalId } });
                  return;
                }
                router.push('/(tabs)/brain');
              }}
              style={[
                styles.secondaryAction,
                { borderColor: palette.border, opacity: topCompositePick ? 1 : 0.5 },
              ]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>
                {canOpenCompositeDetail(topCompositePick) ? '看综合详情' : '去决策台复核'}
              </Text>
            </Pressable>
          </View>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>首推推荐</Text>
            <StatusPill
              label={data?.system.todaySignals === 0 ? '最近一次推荐' : '新推荐'}
              tone={data?.system.todaySignals === 0 ? 'warning' : 'info'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {latestSignal ? `${latestSignal.code} ${latestSignal.name}` : '今天还没有新的推荐'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {latestSignal
              ? `${formatTimestamp(latestSignal.timestamp)} / 评分 ${latestSignal.score.toFixed(3)} / 当前价 ${latestSignal.price.toFixed(2)} / 风险收益比 ${latestSignal.riskReward.toFixed(1)}`
              : '系统今天没出新触发，可以先去决策台手动诊股。'}
          </Text>
          {latestSignal ? (
            <View style={styles.metricStrip}>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>入场</Text>
                <Text style={[styles.metricChipValue, { color: palette.text }]}>
                  {latestSignal.buyPrice.toFixed(2)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>止损</Text>
                <Text style={[styles.metricChipValue, { color: palette.danger }]}>
                  {latestSignal.stopLoss.toFixed(2)}
                </Text>
              </View>
              <View style={styles.metricChip}>
                <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>目标</Text>
                <Text style={[styles.metricChipValue, { color: palette.success }]}>
                  {latestSignal.targetPrice.toFixed(2)}
                </Text>
              </View>
            </View>
          ) : null}
          <View style={styles.actionRow}>
            <Pressable
              disabled={!latestSignal}
              onPress={() => {
                if (!latestSignal) {
                  return;
                }
                router.push({ pathname: '/signal/[id]', params: { id: latestSignal.id } });
              }}
              style={[
                styles.primaryAction,
                { backgroundColor: latestSignal ? palette.tint : palette.icon },
              ]}>
              <Text style={styles.primaryActionText}>看推荐详情</Text>
            </Pressable>
            <Pressable
              onPress={() => {
                router.push('/(tabs)/signals');
              }}
              style={[styles.secondaryAction, { borderColor: palette.border }]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看推荐队列</Text>
            </Pressable>
          </View>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>强势收益引擎</Text>
            <StatusPill
              label={topStrongMove ? topStrongMove.setupLabel : '暂无候选'}
              tone={topStrongMove ? getStrongMoveTone(topStrongMove) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topStrongMove ? `${topStrongMove.code} ${topStrongMove.name}` : '今天还没有高质量强势股候选'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topStrongMove
              ? `${getStrongMoveSummary(topStrongMove)} / ${topStrongMove.thesis}`
              : '这块专门找大波段和连涨候选，不跟全部推荐混在一起。'}
          </Text>
          {topStrongMove ? (
            <>
              <View style={styles.metricStrip}>
                <View style={styles.metricChip}>
                  <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>综合分</Text>
                  <Text style={[styles.metricChipValue, { color: palette.text }]}>
                    {topStrongMove.compositeScore.toFixed(0)}
                  </Text>
                </View>
                <View style={styles.metricChip}>
                  <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>首仓位</Text>
                  <Text style={[styles.metricChipValue, { color: palette.tint }]}>
                    {topStrongMove.conviction === 'high' ? '12%-15%' : '8%-10%'}
                  </Text>
                </View>
                <View style={styles.metricChip}>
                  <Text style={[styles.metricChipLabel, { color: palette.subtext }]}>止损</Text>
                  <Text style={[styles.metricChipValue, { color: palette.danger }]}>
                    {topStrongMove.stopLoss.toFixed(2)}
                  </Text>
                </View>
              </View>
              <View style={styles.reasonList}>
                {topStrongMove.reasons.map((reason) => (
                  <View key={`${topStrongMove.id}-${reason}`} style={styles.reasonRow}>
                    <View style={[styles.reasonDot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.reasonText, { color: palette.subtext }]}>{reason}</Text>
                  </View>
                ))}
              </View>
              <Text style={[styles.cardCopy, { color: palette.subtext }]}>{topStrongMove.nextStep}</Text>
            </>
          ) : null}
          <View style={styles.actionRow}>
            <Pressable
              disabled={!topStrongMove}
              onPress={() => {
                if (!topStrongMove) {
                  return;
                }
                router.push({ pathname: '/signal/[id]', params: { id: topStrongMove.signalId } });
              }}
              style={[
                styles.primaryAction,
                { backgroundColor: topStrongMove ? palette.tint : palette.icon },
              ]}>
              <Text style={styles.primaryActionText}>看强势详情</Text>
            </Pressable>
            <Pressable
              onPress={() => {
                router.push('/(tabs)/signals');
              }}
              style={[styles.secondaryAction, { borderColor: palette.border }]}>
              <Text style={[styles.secondaryActionText, { color: palette.tint }]}>回推荐页</Text>
            </Pressable>
          </View>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>风险仓位</Text>
            <StatusPill
              label={riskyPositions.length > 0 ? `${riskyPositions.length} 个优先处理` : '暂无异常'}
              tone={riskyPositions.length > 0 ? 'warning' : 'success'}
            />
          </View>
          {riskyPositions.length === 0 ? (
            <Text style={[styles.cardCopy, { color: palette.subtext }]}>
              当前没有持仓异动，组合整体处在可控区间。
            </Text>
          ) : (
            riskyPositions.map((position) => {
              const stopBufferPct = getStopBufferPct(position);
              return (
                <Pressable
                  key={position.code}
                  onPress={() => {
                    router.push({ pathname: '/position/[code]', params: { code: position.code } });
                  }}
                  style={[styles.riskRow, { borderColor: palette.border }]}>
                  <View style={styles.riskMain}>
                    <View style={styles.riskHeader}>
                      <Text style={[styles.riskCode, { color: palette.text }]}>
                        {position.code} {position.name}
                      </Text>
                      <StatusPill label={getPositionRiskLabel(position)} tone={getPositionRiskTone(position)} />
                    </View>
                    <Text style={[styles.riskMeta, { color: palette.subtext }]}>
                      当前价 {position.currentPrice.toFixed(2)} / 止损 {position.stopLoss.toFixed(2)} / 距离止损{' '}
                      {stopBufferPct === null ? '--' : formatPercent(stopBufferPct / 100)}
                    </Text>
                    <Text
                      style={[
                        styles.riskMeta,
                        { color: position.profitLossPct >= 0 ? palette.success : palette.danger },
                      ]}>
                      浮盈 {formatCurrency(position.profitLoss)} / {formatPercent(position.profitLossPct / 100)}
                    </Text>
                  </View>
                  <Text style={[styles.focusAction, { color: palette.tint }]}>处理</Text>
                </Pressable>
              );
            })
          )}
          <Pressable
            onPress={() => {
              router.push('/(tabs)/positions');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看全部持仓</Text>
          </Pressable>
        </SurfaceCard>
      </View>

      <SectionHeading
        title="综合来源分层"
        subtitle="把主线种子、中期波段和普通策略候选拆开看，先知道今天该盯哪一类。"
      />
      <View style={styles.deck}>
        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>主线种子</Text>
            <StatusPill
              label={topThemeSeedPick ? topThemeSeedPick.horizonLabel : '暂无'}
              tone={topThemeSeedPick ? getCompositeSourceTone(topThemeSeedPick.sourceCategory) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topThemeSeedPick
              ? `${topThemeSeedPick.code} ${topThemeSeedPick.name}`
              : '今天还没有新的主线孵化候选'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topThemeSeedPick
              ? `${topThemeSeedPick.themeSector ?? '主线观察'} / ${topThemeSeedPick.sourceLabel} / 首仓 ${topThemeSeedPick.firstPositionPct}% / ${topThemeSeedPick.action}`
              : '这层专门提前暴露主线和资金先盯上的票，不要求先有原始策略信号。'}
          </Text>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台复核</Text>
          </Pressable>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>中期波段 / 连涨</Text>
            <StatusPill
              label={topSwingCompositePick ? topSwingCompositePick.horizonLabel : '暂无'}
              tone={topSwingCompositePick ? 'warning' : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topSwingCompositePick
              ? `${topSwingCompositePick.code} ${topSwingCompositePick.name}`
              : '今天还没有中期波段或连涨接力候选'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topSwingCompositePick
              ? `${topSwingCompositePick.sourceLabel} / 综合分 ${topSwingCompositePick.compositeScore.toFixed(1)} / ${topSwingCompositePick.action}`
              : '这层专门看更可能走成波段和续强的票，不和普通短线观察混在一起。'}
          </Text>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/signals');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去推荐页看分层</Text>
          </Pressable>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>策略候选</Text>
            <StatusPill
              label={topStrategyCompositePick ? topStrategyCompositePick.sourceLabel : '暂无'}
              tone={topStrategyCompositePick ? getCompositeSourceTone(topStrategyCompositePick.sourceCategory) : 'neutral'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {topStrategyCompositePick
              ? `${topStrategyCompositePick.code} ${topStrategyCompositePick.name}`
              : '今天还没有需要讲的策略候选'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {topStrategyCompositePick
              ? `${topStrategyCompositePick.horizonLabel} / 事件${topStrategyCompositePick.eventBias} / 首仓 ${topStrategyCompositePick.firstPositionPct}%`
              : '这层还是传统策略池，但已经被事件、资金和执行纪律重新排过序。'}
          </Text>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/signals');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看综合推荐</Text>
          </Pressable>
        </SurfaceCard>
      </View>

      <SectionHeading title="学习与外发镜像" subtitle="让你知道系统有没有进步、外面又看到了什么。" />
      <View style={styles.deck}>
        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>日日精进</Text>
            <StatusPill
              label={data?.dailyAdvance.todayCompleted ? '已完成' : '待执行'}
              tone={data?.dailyAdvance.todayCompleted ? 'success' : 'warning'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {data?.dailyAdvance.summary ?? '正在读取学习状态'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            最近完成 {data?.dailyAdvance.lastCompletedAt ? formatTimestamp(data.dailyAdvance.lastCompletedAt) : '暂无'} / 入库 {data?.dailyAdvance.ingestedSignals ?? '--'} / 验证 {data?.dailyAdvance.verifiedSignals ?? '--'}
          </Text>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}
            style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryActionText}>去决策台</Text>
          </Pressable>
        </SurfaceCard>

        <SurfaceCard style={styles.decisionCard}>
          <View style={styles.cardHead}>
            <Text style={[styles.cardEyebrow, { color: palette.subtext }]}>微信镜像</Text>
            <StatusPill
              label={permissionState === 'granted' ? '通知已开' : '通知待开'}
              tone={permissionState === 'granted' ? 'success' : 'warning'}
            />
          </View>
          <Text style={[styles.cardTitle, { color: palette.text }]}>
            {latestMessage ? latestMessage.title : '当前还没有镜像消息'}
          </Text>
          <Text style={[styles.cardCopy, { color: palette.subtext }]}>
            {latestMessage
              ? `${formatTimestamp(latestMessage.createdAt)} / ${latestMessage.channel} / ${latestMessage.preview}`
              : '推荐、告警和学习结果发出去后，这里会自动镜像回来。'}
          </Text>
          <Pressable
            onPress={() => {
              router.push('/messages');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看消息中心</Text>
          </Pressable>
        </SurfaceCard>
      </View>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  hero: {
    borderRadius: 28,
    padding: 24,
    gap: 12,
  },
  heroEyebrow: {
    color: '#8CC7FF',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  heroTitle: {
    color: '#F7FBFF',
    fontSize: 28,
    fontWeight: '800',
    lineHeight: 34,
  },
  heroCopy: {
    color: '#C8D8EB',
    fontSize: 15,
    lineHeight: 22,
  },
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  channelHub: {
    gap: 14,
  },
  chainBoard: {
    gap: 12,
  },
  channelGrid: {
    gap: 12,
  },
  channelPanel: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 12,
  },
  channelTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  channelCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  directionSummaryGrid: {
    gap: 12,
  },
  directionSummaryCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 10,
  },
  directionSummaryHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  directionSummaryEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.1,
    textTransform: 'uppercase',
  },
  directionSummaryTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  directionSummaryCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  directionSummaryBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  chainCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 8,
  },
  chainStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  chainTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  chainLabel: {
    fontSize: 13,
    lineHeight: 20,
  },
  chainCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  primaryTaskCard: {
    gap: 14,
  },
  governanceCard: {
    gap: 12,
  },
  todoList: {
    gap: 12,
  },
  todoCard: {
    gap: 10,
  },
  todoHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  todoTitleWrap: {
    flex: 1,
    gap: 4,
  },
  todoTitle: {
    fontSize: 17,
    fontWeight: '800',
    lineHeight: 23,
  },
  todoMeta: {
    fontSize: 12,
    lineHeight: 18,
  },
  todoPills: {
    alignItems: 'flex-end',
    gap: 8,
  },
  todoSummary: {
    fontSize: 14,
    lineHeight: 22,
  },
  todoAction: {
    fontSize: 14,
    fontWeight: '800',
  },
  taskHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  taskEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.1,
    textTransform: 'uppercase',
  },
  taskTitle: {
    fontSize: 24,
    fontWeight: '800',
    lineHeight: 31,
  },
  taskSummary: {
    fontSize: 15,
    lineHeight: 23,
  },
  primaryButton: {
    minHeight: 48,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
  deck: {
    gap: 14,
  },
  demoGrid: {
    gap: 12,
  },
  demoCard: {
    gap: 10,
  },
  demoHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  demoBadge: {
    width: 28,
    height: 28,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  demoBadgeText: {
    fontSize: 13,
    fontWeight: '800',
  },
  demoTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
    lineHeight: 22,
  },
  demoCopy: {
    fontSize: 14,
    lineHeight: 21,
  },
  decisionCard: {
    gap: 14,
  },
  cardHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  cardEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.1,
    textTransform: 'uppercase',
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  cardCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  metricStrip: {
    flexDirection: 'row',
    gap: 10,
  },
  metricChip: {
    flex: 1,
    borderRadius: 18,
    padding: 12,
    backgroundColor: 'rgba(21, 94, 239, 0.07)',
    gap: 4,
  },
  metricChipLabel: {
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  metricChipValue: {
    fontSize: 17,
    fontWeight: '800',
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryAction: {
    flex: 1,
    minHeight: 46,
    borderRadius: 16,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryActionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  secondaryAction: {
    borderWidth: 1,
    borderRadius: 16,
    minHeight: 46,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryActionText: {
    fontSize: 14,
    fontWeight: '800',
  },
  riskRow: {
    borderWidth: 1,
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  riskMain: {
    gap: 6,
  },
  riskHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  riskCode: {
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
  },
  riskMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  focusAction: {
    fontSize: 13,
    fontWeight: '800',
  },
  reasonList: {
    gap: 8,
  },
  eventBox: {
    borderWidth: 1,
    borderRadius: 18,
    padding: 14,
    gap: 8,
  },
  reasonRow: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'center',
  },
  reasonDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
  },
  reasonText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 20,
  },
});
