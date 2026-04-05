import { Pressable, StyleSheet, Text } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { AlertCard } from '@/components/app/alert-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { resolveAppHref } from '@/lib/app-routes';
import { getAlerts } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function AlertsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ focus?: string }>();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getAlerts(token ?? undefined),
    [token, apiBaseUrl]
  );
  const alerts = data ?? [];
  const highlightedAlerts = params.focus
    ? [...alerts].sort((a, b) => Number(b.level === params.focus) - Number(a.level === params.focus))
    : alerts;
  const focusAlert = highlightedAlerts[0] ?? null;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回</Text>
      </Pressable>

      <SectionHeading title="风控提醒" />

      <SurfaceCard style={styles.summaryCard}>
        <Text style={[styles.summaryTitle, { color: palette.text }]}>
          {focusAlert ? focusAlert.title : '当前没有高优先级提醒'}
        </Text>
        {focusAlert ? (
          <Text style={[styles.summaryHint, { color: palette.subtext }]} numberOfLines={1}>
            {focusAlert.message}
          </Text>
        ) : null}
        {focusAlert?.route ? (
          <Pressable
            onPress={() => {
              router.push(resolveAppHref(focusAlert.route ?? '/'));
            }}
            style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryActionText}>处理</Text>
          </Pressable>
        ) : null}
      </SurfaceCard>
      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取提醒中心" />

      {highlightedAlerts.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有风险提醒。
          </Text>
        </SurfaceCard>
      ) : null}

      {highlightedAlerts.slice(0, 1).map((alert) => (
        <AlertCard
          key={alert.id}
          alert={alert}
          onPress={
            alert.route
              ? () => {
                  router.push(resolveAppHref(alert.route));
                }
              : undefined
          }
        />
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
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  summaryCard: {
    gap: 12,
  },
  summaryTitle: {
    fontSize: 20,
    fontWeight: '800',
  },
  summaryHint: {
    fontSize: 13,
    lineHeight: 19,
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
});
