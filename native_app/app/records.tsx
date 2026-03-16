import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { getPortfolioHistory } from '@/lib/api';
import { formatCurrency, formatPercent, formatTimestamp } from '@/lib/format';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

function tradeTypeLabel(type: string) {
  if (type === 'buy') {
    return '买入';
  }
  if (type === 'sell') {
    return '卖出';
  }
  if (type === 'adjust') {
    return '风控调整';
  }
  return type || '未分类';
}

function statusLabel(status: string) {
  return status === 'closed' ? '已平仓' : '持仓中';
}

function statusTone(status: string): 'neutral' | 'info' | 'success' {
  if (status === 'closed') {
    return 'neutral';
  }
  return 'info';
}

export default function RecordsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ focus?: string }>();
  const focusedCode = typeof params.focus === 'string' ? params.focus : null;
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getPortfolioHistory(token ?? undefined),
    [token, apiBaseUrl]
  );

  const history = data ?? {
    realizedProfitLoss: 0,
    closedPositions: [],
    recentTrades: [],
  };
  const recentTrades = [...history.recentTrades].sort(
    (a, b) => Number(b.code === focusedCode) - Number(a.code === focusedCode)
  );
  const closedPositions = [...history.closedPositions].sort(
    (a, b) => Number(b.code === focusedCode) - Number(a.code === focusedCode)
  );
  const highlightedClosedPosition = focusedCode
    ? closedPositions.find((position) => position.code === focusedCode)
    : null;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回持仓页</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Execution Ledger"
        title="交易记录"
        subtitle="这里统一看最近动作、已平仓结果和已实现盈亏。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>EXECUTION LEDGER</Text>
        <Text style={styles.heroTitle}>
          {focusedCode ? `围绕 ${focusedCode} 的动作记录` : '最近动作与已平仓结果'}
        </Text>
        <Text style={styles.heroCopy}>
          {focusedCode
            ? '这页已经把相关动作和已平仓记录提上来，方便直接复盘。'
            : '先看整体交易动作、已平仓结果和已实现盈亏，再进入具体记录。'}
        </Text>
      </View>

      <SectionHeading
        title="一页台账判断"
        subtitle="先把最近动作、平仓结果和当前焦点压成一页，再往下看完整流水。"
      />
      <SurfaceCard style={styles.summaryCard}>
        <ExecutiveSummaryGrid
          items={[
            {
              key: 'records-trades',
              step: '01 最近动作',
              title: history.recentTrades.length > 0 ? `${history.recentTrades.length} 条动作` : '当前还没有动作流水',
              meta: history.recentTrades[0]
                ? `${history.recentTrades[0].code} / ${tradeTypeLabel(history.recentTrades[0].type)}`
                : '等待首次真实操作',
              body: '这里统一回放开仓、减仓、风控调整和平仓动作，不用再分散到多个页面找。',
            },
            {
              key: 'records-closed',
              step: '02 已平仓结果',
              title: `${history.closedPositions.length} 笔归档`,
              meta: `已实现盈亏 ${formatCurrency(history.realizedProfitLoss)}`,
              body: '平仓记录独立归档，方便回看结果，不和当前持仓混在一起。',
            },
            {
              key: 'records-focus',
              step: '03 当前焦点',
              title: highlightedClosedPosition
                ? `${highlightedClosedPosition.code} ${highlightedClosedPosition.name}`
                : focusedCode
                  ? `${focusedCode} 暂无平仓归档`
                  : '当前没有指定焦点票',
              meta: highlightedClosedPosition
                ? `平仓 ${highlightedClosedPosition.closePrice.toFixed(2)} / 持有 ${highlightedClosedPosition.holdDays} 天`
                : '可从持仓页带着代码跳进来复盘',
              body: highlightedClosedPosition?.closeReason || '如果当前没有指定焦点票，这页默认按时间顺序展示。',
            },
          ]}
        />
      </SurfaceCard>

      <View style={styles.grid}>
        <MetricCard label="最近动作" value={`${history.recentTrades.length}`} tone="neutral" />
        <MetricCard label="已平仓" value={`${history.closedPositions.length}`} tone="info" />
        <MetricCard
          label="已实现盈亏"
          value={formatCurrency(history.realizedProfitLoss)}
          tone={history.realizedProfitLoss >= 0 ? 'success' : 'danger'}
        />
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步交易记录" />

      {highlightedClosedPosition ? (
        <SurfaceCard
          style={[
            styles.focusCard,
            {
              backgroundColor: palette.accentSoft,
              borderColor: palette.tint,
            },
          ]}>
          <Text style={[styles.focusTitle, { color: palette.text }]}>
            已定位到 {highlightedClosedPosition.code} 最近平仓记录
          </Text>
          <Text style={[styles.focusCopy, { color: palette.subtext }]}>
            {highlightedClosedPosition.closeReason || '本次平仓未写入额外说明'}，成交价{' '}
            {highlightedClosedPosition.closePrice.toFixed(2)}，已实现{' '}
            {formatCurrency(highlightedClosedPosition.realizedProfitLoss)}。
          </Text>
        </SurfaceCard>
      ) : null}

      <SectionHeading title="最近动作" subtitle="开仓、调风控、减仓、平仓都按时间倒序放在这里。" />
      {recentTrades.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前还没有可展示的动作流水。等你第一次从 App 里开仓或调整风控，这里会自动出现。
          </Text>
        </SurfaceCard>
      ) : null}

      {recentTrades.map((trade) => {
        const canOpenPosition = trade.status !== 'closed';
        return (
          <Pressable
            key={trade.id}
            disabled={!canOpenPosition}
            onPress={() => {
              if (!canOpenPosition) {
                return;
              }
              router.push({ pathname: '/position/[code]', params: { code: trade.code } });
            }}
            style={({ pressed }) => (pressed ? styles.pressed : undefined)}>
            <SurfaceCard
              style={[
                styles.recordCard,
                trade.code === focusedCode
                  ? {
                      borderColor: palette.tint,
                    }
                  : {},
              ]}>
              <View style={styles.rowBetween}>
                <View style={styles.titleWrap}>
                  <Text style={[styles.code, { color: palette.text }]}>
                    {trade.code} {trade.name}
                  </Text>
                  <Text style={[styles.meta, { color: palette.subtext }]}>
                    {trade.strategy || '未标记策略'} · {formatTimestamp(trade.time.replace(' ', 'T'))}
                  </Text>
                </View>
                <StatusPill label={statusLabel(trade.status)} tone={statusTone(trade.status)} />
              </View>
              <View style={styles.rowBetween}>
                <View style={styles.tradeInfo}>
                  <Text style={[styles.tradeType, { color: palette.text }]}>
                    {tradeTypeLabel(trade.type)}
                  </Text>
                  <Text style={[styles.tradeReason, { color: palette.subtext }]}>{trade.reason}</Text>
                </View>
                <View style={styles.tradeMeta}>
                  <Text style={[styles.tradePrice, { color: palette.text }]}>
                    {trade.price.toFixed(2)} x {trade.quantity}
                  </Text>
                  <Text style={[styles.tradeHint, { color: palette.subtext }]}>
                    {canOpenPosition ? '点开继续管理持仓' : '已归档到平仓记录'}
                  </Text>
                </View>
              </View>
            </SurfaceCard>
          </Pressable>
        );
      })}

      <SectionHeading title="已平仓" subtitle="完整结束的仓位放这里，专门看结果，不跟当前持仓混在一起。" />
      {closedPositions.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前还没有已平仓记录。等你第一次完整平仓后，这里会自动归档。
          </Text>
        </SurfaceCard>
      ) : null}

      {closedPositions.map((position) => (
        <SurfaceCard
          key={`${position.code}-${position.closedAt}`}
          style={[
            styles.recordCard,
            position.code === focusedCode
              ? {
                  borderColor: palette.tint,
                }
              : {},
          ]}>
          <View style={styles.rowBetween}>
            <View style={styles.titleWrap}>
              <Text style={[styles.code, { color: palette.text }]}>
                {position.code} {position.name}
              </Text>
              <Text style={[styles.meta, { color: palette.subtext }]}>
                {position.strategy || '未标记策略'} · 持有 {position.holdDays} 天
              </Text>
            </View>
            <Text
              style={[
                styles.realized,
                {
                  color: position.realizedProfitLoss >= 0 ? palette.success : palette.danger,
                },
              ]}>
              {formatCurrency(position.realizedProfitLoss)}
            </Text>
          </View>
          <View style={styles.dataRow}>
            <Text style={[styles.meta, { color: palette.subtext }]}>数量 {position.quantity}</Text>
            <Text style={[styles.meta, { color: palette.subtext }]}>
              成本 {position.costPrice.toFixed(2)}
            </Text>
            <Text style={[styles.meta, { color: palette.subtext }]}>
              平仓 {position.closePrice.toFixed(2)}
            </Text>
            <Text
              style={[
                styles.meta,
                {
                  color: position.realizedProfitLossPct >= 0 ? palette.success : palette.danger,
                },
              ]}>
              {formatPercent(position.realizedProfitLossPct / 100)}
            </Text>
          </View>
          <Text style={[styles.tradeReason, { color: palette.subtext }]}>
            {position.closeReason || '未写入平仓原因'}
          </Text>
          <Text style={[styles.tradeHint, { color: palette.subtext }]}>
            {position.closedAt
              ? `平仓时间 ${formatTimestamp(position.closedAt)}`
              : '平仓时间暂未写入'}
          </Text>
        </SurfaceCard>
      ))}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
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
  summaryCard: {
    gap: 14,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  focusCard: {
    gap: 6,
  },
  focusTitle: {
    fontSize: 15,
    fontWeight: '800',
  },
  focusCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  pressed: {
    opacity: 0.92,
  },
  recordCard: {
    gap: 12,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  titleWrap: {
    flex: 1,
    gap: 4,
  },
  code: {
    fontSize: 17,
    fontWeight: '800',
  },
  meta: {
    fontSize: 13,
  },
  tradeInfo: {
    flex: 1,
    gap: 4,
  },
  tradeMeta: {
    alignItems: 'flex-end',
    gap: 4,
  },
  tradeType: {
    fontSize: 15,
    fontWeight: '700',
  },
  tradeReason: {
    fontSize: 13,
    lineHeight: 19,
  },
  tradePrice: {
    fontSize: 14,
    fontWeight: '800',
  },
  tradeHint: {
    fontSize: 12,
  },
  dataRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 14,
  },
  realized: {
    fontSize: 20,
    fontWeight: '800',
  },
});
