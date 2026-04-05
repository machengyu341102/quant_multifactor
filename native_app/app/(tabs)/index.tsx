import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter, type Href } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getHomeSnapshot } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import { useAuth } from '@/providers/auth-provider';
import { useNotifications } from '@/providers/notification-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { CompositePick, Position, Signal } from '@/types/trading';

type PillTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function getRiskPosition(positions: Position[]): Position | null {
  if (!positions.length) {
    return null;
  }

  return [...positions].sort((left, right) => {
    const rightRisk = Math.abs(Math.min(right.profitLossPct, 0)) + right.holdDays * 0.2;
    const leftRisk = Math.abs(Math.min(left.profitLossPct, 0)) + left.holdDays * 0.2;
    return rightRisk - leftRisk;
  })[0] ?? null;
}

function getPrimaryFocus(params: {
  topAlertTitle: string | null;
  topAlertMessage: string | null;
  worldActionTitle: string | null;
  worldActionSummary: string | null;
  signal: Signal | null;
  todayCompleted: boolean;
}): {
  title: string;
  summary: string;
  tone: PillTone;
} {
  if (params.topAlertTitle) {
    return {
      title: params.topAlertTitle,
      summary: params.topAlertMessage ?? '先把当前风险处理掉，再谈新增机会。',
      tone: 'danger',
    };
  }

  if (params.worldActionTitle) {
    return {
      title: params.worldActionTitle,
      summary: params.worldActionSummary ?? '先按当前世界判断收口动作。',
      tone: 'info',
    };
  }

  if (params.signal) {
    return {
      title: `${params.signal.code} ${params.signal.name}`,
      summary: `当前最强推荐，先看入场、止损和目标位。`,
      tone: 'success',
    };
  }

  if (!params.todayCompleted) {
    return {
      title: '今天先补学习',
      summary: '学习链还没收口，先把系统跑完再判断进攻强度。',
      tone: 'warning',
    };
  }

  return {
    title: '当前没有强制动作',
    summary: '先看世界判断和仓位节奏，再决定今天要不要出手。',
    tone: 'neutral',
  };
}

export default function HomeScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { pushRiskAlerts, pushTakeoverAction } = useNotifications();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getHomeSnapshot(token ?? undefined),
    [token, apiBaseUrl],
    { refreshOnFocus: true }
  );

  const alerts = data?.alerts ?? [];
  const positions = data?.positions ?? [];
  const signals = data?.signals ?? [];
  const compositePicks = data?.compositePicks ?? [];
  const topAlert = alerts.find((item) => item.level !== 'info') ?? alerts[0] ?? null;
  const topPosition = getRiskPosition(positions);
  const topPick: CompositePick | null = compositePicks[0] ?? null;
  const topSignal: Signal | null = signals[0] ?? null;
  const worldState = data?.worldState ?? null;
  const worldAction = worldState?.actions[0] ?? null;
  const focus = getPrimaryFocus({
    topAlertTitle: topAlert?.title ?? null,
    topAlertMessage: topAlert?.message ?? null,
    worldActionTitle: worldAction?.title ?? null,
    worldActionSummary: worldAction?.summary ?? null,
    signal: topSignal,
    todayCompleted: data?.dailyAdvance.todayCompleted ?? false,
  });

  useEffect(() => {
    if ((data?.alerts?.length ?? 0) > 0) {
      void pushRiskAlerts(data?.alerts ?? []);
    }
  }, [data?.alerts, pushRiskAlerts]);

  useEffect(() => {
    if ((data?.actionBoard?.length ?? 0) > 0) {
      void pushTakeoverAction(data?.actionBoard ?? []);
    }
  }, [data?.actionBoard, pushTakeoverAction]);

  const recommendationRoute: Href =
    topSignal && 'signalId' in topSignal
      ? ({ pathname: '/signal/[id]', params: { id: topSignal.signalId } } as Href)
      : topSignal
        ? ({ pathname: '/signal/[id]', params: { id: topSignal.id } } as Href)
        : ('/(tabs)/signals' as Href);

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading title="首页" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取首页" />

      {data ? (
        <>
          <SurfaceCard style={styles.cardGap}>
            <View style={styles.cardHead}>
              <View style={styles.cardMain}>
                <Text style={[styles.cardTitle, { color: palette.text }]}>{focus.title}</Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>{focus.summary}</Text>
              </View>
              <StatusPill label={data.system.status} tone={focus.tone} />
            </View>
            <Text style={[styles.tipText, { color: palette.text }]}>
              世界 {worldState?.marketPhaseLabel ?? '待定'} / {data.productionGuard?.hardRiskGate ? '风控收紧' : '风控正常'}
            </Text>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {topSignal ? `${topSignal.code} ${topSignal.name}` : '当前没有新的主推荐'}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {topPick
                ? `策略 ${topPick.strategy} / 买点 ${topPick.buyPrice.toFixed(2)} / 止损 ${topPick.stopLoss.toFixed(2)} / 目标 ${topPick.targetPrice.toFixed(2)}`
                : topSignal
                  ? `策略 ${topSignal.strategy} / 买点 ${topSignal.buyPrice.toFixed(2)} / 止损 ${topSignal.stopLoss.toFixed(2)} / 目标 ${topSignal.targetPrice.toFixed(2)}`
                : '先等下一条有效推荐，或去推荐页看完整列表。'}
            </Text>
            <Text style={[styles.tipText, { color: palette.text }]}>今日推荐 {data.system.todaySignals} 条</Text>
            <Pressable
              onPress={() => {
                router.push(recommendationRoute);
              }}
              style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryButtonText}>{topSignal ? '看这只票' : '去推荐页'}</Text>
            </Pressable>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {topPosition ? `${topPosition.code} ${topPosition.name}` : '当前没有持仓压力'}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {topPosition
                ? `浮盈亏 ${topPosition.profitLossPct.toFixed(2)}% / 持有 ${topPosition.holdDays} 天 / 当前市值 ${formatCurrency(topPosition.marketValue)}`
                : `当前总仓建议 ${Math.round(data.positioningPlan.targetExposurePct)}%，可以先按世界判断决定要不要开新仓。`}
            </Text>
            <Pressable
              onPress={() => {
                router.push(topPosition ? ({ pathname: '/position/[code]', params: { code: topPosition.code } } as never) : ('/(tabs)/positions' as never));
              }}
              style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryButtonText}>{topPosition ? '处理仓位' : '去持仓页'}</Text>
            </Pressable>
          </SurfaceCard>
        </>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  cardGap: {
    gap: 12,
  },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
  },
  cardMain: {
    flex: 1,
    gap: 6,
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
  },
  primaryButton: {
    flex: 1,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    paddingHorizontal: 16,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  tipText: {
    fontSize: 13,
    lineHeight: 20,
  },
});
