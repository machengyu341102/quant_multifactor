import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { resolveAppHref } from '@/lib/app-routes';
import { formatPercent, formatTimestamp } from '@/lib/format';
import {
  getCompositeCompare,
  getCompositePicks,
  getCompositeReplay,
  getIndustryCapital,
  getPolicyWatch,
  getPositioningPlan,
  getSignals,
  getSystemStatus,
} from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type {
  CompositePick,
  CompositeReplayItem,
  IndustryCapitalDirection,
  PolicyWatchItem,
  PositioningPlan,
  RecommendationCompareSnapshot,
  Signal,
  SystemStatus,
} from '@/types/trading';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function buildRecommendation(signal: Signal): {
  verdict: string;
  tone: Tone;
  summary: string;
  reasons: string[];
  riskText: string;
  actionHint: string;
} {
  const reasons = [
    `${signal.strategy} 当前在发出这条推荐。`,
    `综合评分 ${signal.score.toFixed(3)}，风险收益比 ${signal.riskReward.toFixed(1)}。`,
  ];

  if (signal.consensusCount > 1) {
    reasons.push(`${signal.consensusCount} 个策略同时给出共识。`);
  } else if (signal.changePct > 0 && signal.changePct < 4) {
    reasons.push('涨幅还没有失控，位置不算特别拥挤。');
  } else if (signal.changePct <= 0) {
    reasons.push('当天没有明显冲高，适合继续观察入场节奏。');
  }

  if (signal.score >= 0.92 && signal.riskReward >= 2) {
    return {
      verdict: '可以执行',
      tone: 'success',
      summary: '评分和盈亏结构同时在线，适合优先做完整判断。',
      reasons: reasons.slice(0, 3),
      riskText: `止损 ${signal.stopLoss.toFixed(2)}，目标 ${signal.targetPrice.toFixed(2)}，失效就不要硬扛。`,
      actionHint: '先看详情，确认位置和环境后再下第一笔。',
    };
  }

  if (signal.changePct >= 5) {
    return {
      verdict: '不建议追高',
      tone: 'warning',
      summary: '票不一定差，但当前位置太热，先防止情绪化追价。',
      reasons: reasons.slice(0, 2),
      riskText: `当前涨幅 ${formatPercent(signal.changePct / 100)}，更适合等回落或去诊股确认。`,
      actionHint: '先放进观察队列，等位置舒服再说。',
    };
  }

  if (signal.score >= 0.84) {
    return {
      verdict: '优先观察',
      tone: 'info',
      summary: '信号质量够看，但还差最后一脚确认。',
      reasons: reasons.slice(0, 3),
      riskText: `先盯 ${signal.stopLoss.toFixed(2)} 这条线，没把握就别急着执行。`,
      actionHint: '适合去决策台复诊，确认环境和个股状态。',
    };
  }

  return {
    verdict: '继续观察',
    tone: 'warning',
    summary: '这条推荐更像备选，不值得抢在最前面出手。',
    reasons: reasons.slice(0, 2),
    riskText: `评分还不够硬，先观察而不是直接上手。止损线 ${signal.stopLoss.toFixed(2)}。`,
    actionHint: '保留在推荐池里，等更强信号或更好位置。',
  };
}

function buildCompositeRecommendation(pick: CompositePick): {
  verdict: string;
  tone: Tone;
  summary: string;
} {
  if (pick.eventBias === '偏空' && pick.eventScore < 45) {
    return {
      verdict: '事件压制',
      tone: 'warning',
      summary: '宏观事件面对这类方向不友好，综合层会先降权，再决定是否保留观察。',
    };
  }

  if (pick.themeIntensity === '高热主线' && pick.compositeScore >= 76) {
    return {
      verdict: '主线共振',
      tone: 'success',
      summary: '事件、资金和策略已经进入同一方向，这类票优先级应该高于普通推荐。',
    };
  }

  if (pick.compositeScore >= 74) {
    return {
      verdict: '综合优先',
      tone: 'success',
      summary: '综合评分已经进入进攻区间，适合先打首仓再看确认。',
    };
  }

  if (pick.compositeScore >= 66) {
    return {
      verdict: '重点观察',
      tone: 'info',
      summary: '不是最强共振，但已经值得放到第一批观察名单。',
    };
  }

  return {
    verdict: '备选观察',
    tone: 'warning',
    summary: '这条更适合留在影子候选池里，等待主线和量能继续确认。',
  };
}

function getReplayTone(item: CompositeReplayItem): Tone {
  if (item.reviewLabel === '验证通过' || item.reviewLabel === '波段兑现') {
    return 'success';
  }
  if (item.reviewLabel === '短线承接') {
    return 'info';
  }
  if (item.reviewLabel === '待观察') {
    return 'neutral';
  }
  return 'warning';
}

function getCompareTone(label: string): Tone {
  if (label.includes('综合领先')) {
    return 'success';
  }
  if (label.includes('原推荐领先')) {
    return 'warning';
  }
  if (label.includes('接近')) {
    return 'info';
  }
  return 'neutral';
}

function getReadinessTone(status: string): Tone {
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

function getCompositeSourceTone(category: string): Tone {
  if (category === 'theme_seed' || category === 'resonance') {
    return 'success';
  }
  if (category === 'strong_move') {
    return 'info';
  }
  return 'neutral';
}

function getPolicyWatchTone(item: PolicyWatchItem): Tone {
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

function getIndustryCapitalTone(item: IndustryCapitalDirection): Tone {
  if (item.strategicLabel === '逆风跟踪') {
    return 'warning';
  }
  if (item.participationLabel === '中期波段' || item.participationLabel === '连涨接力') {
    return 'success';
  }
  return 'info';
}

function canOpenCompositeDetail(pick: CompositePick | null): boolean {
  return Boolean(pick && pick.sourceCategory !== 'theme_seed' && !pick.signalId.startsWith('theme-seed-'));
}

async function loadSignalsScreen(token?: string): Promise<{
  signals: Signal[];
  compositePicks: CompositePick[];
  compositeReplay: CompositeReplayItem[];
  compositeCompare: RecommendationCompareSnapshot;
  system: SystemStatus;
  policyWatch: PolicyWatchItem[];
  industryCapital: IndustryCapitalDirection[];
  positioningPlan: PositioningPlan;
}> {
  const [signals, compositePicks, compositeReplay, compositeCompare, system, policyWatch, industryCapital, positioningPlan] = await Promise.all([
    getSignals(token),
    getCompositePicks(token),
    getCompositeReplay(token),
    getCompositeCompare(token),
    getSystemStatus(token),
    getPolicyWatch(token),
    getIndustryCapital(token),
    getPositioningPlan(token),
  ]);

  return { signals, compositePicks, compositeReplay, compositeCompare, system, policyWatch, industryCapital, positioningPlan };
}

export default function SignalsScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => loadSignalsScreen(token ?? undefined),
    [token, apiBaseUrl]
  );
  const signals = data?.signals ?? [];
  const compositePicks = data?.compositePicks ?? [];
  const compositeReplay = data?.compositeReplay ?? [];
  const compositeCompare = data?.compositeCompare;
  const system = data?.system;
  const policyWatch = data?.policyWatch ?? [];
  const industryCapital = data?.industryCapital ?? [];
  const positioningPlan = data?.positioningPlan ?? null;
  const focusSignal = signals[0] ?? null;
  const focusRecommendation = focusSignal ? buildRecommendation(focusSignal) : null;
  const focusComposite = compositePicks[0] ?? null;
  const focusCompositeRecommendation = focusComposite ? buildCompositeRecommendation(focusComposite) : null;
  const topPolicyWatch = policyWatch[0] ?? null;
  const topIndustryCapital = industryCapital[0] ?? null;
  const queuedCompositePicks = focusComposite
    ? compositePicks.filter((item) => item.id !== focusComposite.id)
    : compositePicks;
  const themeSeedPicks = queuedCompositePicks.filter((item) => item.sourceCategory === 'theme_seed');
  const swingCompositePicks = queuedCompositePicks.filter(
    (item) => item.horizonLabel === '中期波段' || item.horizonLabel === '连涨接力'
  );
  const strategyCompositePicks = queuedCompositePicks.filter(
    (item) => item.sourceCategory !== 'theme_seed' && item.horizonLabel !== '中期波段' && item.horizonLabel !== '连涨接力'
  );

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading
        eyebrow="Recommendation Desk"
        title="推荐"
        subtitle="这页只干一件事：把今天最值得看的推荐先讲明白，再把其他候选排好顺序。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>RECOMMENDATION DESK</Text>
        <Text style={styles.heroTitle}>
          {focusSignal ? `${focusSignal.code} ${focusSignal.name} 是当前焦点` : '当前没有新的高质量推荐'}
        </Text>
        <Text style={styles.heroCopy}>
          {focusSignal
            ? `${focusRecommendation?.summary} ${focusRecommendation?.actionHint}`
            : '今天没有新的强推荐时，这里会明确告诉你不要空转，而是去决策台手动诊股。'}
        </Text>
        <View style={styles.heroPills}>
          <StatusPill label={`今日新信号 ${system?.todaySignals ?? 0}`} tone="info" />
          <StatusPill label={`${signals.length} 条推荐`} tone="neutral" />
          <StatusPill
            label={focusSignal ? formatTimestamp(focusSignal.timestamp) : '暂无时间'}
            tone={focusSignal ? 'success' : 'warning'}
          />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在拉取推荐列表" />

      <SectionHeading
        title="推荐前置约束"
        subtitle="推荐不是孤立票单，先服从政策方向、产业方向和仓位计划，再谈执行。"
      />
      <SurfaceCard style={styles.contextBoard}>
        <View style={styles.contextGrid}>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}>
            <View style={[styles.contextCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <View style={styles.contextHead}>
                <Text style={[styles.contextEyebrow, { color: palette.subtext }]}>政策方向</Text>
                <StatusPill
                  label={topPolicyWatch ? topPolicyWatch.stageLabel : '读取中'}
                  tone={topPolicyWatch ? getPolicyWatchTone(topPolicyWatch) : 'neutral'}
                />
              </View>
              <Text style={[styles.contextTitle, { color: palette.text }]}>
                {topPolicyWatch ? topPolicyWatch.direction : '正在读取政策方向'}
              </Text>
              <Text style={[styles.contextMeta, { color: palette.subtext }]}>
                {topPolicyWatch
                  ? `${topPolicyWatch.policyBucket} / ${topPolicyWatch.focusSector} / ${topPolicyWatch.industryPhase}`
                  : '先判断政策、地缘和需求变化落在哪条线上。'}
              </Text>
              <Text style={[styles.contextCopy, { color: palette.text }]}>
                {topPolicyWatch?.action ?? '去决策台先看政策方向雷达。'}
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
            <View style={[styles.contextCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <View style={styles.contextHead}>
                <Text style={[styles.contextEyebrow, { color: palette.subtext }]}>产业方向</Text>
                <StatusPill
                  label={topIndustryCapital ? topIndustryCapital.capitalHorizon : '读取中'}
                  tone={topIndustryCapital ? getIndustryCapitalTone(topIndustryCapital) : 'neutral'}
                />
              </View>
              <Text style={[styles.contextTitle, { color: palette.text }]}>
                {topIndustryCapital ? topIndustryCapital.direction : '正在读取产业方向'}
              </Text>
              <Text style={[styles.contextMeta, { color: palette.subtext }]}>
                {topIndustryCapital
                  ? `${topIndustryCapital.policyBucket} / ${topIndustryCapital.focusSector} / ${topIndustryCapital.strategicLabel}`
                  : '把政策主线翻译成事业动作、资本动作和重点跟踪对象。'}
              </Text>
              <Text style={[styles.contextCopy, { color: palette.text }]}>
                {topIndustryCapital?.capitalAction ?? '去方向深页看催化、时间轴和验证门槛。'}
              </Text>
            </View>
          </Pressable>

          <Pressable
            onPress={() => {
              router.push('/(tabs)/positions');
            }}>
            <View style={[styles.contextCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <View style={styles.contextHead}>
                <Text style={[styles.contextEyebrow, { color: palette.subtext }]}>仓位计划</Text>
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
              <Text style={[styles.contextTitle, { color: palette.text }]}>
                {positioningPlan
                  ? `目标总仓 ${positioningPlan.targetExposurePct.toFixed(0)}% / 首仓 ${positioningPlan.firstEntryPositionPct}%`
                  : '正在读取仓位计划'}
              </Text>
              <Text style={[styles.contextMeta, { color: palette.subtext }]}>
                {positioningPlan
                  ? `事件 ${positioningPlan.eventBias} / 单票 ${positioningPlan.maxSinglePositionPct}% / 主题 ${positioningPlan.maxThemeExposurePct}%`
                  : '先决定总仓和分仓，再决定今天这批推荐怎么处理。'}
              </Text>
              <Text style={[styles.contextCopy, { color: palette.text }]}>
                {positioningPlan?.eventSummary ?? '去持仓纪律页看仓位与风控部署。'}
              </Text>
            </View>
          </Pressable>
        </View>
      </SurfaceCard>

      {system?.todaySignals === 0 && focusSignal ? (
        <SurfaceCard style={styles.noticeCard}>
          <Text style={[styles.noticeTitle, { color: palette.text }]}>今天没有新的触发推荐</Text>
          <Text style={[styles.noticeCopy, { color: palette.subtext }]}>
            下面展示最近一次有效推荐，时间 {formatTimestamp(focusSignal.timestamp)}。这不是系统坏了，是今天没有新的高质量触发。
          </Text>
        </SurfaceCard>
      ) : null}

      {compositePicks.length > 0 ? (
        <>
          <SectionHeading
            title="综合推荐榜"
            subtitle="影子模式并行运行。它把事件、资金、策略和执行条件放在一起，比老推荐链更综合。"
          />
          <SurfaceCard style={styles.compositeCard}>
            <View style={styles.focusHead}>
              <View style={styles.focusTitleWrap}>
                <Text style={[styles.focusCode, { color: palette.text }]}>
                  {focusComposite?.code} {focusComposite?.name}
                </Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  {focusComposite?.themeSector
                    ? `${focusComposite.themeSector} / ${focusComposite.themeIntensity ?? '主线观察'} / `
                    : ''}
                  {focusComposite?.sourceLabel ?? '策略候选'} / {focusComposite?.horizonLabel ?? '短线观察'} /{' '}
                  {formatTimestamp(focusComposite?.timestamp ?? '')} / 事件{focusComposite?.eventBias ?? '中性'} / 建议首仓{' '}
                  {focusComposite?.firstPositionPct ?? 0}%
                </Text>
              </View>
              <StatusPill
                label={focusCompositeRecommendation?.verdict ?? '综合观察'}
                tone={focusCompositeRecommendation?.tone ?? 'neutral'}
              />
            </View>

            <View style={styles.heroPills}>
              <StatusPill
                label={focusComposite?.sourceLabel ?? '策略候选'}
                tone={getCompositeSourceTone(focusComposite?.sourceCategory ?? 'strategy')}
              />
              <StatusPill label={focusComposite?.horizonLabel ?? '短线观察'} tone="neutral" />
              {focusComposite?.themeSector ? (
                <StatusPill label={focusComposite.themeSector} tone="info" />
              ) : null}
            </View>

            <Text style={[styles.focusSummary, { color: palette.text }]}>
              {focusCompositeRecommendation?.summary}
            </Text>
            <Text style={[styles.hintText, { color: palette.subtext }]}>{focusComposite?.thesis}</Text>

            <View style={styles.metricGrid}>
              <MetricCard label="综合分" value={`${focusComposite?.compositeScore.toFixed(1) ?? '--'}`} tone="success" />
              <MetricCard label="策略分" value={`${focusComposite?.strategyScore.toFixed(1) ?? '--'}`} tone="info" />
              <MetricCard label="资金分" value={`${focusComposite?.capitalScore.toFixed(1) ?? '--'}`} tone="warning" />
              <MetricCard label="主题分" value={`${focusComposite?.themeScore.toFixed(1) ?? '--'}`} tone="neutral" />
              <MetricCard
                label="事件分"
                value={`${focusComposite?.eventScore.toFixed(1) ?? '--'}`}
                tone={
                  focusComposite?.eventBias === '偏多'
                    ? 'success'
                    : focusComposite?.eventBias === '偏空'
                      ? 'danger'
                      : 'neutral'
                }
              />
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.listTitle, { color: palette.text }]}>为什么入榜</Text>
              {(focusComposite?.reasons ?? []).map((reason) => (
                <View key={reason} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                  <Text style={[styles.listText, { color: palette.text }]}>{reason}</Text>
                </View>
              ))}
            </View>

            <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.hintTitle, { color: palette.text }]}>事件总控</Text>
              <Text style={[styles.hintText, { color: palette.subtext }]}>
                {focusComposite?.eventSummary ?? '事件面暂无明确偏向，当前按中性看待。'}
              </Text>
            </View>

            <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.hintTitle, { color: palette.text }]}>建议动作</Text>
              <Text style={[styles.hintText, { color: palette.subtext }]}>{focusComposite?.action}</Text>
            </View>

            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  if (!focusComposite) {
                    return;
                  }
                  if (canOpenCompositeDetail(focusComposite)) {
                    router.push({ pathname: '/signal/[id]', params: { id: focusComposite.signalId } });
                    return;
                  }
                  router.push('/(tabs)/brain');
                }}
                style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryActionText}>
                  {canOpenCompositeDetail(focusComposite) ? '看综合详情锚点' : '去决策台复核'}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  router.push('/(tabs)/brain');
                }}
                style={[styles.secondaryAction, { borderColor: palette.border }]}>
                <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台复核</Text>
              </Pressable>
            </View>
          </SurfaceCard>

          {themeSeedPicks.length > 0 ? (
            <>
              <SectionHeading
                title="主线种子候选"
                subtitle="这批票不一定先被策略打出来，但已经被主线和资金雷达提前盯上。"
              />
              <View style={styles.queueWrap}>
                {themeSeedPicks.map((pick) => {
                  const recommendation = buildCompositeRecommendation(pick);
                  return (
                    <SurfaceCard key={pick.id} style={styles.queueCard}>
                      <View style={styles.cardHead}>
                        <View style={styles.titleWrap}>
                          <Text style={[styles.code, { color: palette.text }]}>
                            {pick.code} {pick.name}
                          </Text>
                          <Text style={[styles.meta, { color: palette.subtext }]}>
                            {pick.themeSector ? `${pick.themeSector} / ` : ''}
                            {pick.sourceLabel} / {pick.horizonLabel} / 首仓 {pick.firstPositionPct}% / {formatTimestamp(pick.timestamp)}
                          </Text>
                        </View>
                        <StatusPill label={recommendation.verdict} tone={recommendation.tone} />
                      </View>
                      <Text style={[styles.summaryText, { color: palette.text }]}>{recommendation.summary}</Text>
                      <Text style={[styles.hintText, { color: palette.subtext }]}>{pick.action}</Text>
                    </SurfaceCard>
                  );
                })}
              </View>
            </>
          ) : null}

          {swingCompositePicks.length > 0 ? (
            <>
              <SectionHeading
                title="中期波段 / 连涨候选"
                subtitle="这批票更像能走成波段或续强，不只是当天博弈。"
              />
              <View style={styles.queueWrap}>
                {swingCompositePicks.map((pick) => {
                  const recommendation = buildCompositeRecommendation(pick);
                  return (
                    <SurfaceCard key={pick.id} style={styles.queueCard}>
                      <View style={styles.cardHead}>
                        <View style={styles.titleWrap}>
                          <Text style={[styles.code, { color: palette.text }]}>
                            {pick.code} {pick.name}
                          </Text>
                          <Text style={[styles.meta, { color: palette.subtext }]}>
                            {pick.sourceLabel} / {pick.horizonLabel} / 综合分 {pick.compositeScore.toFixed(1)} / {formatTimestamp(pick.timestamp)}
                          </Text>
                        </View>
                        <StatusPill label={recommendation.verdict} tone={recommendation.tone} />
                      </View>
                      <Text style={[styles.summaryText, { color: palette.text }]}>{recommendation.summary}</Text>
                      <Text style={[styles.hintText, { color: palette.subtext }]}>{pick.action}</Text>
                    </SurfaceCard>
                  );
                })}
              </View>
            </>
          ) : null}

          {strategyCompositePicks.length > 0 ? (
            <View style={styles.queueWrap}>
              <SectionHeading
                title="综合候选队列"
                subtitle="这批还是策略候选为主，但已经吃到事件、资金和执行纪律的统一排序。"
              />
              {strategyCompositePicks.slice(0, 4).map((pick) => {
                const recommendation = buildCompositeRecommendation(pick);
                return (
                  <SurfaceCard key={pick.id} style={styles.queueCard}>
                    <View style={styles.cardHead}>
                      <View style={styles.titleWrap}>
                        <Text style={[styles.code, { color: palette.text }]}>
                          {pick.code} {pick.name}
                        </Text>
                        <Text style={[styles.meta, { color: palette.subtext }]}>
                          {pick.themeSector ? `${pick.themeSector} / ` : ''}
                          {pick.sourceLabel} / {pick.horizonLabel} / 事件{pick.eventBias} / 首仓 {pick.firstPositionPct}% / {formatTimestamp(pick.timestamp)}
                        </Text>
                      </View>
                      <StatusPill label={recommendation.verdict} tone={recommendation.tone} />
                    </View>
                    <Text style={[styles.summaryText, { color: palette.text }]}>{recommendation.summary}</Text>
                    {pick.eventSummary ? (
                      <Text style={[styles.hintText, { color: palette.subtext }]}>{pick.eventSummary}</Text>
                    ) : null}
                    <Text style={[styles.hintText, { color: palette.subtext }]}>{pick.action}</Text>
                  </SurfaceCard>
                );
              })}
            </View>
          ) : null}
        </>
      ) : null}

      {compositeCompare ? (
        <>
          <SectionHeading
            title="影子对比统计"
            subtitle="不靠感觉判断综合榜强不强，直接拿最近几天的同口径结果去比。"
          />
          <SurfaceCard style={styles.compositeCard}>
            <View style={styles.focusHead}>
              <View style={styles.focusTitleWrap}>
                <Text style={[styles.focusCode, { color: palette.text }]}>综合榜 vs 原推荐榜</Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  最近 {compositeCompare.composite.sampleDays} 个交易日影子观察 / T+3 更适合看持续性
                </Text>
              </View>
              <StatusPill
                label={
                  compositeCompare.advantage[0]?.includes('综合榜领先')
                    ? '综合占优'
                    : compositeCompare.advantage[0]?.includes('原推荐榜领先')
                      ? '原推荐占优'
                      : '继续观察'
                }
                tone={
                  compositeCompare.advantage[0]?.includes('综合榜领先')
                    ? 'success'
                    : compositeCompare.advantage[0]?.includes('原推荐榜领先')
                      ? 'warning'
                      : 'info'
                }
              />
            </View>

            <View style={styles.metricGrid}>
              <MetricCard
                label="综合 T+1"
                value={
                  compositeCompare.composite.avgT1ReturnPct === null
                    ? '--'
                    : formatPercent(compositeCompare.composite.avgT1ReturnPct / 100)
                }
                tone={
                  (compositeCompare.composite.avgT1ReturnPct ?? 0) >= 0 ? 'success' : 'danger'
                }
              />
              <MetricCard
                label="综合 T+3"
                value={
                  compositeCompare.composite.avgT3ReturnPct === null
                    ? '--'
                    : formatPercent(compositeCompare.composite.avgT3ReturnPct / 100)
                }
                tone={
                  (compositeCompare.composite.avgT3ReturnPct ?? 0) >= 0 ? 'success' : 'danger'
                }
              />
              <MetricCard
                label="原推荐 T+1"
                value={
                  compositeCompare.baseline.avgT1ReturnPct === null
                    ? '--'
                    : formatPercent(compositeCompare.baseline.avgT1ReturnPct / 100)
                }
                tone={
                  (compositeCompare.baseline.avgT1ReturnPct ?? 0) >= 0 ? 'info' : 'warning'
                }
              />
              <MetricCard
                label="原推荐 T+3"
                value={
                  compositeCompare.baseline.avgT3ReturnPct === null
                    ? '--'
                    : formatPercent(compositeCompare.baseline.avgT3ReturnPct / 100)
                }
                tone={
                  (compositeCompare.baseline.avgT3ReturnPct ?? 0) >= 0 ? 'info' : 'warning'
                }
              />
              <MetricCard
                label="综合胜率"
                value={
                  compositeCompare.composite.t1WinRate === null
                    ? '--'
                    : `${compositeCompare.composite.t1WinRate.toFixed(0)}%`
                }
                tone="success"
              />
              <MetricCard
                label="原推荐胜率"
                value={
                  compositeCompare.baseline.t1WinRate === null
                    ? '--'
                    : `${compositeCompare.baseline.t1WinRate.toFixed(0)}%`
                }
                tone="neutral"
              />
            </View>

            <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.hintTitle, { color: palette.text }]}>接管判断</Text>
              <View style={styles.readinessHead}>
                <Text style={[styles.readinessTitle, { color: palette.text }]}>
                  {compositeCompare.readiness.label}
                </Text>
                <StatusPill
                  label={`置信 ${compositeCompare.readiness.confidenceScore.toFixed(0)}`}
                  tone={getReadinessTone(compositeCompare.readiness.status)}
                />
              </View>
              <Text style={[styles.hintText, { color: palette.subtext }]}>
                {compositeCompare.readiness.summary}
              </Text>
              <Text style={[styles.hintText, { color: palette.subtext }]}>
                {compositeCompare.readiness.recommendedAction}
              </Text>
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.listTitle, { color: palette.text }]}>当前结论</Text>
              {compositeCompare.advantage.map((item) => (
                <View key={item} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                  <Text style={[styles.listText, { color: palette.text }]}>{item}</Text>
                </View>
              ))}
              {compositeCompare.readiness.conditions.map((item) => (
                <View key={item} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.subtext }]} />
                  <Text style={[styles.listText, { color: palette.subtext }]}>{item}</Text>
                </View>
              ))}
            </View>
          </SurfaceCard>

          {compositeCompare.days.length > 0 ? (
            <View style={styles.queueWrap}>
              {compositeCompare.days.map((item) => (
                <SurfaceCard key={`compare-${item.tradeDate}`} style={styles.queueCard}>
                  <View style={styles.cardHead}>
                    <View style={styles.titleWrap}>
                      <Text style={[styles.code, { color: palette.text }]}>{item.tradeDate}</Text>
                      <Text style={[styles.meta, { color: palette.subtext }]}>
                        综合 {item.compositeCode ?? '--'} / 原推荐 {item.baselineCode ?? '--'}
                      </Text>
                    </View>
                    <StatusPill label={item.winnerLabel} tone={getCompareTone(item.winnerLabel)} />
                  </View>
                  <Text style={[styles.summaryText, { color: palette.text }]}>{item.summary}</Text>
                  <View style={styles.metricRow}>
                    <View style={styles.metricBlock}>
                      <Text style={[styles.metricLabel, { color: palette.subtext }]}>综合 T+1 / T+3</Text>
                      <Text style={[styles.metricValue, { color: palette.text }]}>
                        {item.compositeT1ReturnPct === null ? '--' : formatPercent(item.compositeT1ReturnPct / 100)} /{' '}
                        {item.compositeT3ReturnPct === null ? '--' : formatPercent(item.compositeT3ReturnPct / 100)}
                      </Text>
                    </View>
                    <View style={styles.metricBlock}>
                      <Text style={[styles.metricLabel, { color: palette.subtext }]}>原推荐 T+1 / T+3</Text>
                      <Text style={[styles.metricValue, { color: palette.text }]}>
                        {item.baselineT1ReturnPct === null ? '--' : formatPercent(item.baselineT1ReturnPct / 100)} /{' '}
                        {item.baselineT3ReturnPct === null ? '--' : formatPercent(item.baselineT3ReturnPct / 100)}
                      </Text>
                    </View>
                  </View>
                </SurfaceCard>
              ))}
            </View>
          ) : null}
        </>
      ) : null}

      {compositeReplay.length > 0 ? (
        <>
          <SectionHeading
            title="连续观察回放"
            subtitle="不是只看今天。这里回放最近几天综合榜首，直接看它后面走成什么。"
          />
          <View style={styles.queueWrap}>
            {compositeReplay.map((item) => (
              <SurfaceCard key={item.id} style={styles.queueCard}>
                <View style={styles.cardHead}>
                  <View style={styles.titleWrap}>
                    <Text style={[styles.code, { color: palette.text }]}>
                      {item.code} {item.name}
                    </Text>
                    <Text style={[styles.meta, { color: palette.subtext }]}>
                      {item.tradeDate}
                      {item.themeSector ? ` / ${item.themeSector}` : ''} / 当时首仓 {item.firstPositionPct}% / 综合分{' '}
                      {item.compositeScore.toFixed(1)}
                    </Text>
                  </View>
                  <StatusPill label={item.reviewLabel} tone={getReplayTone(item)} />
                </View>
                <Text style={[styles.summaryText, { color: palette.text }]}>{item.outcomeSummary}</Text>
                <Text style={[styles.hintText, { color: palette.subtext }]}>{item.review}</Text>
                <View style={styles.metricRow}>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>T+1</Text>
                    <Text
                      style={[
                        styles.metricValue,
                        { color: (item.t1ReturnPct ?? 0) >= 0 ? palette.success : palette.danger },
                      ]}>
                      {item.t1ReturnPct === null ? '--' : formatPercent(item.t1ReturnPct / 100)}
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>T+3</Text>
                    <Text
                      style={[
                        styles.metricValue,
                        { color: (item.t3ReturnPct ?? 0) >= 0 ? palette.success : palette.danger },
                      ]}>
                      {item.t3ReturnPct === null ? '--' : formatPercent(item.t3ReturnPct / 100)}
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>T+5</Text>
                    <Text
                      style={[
                        styles.metricValue,
                        { color: (item.t5ReturnPct ?? 0) >= 0 ? palette.success : palette.danger },
                      ]}>
                      {item.t5ReturnPct === null ? '--' : formatPercent(item.t5ReturnPct / 100)}
                    </Text>
                  </View>
                </View>
              </SurfaceCard>
            ))}
          </View>
        </>
      ) : null}

      {signals.length === 0 && !error ? (
        <SurfaceCard style={styles.noticeCard}>
          <Text style={[styles.noticeTitle, { color: palette.text }]}>当前没有推荐</Text>
          <Text style={[styles.noticeCopy, { color: palette.subtext }]}>
            先去决策台手动诊股，或者等下一次策略触发。
          </Text>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}
            style={[styles.secondaryAction, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台</Text>
          </Pressable>
        </SurfaceCard>
      ) : null}

      {focusSignal && focusRecommendation ? (
        <>
          <SectionHeading title="今日焦点推荐" subtitle="先把最强的一条讲清楚，再看后面的队列。" />
          <SurfaceCard style={styles.focusCard}>
            <View style={styles.focusHead}>
              <View style={styles.focusTitleWrap}>
                <Text style={[styles.focusCode, { color: palette.text }]}>
                  {focusSignal.code} {focusSignal.name}
                </Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  {formatTimestamp(focusSignal.timestamp)} / 现价 {focusSignal.price.toFixed(2)} / 涨跌{' '}
                  {formatPercent(focusSignal.changePct / 100)}
                </Text>
              </View>
              <StatusPill label={focusRecommendation.verdict} tone={focusRecommendation.tone} />
            </View>

            <Text style={[styles.focusSummary, { color: palette.text }]}>{focusRecommendation.summary}</Text>

            <View style={styles.metricGrid}>
              <MetricCard label="评分" value={focusSignal.score.toFixed(3)} tone="info" />
              <MetricCard label="止损" value={focusSignal.stopLoss.toFixed(2)} tone="danger" />
              <MetricCard label="目标" value={focusSignal.targetPrice.toFixed(2)} tone="success" />
              <MetricCard label="盈亏比" value={focusSignal.riskReward.toFixed(1)} tone="neutral" />
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.listTitle, { color: palette.text }]}>为什么看它</Text>
              {focusRecommendation.reasons.map((reason) => (
                <View key={reason} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                  <Text style={[styles.listText, { color: palette.text }]}>{reason}</Text>
                </View>
              ))}
            </View>

            <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.hintTitle, { color: palette.text }]}>风险提醒</Text>
              <Text style={[styles.hintText, { color: palette.subtext }]}>{focusRecommendation.riskText}</Text>
            </View>

            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  router.push({ pathname: '/signal/[id]', params: { id: focusSignal.id } });
                }}
                style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryActionText}>看推荐详情</Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  router.push('/(tabs)/brain');
                }}
                style={[styles.secondaryAction, { borderColor: palette.border }]}>
                <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去决策台复诊</Text>
              </Pressable>
            </View>
          </SurfaceCard>
        </>
      ) : null}

      {signals.length > 1 ? (
        <>
          <SectionHeading title="推荐队列" subtitle="后面的票不再平铺直叙，统一按结论卡展示。" />
          {signals.slice(1).map((signal) => {
            const recommendation = buildRecommendation(signal);

            return (
              <SurfaceCard key={signal.id} style={styles.card}>
                <View style={styles.cardHead}>
                  <View style={styles.titleWrap}>
                    <Text style={[styles.code, { color: palette.text }]}>
                      {signal.code} {signal.name}
                    </Text>
                    <Text style={[styles.meta, { color: palette.subtext }]}>
                      {formatTimestamp(signal.timestamp)} / 现价 {signal.price.toFixed(2)} / 涨跌{' '}
                      {formatPercent(signal.changePct / 100)}
                    </Text>
                  </View>
                  <StatusPill label={recommendation.verdict} tone={recommendation.tone} />
                </View>

                <Text style={[styles.summaryText, { color: palette.text }]}>{recommendation.summary}</Text>

                <View style={styles.reasonWrap}>
                  {recommendation.reasons.map((reason) => (
                    <View key={reason} style={styles.listRow}>
                      <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                      <Text style={[styles.listText, { color: palette.text }]}>{reason}</Text>
                    </View>
                  ))}
                </View>

                <View style={styles.metricRow}>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>评分</Text>
                    <Text style={[styles.metricValue, { color: palette.text }]}>
                      {signal.score.toFixed(3)}
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>止损</Text>
                    <Text style={[styles.metricValue, { color: palette.danger }]}>
                      {signal.stopLoss.toFixed(2)}
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>目标</Text>
                    <Text style={[styles.metricValue, { color: palette.success }]}>
                      {signal.targetPrice.toFixed(2)}
                    </Text>
                  </View>
                </View>

                <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
                  <Text style={[styles.hintTitle, { color: palette.text }]}>现在怎么处理</Text>
                  <Text style={[styles.hintText, { color: palette.subtext }]}>{recommendation.actionHint}</Text>
                </View>

                <View style={styles.actionRow}>
                  <Pressable
                    onPress={() => {
                      router.push({ pathname: '/signal/[id]', params: { id: signal.id } });
                    }}
                    style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                    <Text style={styles.primaryActionText}>看详情</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => {
                      router.push('/(tabs)/brain');
                    }}
                    style={[styles.secondaryAction, { borderColor: palette.border }]}>
                    <Text style={[styles.secondaryActionText, { color: palette.tint }]}>去诊股</Text>
                  </Pressable>
                </View>
              </SurfaceCard>
            );
          })}
        </>
      ) : null}
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
  contextBoard: {
    gap: 12,
  },
  contextGrid: {
    gap: 12,
  },
  contextCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 8,
  },
  contextHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  contextEyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  contextTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  contextMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  contextCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  noticeCard: {
    gap: 12,
  },
  compositeCard: {
    gap: 16,
  },
  noticeTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  noticeCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  focusCard: {
    gap: 16,
  },
  focusHead: {
    gap: 10,
  },
  focusTitleWrap: {
    gap: 4,
  },
  focusCode: {
    fontSize: 24,
    fontWeight: '800',
    lineHeight: 30,
  },
  focusMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  focusSummary: {
    fontSize: 16,
    lineHeight: 24,
    fontWeight: '700',
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  listGroup: {
    gap: 8,
  },
  listTitle: {
    fontSize: 15,
    fontWeight: '800',
  },
  listRow: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    marginTop: 7,
  },
  listText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 22,
  },
  hintBox: {
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  hintTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  readinessHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  readinessTitle: {
    fontSize: 15,
    fontWeight: '800',
    lineHeight: 22,
  },
  hintText: {
    fontSize: 13,
    lineHeight: 20,
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryAction: {
    flex: 1,
    borderRadius: 18,
    minHeight: 46,
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
    borderRadius: 18,
    minHeight: 46,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryActionText: {
    fontSize: 14,
    fontWeight: '800',
  },
  card: {
    gap: 14,
  },
  queueWrap: {
    gap: 10,
  },
  queueCard: {
    gap: 12,
  },
  cardHead: {
    gap: 10,
  },
  titleWrap: {
    gap: 4,
  },
  code: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  meta: {
    fontSize: 13,
    lineHeight: 20,
  },
  summaryText: {
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '700',
  },
  reasonWrap: {
    gap: 8,
  },
  metricRow: {
    flexDirection: 'row',
    gap: 12,
  },
  metricBlock: {
    flex: 1,
    borderRadius: 18,
    padding: 14,
    backgroundColor: 'rgba(21, 94, 239, 0.07)',
    gap: 4,
  },
  metricLabel: {
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.7,
  },
  metricValue: {
    fontSize: 18,
    fontWeight: '800',
  },
});
