import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getOpsSummary } from '@/lib/api';
import { formatTimestamp } from '@/lib/format';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function OperatingTasksScreen() {
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
  const operatingProfile = worldState?.operatingProfile ?? null;
  const operatingActions = worldState?.operatingActions ?? [];
  const operatingChecks = (worldState?.checks ?? []).filter((item) => {
    const text = `${item.title} ${item.message}`.toLowerCase();
    return text.includes('经营') || text.includes('画像') || text.includes('库存') || text.includes('供应') || text.includes('现金');
  });
  const sourceBlockers = (worldState?.sourceStatuses ?? []).filter(
    (item) => item.external && (item.originMode !== 'remote_live' || item.stale || Boolean(item.blockReason))
  );

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回上一页</Text>
      </Pressable>

      <SectionHeading title="经营待办" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取经营待办" />

      {data ? (
        <>
          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {operatingActions[0]?.title ?? operatingProfile?.recommendedActions[0] ?? '先补经营画像'}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {operatingActions[0]?.summary ?? operatingProfile?.summary ?? '先把经营画像补齐，再让系统给出更准的经营动作。'}
            </Text>
            <Text style={[styles.todoBody, { color: palette.text }]}>
              {operatingProfile ? `完整度 ${Math.round(operatingProfile.completenessScore)} 分` : '画像未接入'}
            </Text>
            {(operatingActions.length ? operatingActions : []).slice(0, 1).map((action) => (
              <View key={action.key} style={[styles.todoRow, { borderBottomColor: palette.border }]}>
                <View style={styles.todoMain}>
                  <Text style={[styles.todoTitle, { color: palette.text }]}>{action.title}</Text>
                  <Text style={[styles.todoBody, { color: palette.subtext }]}>{action.summary}</Text>
                </View>
                <StatusPill
                  label={action.actionType}
                  tone={action.actionType === 'expand' || action.actionType === 'accelerate_rnd' ? 'success' : action.actionType === 'delay_capex' || action.actionType === 'hedge' || action.actionType === 'stockpile' ? 'warning' : 'info'}
                />
              </View>
            ))}
            {!operatingActions.length && operatingProfile?.recommendedActions.length ? (
              operatingProfile.recommendedActions.slice(0, 1).map((item, index) => (
                <Text key={`${item}-${index}`} style={[styles.todoBody, { color: palette.text }]}>
                  - {item}
                </Text>
              ))
            ) : null}
            <Pressable
              onPress={() => {
                router.push('/operating-profile' as never);
              }}
              style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryActionText}>去补经营画像</Text>
            </Pressable>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            {operatingProfile ? (
              <>
                <Text style={[styles.cardTitle, { color: palette.text }]}>
                  {operatingProfile.companyName} / {operatingProfile.operatingMode}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  行业 {operatingProfile.primaryIndustries.join(' / ') || '继续观察'} / 更新时间 {operatingProfile.updatedAt ? formatTimestamp(operatingProfile.updatedAt) : '暂无'}
                </Text>
                <Text style={[styles.todoBody, { color: palette.text }]}>
                  供应商集中度 {operatingProfile.supplierConcentrationPct.toFixed(0)}%
                </Text>
                {operatingProfile.missingFields.length ? (
                  <Text style={[styles.cardBody, { color: palette.warning }]}>
                    缺口：{operatingProfile.missingFields.slice(0, 3).join(' / ')}
                  </Text>
                ) : null}
                {operatingProfile.recommendedActions[0] ? (
                  <Text style={[styles.cardBody, { color: palette.text }]}>下一步：{operatingProfile.recommendedActions[0]}</Text>
                ) : null}
              </>
            ) : (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>当前还没有经营画像。</Text>
            )}
            {operatingChecks.length === 0 && sourceBlockers.length === 0 ? (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>当前没有明显经营阻塞，可以继续沿经营动作执行。</Text>
            ) : null}
            {operatingChecks.slice(0, 1).map((item) => (
              <Text key={item.key} style={[styles.todoBody, { color: item.level === 'critical' ? palette.danger : palette.text }]}>
                {item.title}：{item.message}
              </Text>
            ))}
            {sourceBlockers.slice(0, 1).map((item) => (
              <Text key={item.key} style={[styles.todoBody, { color: item.blockReason ? palette.danger : palette.subtext }]}>
                {item.label}：{item.freshnessLabel} / {item.originMode === 'remote_live' ? '远端直连' : item.degradedToDerived ? '派生兜底' : item.remoteConfigured ? '已配待直连' : '远端未配'}
                {item.blockReason ? ` / 阻塞：${item.blockReason}` : ''}
              </Text>
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
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
  },
  todoRow: {
    flexDirection: 'row',
    gap: 12,
    justifyContent: 'space-between',
    paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  todoMain: {
    flex: 1,
    gap: 4,
  },
  todoTitle: {
    fontSize: 15,
    fontWeight: '800',
    lineHeight: 21,
  },
  todoBody: {
    fontSize: 13,
    lineHeight: 20,
  },
  primaryAction: {
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
});
