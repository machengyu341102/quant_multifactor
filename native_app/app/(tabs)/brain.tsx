import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { resolveAppHref } from '@/lib/app-routes';
import { formatPercent, formatTimestamp } from '@/lib/format';
import { getBrainSnapshot, getStockDiagnosis } from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type {
  BrainSnapshot,
  CompositePick,
  PolicyWatchItem,
  RecommendationCompareSnapshot,
  Signal,
  StockDiagnosis,
} from '@/types/trading';

const SCORE_LABELS: Record<string, string> = {
  trend: '趋势',
  momentum: '动量',
  volume: '量价',
  position: '位置',
  fund_flow: '资金',
};

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function buildTakeoverSummary(
  compare: RecommendationCompareSnapshot | null | undefined,
  pick: CompositePick | null
): string {
  if (!compare) {
    return '综合榜接管判断还没同步下来，先看推荐页的影子对比。';
  }

  if (!pick) {
    return `${compare.readiness.summary} 当前还没形成足够强的综合候选，先继续观察原推荐和强势收益引擎。`;
  }

  return `${compare.readiness.summary} 当前头部候选是 ${pick.code} ${pick.name}，${pick.setupLabel}，建议首仓 ${pick.firstPositionPct}%。`;
}

function buildBrainHeadline(data: BrainSnapshot | null | undefined): {
  title: string;
  tone: Tone;
  summary: string;
  tasks: string[];
} {
  if (!data) {
    return {
      title: '正在同步脑子状态',
      tone: 'neutral',
      summary: '等系统快照回来后，这里会把今天该盯的判断先说清楚。',
      tasks: [],
    };
  }

  const tasks: string[] = [];
  const topThemeSeed = data.compositePicks.find((item) => item.sourceCategory === 'theme_seed') ?? null;
  const topSwing = data.compositePicks.find(
    (item) => item.horizonLabel === '中期波段' || item.horizonLabel === '连涨接力'
  ) ?? null;
  if (!data.dailyAdvance.todayCompleted) {
    tasks.push('今天的日日精进还没跑完，先把学习链补齐。');
  } else {
    tasks.push('今天的学习闭环已经完成，可以放心看推荐和诊股。');
  }

  if (data.ops.recommendations[0]) {
    tasks.push(data.ops.recommendations[0].message);
  }

  if (data.compositeCompare?.readiness) {
    tasks.push(
      `综合榜当前判断是 ${data.compositeCompare.readiness.label}，${data.compositeCompare.readiness.recommendedAction}`
    );
  }

  if (topThemeSeed) {
    tasks.push(
      `今天先复核主线种子 ${topThemeSeed.code} ${topThemeSeed.name}，再决定要不要转入推荐或现场诊股。`
    );
  } else if (topSwing) {
    tasks.push(`今天先看中期波段 ${topSwing.code} ${topSwing.name}，判断是不是要放进首批观察。`);
  }

  if (data.themeRadar[0]) {
    tasks.push(`当前最热主线是 ${data.themeRadar[0].sector}，先看主线和强势股有没有共振。`);
  }

  if (data.system.todaySignals > 0) {
    tasks.push(`今天有 ${data.system.todaySignals} 条真实推荐，适合先从推荐池里挑重点票。`);
  } else {
    tasks.push('今天没有新增高质量推荐，更适合用手动诊股做复核。');
  }

  if (topThemeSeed) {
    return {
      title: '今天先看主线种子',
      tone: topThemeSeed.eventBias === '偏空' ? 'warning' : 'success',
      summary: `${topThemeSeed.code} ${topThemeSeed.name} 属于 ${topThemeSeed.horizonLabel}，先复核主线，再决定要不要转入推荐或诊股。`,
      tasks,
    };
  }

  if (topSwing) {
    return {
      title: '今天先看中期波段',
      tone: topSwing.eventBias === '偏空' ? 'warning' : 'info',
      summary: `${topSwing.code} ${topSwing.name} 当前更像 ${topSwing.horizonLabel}，适合先判断它是不是今天的主观察对象。`,
      tasks,
    };
  }

  if (data.system.healthScore >= 85 && data.dailyAdvance.todayCompleted) {
    return {
      title: '脑子状态在线',
      tone: 'success',
      summary: '系统、学习和推荐链都在正常工作，当前更像挑机会，而不是先救火。',
      tasks,
    };
  }

  if (data.system.healthScore < 80) {
    return {
      title: '先看系统健康',
      tone: 'warning',
      summary: '健康分偏低，演示时可以讲“有诊断能力”，但别硬讲成全自动稳定产线。',
      tasks,
    };
  }

  return {
    title: '今天先补学习再决策',
    tone: 'info',
    summary: '系统还活着，但今天最值钱的动作是把学习链跑完，再让决策更有说服力。',
    tasks,
  };
}

function buildCandidateReason(signal: Signal): string {
  if (signal.score >= 0.92 && signal.riskReward >= 2) {
    return '评分和盈亏结构都够硬，适合优先复核。';
  }
  if (signal.changePct >= 5) {
    return '票本身不差，但位置偏热，先防追高。';
  }
  if (signal.consensusCount > 1) {
    return `${signal.consensusCount} 个策略共识，适合放进首批观察。`;
  }
  return '适合用诊股做第二次确认。';
}

export default function BrainScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getBrainSnapshot(token ?? undefined),
    [token, apiBaseUrl]
  );
  const [diagnosisCode, setDiagnosisCode] = useState('');
  const [diagnosisError, setDiagnosisError] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnosis, setDiagnosis] = useState<StockDiagnosis | null>(null);

  const compositePicks = data?.compositePicks ?? [];
  const compositeCompare = data?.compositeCompare;
  const topCompositePick = compositePicks[0] ?? null;
  const topThemeSeedPick = compositePicks.find((item) => item.sourceCategory === 'theme_seed') ?? null;
  const topSwingCompositePick =
    compositePicks.find((item) => item.horizonLabel === '中期波段' || item.horizonLabel === '连涨接力') ?? null;
  const policyWatch = data?.policyWatch ?? [];
  const industryCapital = data?.industryCapital ?? [];
  const themeStages = data?.themeStages ?? [];
  const topPolicyWatch = policyWatch[0] ?? null;
  const topIndustryCapital = industryCapital[0] ?? null;
  const topThemeStage = themeStages[0] ?? null;
  const latestCandidates = (data?.signals ?? []).slice(0, 1);
  const brainHeadline = buildBrainHeadline(data);
  const openPolicyWatchDetail = (item: PolicyWatchItem) => {
    const expectedDetailId = `industry-capital-${item.id}`;
    const matchedDirection =
      industryCapital.find((direction) => direction.id === expectedDetailId) ??
      industryCapital.find(
        (direction) => direction.direction === item.direction && direction.focusSector === item.focusSector
      ) ??
      industryCapital.find((direction) => direction.direction === item.direction) ??
      industryCapital.find(
        (direction) => direction.focusSector === item.focusSector && direction.policyBucket === item.policyBucket
      );

    router.push(resolveAppHref(`/industry-capital/${matchedDirection?.id ?? expectedDetailId}`));
  };
  const matchedSignal = diagnosis ? (data?.signals ?? []).find((item) => item.code === diagnosis.code) : null;
  const scoreEntries = diagnosis
    ? Object.entries(diagnosis.scores).map(([key, value]) => ({
        key,
        label: SCORE_LABELS[key] ?? key,
        value,
        details: diagnosis.details[key] ?? [],
      }))
    : [];

  async function handleDiagnose(nextCode?: string) {
    const normalized = (nextCode ?? diagnosisCode).replace(/\D/g, '').slice(0, 6);
    if (!normalized || normalized.length !== 6) {
      setDiagnosisError('请输入 6 位股票代码');
      return;
    }

    setDiagnosisCode(normalized);
    setDiagnosing(true);
    setDiagnosisError(null);

    try {
      const result = await getStockDiagnosis(normalized, token ?? undefined);
      setDiagnosis(result);
    } catch (err) {
      setDiagnosisError(err instanceof Error ? err.message : '诊股失败');
    } finally {
      setDiagnosing(false);
    }
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading title="决策" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步脑子状态" />
      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.cardTitle, { color: palette.text }]}>{brainHeadline.title}</Text>
        <Text style={[styles.cardBody, { color: palette.subtext }]}>{brainHeadline.summary}</Text>
        <Text style={[styles.bodyText, { color: palette.text }]}>健康分 {data?.system.healthScore ?? '--'}</Text>
      </SurfaceCard>

      <SectionHeading title="今日脑子结论" />
      <SurfaceCard style={styles.cardGap}>
        {brainHeadline.tasks.slice(0, 1).map((item) => (
          <View key={item} style={styles.rowWithDot}>
            <View style={[styles.dot, { backgroundColor: palette.tint }]} />
            <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}
      </SurfaceCard>

      <SectionHeading title="方向快照" />
      <SurfaceCard style={styles.cardGap}>
        {topCompositePick ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.headlineTitle, { color: palette.text }]}>
              {topCompositePick.code} {topCompositePick.name}
            </Text>
            <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
              {topCompositePick.sourceLabel} / 建议首仓 {topCompositePick.firstPositionPct}% / {compositeCompare?.readiness.label ?? '继续影子'}
            </Text>
            <Text style={[styles.bodyText, { color: palette.text }]}>
              {buildTakeoverSummary(compositeCompare, topCompositePick)}
            </Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>
              下一步：{compositeCompare?.readiness.recommendedAction ?? topCompositePick.action}
            </Text>
            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  router.push('/(tabs)/signals');
                }}
                style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.secondaryActionText}>看推荐页</Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        {!topCompositePick && topPolicyWatch ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>{topPolicyWatch.direction}</Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {topPolicyWatch.policyBucket} / {topPolicyWatch.focusSector} / {topPolicyWatch.stageLabel} / {topPolicyWatch.participationLabel}
                </Text>
              </View>
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{topPolicyWatch.summary}</Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>{topPolicyWatch.action}</Text>
            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  openPolicyWatchDetail(topPolicyWatch);
                }}
                style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.secondaryActionText}>看方向深页</Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        {!topCompositePick && (topIndustryCapital || topThemeStage || topThemeSeedPick || topSwingCompositePick) ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>
                  {topIndustryCapital?.direction ?? topThemeStage?.sector ?? topThemeSeedPick?.name ?? topSwingCompositePick?.name ?? '继续观察'}
                </Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {topIndustryCapital
                    ? `${topIndustryCapital.strategicLabel} / ${topIndustryCapital.capitalHorizon} / ${topIndustryCapital.participationLabel}`
                    : topThemeStage
                      ? `${topThemeStage.stageLabel} / ${topThemeStage.participationLabel} / ${topThemeStage.intensity}`
                      : `${topThemeSeedPick?.horizonLabel ?? topSwingCompositePick?.horizonLabel ?? '观察单'}`}
                </Text>
              </View>
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>
              {topIndustryCapital?.businessAction ??
                topThemeStage?.summary ??
                topThemeSeedPick?.action ??
                topSwingCompositePick?.action ??
                '当前先盯主线、方向和候选的相互验证。'}
            </Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>
              {topIndustryCapital?.capitalAction ??
                topThemeStage?.action ??
                topIndustryCapital?.riskNote ??
                topThemeStage?.riskNote ??
                '没有明确催化前，先按观察单处理。'}
            </Text>
            <View style={styles.actionRow}>
              {topIndustryCapital ? (
                <Pressable
                  onPress={() => {
                    router.push(resolveAppHref(`/industry-capital/${topIndustryCapital.id}`));
                  }}
                  style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                  <Text style={styles.secondaryActionText}>看产业深页</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {!topCompositePick && !topPolicyWatch && !topIndustryCapital && !topThemeStage ? (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            当前方向还没收敛，先用下面的诊股和学习推进做当天主轴。
          </Text>
        ) : null}
      </SurfaceCard>

      <SectionHeading title="交互诊股" />
      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.label, { color: palette.subtext }]}>股票代码</Text>
        <TextInput
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="number-pad"
          maxLength={6}
          onChangeText={(value) => {
            setDiagnosisCode(value.replace(/\D/g, '').slice(0, 6));
            setDiagnosisError(null);
          }}
          placeholder="例如 000001"
          placeholderTextColor={palette.icon}
          style={[
            styles.input,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          value={diagnosisCode}
        />

        {latestCandidates.length > 0 ? (
          <View style={styles.candidateWrap}>
              {latestCandidates.map((item) => (
              <Pressable
                key={item.id}
                onPress={() => {
                  void handleDiagnose(item.code);
                }}
                style={[styles.candidateCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <View style={styles.candidateHead}>
                  <Text style={[styles.candidateCode, { color: palette.text }]}>{item.code}</Text>
                  <Text style={[styles.candidateMini, { color: palette.subtext }]}>{item.strategy}</Text>
                </View>
                <Text style={[styles.candidateName, { color: palette.text }]}>{item.name}</Text>
                <Text style={[styles.candidateReason, { color: palette.subtext }]}>
                  {buildCandidateReason(item)}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        <Pressable
          disabled={diagnosing}
          onPress={() => {
            void handleDiagnose();
          }}
          style={[styles.primaryButton, { backgroundColor: diagnosing ? palette.icon : palette.tint }]}>
          {diagnosing ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.primaryButtonText}>开始诊股</Text>
          )}
        </Pressable>

        {diagnosisError ? <Text style={[styles.errorText, { color: palette.danger }]}>{diagnosisError}</Text> : null}

        {diagnosis ? (
          <View style={styles.analysisGap}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>
                  {diagnosis.name} ({diagnosis.code})
                </Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {diagnosis.verdict} / {diagnosis.confidenceLabel} / {diagnosis.price.toFixed(2)} /{' '}
                  {formatTimestamp(diagnosis.asOf)} / {diagnosis.actionable ? '可交易' : '观察单'}
                </Text>
              </View>
            </View>

            <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.insightTitle, { color: palette.text }]}>一句判断</Text>
              <Text style={[styles.insightText, { color: palette.subtext }]}>
                {diagnosis.advice || diagnosis.reportText || diagnosis.regimeSummary}
              </Text>
            </View>

            <Text style={[styles.bodyText, { color: palette.subtext }]}>
              综合 {Math.round(diagnosis.totalScore * 100)} / 环境 {Math.round(diagnosis.regimeScore * 100)}
            </Text>

            <Text style={[styles.bodyText, { color: palette.text }]}>{diagnosis.regimeSummary}</Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>{diagnosis.healthBias}</Text>

            {diagnosis.topStrategy ? (
              <Text style={[styles.bodyText, { color: palette.subtext }]}>
                当前最值得参考的策略是 {diagnosis.topStrategy}，胜率{' '}
                {diagnosis.topStrategyWinRate !== null
                  ? formatPercent((diagnosis.topStrategyWinRate ?? 0) / 100, 0)
                  : '--'}
                ，均收{' '}
                {diagnosis.topStrategyAvgReturn !== null
                  ? formatPercent((diagnosis.topStrategyAvgReturn ?? 0) / 100)
                  : '--'}。
              </Text>
            ) : null}

            {scoreEntries.length ? (
              <Text style={[styles.bodyText, { color: palette.subtext }]}>
                {scoreEntries
                  .slice(0, 2)
                  .map((item) => `${item.label} ${Math.round(item.value * 100)}`)
                  .join(' / ')}
              </Text>
            ) : null}

            <View style={styles.listGroup}>
              <Text style={[styles.subTitle, { color: palette.text }]}>风险提示</Text>
              {(diagnosis.riskFlags.length > 0 ? diagnosis.riskFlags : ['当前没有额外风险旗标。']).slice(0, 1).map((item) => (
                <View key={item} style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
                </View>
              ))}
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.subTitle, { color: palette.text }]}>下一步</Text>
            {diagnosis.nextActions.slice(0, 1).map((item) => (
                <View key={item} style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.success }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
                </View>
              ))}
            </View>

            <View style={styles.actionRow}>
              {matchedSignal ? (
                <Pressable
                  onPress={() => {
                    router.push({ pathname: '/signal/[id]', params: { id: matchedSignal.id } });
                  }}
                  style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                  <Text style={styles.secondaryActionText}>看推荐详情</Text>
                </Pressable>
              ) : null}
              {diagnosis.inPortfolio ? (
                <Pressable
                  onPress={() => {
                    router.push({ pathname: '/position/[code]', params: { code: diagnosis.code } });
                  }}
                  style={[styles.ghostAction, { borderColor: palette.border }]}>
                  <Text style={[styles.ghostActionText, { color: palette.text }]}>看持仓详情</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}
      </SurfaceCard>

    </AppScreen>
  );
}

const styles = StyleSheet.create({
  cardGap: {
    gap: 14,
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  label: {
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  candidateWrap: {
    gap: 10,
  },
  candidateCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  candidateHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 10,
    alignItems: 'center',
  },
  candidateCode: {
    fontSize: 17,
    fontWeight: '800',
  },
  candidateMini: {
    fontSize: 12,
    lineHeight: 16,
  },
  candidateName: {
    fontSize: 15,
    fontWeight: '700',
  },
  candidateReason: {
    fontSize: 13,
    lineHeight: 20,
  },
  primaryButton: {
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },
  errorText: {
    fontSize: 14,
    fontWeight: '700',
  },
  analysisGap: {
    gap: 14,
  },
  headlineRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  headlineMain: {
    flex: 1,
    gap: 4,
  },
  headlineTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  headlineMeta: {
    fontSize: 13,
    lineHeight: 18,
  },
  insightBox: {
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  insightTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  insightText: {
    fontSize: 14,
    lineHeight: 22,
  },
  listGroup: {
    gap: 8,
  },
  rowWithDot: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    marginTop: 6,
  },
  bodyText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 21,
  },
  subTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  secondaryAction: {
    flex: 1,
    minHeight: 46,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  secondaryActionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  ghostAction: {
    flex: 1,
    minHeight: 46,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  ghostActionText: {
    fontSize: 14,
    fontWeight: '700',
  },
  checkRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  recommendationRow: {
    gap: 8,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(84, 99, 116, 0.22)',
  },
  themeCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 12,
  },
  themeFollowerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(84, 99, 116, 0.18)',
  },
  themeFollowerMain: {
    flex: 1,
    gap: 4,
  },
  themeFollowerRight: {
    alignItems: 'flex-end',
    gap: 4,
  },
  themeFollowerCode: {
    fontSize: 15,
    fontWeight: '700',
  },
  themeFollowerChange: {
    fontSize: 15,
    fontWeight: '800',
  },
  themeFollowerMeta: {
    fontSize: 12,
    lineHeight: 17,
  },
  strategyRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(84, 99, 116, 0.22)',
  },
  strategyMain: {
    flex: 1,
    gap: 4,
  },
  strategyRight: {
    alignItems: 'flex-end',
    gap: 4,
  },
  strategyName: {
    fontSize: 16,
    fontWeight: '700',
  },
  strategyValue: {
    fontSize: 18,
    fontWeight: '800',
  },
  strategyMeta: {
    fontSize: 13,
  },
});
