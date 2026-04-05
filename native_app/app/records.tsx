import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
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
  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回持仓页</Text>
      </Pressable>

      <SectionHeading title="交易记录" />

      <SurfaceCard style={styles.summaryCard}>
        <Text style={[styles.summaryTitle, { color: palette.text }]}>
          {focusedCode ? `${focusedCode} 交易台账` : '最近动作与已平仓结果'}
        </Text>
        <Text style={[styles.meta, { color: history.realizedProfitLoss >= 0 ? palette.success : palette.danger }]}>
          已实现 {formatCurrency(history.realizedProfitLoss)}
        </Text>
      </SurfaceCard>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步交易记录" />

      <SectionHeading title="最近动作" />
      {recentTrades.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前还没有动作流水。
          </Text>
        </SurfaceCard>
      ) : null}

      {recentTrades.slice(0, 1).map((trade) => {
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
                  <Text style={[styles.meta, { color: palette.subtext }]}>
                    {statusLabel(trade.status)}
                  </Text>
                </View>
              </View>
              <View style={styles.rowBetween}>
                <View style={styles.tradeInfo}>
                  <Text style={[styles.tradeType, { color: palette.text }]}>
                    {tradeTypeLabel(trade.type)}
                  </Text>
                  <Text style={[styles.tradeReason, { color: palette.subtext }]} numberOfLines={1}>
                    {trade.reason}
                  </Text>
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

      <SectionHeading title="已平仓" />
      {closedPositions.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前还没有已平仓记录。
          </Text>
        </SurfaceCard>
      ) : null}

      {closedPositions.slice(0, 1).map((position) => (
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
          <Text style={[styles.tradeReason, { color: palette.subtext }]} numberOfLines={1}>
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
  summaryCard: {
    gap: 10,
  },
  summaryTitle: {
    fontSize: 20,
    fontWeight: '800',
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
