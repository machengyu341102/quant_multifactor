import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { AlertCard } from '@/components/app/alert-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
import { StatusPill } from '@/components/app/status-pill';
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
  const criticalCount = alerts.filter((item) => item.level === 'critical').length;
  const warningCount = alerts.filter((item) => item.level === 'warning').length;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回首页</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Alert Center"
        title="风控提醒中心"
        subtitle="这里把系统、学习、推荐和持仓的提醒统一收口，方便你先处理最危险的事。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>RISK CENTER</Text>
        <Text style={styles.heroTitle}>{focusAlert ? focusAlert.title : '当前没有高优先级提醒'}</Text>
        <Text style={styles.heroCopy}>
          {focusAlert
            ? focusAlert.message
            : '没有新的紧急提醒时，这页会明确告诉你当前可控，而不是让你怀疑系统是不是没工作。'}
        </Text>
        <View style={styles.heroPills}>
          <StatusPill label={`紧急 ${criticalCount}`} tone={criticalCount > 0 ? 'danger' : 'neutral'} />
          <StatusPill label={`注意 ${warningCount}`} tone={warningCount > 0 ? 'warning' : 'neutral'} />
          <StatusPill label={`总提醒 ${alerts.length}`} tone="info" />
        </View>
      </View>
      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取提醒中心" />

      <SectionHeading
        title="一页风险摘要"
        subtitle="先把风险级别、当前焦点和下一动作压成一页，再往下看完整提醒列表。"
      />
      <SurfaceCard style={styles.summaryCard}>
        <ExecutiveSummaryGrid
          items={[
            {
              key: 'risk-level',
              step: '01 风险级别',
              title: criticalCount > 0 ? '存在紧急提醒' : warningCount > 0 ? '存在注意提醒' : '当前整体可控',
              meta: `紧急 ${criticalCount} / 注意 ${warningCount} / 总提醒 ${alerts.length}`,
              body:
                criticalCount > 0
                  ? '先处理紧急提醒，不要被普通提示分散注意力。'
                  : warningCount > 0
                    ? '当前重点在收敛风险和复核状态，不一定需要立刻动手。'
                    : '系统当前没有高优先级风险点，可以继续看主链路页面。',
            },
            {
              key: 'risk-focus',
              step: '02 当前焦点',
              title: focusAlert ? focusAlert.title : '暂无焦点告警',
              meta: focusAlert ? `${focusAlert.level} / ${focusAlert.source}` : '没有新的重点提醒',
              body: focusAlert?.message ?? '这页会在没有高优先级提醒时明确告诉你当前可控。',
            },
            {
              key: 'risk-next',
              step: '03 下一动作',
              title: focusAlert?.route ? '去对应页面处理' : '继续主链路',
              meta: focusAlert?.route ? `路由 ${focusAlert.route}` : '没有硬性动作要求',
              body: focusAlert?.route
                ? '优先进入对应页面处理具体问题，再回来复看其他提醒。'
                : '回首页、决策台或推荐页继续主判断，不必在告警页停留过久。',
            },
          ]}
        />

        {focusAlert?.route ? (
          <Pressable
            onPress={() => {
              router.push(resolveAppHref(focusAlert.route ?? '/'));
            }}
            style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryActionText}>处理当前焦点</Text>
          </Pressable>
        ) : null}
      </SurfaceCard>

      {highlightedAlerts.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前没有需要立刻处理的风险提醒。
          </Text>
        </SurfaceCard>
      ) : null}

      {highlightedAlerts.map((alert) => (
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
    gap: 14,
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
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
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
