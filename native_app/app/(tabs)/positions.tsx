import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { formatCurrency, formatPercent } from '@/lib/format';
import { getPositions, getPositioningPlan } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { Position } from '@/types/trading';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function getStopBufferPct(position: Position): number | null {
  if (position.currentPrice <= 0 || position.stopLoss <= 0) {
    return null;
  }

  return ((position.currentPrice - position.stopLoss) / position.currentPrice) * 100;
}

function getPositionRiskScore(position: Position): number {
  const stopBufferPct = getStopBufferPct(position);
  const stopRisk = stopBufferPct === null ? 0 : Math.max(0, 10 - stopBufferPct) * 9;
  const pnlRisk = position.profitLossPct < 0 ? Math.abs(position.profitLossPct) * 2.2 : 0;
  const holdRisk = Math.min(position.holdDays, 20) * 0.4;

  return stopRisk + pnlRisk + holdRisk;
}

function getRiskTone(position: Position): Tone {
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

function getRiskLabel(position: Position): string {
  const stopBufferPct = getStopBufferPct(position);

  if (stopBufferPct !== null && stopBufferPct <= 0) {
    return '跌穿止损';
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

function getActionSuggestion(position: Position): string {
  const stopBufferPct = getStopBufferPct(position);

  if (stopBufferPct !== null && stopBufferPct <= 2) {
    return '优先调整止损或直接减仓。';
  }
  if (stopBufferPct !== null && stopBufferPct <= 5) {
    return '建议上移风险线，别让它变成被动仓位。';
  }
  if (position.profitLossPct >= 5) {
    return '可以考虑锁盈，把止损上移到更安全的位置。';
  }
  if (position.profitLossPct < 0) {
    return '先确认逻辑有没有失效，再决定是否继续拿。';
  }

  return '仓位稳定，继续观察并跟踪止损线。';
}

function getActionButtonLabel(position: Position): string {
  const stopBufferPct = getStopBufferPct(position);

  if (stopBufferPct !== null && stopBufferPct <= 5) {
    return '处理仓位';
  }
  if (position.profitLossPct >= 5) {
    return '锁盈处理';
  }

  return '看详情';
}

function buildPortfolioVerdict(
  priorityCount: number,
  topPriority: Position | null,
  totalProfitLoss: number
): {
  title: string;
  tone: Tone;
  summary: string;
  tasks: string[];
} {
  const tasks: string[] = [];

  if (topPriority) {
    tasks.push(`${topPriority.code} ${topPriority.name} 是当前最该先处理的仓位。`);
  }
  if (priorityCount > 0) {
    tasks.push(`组合里还有 ${priorityCount} 个需要优先处理的仓位，不适合先只盯新增推荐。`);
  } else {
    tasks.push('当前没有高优先级风险仓位，组合整体处在可控区间。');
  }
  tasks.push(
    totalProfitLoss >= 0
      ? `当前组合浮盈 ${formatCurrency(totalProfitLoss)}，现在更适合讲纪律而不是讲救火。`
      : `当前组合浮亏 ${formatCurrency(totalProfitLoss)}，更要把风险边界讲清楚。`
  );

  if (priorityCount > 0 && topPriority) {
    return {
      title: '先处理仓位风险',
      tone: getRiskTone(topPriority),
      summary: '这页先告诉你哪个仓位最危险，再把剩下的仓位按风险顺序排好。',
      tasks,
    };
  }

  if (totalProfitLoss >= 0) {
    return {
      title: '组合状态可控',
      tone: 'success',
      summary: '当前更像锁盈和维持纪律，不像临时救火。',
      tasks,
    };
  }

  return {
    title: '组合需要继续盯',
    tone: 'warning',
    summary: '虽然没有明显爆点，但亏损仓位和持有纪律还是要盯住。',
    tasks,
  };
}

export default function PositionsScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    async () => {
      const [positions, positioningPlan] = await Promise.all([
        getPositions(token ?? undefined),
        getPositioningPlan(token ?? undefined),
      ]);

      return { positions, positioningPlan };
    },
    [token, apiBaseUrl]
  );
  const positions = data?.positions ?? [];
  const positioningPlan = data?.positioningPlan ?? null;
  const rankedPositions = [...positions].sort(
    (left, right) => getPositionRiskScore(right) - getPositionRiskScore(left)
  );
  const topPriority = rankedPositions[0] ?? null;
  const priorityPositions = rankedPositions.filter((position) => getRiskTone(position) !== 'success');
  const stablePositions = rankedPositions.filter((position) => getRiskTone(position) === 'success');
  const totalMarketValue = positions.reduce((sum, item) => sum + item.marketValue, 0);
  const totalProfitLoss = positions.reduce((sum, item) => sum + item.profitLoss, 0);
  const portfolioVerdict = buildPortfolioVerdict(priorityPositions.length, topPriority, totalProfitLoss);

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading
        eyebrow="Portfolio"
        title="持仓"
        subtitle="这页现在先讲组合判断，再告诉你哪个仓位最危险、怎么处理。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>PORTFOLIO CONTROL</Text>
        <Text style={styles.heroTitle}>{portfolioVerdict.title}</Text>
        <Text style={styles.heroCopy}>{portfolioVerdict.summary}</Text>
        <View style={styles.heroPills}>
          <StatusPill label={`持仓 ${positions.length}`} tone="neutral" />
          <StatusPill label={`待处理 ${priorityPositions.length}`} tone={priorityPositions.length > 0 ? 'warning' : 'success'} />
          <StatusPill label={`总市值 ${formatCurrency(totalMarketValue)}`} tone="info" />
          <StatusPill
            label={`浮盈 ${formatCurrency(totalProfitLoss)}`}
            tone={totalProfitLoss >= 0 ? 'success' : 'danger'}
          />
          <StatusPill
            label={`目标总仓 ${positioningPlan ? `${positioningPlan.targetExposurePct.toFixed(0)}%` : '--'}`}
            tone={positioningPlan?.mode === '防守' ? 'warning' : 'info'}
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
        </View>
      </View>

      <View style={styles.heroActions}>
        <Pressable
          onPress={() => {
            router.push('/records');
          }}
          style={[styles.secondaryAction, { borderColor: palette.border }]}>
          <Text style={[styles.secondaryActionText, { color: palette.tint }]}>看交易记录</Text>
        </Pressable>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步持仓" />

      <SectionHeading
        title="一页持仓判断"
        subtitle="先把组合状态、仓位计划、风险仓和下一动作压成一页，再往下看具体仓位。"
      />
      <SurfaceCard style={styles.verdictCard}>
        <View style={styles.snapshotGrid}>
          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>01 组合判断</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>{portfolioVerdict.title}</Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              持仓 {positions.length} / 总市值 {formatCurrency(totalMarketValue)}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>{portfolioVerdict.summary}</Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>02 仓位计划</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {positioningPlan ? `${positioningPlan.mode} / 目标总仓 ${positioningPlan.targetExposurePct.toFixed(0)}%` : '等待仓位计划'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {positioningPlan
                ? `首仓 ${positioningPlan.firstEntryPositionPct}% / 单票 ${positioningPlan.maxSinglePositionPct}% / 主题 ${positioningPlan.maxThemeExposurePct}%`
                : '先看总仓、首仓和主题上限。'}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {positioningPlan?.eventSummary ?? '仓位层会把风险和新增动作统一成纪律语言。'}
            </Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>03 风险仓位</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {topPriority ? `${topPriority.code} ${topPriority.name}` : '当前没有高优先级风险仓'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {topPriority
                ? `${getRiskLabel(topPriority)} / 持有 ${topPriority.holdDays} 天 / 数量 ${topPriority.quantity}`
                : `待处理仓 ${priorityPositions.length} / 稳定仓 ${stablePositions.length}`}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {topPriority ? getActionSuggestion(topPriority) : '当前组合整体处于可控区间，更适合讲纪律与结构。'}
            </Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>04 下一动作</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {priorityPositions.length > 0 ? '先处理风险仓位' : '继续维护纪律'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {priorityPositions.length > 0
                ? `待处理 ${priorityPositions.length} 个 / 浮盈亏 ${formatCurrency(totalProfitLoss)}`
                : `浮盈亏 ${formatCurrency(totalProfitLoss)} / 当前没有硬性风险点`}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {priorityPositions.length > 0
                ? '先按风险顺序处理仓位，再回到推荐页和决策台看新的机会。'
                : '继续盯止损线、锁盈线和总仓纪律，不要因为当前平稳就失去跟踪。'}
            </Text>
          </View>
        </View>
      </SurfaceCard>

      <View style={styles.metricGrid}>
        <MetricCard label="持仓数" value={`${positions.length}`} tone="neutral" />
        <MetricCard label="总市值" value={formatCurrency(totalMarketValue)} tone="info" />
        <MetricCard
          label="组合浮盈"
          value={formatCurrency(totalProfitLoss)}
          tone={totalProfitLoss >= 0 ? 'success' : 'danger'}
        />
        <MetricCard
          label="风险仓位"
          value={`${priorityPositions.length}`}
          tone={priorityPositions.length > 0 ? 'warning' : 'success'}
        />
      </View>

      <SectionHeading title="仓位与分仓建议" subtitle="这层把总仓、单票上限和今天还能打多少先说透。" />
      <SurfaceCard style={styles.verdictCard}>
        <Text style={[styles.listText, { color: palette.text }]}>
          {positioningPlan?.focus ?? '正在读取仓位与分仓建议。'}
        </Text>
        {positioningPlan ? (
          <>
            <View style={styles.metricGrid}>
              <MetricCard
                label="目标总仓"
                value={formatPercent(positioningPlan.targetExposurePct / 100)}
                tone={positioningPlan.mode === '防守' ? 'warning' : 'info'}
              />
              <MetricCard
                label="可再部署"
                value={formatCurrency(positioningPlan.deployableCash)}
                tone={positioningPlan.deployableCash > 0 ? 'success' : 'neutral'}
              />
              <MetricCard
                label="单票上限"
                value={`${positioningPlan.maxSinglePositionPct}%`}
                tone="info"
              />
              <MetricCard
                label="主题上限"
                value={`${positioningPlan.maxThemeExposurePct}%`}
                tone="warning"
              />
              <MetricCard
                label="事件分"
                value={`${positioningPlan.eventScore.toFixed(0)}`}
                tone={
                  positioningPlan.eventBias === '偏空'
                    ? 'danger'
                    : positioningPlan.eventBias === '偏多'
                      ? 'success'
                      : 'neutral'
                }
              />
            </View>
            {positioningPlan.eventSummary ? (
              <SurfaceCard style={styles.eventCard}>
                <Text style={[styles.listText, { color: palette.text }]}>
                  {positioningPlan.eventSummary}
                </Text>
              </SurfaceCard>
            ) : null}
            {positioningPlan.actions.slice(0, 3).map((item) => (
              <View key={item} style={styles.listRow}>
                <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                <Text style={[styles.listText, { color: palette.text }]}>{item}</Text>
              </View>
            ))}
          </>
        ) : null}
      </SurfaceCard>

      <SectionHeading title="组合判断" subtitle="先给一句判断，再把今天该处理的仓位任务列出来。" />
      <SurfaceCard style={styles.verdictCard}>
        {portfolioVerdict.tasks.map((item) => (
          <View key={item} style={styles.listRow}>
            <View style={[styles.dot, { backgroundColor: palette.tint }]} />
            <Text style={[styles.listText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}
      </SurfaceCard>

      <SectionHeading title="首要处理" subtitle="如果今天只能先看一个仓位，就先看它。" />
      <SurfaceCard style={styles.priorityCard}>
        {topPriority ? (
          <>
            <View style={styles.priorityHead}>
              <View style={styles.priorityCopy}>
                <Text style={[styles.priorityCode, { color: palette.text }]}>
                  {topPriority.code} {topPriority.name}
                </Text>
                <Text style={[styles.prioritySummary, { color: palette.subtext }]}>
                  {getActionSuggestion(topPriority)}
                </Text>
              </View>
              <StatusPill label={getRiskLabel(topPriority)} tone={getRiskTone(topPriority)} />
            </View>

            <View style={styles.metricGrid}>
              <MetricCard label="当前价" value={topPriority.currentPrice.toFixed(2)} tone="neutral" />
              <MetricCard label="止损" value={topPriority.stopLoss.toFixed(2)} tone="danger" />
              <MetricCard
                label="浮盈亏"
                value={formatCurrency(topPriority.profitLoss)}
                tone={topPriority.profitLoss >= 0 ? 'success' : 'danger'}
              />
              <MetricCard
                label="距离止损"
                value={
                  getStopBufferPct(topPriority) === null
                    ? '--'
                    : formatPercent((getStopBufferPct(topPriority) ?? 0) / 100)
                }
                tone={getRiskTone(topPriority)}
              />
            </View>

            <Text style={[styles.prioritySummary, { color: palette.subtext }]}>
              持有 {topPriority.holdDays} 天 / 数量 {topPriority.quantity} / 策略 {topPriority.strategy}
            </Text>

            <Pressable
              onPress={() => {
                router.push({ pathname: '/position/[code]', params: { code: topPriority.code } });
              }}
              style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryActionText}>{getActionButtonLabel(topPriority)}</Text>
            </Pressable>
          </>
        ) : (
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有持仓，可以先去推荐页或决策台看新的机会。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading title="优先处理队列" subtitle="这些仓位先处理，不让你靠记忆盯盘。" />
      {priorityPositions.length === 0 ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有高优先级风险仓位，组合整体处在可控区间。
          </Text>
        </SurfaceCard>
      ) : (
        priorityPositions.map((position) => (
          <Pressable
            key={position.code}
            onPress={() => {
              router.push({ pathname: '/position/[code]', params: { code: position.code } });
            }}
            style={({ pressed }) => (pressed ? styles.pressed : undefined)}>
            <SurfaceCard style={styles.card}>
              <View style={styles.cardHead}>
                <View style={styles.cardTitleWrap}>
                  <Text style={[styles.code, { color: palette.text }]}>
                    {position.code} {position.name}
                  </Text>
                  <Text style={[styles.meta, { color: palette.subtext }]}>
                    {getActionSuggestion(position)}
                  </Text>
                </View>
                <StatusPill label={getRiskLabel(position)} tone={getRiskTone(position)} />
              </View>

              <View style={styles.metricRow}>
                <View style={styles.metricBlock}>
                  <Text style={[styles.metricLabel, { color: palette.subtext }]}>现价 / 成本</Text>
                  <Text style={[styles.metricValue, { color: palette.text }]}>
                    {position.currentPrice.toFixed(2)} / {position.costPrice.toFixed(2)}
                  </Text>
                </View>
                <View style={styles.metricBlock}>
                  <Text style={[styles.metricLabel, { color: palette.subtext }]}>止损 / 止盈</Text>
                  <Text style={[styles.metricValue, { color: palette.text }]}>
                    {position.stopLoss.toFixed(2)} / {position.takeProfit.toFixed(2)}
                  </Text>
                </View>
              </View>

              <View style={styles.rowBetween}>
                <Text
                  style={[
                    styles.pnl,
                    { color: position.profitLoss >= 0 ? palette.success : palette.danger },
                  ]}>
                  {formatCurrency(position.profitLoss)} / {formatPercent(position.profitLossPct / 100)}
                </Text>
                <Text style={[styles.meta, { color: palette.subtext }]}>
                  数量 {position.quantity} / 持有 {position.holdDays} 天
                </Text>
              </View>
            </SurfaceCard>
          </Pressable>
        ))
      )}

      <SectionHeading title="稳定仓位" subtitle="这些仓位不用先处理，但也不应该完全失焦。" />
      {stablePositions.length === 0 ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有稳定仓位，说明你现在更该先处理风险。
          </Text>
        </SurfaceCard>
      ) : (
        stablePositions.map((position) => (
          <Pressable
            key={position.code}
            onPress={() => {
              router.push({ pathname: '/position/[code]', params: { code: position.code } });
            }}
            style={({ pressed }) => (pressed ? styles.pressed : undefined)}>
            <SurfaceCard style={styles.stableCard}>
              <View style={styles.cardHead}>
                <View style={styles.cardTitleWrap}>
                  <Text style={[styles.code, { color: palette.text }]}>
                    {position.code} {position.name}
                  </Text>
                  <Text style={[styles.meta, { color: palette.subtext }]}>
                    {position.strategy} / 持有 {position.holdDays} 天
                  </Text>
                </View>
                <Text
                  style={[
                    styles.stablePnl,
                    { color: position.profitLoss >= 0 ? palette.success : palette.danger },
                  ]}>
                  {formatPercent(position.profitLossPct / 100)}
                </Text>
              </View>
            </SurfaceCard>
          </Pressable>
        ))
      )}
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
  heroActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  snapshotGrid: {
    gap: 12,
  },
  snapshotCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 8,
  },
  snapshotStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  snapshotTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  snapshotCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  snapshotBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  verdictCard: {
    gap: 10,
  },
  eventCard: {
    gap: 8,
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
  priorityCard: {
    gap: 16,
  },
  priorityHead: {
    gap: 12,
  },
  priorityCopy: {
    gap: 6,
  },
  priorityCode: {
    fontSize: 24,
    fontWeight: '800',
    lineHeight: 30,
  },
  prioritySummary: {
    fontSize: 14,
    lineHeight: 22,
  },
  primaryAction: {
    borderRadius: 16,
    minHeight: 46,
    paddingHorizontal: 16,
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
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  card: {
    gap: 14,
  },
  cardHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  cardTitleWrap: {
    flex: 1,
    gap: 4,
  },
  code: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  meta: {
    fontSize: 13,
    lineHeight: 20,
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
    letterSpacing: 0.6,
  },
  metricValue: {
    fontSize: 17,
    fontWeight: '800',
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  pnl: {
    fontSize: 14,
    fontWeight: '800',
  },
  stableCard: {
    gap: 10,
  },
  stablePnl: {
    fontSize: 16,
    fontWeight: '800',
  },
  pressed: {
    opacity: 0.9,
  },
});
