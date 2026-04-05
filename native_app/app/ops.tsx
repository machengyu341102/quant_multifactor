import { Pressable, StyleSheet, Text } from 'react-native';
import { useRouter } from 'expo-router';
import Constants from 'expo-constants';

import { AppScreen } from '@/components/app/app-screen';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
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

function formatExportFreshness(stale: boolean) {
  return stale ? '待刷新' : '最新';
}

export default function OpsScreen() {
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
  const installedAppVersion = Constants.expoConfig?.version ?? '未知';
  const installedBuildVersion = String(
    Constants.expoConfig?.android?.versionCode ??
      Constants.expoConfig?.ios?.buildNumber ??
      '未知'
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

      <SurfaceCard style={styles.summaryCard}>
        <Text style={[styles.cardTitle, { color: palette.text }]}>
          {data?.ready ? '系统当前可用' : '系统存在降级项'}
        </Text>
        <Text style={[styles.cardBody, { color: palette.subtext }]}>
          {data
            ? `应用 v${installedAppVersion} / 服务 ${data.service} v${data.version} / 健康分 ${data.systemHealthScore} / 平均延迟 ${formatLatency(data.avgLatencyMs)}。`
            : '先看系统是不是活着、快不快、有没有明显降级。'}
        </Text>
        <Text style={[styles.cardBody, { color: palette.text }]}>
          {data?.ready ? '就绪正常' : '就绪降级'} / 系统 {data?.systemStatus ?? '未知'} / WebSocket {data?.websocketConnections ?? 0}
        </Text>
      </SurfaceCard>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取运维摘要" />

      {data ? (
        <>
          <SurfaceCard>
            <Text style={[styles.cardBody, { color: palette.text }]}>
              请求 {data.requestCount} / 错误率 {formatPercentValue(data.errorRate)} / 延迟 {formatLatency(data.avgLatencyMs)} / 健康分 {data.systemHealthScore}
            </Text>
          </SurfaceCard>

          <SurfaceCard>
            <Text style={[styles.cardTitle, { color: palette.text }]}>运行上下文</Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              应用版本 v{installedAppVersion} / build {installedBuildVersion}
            </Text>
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

          <SurfaceCard>
            {data.worldState ? (
              <>
                <Text style={[styles.cardTitle, { color: palette.text }]}>
                  {data.worldState.marketPhaseLabel} / {data.worldState.dominantComponent ?? '结构观察'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  {data.worldState.structuralSummary ?? data.worldState.summary}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  估值 {data.worldState.valuationRegime} / 资金 {data.worldState.capitalStyle} / 技术 {data.worldState.technologyFocus ?? '继续观察'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  国别博弈 {data.worldState.geopoliticsBias} / 供应链 {data.worldState.supplyChainMode} / 置信度 {data.worldState.phaseConfidence}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  科技突破 {data.worldState.technologyBreakthroughScore.toFixed(1)} / {data.worldState.technologyBreakthroughSummary ?? '继续观察技术突破。'}
                </Text>
                {data.worldState.refreshPlan ? (
                  <Text style={[styles.cardBody, { color: data.worldState.refreshPlan.escalationActive ? palette.tint : palette.subtext }]}>
                    抓取节奏 {data.worldState.refreshPlan.modeLabel} / {data.worldState.refreshPlan.activeWindowLabel} / 新闻 {data.worldState.refreshPlan.newsIntervalMinutes}m / 世界 {data.worldState.refreshPlan.feedsIntervalMinutes}m / 硬源 {data.worldState.refreshPlan.hardSourceIntervalMinutes}m / 官方 {data.worldState.refreshPlan.policyIntervalMinutes}m
                  </Text>
                ) : null}
                {data.worldState.refreshPlan?.overdueSources.length ? (
                  <Text style={[styles.cardBody, { color: palette.danger }]}>
                    待补抓 {data.worldState.refreshPlan.overdueSources.join(' / ')}
                  </Text>
                ) : null}
                {data.worldState.sourceStatuses.slice(0, 1).map((source) => (
                  <Text key={source.key} style={[styles.cardBody, { color: palette.subtext }]}>
                    - 数据源 {source.label}：可靠 {source.reliabilityScore} / 权威 {source.authorityScore} / 及时 {source.timelinessScore} / 质量 {source.dataQualityScore} / {source.freshnessLabel} / {source.originMode === 'remote_live' ? '远端直连' : source.degradedToDerived ? '派生兜底' : source.remoteConfigured ? '已配待直连' : source.external ? '远端未配' : '本地派生'}
                  </Text>
                ))}
                {data.worldState.topDirections.slice(0, 1).map((direction) => (
                  <Text key={direction.directionId} style={[styles.cardBody, { color: palette.subtext }]}>
                    - 主导方向 {direction.direction}：总分 {direction.totalScore} / 官方 {direction.officialScore} / 链路 {direction.chainControlScore} / 硬源 {direction.hardSourceScore} / 突破 {direction.technologyBreakthroughScore}
                  </Text>
                ))}
                {data.worldState.crossAssetSignals.slice(0, 1).map((signal) => (
                  <Text key={signal.key} style={[styles.cardBody, { color: palette.subtext }]}>
                    - 跨资产 {signal.label}：{signal.bias} / {signal.score} / {signal.summary}
                  </Text>
                ))}
                {data.worldState.eventCascades.slice(0, 1).map((event) => (
                  <Text key={event.eventId} style={[styles.cardBody, { color: palette.subtext }]}>
                    - 事件跟踪 {event.title}：{event.followUpSignal} / 可信度 {event.confidenceScore.toFixed(0)} / {event.restrictionScope} / 影响 {event.estimatedFlowImpactPct.toFixed(0)}%
                  </Text>
                ))}
                {data.worldState.operatingActions.slice(0, 1).map((action) => (
                  <Text key={action.key} style={[styles.cardBody, { color: palette.subtext }]}>
                    - 经营动作 {action.title}：{action.summary}
                  </Text>
                ))}
                {data.worldState.actions.slice(0, 1).map((action) => (
                  <Text key={action.key} style={[styles.cardBody, { color: palette.text }]}>
                    - 顶层动作 {action.title}：{action.summary}
                  </Text>
                ))}
                {data.worldState.checks.slice(0, 1).map((check) => (
                  <Text key={check.key} style={[styles.cardBody, { color: check.level === 'critical' ? palette.danger : palette.subtext }]}>
                    - 自检 {check.title}：{check.message}
                  </Text>
                ))}
              </>
            ) : (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>
                当前还没有顶层世界状态快照，执行层缺少更高一层的结构判断。
              </Text>
            )}
          </SurfaceCard>

          <SurfaceCard style={styles.summaryCard}>
            {data.worldStateExport ? (
              <>
                <Text style={[styles.cardTitle, { color: palette.text }]}>
                  顶层归档：{data.worldStateExport.latestExportId ?? '未生成'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  周期 {data.worldStateExport.period} / 状态 {formatExportFreshness(data.worldStateExport.stale)} / 历史 {data.worldStateExport.historyCount} 份 / 资产 {data.worldStateExport.latestAssetCount} 个
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  最新 {data.worldStateExport.latestExportAt ? formatTimestamp(data.worldStateExport.latestExportAt) : '暂无'} / Bundle {data.worldStateExport.latestBundleRoute ?? '暂无'}
                </Text>
              </>
            ) : (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>
                当前还没有 world state 固定导出，顶层世界判断只能看即时值，缺少稳定归档。
              </Text>
            )}
            {data.executionPolicyExport ? (
              <>
                <Text style={[styles.cardTitle, { color: palette.text }]}>
                  执行归档：{data.executionPolicyExport.latestExportId ?? '未生成'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  周期 {data.executionPolicyExport.period} / 状态 {formatExportFreshness(data.executionPolicyExport.stale)} / 历史 {data.executionPolicyExport.historyCount} 份 / 资产 {data.executionPolicyExport.latestAssetCount} 个
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  最新 {data.executionPolicyExport.latestExportAt ? formatTimestamp(data.executionPolicyExport.latestExportAt) : '暂无'} / Bundle {data.executionPolicyExport.latestBundleRoute ?? '暂无'}
                </Text>
              </>
            ) : (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>
                当前还没有 execution policy 固定导出，运维页只能看到即时状态，缺少可回溯留档。
              </Text>
            )}
          </SurfaceCard>

          <SurfaceCard>
            {data.productionGuard ? (
              <>
                <Text style={[styles.cardTitle, { color: palette.text }]}>
                  {data.productionGuard.hardRiskGate
                    ? '硬风控已触发'
                    : data.productionGuard.blockedAdditions
                    ? '当前禁止新增'
                    : '当前未触发硬风控'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  {data.productionGuard.marketPhaseLabel} / 当前回撤 {data.productionGuard.currentDrawdownPct}% / 历史最大回撤 {data.productionGuard.maxDrawdownPct}%
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  Walk-forward 风险 {data.productionGuard.walkForwardRisk} / 退化 {data.productionGuard.walkForwardDegradation ?? '暂无'}
                </Text>
                <Text style={[styles.cardBody, { color: palette.subtext }]}>
                  {data.productionGuard.summary}
                </Text>
                {data.productionGuard.unstableStrategies.length > 0 ? (
                  <Text style={[styles.cardBody, { color: palette.subtext }]}>
                    不稳定策略 {data.productionGuard.unstableStrategies.join(' / ')}
                  </Text>
                ) : null}
                {data.productionGuard.actions.map((action) => (
                  <Text key={action} style={[styles.cardBody, { color: palette.subtext }]}>
                    - {action}
                  </Text>
                ))}
              </>
            ) : (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>
                当前还没有 production guard 快照，执行层还缺自动风控闭环。
              </Text>
            )}
          </SurfaceCard>
          <SurfaceCard>
            <Text style={[styles.cardTitle, { color: palette.text }]}>当前阻塞</Text>
            {data.readinessIssues.length === 0 ? (
              <Text style={[styles.cardBody, { color: palette.success }]}>
                核心就绪通过。
              </Text>
            ) : (
              <Text style={[styles.issueText, { color: palette.danger }]}>
                {data.readinessIssues[0]}
              </Text>
            )}
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              数据 {data.dataStatus.signalCount} / 持仓 {data.dataStatus.activePositions} / 反馈 {data.dataStatus.feedbackItems}
            </Text>
            {data.recommendations[0] ? (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>
                下一步：{data.recommendations[0].message}
              </Text>
            ) : null}
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
  summaryCard: {
    gap: 14,
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
});
