import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
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
  const rankedPositions = [...positions].sort(
    (left, right) => getPositionRiskScore(right) - getPositionRiskScore(left)
  );
  const topPriority = rankedPositions[0] ?? null;
  const priorityPositions = rankedPositions.filter((position) => getRiskTone(position) !== 'success');
  const stablePositions = rankedPositions.filter((position) => getRiskTone(position) === 'success');
  const totalProfitLoss = positions.reduce((sum, item) => sum + item.profitLoss, 0);
  const portfolioVerdict = buildPortfolioVerdict(priorityPositions.length, topPriority, totalProfitLoss);

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading title="持仓" />

      <SurfaceCard style={styles.verdictCard}>
        <Text style={[styles.cardTitle, { color: palette.text }]}>{portfolioVerdict.title}</Text>
        <Text style={[styles.listText, { color: palette.subtext }]}>{portfolioVerdict.summary}</Text>
        <Text style={[styles.listText, { color: palette.text }]}>
          持仓 {positions.length} / 待处理 {priorityPositions.length}
        </Text>
        {portfolioVerdict.tasks.slice(0, 1).map((item) => (
          <View key={item} style={styles.listRow}>
            <View style={[styles.dot, { backgroundColor: palette.tint }]} />
            <Text style={[styles.listText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}
        {topPriority ? (
          <Text style={[styles.listText, { color: palette.text }]}>
            先看 {topPriority.code} {topPriority.name}：{getActionSuggestion(topPriority)}
          </Text>
        ) : null}
      </SurfaceCard>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步持仓" />

      <SectionHeading title="首要处理" />
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

            <Text style={[styles.prioritySummary, { color: palette.subtext }]}>
              现价 {topPriority.currentPrice.toFixed(2)} / 止损 {topPriority.stopLoss.toFixed(2)} / 浮盈亏 {formatCurrency(topPriority.profitLoss)}
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

      <SectionHeading title="优先处理队列" />
      {priorityPositions.length === 0 ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有高优先级风险仓位，组合整体处在可控区间。
          </Text>
        </SurfaceCard>
      ) : (
        priorityPositions.slice(0, 1).map((position) => (
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

              <Text style={[styles.meta, { color: palette.text }]}>
                现价/成本 {position.currentPrice.toFixed(2)} / {position.costPrice.toFixed(2)} · 止损/止盈 {position.stopLoss.toFixed(2)} / {position.takeProfit.toFixed(2)}
              </Text>

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

      <SectionHeading title="稳定仓位" />
      {stablePositions.length === 0 ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有稳定仓位，说明你现在更该先处理风险。
          </Text>
        </SurfaceCard>
      ) : (
        stablePositions.slice(0, 1).map((position) => (
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
  pillRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  verdictCard: {
    gap: 10,
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
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
