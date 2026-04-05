import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getOpsSummary } from '@/lib/api';
import { formatTimestamp } from '@/lib/format';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function WorldScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getOpsSummary(token ?? undefined),
    [token, apiBaseUrl],
    { refreshOnFocus: true }
  );

  const worldState = data?.worldState ?? null;
  const topAction = worldState?.actions[0] ?? null;
  const topOperatingAction = worldState?.operatingActions[0] ?? null;
  const topCascade = worldState?.eventCascades[0] ?? null;
  const sourceProblems = (worldState?.sourceStatuses ?? []).filter(
    (item) => item.external && (item.originMode !== 'remote_live' || item.stale || Boolean(item.blockReason))
  );
  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回</Text>
      </Pressable>

      <SectionHeading title="世界判断" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取世界判断" />

      {worldState ? (
        <>
          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {worldState.marketPhaseLabel}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {worldState.structuralSummary ?? worldState.summary}
            </Text>
            <Text style={[styles.tipText, { color: palette.text }]}>
              主导 {worldState.dominantComponent ?? '继续观察'} / 估值 {worldState.valuationRegime}
            </Text>
            <Text style={[styles.tipText, { color: palette.text }]}>
              {worldState.technologyFocus
                ? `技术主线：${worldState.technologyFocus} / 科技突破 ${Math.round(worldState.technologyBreakthroughScore)}`
                : `科技突破 ${Math.round(worldState.technologyBreakthroughScore)}`}
            </Text>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {topAction?.title ?? '当前没有新的交易先手'}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {topAction?.summary ?? '继续按当前 execution policy 管仓位和策略开关。'}
            </Text>
            {topOperatingAction ? (
              <Text style={[styles.tipText, { color: palette.text }]}>
                经营先手：{topOperatingAction.title}。{topOperatingAction.summary}
              </Text>
            ) : null}
            <Pressable
              onPress={() => {
                router.push('/operating-profile' as never);
              }}
              style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryButtonText}>维护经营画像</Text>
            </Pressable>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {sourceProblems.length
                ? '这些源还在兜底或偏旧，别把世界判断当成无条件真理。'
                : '关键源当前都在可用区间。'}
            </Text>
            {topCascade ? (
              <Text style={[styles.tipText, { color: palette.text }]}>
                当前事件：{topCascade.title}
              </Text>
            ) : null}
            {(sourceProblems.length ? sourceProblems.slice(0, 1) : worldState.sourceStatuses.slice(0, 1)).map((item) => (
              <View key={item.key} style={[styles.sourceRow, { borderBottomColor: palette.border }]}>
                <View style={styles.sourceMain}>
                  <Text style={[styles.sourceTitle, { color: palette.text }]}>{item.label}</Text>
                  <Text style={[styles.sourceCopy, { color: palette.subtext }]}>
                    {item.freshnessLabel} / {item.originMode === 'remote_live' ? '直连' : item.degradedToDerived ? '兜底' : '未配'}
                    {item.updatedAt ? ` / ${formatTimestamp(item.updatedAt)}` : ''} / 质量 {Math.round(item.dataQualityScore)}
                  </Text>
                  {item.blockReason ? (
                    <Text style={[styles.sourceCopy, { color: palette.danger }]}>阻塞：{item.blockReason}</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </SurfaceCard>
        </>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignSelf: 'flex-start',
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
  cardGap: {
    gap: 12,
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
  tipText: {
    fontSize: 13,
    lineHeight: 20,
  },
  primaryButton: {
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
  sourceRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
    paddingBottom: 10,
    marginBottom: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  sourceMain: {
    flex: 1,
    gap: 4,
  },
  sourceTitle: {
    fontSize: 14,
    fontWeight: '700',
  },
  sourceCopy: {
    fontSize: 12,
    lineHeight: 18,
  },
});
