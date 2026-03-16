import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { resolveAppHref } from '@/lib/app-routes';
import { formatPercent, formatTimestamp } from '@/lib/format';
import { getBrainSnapshot, getStockDiagnosis, runLearningAdvance } from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type {
  BrainSnapshot,
  CompositePick,
  IndustryCapitalDirection,
  PolicyWatchItem,
  RecommendationCompareSnapshot,
  Signal,
  StockDiagnosis,
  ThemeStageItem,
} from '@/types/trading';

const SCORE_LABELS: Record<string, string> = {
  trend: '趋势',
  momentum: '动量',
  volume: '量价',
  position: '位置',
  fund_flow: '资金',
};

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function toneFromLevel(level: string): Tone {
  if (level === 'critical') {
    return 'danger';
  }
  if (level === 'warning') {
    return 'warning';
  }
  if (level === 'success') {
    return 'success';
  }
  if (level === 'info') {
    return 'info';
  }
  return 'neutral';
}

function getDiagnosisTone(diagnosis: StockDiagnosis): Tone {
  if (diagnosis.actionable && diagnosis.regimeScore >= 0.7) {
    return 'success';
  }
  if (diagnosis.actionable) {
    return 'info';
  }
  if (diagnosis.riskFlags.length > 0) {
    return 'warning';
  }
  return 'neutral';
}

function getThemeTone(intensity: string): Tone {
  if (intensity.includes('高热')) {
    return 'warning';
  }
  if (intensity.includes('升温')) {
    return 'info';
  }
  return 'neutral';
}

function getReadinessTone(status: string): Tone {
  if (status === 'ready') {
    return 'success';
  }
  if (status === 'pilot') {
    return 'info';
  }
  if (status === 'hold') {
    return 'danger';
  }
  return 'warning';
}

function getCompositeSourceTone(category: string): Tone {
  if (category === 'theme_seed' || category === 'resonance') {
    return 'success';
  }
  if (category === 'strong_move') {
    return 'info';
  }
  return 'neutral';
}

function getThemeStageTone(item: ThemeStageItem): Tone {
  if (item.participationLabel === '后排回避') {
    return 'danger';
  }
  if (item.stageLabel === '主升波段') {
    return 'success';
  }
  if (item.stageLabel === '中期扩散') {
    return 'info';
  }
  return 'warning';
}

function getPolicyWatchTone(item: PolicyWatchItem): Tone {
  if (item.stageLabel === '承压观察') {
    return 'warning';
  }
  if (item.stageLabel === '兑现扩散') {
    return 'success';
  }
  if (item.stageLabel === '催化升温') {
    return 'info';
  }
  return 'neutral';
}

function getIndustryCapitalTone(item: IndustryCapitalDirection): Tone {
  if (item.strategicLabel === '逆风跟踪') {
    return 'warning';
  }
  if (item.participationLabel === '中期波段' || item.participationLabel === '连涨接力') {
    return 'success';
  }
  return 'info';
}

function getIndustryResearchTone(label: string): Tone {
  if (label === '验证增强') {
    return 'success';
  }
  if (label === '出现阻力') {
    return 'warning';
  }
  if (label === '继续验证') {
    return 'info';
  }
  return 'neutral';
}

function canOpenCompositeDetail(pick: CompositePick | null): boolean {
  return Boolean(pick && pick.sourceCategory !== 'theme_seed' && !pick.signalId.startsWith('theme-seed-'));
}

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
  const [learningSubmitting, setLearningSubmitting] = useState(false);
  const [diagnosis, setDiagnosis] = useState<StockDiagnosis | null>(null);

  const compositePicks = data?.compositePicks ?? [];
  const compositeCompare = data?.compositeCompare;
  const topCompositePick = compositePicks[0] ?? null;
  const topThemeSeedPick = compositePicks.find((item) => item.sourceCategory === 'theme_seed') ?? null;
  const topSwingCompositePick =
    compositePicks.find((item) => item.horizonLabel === '中期波段' || item.horizonLabel === '连涨接力') ?? null;
  const topStrategyCompositePick =
    compositePicks.find((item) => item.sourceCategory !== 'theme_seed') ?? null;
  const policyWatch = data?.policyWatch ?? [];
  const industryCapital = data?.industryCapital ?? [];
  const themeStages = data?.themeStages ?? [];
  const topPolicyWatch = policyWatch[0] ?? null;
  const topIndustryCapital = industryCapital[0] ?? null;
  const topThemeStage = themeStages[0] ?? null;
  const latestCandidates = (data?.signals ?? []).slice(0, 4);
  const topStrategies = (data?.strategies ?? []).slice(0, 5);
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

  async function handleRunLearningAdvance() {
    if (!token) {
      return;
    }

    setLearningSubmitting(true);
    try {
      await runLearningAdvance(token);
      await refresh();
    } catch (err) {
      setDiagnosisError(err instanceof Error ? err.message : '启动日日精进失败');
    } finally {
      setLearningSubmitting(false);
    }
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeading
        eyebrow="Brain Console"
        title="AI 决策台"
        subtitle="这页现在只做三件事：给今天一句判断、现场诊股、推进学习闭环。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>TODAY&apos;S BRAIN</Text>
        <Text style={styles.heroTitle}>{brainHeadline.title}</Text>
        <Text style={styles.heroCopy}>{brainHeadline.summary}</Text>
        <View style={styles.heroPills}>
          <StatusPill label={`健康分 ${data?.system.healthScore ?? '--'}`} tone={brainHeadline.tone} />
          <StatusPill
            label={`准确率 ${formatPercent(data?.learning.decisionAccuracy ?? 0, 0)}`}
            tone="success"
          />
          <StatusPill
            label={`接管 ${compositeCompare?.readiness.label ?? '继续影子'}`}
            tone={getReadinessTone(compositeCompare?.readiness.status ?? 'shadow')}
          />
          <StatusPill
            label={data?.dailyAdvance.todayCompleted ? '日日精进已完成' : '日日精进待执行'}
            tone={data?.dailyAdvance.todayCompleted ? 'success' : 'warning'}
          />
          <StatusPill label={`今日推荐 ${data?.system.todaySignals ?? 0}`} tone="info" />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在同步脑子状态" />

      <SectionHeading
        title="一页判断"
        subtitle="先把今天的大逻辑、主线、方向和学习状态压成一页，再往下看详细证据。"
      />
      <SurfaceCard style={styles.cardGap}>
        <View style={styles.snapshotGrid}>
          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>01 今日判断</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>{brainHeadline.title}</Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              健康分 {data?.system.healthScore ?? '--'} / 今日推荐 {data?.system.todaySignals ?? 0}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>{brainHeadline.summary}</Text>
          </View>

          <Pressable
            onPress={() => {
              router.push('/(tabs)/brain');
            }}>
            <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <Text style={[styles.snapshotStep, { color: palette.tint }]}>02 政策方向</Text>
              <Text style={[styles.snapshotTitle, { color: palette.text }]}>
                {topPolicyWatch ? topPolicyWatch.direction : '正在归纳政策大方向'}
              </Text>
              <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                {topPolicyWatch
                  ? `${topPolicyWatch.policyBucket} / ${topPolicyWatch.industryPhase} / ${topPolicyWatch.stageLabel}`
                  : '先判断政策、地缘和需求从哪里开始传导。'}
              </Text>
              <Text style={[styles.snapshotBody, { color: palette.text }]}>
                {topPolicyWatch?.action ?? '继续等待政策方向雷达同步。'}
              </Text>
            </View>
          </Pressable>

          <Pressable
            onPress={() => {
              if (topIndustryCapital) {
                router.push(resolveAppHref(`/industry-capital/${topIndustryCapital.id}`));
                return;
              }
              router.push('/(tabs)/brain');
            }}>
            <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <Text style={[styles.snapshotStep, { color: palette.tint }]}>03 产业动作</Text>
              <Text style={[styles.snapshotTitle, { color: palette.text }]}>
                {topIndustryCapital ? topIndustryCapital.direction : '正在翻译成产业资本动作'}
              </Text>
              <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                {topIndustryCapital
                  ? `${topIndustryCapital.strategicLabel} / ${topIndustryCapital.capitalHorizon} / ${topIndustryCapital.participationLabel}`
                  : '把政策方向落成事业动作、资本动作和公司清单。'}
              </Text>
              <Text style={[styles.snapshotBody, { color: palette.text }]}>
                {topIndustryCapital?.capitalAction ?? '继续等待产业方向深页同步。'}
              </Text>
            </View>
          </Pressable>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>04 主线与接管</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {topThemeStage ? topThemeStage.sector : compositeCompare?.readiness.label ?? '继续影子'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              {topThemeStage
                ? `${topThemeStage.stageLabel} / ${topThemeStage.participationLabel}`
                : `接管 ${compositeCompare?.readiness.label ?? '继续影子'}`}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {topThemeStage?.action ?? compositeCompare?.readiness.recommendedAction ?? '继续观察主线与综合榜。'}
            </Text>
          </View>

          <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.snapshotStep, { color: palette.tint }]}>05 学习状态</Text>
            <Text style={[styles.snapshotTitle, { color: palette.text }]}>
              {data?.dailyAdvance.todayCompleted ? '今日学习已完成' : '今日学习待执行'}
            </Text>
            <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
              准确率 {formatPercent(data?.learning.decisionAccuracy ?? 0, 0)} / 在线更新 {data?.learning.onlineUpdates ?? '--'}
            </Text>
            <Text style={[styles.snapshotBody, { color: palette.text }]}>
              {data?.dailyAdvance.summary ?? '继续把学习链补齐，让后面的判断更硬。'}
            </Text>
          </View>
        </View>
      </SurfaceCard>

      <SectionHeading title="今日脑子结论" subtitle="先给一句判断，再把今天最该做的事列出来。" />
      <SurfaceCard style={styles.cardGap}>
        {brainHeadline.tasks.map((item) => (
          <View key={item} style={styles.rowWithDot}>
            <View style={[styles.dot, { backgroundColor: palette.tint }]} />
            <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}

        <View style={styles.metricGrid}>
          <MetricCard label="在线更新" value={`${data?.learning.onlineUpdates ?? '--'}`} tone="success" />
          <MetricCard label="因子调整" value={`${data?.learning.factorAdjustments ?? '--'}`} tone="info" />
          <MetricCard label="新因子" value={`${data?.learning.newFactorsDeployed ?? '--'}`} tone="warning" />
          <MetricCard label="运行实验" value={`${data?.learning.experimentsRunning ?? '--'}`} tone="neutral" />
        </View>
      </SurfaceCard>

      <SectionHeading
        title="综合榜接管判断"
        subtitle="这块不是展示比分，而是明确告诉你综合榜为什么还在影子期、什么时候能往主排序上走。"
      />
      <SurfaceCard style={styles.cardGap}>
        <View style={styles.headlineRow}>
          <View style={styles.headlineMain}>
            <Text style={[styles.headlineTitle, { color: palette.text }]}>
              {compositeCompare?.readiness.label ?? '继续影子'}
            </Text>
            <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
              置信 {compositeCompare?.readiness.confidenceScore.toFixed(0) ?? '--'} / 最近观察{' '}
              {compositeCompare?.composite.sampleDays ?? 0} 天
            </Text>
          </View>
          <StatusPill
            label={compositeCompare?.readiness.status ?? 'shadow'}
            tone={getReadinessTone(compositeCompare?.readiness.status ?? 'shadow')}
          />
        </View>

        <Text style={[styles.bodyText, { color: palette.text }]}>
          {buildTakeoverSummary(compositeCompare, topCompositePick)}
        </Text>

        <View style={styles.metricGrid}>
          <MetricCard
            label="综合榜 T+1"
            value={
              compositeCompare?.composite.avgT1ReturnPct !== null &&
              compositeCompare?.composite.avgT1ReturnPct !== undefined
                ? `${compositeCompare.composite.avgT1ReturnPct.toFixed(2)}%`
                : '--'
            }
            tone="info"
          />
          <MetricCard
            label="原推荐 T+1"
            value={
              compositeCompare?.baseline.avgT1ReturnPct !== null &&
              compositeCompare?.baseline.avgT1ReturnPct !== undefined
                ? `${compositeCompare.baseline.avgT1ReturnPct.toFixed(2)}%`
                : '--'
            }
            tone="neutral"
          />
          <MetricCard
            label="综合头部票"
            value={topCompositePick ? topCompositePick.code : '--'}
            tone="success"
          />
          <MetricCard
            label="建议首仓"
            value={topCompositePick ? `${topCompositePick.firstPositionPct}%` : '--'}
            tone="warning"
          />
        </View>

        {topCompositePick ? (
          <View style={styles.heroPills}>
            <StatusPill
              label={topCompositePick.sourceLabel}
              tone={getCompositeSourceTone(topCompositePick.sourceCategory)}
            />
            <StatusPill label={topCompositePick.horizonLabel} tone="neutral" />
            {topCompositePick.themeSector ? (
              <StatusPill label={topCompositePick.themeSector} tone="info" />
            ) : null}
          </View>
        ) : null}

        <View style={styles.listGroup}>
          <Text style={[styles.subTitle, { color: palette.text }]}>为什么还没切</Text>
          {(compositeCompare?.readiness.conditions ?? ['正在等待更多影子样本。']).map((item) => (
            <View key={item} style={styles.rowWithDot}>
              <View style={[styles.dot, { backgroundColor: palette.warning }]} />
              <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
            </View>
          ))}
        </View>

        <View style={styles.listGroup}>
          <Text style={[styles.subTitle, { color: palette.text }]}>下一步</Text>
          <View style={styles.rowWithDot}>
            <View style={[styles.dot, { backgroundColor: palette.success }]} />
            <Text style={[styles.bodyText, { color: palette.text }]}>
              {compositeCompare?.readiness.recommendedAction ?? '继续观察推荐页的影子对比。'}
            </Text>
          </View>
          {topCompositePick ? (
            <View style={styles.rowWithDot}>
              <View style={[styles.dot, { backgroundColor: palette.tint }]} />
              <Text style={[styles.bodyText, { color: palette.text }]}>
                当前先复核 {topCompositePick.code} {topCompositePick.name}，看它能不能继续证明综合榜的判断。
              </Text>
            </View>
          ) : null}
        </View>

        <View style={styles.actionRow}>
          <Pressable
            onPress={() => {
              router.push('/(tabs)/signals');
            }}
            style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
            <Text style={styles.secondaryActionText}>看接管对比</Text>
          </Pressable>
          {topCompositePick ? (
            <Pressable
              onPress={() => {
                if (canOpenCompositeDetail(topCompositePick)) {
                  router.push({ pathname: '/signal/[id]', params: { id: topCompositePick.signalId } });
                  return;
                }
                void handleDiagnose(topCompositePick.code);
              }}
              style={[styles.ghostAction, { borderColor: palette.border }]}>
              <Text style={[styles.ghostActionText, { color: palette.text }]}>
                {canOpenCompositeDetail(topCompositePick) ? '看综合头部票' : '直接诊断头部票'}
              </Text>
            </Pressable>
          ) : null}
        </View>
      </SurfaceCard>

      <SectionHeading
        title="综合候选分层"
        subtitle="把主线孵化、中期波段和普通策略候选拆开看，脑子先告诉你今天该先盯哪一类。"
      />
      <SurfaceCard style={styles.cardGap}>
        {topThemeSeedPick ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>
                  {topThemeSeedPick.code} {topThemeSeedPick.name}
                </Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {topThemeSeedPick.sourceLabel} / {topThemeSeedPick.horizonLabel} / {topThemeSeedPick.themeSector ?? '主线观察'}
                </Text>
              </View>
              <StatusPill label="先看主线" tone="success" />
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{topThemeSeedPick.action}</Text>
          </View>
        ) : null}

        {topSwingCompositePick ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>
                  {topSwingCompositePick.code} {topSwingCompositePick.name}
                </Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {topSwingCompositePick.sourceLabel} / {topSwingCompositePick.horizonLabel} / 综合分 {topSwingCompositePick.compositeScore.toFixed(1)}
                </Text>
              </View>
              <StatusPill label="中期候选" tone="warning" />
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{topSwingCompositePick.action}</Text>
          </View>
        ) : null}

        {topStrategyCompositePick ? (
          <View style={[styles.themeCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>
                  {topStrategyCompositePick.code} {topStrategyCompositePick.name}
                </Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {topStrategyCompositePick.sourceLabel} / {topStrategyCompositePick.horizonLabel} / 事件{topStrategyCompositePick.eventBias}
                </Text>
              </View>
              <StatusPill label="策略重排" tone={getCompositeSourceTone(topStrategyCompositePick.sourceCategory)} />
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{topStrategyCompositePick.action}</Text>
          </View>
        ) : null}

        {!topThemeSeedPick && !topSwingCompositePick && !topStrategyCompositePick ? (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            当前还没有足够清晰的综合候选分层，先看主线资金迁移和手动诊股。
          </Text>
        ) : null}
      </SurfaceCard>

      <SectionHeading
        title="政策方向雷达"
        subtitle="先判断政策、需求、地缘政治和产业链线索落在哪些方向，再决定今天看哪条主线。"
      />
      <SurfaceCard style={styles.cardGap}>
        {policyWatch.length > 0 ? (
          policyWatch.map((item) => (
            <View
              key={item.id}
              style={[
                styles.themeCard,
                {
                  backgroundColor: palette.surfaceMuted,
                  borderColor: palette.border,
                },
              ]}>
              <View style={styles.headlineRow}>
                <View style={styles.headlineMain}>
                  <Text style={[styles.headlineTitle, { color: palette.text }]}>{item.direction}</Text>
                  <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                    {item.policyBucket} / {item.focusSector} / {item.industryPhase} / {item.participationLabel}
                  </Text>
                </View>
                <StatusPill label={item.stageLabel} tone={getPolicyWatchTone(item)} />
              </View>

              <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
              <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.action}</Text>
              <Text style={[styles.bodyText, { color: palette.text }]}>{item.phaseSummary}</Text>

              <View style={styles.metricGrid}>
                <MetricCard label="方向" value={item.directionScore.toFixed(1)} tone="info" />
                <MetricCard label="政策" value={item.policyScore.toFixed(1)} tone="neutral" />
                <MetricCard label="趋势" value={item.trendScore.toFixed(1)} tone="success" />
                <MetricCard label="关注度" value={item.attentionScore.toFixed(1)} tone="warning" />
                <MetricCard label="资金偏好" value={item.capitalPreferenceScore.toFixed(1)} tone="info" />
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>驱动因子</Text>
                {item.drivers.map((driver) => (
                  <View key={`${item.id}-${driver}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{driver}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>产业链位置</Text>
                {item.upstream.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>上游：{item.upstream.join('、')}</Text>
                  </View>
                ) : null}
                {item.midstream.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>中游：{item.midstream.join('、')}</Text>
                  </View>
                ) : null}
                {item.downstream.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>下游：{item.downstream.join('、')}</Text>
                  </View>
                ) : null}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>供需与兑现链</Text>
                {item.demandDrivers.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>需求侧：{item.demandDrivers.join('、')}</Text>
                  </View>
                ) : null}
                {item.supplyDrivers.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>供给侧：{item.supplyDrivers.join('、')}</Text>
                  </View>
                ) : null}
                {item.milestones.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>兑现链：{item.milestones.join(' -> ')}</Text>
                  </View>
                ) : null}
                {item.transmissionPaths.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.danger }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>
                      传导链：{item.transmissionPaths.join(' / ')}
                    </Text>
                  </View>
                ) : null}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>风险与动作</Text>
                <View style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item.riskNote}</Text>
                </View>
              </View>

              {(item.linkedSignalId || item.linkedCode) ? (
                <View style={styles.actionRow}>
                  {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-') ? (
                    <Pressable
                      onPress={() => {
                        router.push({ pathname: '/signal/[id]', params: { id: item.linkedSignalId ?? '' } });
                      }}
                      style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                      <Text style={styles.secondaryActionText}>看焦点票</Text>
                    </Pressable>
                  ) : null}
                  {item.linkedCode ? (
                    <Pressable
                      onPress={() => {
                        void handleDiagnose(item.linkedCode ?? undefined);
                      }}
                      style={[
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? styles.ghostAction
                          : styles.secondaryAction,
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? { borderColor: palette.border }
                          : { backgroundColor: palette.tint },
                      ]}>
                      <Text
                        style={
                          item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                            ? [styles.ghostActionText, { color: palette.text }]
                            : styles.secondaryActionText
                        }>
                        {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? '直接诊股'
                          : '诊断方向焦点'}
                      </Text>
                    </Pressable>
                  ) : null}
                  <Pressable
                    onPress={() => {
                      openPolicyWatchDetail(item);
                    }}
                    style={[
                      item.linkedSignalId || item.linkedCode ? styles.ghostAction : styles.secondaryAction,
                      item.linkedSignalId || item.linkedCode
                        ? { borderColor: palette.border }
                        : { backgroundColor: palette.tint },
                    ]}>
                    <Text
                      style={
                        item.linkedSignalId || item.linkedCode
                          ? [styles.ghostActionText, { color: palette.text }]
                          : styles.secondaryActionText
                      }>
                      看方向深页
                    </Text>
                  </Pressable>
                </View>
              ) : (
                <View style={styles.actionRow}>
                  <Pressable
                    onPress={() => {
                      openPolicyWatchDetail(item);
                    }}
                    style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                    <Text style={styles.secondaryActionText}>看方向深页</Text>
                  </Pressable>
                </View>
              )}
            </View>
          ))
        ) : (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            当前还没有足够集中的政策方向，先看主线阶段引擎和综合候选分层。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading
        title="产业资本方向"
        subtitle="把政策、供需、产业链和资金偏好翻译成事业动作与资本动作。"
      />
      <SurfaceCard style={styles.cardGap}>
        {industryCapital.length > 0 ? (
          industryCapital.map((item) => (
            <View
              key={item.id}
              style={[
                styles.themeCard,
                {
                  backgroundColor: palette.surfaceMuted,
                  borderColor: palette.border,
                },
              ]}>
              <View style={styles.headlineRow}>
                <View style={styles.headlineMain}>
                  <Text style={[styles.headlineTitle, { color: palette.text }]}>{item.direction}</Text>
                  <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                    {item.policyBucket} / {item.focusSector} / {item.strategicLabel} / {item.participationLabel}
                  </Text>
                </View>
                <StatusPill label={item.capitalHorizon} tone={getIndustryCapitalTone(item)} />
              </View>

              <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
              <Text style={[styles.bodyText, { color: palette.text }]}>{item.businessAction}</Text>
              <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.capitalAction}</Text>
              <Text style={[styles.bodyText, { color: palette.text }]}>{item.researchSummary}</Text>
              <Text style={[styles.bodyText, { color: palette.tint }]}>{item.researchNextAction}</Text>
              <Text style={[styles.bodyText, { color: palette.text }]}>
                最新催化：{item.latestCatalystTitle} / {item.currentTimelineStage}
              </Text>
              <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.latestCatalystSummary}</Text>
              {item.officialSourceEntries[0] ? (
                <Text style={[styles.bodyText, { color: palette.subtext }]}>
                  官方原文：{item.officialSourceEntries[0].issuer}
                  {item.officialSourceEntries[0].publishedAt ? ` / ${item.officialSourceEntries[0].publishedAt}` : ''}
                </Text>
              ) : null}
              {item.companyWatchlist[0] ? (
                <Text style={[styles.bodyText, { color: palette.text }]}>
                  重点跟踪：{item.companyWatchlist[0].code ? `${item.companyWatchlist[0].code} ` : ''}
                  {item.companyWatchlist[0].name} / {item.companyWatchlist[0].priorityLabel} /{' '}
                  {item.companyWatchlist[0].marketAlignment} / {item.companyWatchlist[0].timelineAlignment}
                </Text>
              ) : null}
              {item.companyWatchlist[0]?.recentResearchNote ? (
                <Text style={[styles.bodyText, { color: palette.tint }]}>
                  最近调研：{item.companyWatchlist[0].recentResearchNote}
                </Text>
              ) : null}

              <View style={styles.metricGrid}>
                <MetricCard label="优先级" value={item.priorityScore.toFixed(1)} tone="info" />
                <MetricCard label="战略" value={item.strategicScore.toFixed(1)} tone="info" />
                <MetricCard label="政策" value={item.policyScore.toFixed(1)} tone="neutral" />
                <MetricCard label="需求" value={item.demandScore.toFixed(1)} tone="success" />
                <MetricCard label="供给" value={item.supplyScore.toFixed(1)} tone="warning" />
                <MetricCard label="资金偏好" value={item.capitalPreferenceScore.toFixed(1)} tone="info" />
              </View>

              <View style={styles.heroPills}>
                <StatusPill label={`事业 ${item.businessHorizon}`} tone="neutral" />
                <StatusPill label={`资本 ${item.capitalHorizon}`} tone="info" />
                <StatusPill label={item.industryPhase} tone="success" />
                <StatusPill label={`阶段 ${item.currentTimelineStage}`} tone="neutral" />
                <StatusPill label={item.officialFreshnessLabel} tone="warning" />
                <StatusPill label={item.researchSignalLabel} tone={getIndustryResearchTone(item.researchSignalLabel)} />
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>机会落点</Text>
                {item.opportunities.map((opportunity) => (
                  <View key={`${item.id}-${opportunity}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{opportunity}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>官方观察点</Text>
                {item.officialDocuments.map((doc) => (
                  <View key={`${item.id}-${doc}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>原文线索：{doc}</Text>
                  </View>
                ))}
                {item.officialSources.length > 0 ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>
                      官方来源：{item.officialSources.join('、')}
                    </Text>
                  </View>
                ) : null}
                {item.officialWatchpoints.map((watchpoint) => (
                  <View key={`${item.id}-${watchpoint}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{watchpoint}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>兑现时间轴</Text>
                {item.timelineCheckpoints.map((checkpoint) => (
                  <View key={`${item.id}-${checkpoint}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{checkpoint}</Text>
                  </View>
                ))}
              </View>

              {item.timelineEvents.length > 0 ? (
                <View style={styles.listGroup}>
                  <Text style={[styles.subTitle, { color: palette.text }]}>方向时间轴</Text>
                  {item.timelineEvents.slice(0, 3).map((event) => (
                    <View key={event.id} style={styles.rowWithDot}>
                      <View
                        style={[
                          styles.dot,
                          {
                            backgroundColor:
                              event.emphasis === 'success'
                                ? palette.success
                                : event.emphasis === 'warning'
                                  ? palette.warning
                                  : palette.tint,
                          },
                        ]}
                      />
                      <Text style={[styles.bodyText, { color: palette.text }]}>
                        {event.title} / {event.stage}
                        {event.timestamp ? ` / ${formatTimestamp(event.timestamp)}` : ''}
                      </Text>
                    </View>
                  ))}
                </View>
              ) : null}

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>事业调研清单</Text>
                {item.businessChecklist.map((check) => (
                  <View key={`${item.id}-${check}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{check}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>资本验证清单</Text>
                {item.capitalChecklist.map((check) => (
                  <View key={`${item.id}-${check}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.danger }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{check}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>合作对象与方式</Text>
                {item.cooperationTargets.map((target) => (
                  <View key={`${item.id}-${target}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>对象：{target}</Text>
                  </View>
                ))}
                {item.cooperationModes.map((mode) => (
                  <View key={`${item.id}-${mode}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.danger }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>方式：{mode}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>风险与约束</Text>
                <View style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item.riskNote}</Text>
                </View>
              </View>

              {(item.linkedSignalId || item.linkedCode) ? (
                <View style={styles.actionRow}>
                  {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-') ? (
                    <Pressable
                      onPress={() => {
                        router.push({ pathname: '/signal/[id]', params: { id: item.linkedSignalId ?? '' } });
                      }}
                      style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                      <Text style={styles.secondaryActionText}>看交易焦点</Text>
                    </Pressable>
                  ) : null}
                  {item.linkedCode ? (
                    <Pressable
                      onPress={() => {
                        void handleDiagnose(item.linkedCode ?? undefined);
                      }}
                      style={[
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? styles.ghostAction
                          : styles.secondaryAction,
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? { borderColor: palette.border }
                          : { backgroundColor: palette.tint },
                      ]}>
                      <Text
                        style={
                          item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                            ? [styles.ghostActionText, { color: palette.text }]
                            : styles.secondaryActionText
                        }>
                        {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? '直接诊断'
                          : '诊断焦点票'}
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </View>
          ))
        ) : (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            当前还没有足够清晰的产业资本方向，先看政策方向雷达和主线阶段引擎。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading
        title="主线发现与阶段引擎"
        subtitle="先看大方向，再决定今天该打主线种子、中期波段，还是只做观察。"
      />
      <SurfaceCard style={styles.cardGap}>
        {themeStages.length > 0 ? (
          themeStages.map((item) => (
            <View
              key={item.id}
              style={[
                styles.themeCard,
                {
                  backgroundColor: palette.surfaceMuted,
                  borderColor: palette.border,
                },
              ]}>
              <View style={styles.headlineRow}>
                <View style={styles.headlineMain}>
                  <Text style={[styles.headlineTitle, { color: palette.text }]}>{item.sector}</Text>
                  <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                    {item.themeType} / {item.stageLabel} / {item.participationLabel}
                  </Text>
                </View>
                <StatusPill label={item.intensity} tone={getThemeStageTone(item)} />
              </View>

              <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
              <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.action}</Text>

              <View style={styles.metricGrid}>
                <MetricCard label="方向" value={item.directionScore.toFixed(1)} tone="info" />
                <MetricCard label="政策/事件" value={item.policyEventScore.toFixed(1)} tone="neutral" />
                <MetricCard label="趋势" value={item.trendScore.toFixed(1)} tone="success" />
                <MetricCard label="关注度" value={item.attentionScore.toFixed(1)} tone="warning" />
                <MetricCard label="资金偏好" value={item.capitalPreferenceScore.toFixed(1)} tone="info" />
                <MetricCard label="阶段" value={item.stageScore.toFixed(1)} tone={getThemeStageTone(item)} />
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>驱动因子</Text>
                {item.drivers.map((driver) => (
                  <View key={`${item.id}-${driver}`} style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>{driver}</Text>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>风险与动作</Text>
                <View style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item.riskNote}</Text>
                </View>
              </View>

              {(item.linkedSignalId || item.linkedCode) ? (
                <View style={styles.actionRow}>
                  {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-') ? (
                    <Pressable
                      onPress={() => {
                        router.push({ pathname: '/signal/[id]', params: { id: item.linkedSignalId ?? '' } });
                      }}
                      style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                      <Text style={styles.secondaryActionText}>看焦点票</Text>
                    </Pressable>
                  ) : null}
                  {item.linkedCode ? (
                    <Pressable
                      onPress={() => {
                        void handleDiagnose(item.linkedCode ?? undefined);
                      }}
                      style={[
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? styles.ghostAction
                          : styles.secondaryAction,
                        item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? { borderColor: palette.border }
                          : { backgroundColor: palette.tint },
                      ]}>
                      <Text
                        style={
                          item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                            ? [styles.ghostActionText, { color: palette.text }]
                            : styles.secondaryActionText
                        }>
                        {item.linkedSignalId && !item.linkedSignalId.startsWith('theme-seed-')
                          ? '直接诊股'
                          : '诊断主线焦点'}
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </View>
          ))
        ) : (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            主线阶段引擎还没形成清晰结果，先看主题雷达和综合候选。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading
        title="主线资金迁移"
        subtitle="把事件、板块和强势跟随票放在一起，看今天的大钱正在往哪里走。"
      />
      <SurfaceCard style={styles.cardGap}>
        {(data?.themeRadar ?? []).length > 0 ? (
          (data?.themeRadar ?? []).map((item) => (
            <View
              key={item.id}
              style={[
                styles.themeCard,
                {
                  backgroundColor: palette.surfaceMuted,
                  borderColor: palette.border,
                },
              ]}>
              <View style={styles.headlineRow}>
                <View style={styles.headlineMain}>
                  <Text style={[styles.headlineTitle, { color: palette.text }]}>
                    {item.sector}
                  </Text>
                  <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                    {item.themeType} / {formatPercent(item.changePct / 100)} / 热度 {item.score.toFixed(1)} /{' '}
                    {formatTimestamp(item.timestamp)}
                  </Text>
                </View>
                <StatusPill label={item.intensity} tone={getThemeTone(item.intensity)} />
              </View>

              <Text style={[styles.bodyText, { color: palette.text }]}>{item.narrative}</Text>
              <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.action}</Text>

              {item.messageHint ? (
                <View style={[styles.insightBox, { backgroundColor: palette.surface }]}>
                  <Text style={[styles.insightTitle, { color: palette.text }]}>微信镜像摘要</Text>
                  <Text style={[styles.insightText, { color: palette.subtext }]}>{item.messageHint}</Text>
                </View>
              ) : null}

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>跟随票</Text>
                {item.followers.map((follower) => (
                  <View key={`${item.id}-${follower.code}`} style={styles.themeFollowerRow}>
                    <View style={styles.themeFollowerMain}>
                      <Text style={[styles.themeFollowerCode, { color: palette.text }]}>
                        {follower.code} {follower.name}
                      </Text>
                      <Text style={[styles.themeFollowerMeta, { color: palette.subtext }]}>
                        {follower.label}
                      </Text>
                    </View>
                    <View style={styles.themeFollowerRight}>
                      <Text style={[styles.themeFollowerChange, { color: palette.text }]}>
                        {formatPercent(follower.changePct / 100)}
                      </Text>
                      <Text style={[styles.themeFollowerMeta, { color: palette.subtext }]}>
                        盈亏比 {follower.riskReward.toFixed(1)}
                      </Text>
                    </View>
                  </View>
                ))}
              </View>

              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>风险与动作</Text>
                <View style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item.riskNote}</Text>
                </View>
                {item.linkedCode ? (
                  <View style={styles.rowWithDot}>
                    <View style={[styles.dot, { backgroundColor: palette.success }]} />
                    <Text style={[styles.bodyText, { color: palette.text }]}>
                      当前已关联强势候选 {item.linkedCode} {item.linkedName ?? ''}{' '}
                      {item.linkedSetupLabel ? `(${item.linkedSetupLabel})` : ''}
                    </Text>
                  </View>
                ) : null}
              </View>

              {item.linkedSignalId || item.linkedCode || item.followers[0]?.code ? (
                <View style={styles.actionRow}>
                  {item.linkedSignalId ? (
                    <Pressable
                      onPress={() => {
                        router.push({ pathname: '/signal/[id]', params: { id: item.linkedSignalId ?? '' } });
                      }}
                      style={[styles.secondaryAction, { backgroundColor: palette.tint }]}>
                      <Text style={styles.secondaryActionText}>看主线强票</Text>
                    </Pressable>
                  ) : null}
                  {item.linkedCode || item.followers[0]?.code ? (
                    <Pressable
                      onPress={() => {
                        void handleDiagnose(item.linkedCode ?? item.followers[0]?.code);
                      }}
                      style={[
                        item.linkedSignalId ? styles.ghostAction : styles.secondaryAction,
                        item.linkedSignalId
                          ? { borderColor: palette.border }
                          : { backgroundColor: palette.tint },
                      ]}>
                      <Text
                        style={
                          item.linkedSignalId
                            ? [styles.ghostActionText, { color: palette.text }]
                            : styles.secondaryActionText
                        }>
                        {item.linkedSignalId ? '直接诊股' : '诊断主线跟随票'}
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </View>
          ))
        ) : (
          <Text style={[styles.bodyText, { color: palette.subtext }]}>
            今天还没有形成清晰主线，先看强势收益引擎和手动诊股。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading title="交互诊股" subtitle="输入代码、点候选票、现场出判断。这个区域就是现场演示的主轴。" />
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
                  <StatusPill label={item.strategy} tone="neutral" />
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
                  {formatTimestamp(diagnosis.asOf)}
                </Text>
              </View>
              <StatusPill
                label={diagnosis.actionable ? '可交易' : '观察单'}
                tone={getDiagnosisTone(diagnosis)}
              />
            </View>

            <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.insightTitle, { color: palette.text }]}>一句判断</Text>
              <Text style={[styles.insightText, { color: palette.subtext }]}>
                {diagnosis.advice || diagnosis.reportText || diagnosis.regimeSummary}
              </Text>
            </View>

            <View style={styles.metricGrid}>
              <MetricCard label="综合评分" value={`${Math.round(diagnosis.totalScore * 100)}`} tone="info" />
              <MetricCard label="环境分" value={`${Math.round(diagnosis.regimeScore * 100)}`} tone="success" />
              <MetricCard
                label="持仓状态"
                value={diagnosis.inPortfolio ? `${diagnosis.positionQuantity} 股` : '未持有'}
                tone={diagnosis.inPortfolio ? 'warning' : 'neutral'}
              />
              <MetricCard
                label="信号板"
                value={diagnosis.inSignalBoard ? '已在池中' : '未入推荐'}
                tone={diagnosis.inSignalBoard ? 'success' : 'neutral'}
              />
            </View>

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

            <View style={styles.scoreGrid}>
              {scoreEntries.map((item) => (
                <SurfaceCard key={item.key} style={styles.scoreCard}>
                  <Text style={[styles.scoreLabel, { color: palette.subtext }]}>{item.label}</Text>
                  <Text style={[styles.scoreValue, { color: palette.text }]}>{Math.round(item.value * 100)}</Text>
                  <Text style={[styles.scoreMeta, { color: palette.subtext }]}>
                    {item.details[0] ?? '暂无细节'}
                  </Text>
                </SurfaceCard>
              ))}
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.subTitle, { color: palette.text }]}>风险提示</Text>
              {(diagnosis.riskFlags.length > 0 ? diagnosis.riskFlags : ['当前没有额外风险旗标。']).map((item) => (
                <View key={item} style={styles.rowWithDot}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
                </View>
              ))}
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.subTitle, { color: palette.text }]}>下一步</Text>
              {diagnosis.nextActions.map((item) => (
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

      <SectionHeading title="今日学习推进" subtitle="把学习链讲成一条明确的任务，不再像系统日志。" />
      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.headlineTitle, { color: palette.text }]}>
          {data?.dailyAdvance.summary ?? '正在读取日日精进状态'}
        </Text>
        <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
          最近完成 {data?.dailyAdvance.lastCompletedAt ? formatTimestamp(data.dailyAdvance.lastCompletedAt) : '暂无'} /
          健康状态 {data?.dailyAdvance.healthStatus ?? '--'}
        </Text>

        <View style={styles.metricGrid}>
          <MetricCard label="入库信号" value={`${data?.dailyAdvance.ingestedSignals ?? '--'}`} tone="info" />
          <MetricCard label="完成验证" value={`${data?.dailyAdvance.verifiedSignals ?? '--'}`} tone="success" />
          <MetricCard label="回查决策" value={`${data?.dailyAdvance.reviewedDecisions ?? '--'}`} tone="warning" />
          <MetricCard
            label="状态"
            value={data?.dailyAdvance.inProgress ? '运行中' : data?.dailyAdvance.todayCompleted ? '已完成' : '待执行'}
            tone={data?.dailyAdvance.inProgress ? 'info' : data?.dailyAdvance.todayCompleted ? 'success' : 'warning'}
          />
        </View>

        {(data?.dailyAdvance.recommendations ?? []).slice(0, 3).map((item) => (
          <View key={item} style={styles.rowWithDot}>
            <View style={[styles.dot, { backgroundColor: palette.tint }]} />
            <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}

        {(data?.dailyAdvance.checks ?? []).slice(0, 3).map((item) => (
          <View key={`${item.name}-${item.detail}`} style={styles.checkRow}>
            <StatusPill label={item.name} tone={toneFromLevel(item.status)} />
            <Text style={[styles.bodyText, { color: palette.text }]}>{item.detail}</Text>
          </View>
        ))}

        <Pressable
          disabled={learningSubmitting || data?.dailyAdvance.inProgress}
          onPress={() => {
            void handleRunLearningAdvance();
          }}
          style={[
            styles.primaryButton,
            {
              backgroundColor:
                learningSubmitting || data?.dailyAdvance.inProgress ? palette.icon : palette.tint,
            },
          ]}>
          {learningSubmitting ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.primaryButtonText}>
              {data?.dailyAdvance.inProgress ? '日日精进运行中' : '立即推进今日学习'}
            </Text>
          )}
        </Pressable>
      </SurfaceCard>

      <SectionHeading title="系统建议" subtitle="只保留最该盯的建议和最热的策略，不把你拖回后台视角。" />
      <SurfaceCard style={styles.cardGap}>
        {(data?.ops.recommendations ?? []).slice(0, 3).map((item) => (
          <View key={`${item.level}-${item.title}`} style={styles.recommendationRow}>
            <StatusPill label={item.title} tone={toneFromLevel(item.level)} />
            <Text style={[styles.bodyText, { color: palette.text }]}>{item.message}</Text>
          </View>
        ))}

        {topStrategies.map((strategy) => (
          <View key={strategy.id} style={styles.strategyRow}>
            <View style={styles.strategyMain}>
              <Text style={[styles.strategyName, { color: palette.text }]}>{strategy.name}</Text>
              <Text style={[styles.strategyMeta, { color: palette.subtext }]}>
                {strategy.signalCount} 条 / 最近 {strategy.lastSignalTime ?? '暂无'}
              </Text>
            </View>
            <View style={styles.strategyRight}>
              <Text style={[styles.strategyValue, { color: palette.text }]}>
                {formatPercent(strategy.winRate / 100, 0)}
              </Text>
              <Text style={[styles.strategyMeta, { color: palette.subtext }]}>
                均收 {formatPercent(strategy.avgReturn / 100)}
              </Text>
            </View>
          </View>
        ))}
      </SurfaceCard>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
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
  cardGap: {
    gap: 14,
  },
  snapshotGrid: {
    gap: 12,
  },
  snapshotCard: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 8,
  },
  snapshotStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  snapshotTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  snapshotCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  snapshotBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
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
  scoreGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  scoreCard: {
    width: '48%',
    gap: 4,
  },
  scoreLabel: {
    fontSize: 12,
    fontWeight: '700',
  },
  scoreValue: {
    fontSize: 24,
    fontWeight: '800',
  },
  scoreMeta: {
    fontSize: 12,
    lineHeight: 18,
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
