import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getOpsSummary } from '@/lib/api';
import { formatTimestamp } from '@/lib/format';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

function formatPercentValue(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatLatency(value: number) {
  return `${value.toFixed(0)} ms`;
}

function formatUptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

export default function OpsScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getOpsSummary(token ?? undefined),
    [token, apiBaseUrl]
  );

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回我的</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Ops"
        title="运维诊断"
        subtitle="这里不讲故事，直接看服务活性、就绪、延迟、错误率和数据源状态。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>OPS OVERVIEW</Text>
        <Text style={styles.heroTitle}>
          {data?.ready ? '系统当前可用' : '系统存在降级项'}
        </Text>
        <Text style={styles.heroCopy}>
          {data
            ? `就绪 ${data.ready ? '通过' : '降级'}，健康分 ${data.systemHealthScore}，平均延迟 ${formatLatency(data.avgLatencyMs)}。`
            : '先看系统是不是活着、快不快、有没有明显降级，再谈更细的指标。'}
        </Text>
        <View style={styles.pillRow}>
          <StatusPill
            label={data?.ready ? '就绪正常' : '就绪降级'}
            tone={data?.ready ? 'success' : 'warning'}
          />
          <StatusPill
            label={`系统 ${data?.systemStatus ?? '未知'}`}
            tone={data?.systemHealthScore && data.systemHealthScore >= 80 ? 'success' : 'warning'}
          />
          <StatusPill
            label={`WebSocket ${data?.websocketConnections ?? 0}`}
            tone="info"
          />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取运维摘要" />

      {data ? (
        <>
          <SectionHeading
            title="一页运维判断"
            subtitle="先把服务可用性、延迟、数据活性和当前建议压成一页，再往下看细项。"
          />
          <SurfaceCard style={styles.summaryCard}>
            <ExecutiveSummaryGrid
              items={[
                {
                  key: 'ops-status',
                  step: '01 当前状态',
                  title: data.ready ? '当前系统可用' : '存在就绪降级',
                  meta: `服务 ${data.service} / v${data.version}`,
                  body: data.ready
                    ? '核心服务、数据源和接口链当前都能工作。'
                    : '虽然服务还活着，但 readiness 已经提示这不是完全可交付状态。',
                },
                {
                  key: 'ops-performance',
                  step: '02 性能表现',
                  title: `平均 ${formatLatency(data.avgLatencyMs)} / P95 ${formatLatency(data.p95LatencyMs)}`,
                  meta: `请求 ${data.requestCount} / 错误 ${data.errorCount}`,
                  body: `错误率 ${formatPercentValue(data.errorRate)}，运行时长 ${formatUptime(data.uptimeSeconds)}。`,
                },
                {
                  key: 'ops-data',
                  step: '03 数据活性',
                  title: `信号 ${data.dataStatus.signalCount} / 持仓 ${data.dataStatus.activePositions}`,
                  meta: `Scorecard ${data.dataStatus.scorecardRecords} / Feedback ${data.dataStatus.feedbackItems}`,
                  body: '至少要确认脑子在持续吃数据、写反馈、保留推送设备，而不只是页面亮着。',
                },
                {
                  key: 'ops-recommendation',
                  step: '04 当前建议',
                  title: data.recommendations[0]?.title ?? '当前暂无额外建议',
                  meta: `最近错误 ${data.lastErrorAt ? formatTimestamp(data.lastErrorAt) : '暂无'}`,
                  body: data.recommendations[0]?.message ?? '当前没有额外需要立即处理的运维动作。',
                },
              ]}
            />
          </SurfaceCard>

          <SectionHeading title="服务摘要" subtitle="这是你现在能盯住的最核心 8 个指标。" />
          <View style={styles.metricGrid}>
            <MetricCard label="请求量" value={`${data.requestCount}`} tone="neutral" />
            <MetricCard label="错误数" value={`${data.errorCount}`} tone="warning" />
            <MetricCard label="错误率" value={formatPercentValue(data.errorRate)} tone="warning" />
            <MetricCard label="平均延迟" value={formatLatency(data.avgLatencyMs)} tone="info" />
            <MetricCard label="P95 延迟" value={formatLatency(data.p95LatencyMs)} tone="info" />
            <MetricCard label="健康分" value={`${data.systemHealthScore}`} tone="success" />
            <MetricCard label="今日信号" value={`${data.todaySignals}`} tone="success" />
            <MetricCard label="运行时长" value={formatUptime(data.uptimeSeconds)} tone="neutral" />
          </View>

          <SurfaceCard>
            <Text style={[styles.cardTitle, { color: palette.text }]}>运行上下文</Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              服务 {data.service} / v{data.version}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              启动时间 {formatTimestamp(data.startedAt)}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              API 地址 {apiBaseUrl}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              最近错误 {data.lastErrorAt ? `${formatTimestamp(data.lastErrorAt)} / ${data.lastErrorPath}` : '暂无'}
            </Text>
          </SurfaceCard>

          <SectionHeading title="数据源状态" subtitle="至少要知道脑子有没有在吃数据，而不是页面看着亮。 " />
          <View style={styles.metricGrid}>
            <MetricCard
              label="Scorecard"
              value={`${data.dataStatus.scorecardRecords}`}
              tone="neutral"
            />
            <MetricCard
              label="TradeJournal"
              value={`${data.dataStatus.tradeJournalRecords}`}
              tone="neutral"
            />
            <MetricCard label="Signals" value={`${data.dataStatus.signalCount}`} tone="success" />
            <MetricCard
              label="Positions"
              value={`${data.dataStatus.activePositions}`}
              tone="info"
            />
            <MetricCard
              label="Feedback"
              value={`${data.dataStatus.feedbackItems}`}
              tone="warning"
            />
            <MetricCard
              label="PushDevices"
              value={`${data.dataStatus.pushDevices}`}
              tone="info"
            />
          </View>

          <SectionHeading title="就绪检查" subtitle="这些项一旦挂了，页面还能开，也不算真正可用。" />
          <SurfaceCard>
            {data.readinessIssues.length === 0 ? (
              <Text style={[styles.cardBody, { color: palette.success }]}>
                当前 readiness 通过，没有发现核心数据源加载失败。
              </Text>
            ) : (
              data.readinessIssues.map((issue) => (
                <Text key={issue} style={[styles.issueText, { color: palette.danger }]}>
                  {issue}
                </Text>
              ))
            )}
          </SurfaceCard>

          <SectionHeading title="系统建议" subtitle="先给出该做什么，不只是堆指标。" />
          <SurfaceCard>
            {data.recommendations.map((item) => (
              <View key={`${item.level}-${item.title}`} style={styles.routeRow}>
                <Text style={[styles.routeTitle, { color: palette.text }]}>{item.title}</Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>{item.message}</Text>
              </View>
            ))}
          </SurfaceCard>

          <SectionHeading title="热点接口" subtitle="优先盯错误多和请求多的路由。" />
          <SurfaceCard>
            {data.routes.map((route) => (
              <View key={`${route.method}-${route.path}`} style={styles.routeRow}>
                <View style={styles.routeMain}>
                  <Text style={[styles.routeTitle, { color: palette.text }]}>
                    {route.method} {route.path}
                  </Text>
                  <Text style={[styles.routeMeta, { color: palette.subtext }]}>
                    最近访问 {route.lastSeenAt ? formatTimestamp(route.lastSeenAt) : '暂无'}
                  </Text>
                </View>
                <View style={styles.routeSide}>
                  <Text style={[styles.routeValue, { color: palette.text }]}>
                    {route.count} 次 / {route.errorCount} 错
                  </Text>
                  <Text style={[styles.routeMeta, { color: palette.subtext }]}>
                    平均 {formatLatency(route.avgLatencyMs)} / Max {formatLatency(route.maxLatencyMs)}
                  </Text>
                </View>
              </View>
            ))}
          </SurfaceCard>

          <SurfaceCard>
            <Text style={[styles.cardTitle, { color: palette.text }]}>SLA 结论</Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              这套现在已经可维护、可监控，但还是单机 + 文件存储形态，不能对外承诺 99.99%。
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              真要碰 99.99%，至少还要补双实例、反向代理健康探针、Postgres/Redis、进程守护、外部告警和灰度发布。
            </Text>
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
  pillRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  summaryCard: {
    gap: 14,
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 8,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
  },
  issueText: {
    fontSize: 14,
    lineHeight: 21,
    marginBottom: 6,
  },
  routeRow: {
    gap: 6,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#D5E0EB',
  },
  routeMain: {
    gap: 4,
  },
  routeSide: {
    gap: 2,
  },
  routeTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  routeValue: {
    fontSize: 14,
    fontWeight: '700',
  },
  routeMeta: {
    fontSize: 12,
    lineHeight: 18,
  },
});
