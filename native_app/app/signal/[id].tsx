import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { KlineSnapshot } from '@/components/app/kline-snapshot';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { buildActionReceiptHref } from '@/lib/action-receipt';
import { formatCurrency, formatPercent, formatTimestamp } from '@/lib/format';
import { getKlineBars, getSignalDetail, openSignalPosition } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { SignalDetail } from '@/types/trading';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

function getEntryGapPct(signal: SignalDetail): number {
  if (signal.buyPrice <= 0) {
    return 0;
  }

  return (signal.price - signal.buyPrice) / signal.buyPrice;
}

function getStopBufferPct(signal: SignalDetail): number {
  if (signal.buyPrice <= 0) {
    return 0;
  }

  return (signal.buyPrice - signal.stopLoss) / signal.buyPrice;
}

function getUpsidePct(signal: SignalDetail): number {
  if (signal.buyPrice <= 0) {
    return 0;
  }

  return (signal.targetPrice - signal.buyPrice) / signal.buyPrice;
}

function buildSignalDecision(signal: SignalDetail): {
  verdict: string;
  tone: Tone;
  summary: string;
  executionHint: string;
  reasons: string[];
  warnings: string[];
} {
  const entryGapPct = getEntryGapPct(signal);
  const stopBufferPct = getStopBufferPct(signal);
  const upsidePct = getUpsidePct(signal);
  const reasons = [
    `${signal.strategy} 是当前主导策略，综合评分 ${signal.score.toFixed(3)}。`,
    `${signal.consensusCount} 个策略给出共识，环境适配度 ${(signal.regimeScore * 100).toFixed(0)}%。`,
    `预设盈亏比 ${signal.riskReward.toFixed(1)} : 1，上方空间 ${formatPercent(upsidePct)}。`,
  ];
  const warnings: string[] = [];

  if (entryGapPct > 0.03) {
    warnings.push(`当前价比计划入场高 ${formatPercent(entryGapPct)}，先别追。`);
  } else if (entryGapPct < -0.02) {
    warnings.push(`当前价比计划入场低 ${formatPercent(Math.abs(entryGapPct))}，可以等确认后分批。`);
  } else {
    warnings.push('当前价仍在计划入场区附近，执行节奏相对顺手。');
  }

  if (signal.regimeScore < 0.65) {
    warnings.push(`环境适配度只有 ${(signal.regimeScore * 100).toFixed(0)}%，别把它当满仓票。`);
  }

  if (stopBufferPct > 0) {
    warnings.push(`止损缓冲 ${formatPercent(stopBufferPct)}，跌破 ${signal.stopLoss.toFixed(2)} 就失效。`);
  }

  if (signal.score >= 0.92 && signal.regimeScore >= 0.72 && signal.riskReward >= 2 && entryGapPct <= 0.03) {
    return {
      verdict: '可以执行',
      tone: 'success',
      summary: '评分、环境和盈亏结构同时在线，适合按纪律开第一笔仓位。',
      executionHint:
        entryGapPct > 0.015
          ? '现价略高于计划入场位，优先等回落到买点附近再执行。'
          : '先用小到中等仓位进场，失效就严格执行止损。',
      reasons,
      warnings,
    };
  }

  if (signal.changePct >= 5 || entryGapPct > 0.05) {
    return {
      verdict: '不建议追高',
      tone: 'warning',
      summary: '票本身不差，但当前位置已经拥挤，最该避免的是情绪化追价。',
      executionHint: '先放进观察名单，等回到计划价附近或者去决策台复诊后再决定。',
      reasons,
      warnings,
    };
  }

  if (signal.score >= 0.84) {
    return {
      verdict: '优先观察',
      tone: 'info',
      summary: '信号质量够看，但还差最后一脚确认，适合继续盯而不是直接梭。',
      executionHint: '关注是否继续保持共识和环境适配，必要时先小仓试单。',
      reasons,
      warnings,
    };
  }

  return {
    verdict: '继续观察',
    tone: 'warning',
    summary: '这条信号目前更像备选，不值得抢在前面出手。',
    executionHint: '先把它留在列表里，等评分或环境改善再做下一步。',
    reasons: reasons.slice(0, 2),
    warnings,
  };
}

function getGuideTone(mode: string, eventBias: string): Tone {
  if (mode.includes('允许')) {
    return 'success';
  }
  if (eventBias === '偏空') {
    return 'warning';
  }
  if (mode.includes('轻仓')) {
    return 'info';
  }
  return 'neutral';
}

function getSignalCallout(signal: SignalDetail, decision: ReturnType<typeof buildSignalDecision>): {
  title: string;
  summary: string;
  tone: Tone;
} {
  const entryGapPct = getEntryGapPct(signal);

  if (decision.verdict === '可以执行') {
    return {
      title: '可以按纪律试第一笔',
      summary: '评分、环境和盈亏结构同时过关，但执行仍然必须服从仓位和事件约束。',
      tone: 'success',
    };
  }

  if (decision.verdict === '不建议追高' || entryGapPct > 0.03) {
    return {
      title: '位置偏热，先别追',
      summary: '票本身未必差，但执行层最容易在这个位置出问题，先等回到纪律区再动。',
      tone: 'warning',
    };
  }

  if (decision.verdict === '优先观察') {
    return {
      title: '值得盯，但还差确认',
      summary: '方向和信号质量已经够看，接下来关键看环境、共识和位置是否继续配合。',
      tone: 'info',
    };
  }

  return {
    title: '先放观察，不抢动作',
    summary: '当前更适合把它当备选，不要跳过上层判断直接执行。',
    tone: 'warning',
  };
}

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const [quantityDraft, setQuantityDraft] = useState('100');
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    async () => {
      if (!id) {
        throw new Error('缺少信号 ID');
      }

      const signal = await getSignalDetail(id, token ?? undefined);
      const klines = await getKlineBars(signal.code, 60, token ?? undefined);
      return { signal, klines };
    },
    [id, token, apiBaseUrl]
  );

  const signal = data?.signal;
  const klines = data?.klines ?? [];
  const decision = signal ? buildSignalDecision(signal) : null;
  const signalCallout = signal && decision ? getSignalCallout(signal, decision) : null;
  const entryGuide = signal?.entryGuide ?? null;
  const suggestedQuantity = entryGuide?.suggestedQuantity ?? 0;
  const topFactors = signal
    ? Object.entries(signal.factorScores)
        .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))
        .slice(0, 6)
    : [];
  const maxFactorValue = Math.max(...topFactors.map(([, value]) => Math.abs(value)), 0.01);
  const intendedQuantity = Number.parseInt(quantityDraft, 10);
  const estimatedCost =
    signal && Number.isInteger(intendedQuantity) && intendedQuantity > 0
      ? signal.buyPrice * intendedQuantity
      : 0;
  const quantityPresets = [100, 200, 500];
  const quantityOptions = Array.from(
    new Set([entryGuide?.suggestedQuantity ?? 0, ...quantityPresets].filter((value) => value > 0))
  ).slice(0, 4);
  const entryGapPct = signal ? getEntryGapPct(signal) : null;
  const stopBufferPct = signal ? getStopBufferPct(signal) : null;
  const upsidePct = signal ? getUpsidePct(signal) : null;
  const estimatedPositionPct =
    entryGuide && entryGuide.totalAssets > 0 && estimatedCost > 0
      ? (estimatedCost / entryGuide.totalAssets) * 100
      : 0;
  const projectedThemeExposurePct =
    entryGuide?.sectorBucket && estimatedPositionPct > 0
      ? entryGuide.currentThemeExposurePct + estimatedPositionPct
      : entryGuide?.currentThemeExposurePct ?? 0;
  const executionSoftWarnings: string[] = [];
  const executionHardWarnings: string[] = [];

  if (entryGuide && estimatedCost > 0) {
    if (entryGuide.deployableCash > 0 && estimatedCost > entryGuide.deployableCash) {
      executionHardWarnings.push(
        `这笔预计占用 ${formatCurrency(estimatedCost)}，已经高于当前可再部署资金 ${formatCurrency(entryGuide.deployableCash)}。`
      );
    }
    if (
      entryGuide.maxSinglePositionPct > 0 &&
      estimatedPositionPct > entryGuide.maxSinglePositionPct
    ) {
      executionHardWarnings.push(
        `按当前数量计算，单票会占总资产 ${estimatedPositionPct.toFixed(1)}%，高于单票上限 ${entryGuide.maxSinglePositionPct}%。`
      );
    }
    if (
      entryGuide.sectorBucket &&
      entryGuide.maxThemeExposurePct > 0 &&
      projectedThemeExposurePct > entryGuide.maxThemeExposurePct
    ) {
      executionHardWarnings.push(
        `${entryGuide.sectorBucket} 方向执行后会到 ${projectedThemeExposurePct.toFixed(1)}%，高于主题上限 ${entryGuide.maxThemeExposurePct}%。`
      );
    }
    if (
      entryGuide.recommendedFirstPositionPct > 0 &&
      estimatedPositionPct > entryGuide.recommendedFirstPositionPct
    ) {
      executionSoftWarnings.push(
        `这笔会占总资产 ${estimatedPositionPct.toFixed(1)}%，高于建议首仓 ${entryGuide.recommendedFirstPositionPct}%。`
      );
    }
    if (entryGuide.eventBias === '偏空' && estimatedPositionPct > entryGuide.recommendedFirstPositionPct) {
      executionSoftWarnings.push('当前事件偏空，超出建议首仓时更容易把试错单变成情绪单。');
    }
    if (entryGuide.mode === '先观察' || entryGuide.mode === '优先观察') {
      executionSoftWarnings.push('当前更适合观察，不适合把这条票当成主动进攻单。');
    }
  }
  const isDisciplineBlocked = executionHardWarnings.length > 0;
  const executionStatusLabel =
    estimatedCost <= 0
      ? '等待输入数量'
      : isDisciplineBlocked
        ? '超出纪律'
        : executionSoftWarnings.length > 0
          ? '需要收敛'
          : '仍在纪律内';
  const executionStatusTone: Tone =
    estimatedCost <= 0 ? 'neutral' : isDisciplineBlocked ? 'danger' : executionSoftWarnings.length > 0 ? 'warning' : 'success';

  useEffect(() => {
    setQuantityDraft('100');
    setActionError(null);
  }, [id]);

  useEffect(() => {
    if (!entryGuide) {
      return;
    }
    if (suggestedQuantity > 0) {
      setQuantityDraft(String(suggestedQuantity));
      return;
    }
    setQuantityDraft('100');
  }, [entryGuide, suggestedQuantity]);

  async function handleOpenPosition() {
    if (!signal || !id) {
      return;
    }

    if (!Number.isInteger(intendedQuantity) || intendedQuantity <= 0) {
      setActionError('请输入有效的买入数量。');
      return;
    }
    if (isDisciplineBlocked) {
      setActionError(executionHardWarnings[0] ?? '当前数量超出纪律限制，请先收缩仓位。');
      return;
    }

    setIsSubmitting(true);
    setActionError(null);

    try {
      const result = await openSignalPosition(
        id,
        {
          quantity: intendedQuantity,
          stopLoss: signal.stopLoss,
          takeProfit: signal.targetPrice,
        },
        token ?? undefined
      );
      router.replace(
        buildActionReceiptHref(result, {
          source: 'signal',
          signalId: id,
          positionCode: result.position?.code ?? result.code,
        })
      );
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : '开仓失败');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回推荐列表</Text>
      </Pressable>
      <Pressable
        onPress={() => {
          router.push({
            pathname: '/feedback',
            params: {
              title: signal ? `${signal.code} 信号体验反馈` : '信号页体验反馈',
              message: signal
                ? `我在信号页查看 ${signal.code} ${signal.name} 时，建议优化：`
                : '我在信号页使用时，建议优化：',
              category: 'strategy',
              sourceType: 'signal',
              sourceId: id ?? '',
              sourceRoute: id ? `/signal/${id}` : '/signal',
            },
          });
        }}
        style={styles.feedbackButton}>
        <Text style={[styles.feedbackButtonText, { color: palette.tint }]}>提意见</Text>
      </Pressable>

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>RECOMMENDATION DETAIL</Text>
        <Text style={styles.heroTitle}>
          {signal?.code ?? '--'} {signal?.name ?? ''}
        </Text>
        <Text style={styles.heroCopy}>
          {decision?.summary ?? '先把这条推荐拆成结论、风险和动作，再决定要不要下手。'}
        </Text>
        <View style={styles.heroPills}>
          <StatusPill label={decision?.verdict ?? '等待数据'} tone={decision?.tone ?? 'neutral'} />
          <StatusPill label={signal?.strategy ?? '暂无策略'} tone="neutral" />
          {entryGuide ? (
            <StatusPill
              label={entryGuide.mode}
              tone={getGuideTone(entryGuide.mode, entryGuide.eventBias)}
            />
          ) : null}
          <StatusPill
            label={signal ? `适配 ${(signal.regimeScore * 100).toFixed(0)}%` : '环境待定'}
            tone={signal && signal.regimeScore >= 0.7 ? 'success' : 'warning'}
          />
          <StatusPill
            label={signal ? `现价 ${signal.price.toFixed(2)}` : '现价 --'}
            tone="info"
          />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取推荐详情" />

      {signal && decision ? (
        <>
          <SectionHeading
            title="一页执行摘要"
            subtitle="先把结论、纪律、参数和下一动作压成一页，再往下看详细证据。"
          />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.summaryHeader}>
              <View style={styles.summaryCopy}>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>{signalCallout?.title}</Text>
                <Text style={[styles.summaryText, { color: palette.subtext }]}>
                  {signalCallout?.summary}
                </Text>
              </View>
              <StatusPill label={decision.verdict} tone={signalCallout?.tone ?? decision.tone} />
            </View>

            <View style={styles.snapshotGrid}>
              <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.snapshotStep, { color: palette.tint }]}>01 当前结论</Text>
                <Text style={[styles.snapshotTitle, { color: palette.text }]}>{decision.verdict}</Text>
                <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                  评分 {signal.score.toFixed(3)} / 环境 {(signal.regimeScore * 100).toFixed(0)}% / 盈亏比 {signal.riskReward.toFixed(1)}
                </Text>
                <Text style={[styles.snapshotBody, { color: palette.text }]}>{decision.summary}</Text>
              </View>

              <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.snapshotStep, { color: palette.tint }]}>02 仓位纪律</Text>
                <Text style={[styles.snapshotTitle, { color: palette.text }]}>
                  {entryGuide?.mode ?? '等待纪律数据'}
                </Text>
                <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                  {entryGuide
                    ? `事件 ${entryGuide.eventBias} / 首仓 ${entryGuide.recommendedFirstPositionPct}% / 单票 ${entryGuide.maxSinglePositionPct}%`
                    : '先看事件面、首仓建议和组合上限。'}
                </Text>
                <Text style={[styles.snapshotBody, { color: palette.text }]}>
                  {entryGuide?.summary ?? '纪律层会决定这条推荐能不能动、该怎么动。'}
                </Text>
              </View>

              <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.snapshotStep, { color: palette.tint }]}>03 风险界线</Text>
                <Text style={[styles.snapshotTitle, { color: palette.text }]}>
                  止损 {signal.stopLoss.toFixed(2)} / 目标 {signal.targetPrice.toFixed(2)}
                </Text>
                <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                  {entryGapPct === null ? '位置待定' : `现价偏离 ${formatPercent(Math.abs(entryGapPct))}`} / 止损缓冲 {stopBufferPct === null ? '--' : formatPercent(stopBufferPct)}
                </Text>
                <Text style={[styles.snapshotBody, { color: palette.text }]}>
                  {decision.warnings[0] ?? '先确认位置还在纪律区，再谈执行。'}
                </Text>
              </View>

              <View style={[styles.snapshotCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.snapshotStep, { color: palette.tint }]}>04 下一动作</Text>
                <Text style={[styles.snapshotTitle, { color: palette.text }]}>
                  {isDisciplineBlocked ? '先收缩数量' : '按计划推进'}
                </Text>
                <Text style={[styles.snapshotCopy, { color: palette.subtext }]}>
                  {estimatedCost > 0 ? `预计占用 ${formatCurrency(estimatedCost)}` : '先输入数量再校验纪律'}
                </Text>
                <Text style={[styles.snapshotBody, { color: palette.text }]}>
                  {isDisciplineBlocked
                    ? executionHardWarnings[0]
                    : executionSoftWarnings[0] ?? decision.executionHint}
                </Text>
              </View>
            </View>
          </SurfaceCard>

          <SectionHeading title="当前结论" subtitle="先判断这条推荐现在值不值得出手，再谈参数。" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.summaryHeader}>
              <View style={styles.summaryCopy}>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>{decision.verdict}</Text>
                <Text style={[styles.summaryText, { color: palette.subtext }]}>{decision.summary}</Text>
              </View>
              <StatusPill label={`评分 ${signal.score.toFixed(3)}`} tone={decision.tone} />
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.listHeading, { color: palette.text }]}>为什么现在看它</Text>
              {decision.reasons.map((reason) => (
                <View key={reason} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                  <Text style={[styles.listText, { color: palette.text }]}>{reason}</Text>
                </View>
              ))}
            </View>

            <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.insightTitle, { color: palette.text }]}>执行提醒</Text>
              <Text style={[styles.insightText, { color: palette.subtext }]}>{decision.executionHint}</Text>
            </View>

            <View style={styles.listGroup}>
              <Text style={[styles.listHeading, { color: palette.text }]}>当前最该防什么</Text>
              {decision.warnings.map((warning) => (
                <View key={warning} style={styles.listRow}>
                  <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                  <Text style={[styles.listText, { color: palette.text }]}>{warning}</Text>
                </View>
              ))}
            </View>
          </SurfaceCard>

          {entryGuide ? (
            <>
              <SectionHeading
                title="开仓纪律"
                subtitle="先看事件、主线和组合上限，再决定这条票能不能动。"
              />
              <SurfaceCard style={styles.sectionCard}>
                <View style={styles.summaryHeader}>
                  <View style={styles.summaryCopy}>
                    <Text style={[styles.summaryTitle, { color: palette.text }]}>{entryGuide.mode}</Text>
                    <Text style={[styles.summaryText, { color: palette.subtext }]}>{entryGuide.summary}</Text>
                  </View>
                  <StatusPill
                    label={`事件 ${entryGuide.eventBias}`}
                    tone={getGuideTone(entryGuide.mode, entryGuide.eventBias)}
                  />
                </View>

                <View style={styles.metricGrid}>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>建议首仓</Text>
                    <Text style={[styles.metricValue, { color: palette.text }]}>
                      {entryGuide.recommendedFirstPositionPct}%
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>单票上限</Text>
                    <Text style={[styles.metricValue, { color: palette.text }]}>
                      {entryGuide.maxSinglePositionPct}%
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>主题上限</Text>
                    <Text style={[styles.metricValue, { color: palette.text }]}>
                      {entryGuide.maxThemeExposurePct}%
                    </Text>
                  </View>
                  <View style={styles.metricBlock}>
                    <Text style={[styles.metricLabel, { color: palette.subtext }]}>总仓建议</Text>
                    <Text style={[styles.metricValue, { color: palette.text }]}>
                      {entryGuide.targetExposurePct.toFixed(1)}%
                    </Text>
                  </View>
                </View>

                <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
                  <Text style={[styles.insightTitle, { color: palette.text }]}>纪律说明</Text>
                  <Text style={[styles.insightText, { color: palette.subtext }]}>{entryGuide.action}</Text>
                </View>

                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>主线匹配</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {entryGuide.themeSector
                      ? `${entryGuide.themeSector} · ${entryGuide.themeAlignment}`
                      : entryGuide.themeAlignment}
                  </Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>可部署现金</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {formatCurrency(entryGuide.deployableCash)}
                  </Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>建议首笔</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {entryGuide.suggestedQuantity > 0
                      ? `${entryGuide.suggestedQuantity} 股 / ${formatCurrency(entryGuide.suggestedAmount)}`
                      : `约 ${formatCurrency(entryGuide.suggestedAmount)}，当前不够一手`}
                  </Text>
                </View>

                {entryGuide.eventSummary ? (
                  <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
                    <Text style={[styles.insightTitle, { color: palette.text }]}>事件总控</Text>
                    <Text style={[styles.insightText, { color: palette.subtext }]}>
                      {entryGuide.eventSummary} 事件分 {entryGuide.eventScore.toFixed(1)}。
                    </Text>
                  </View>
                ) : null}

                {entryGuide.warnings.length > 0 ? (
                  <View style={styles.listGroup}>
                    <Text style={[styles.listHeading, { color: palette.text }]}>开仓前先防这些</Text>
                    {entryGuide.warnings.map((warning) => (
                      <View key={warning} style={styles.listRow}>
                        <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                        <Text style={[styles.listText, { color: palette.text }]}>{warning}</Text>
                      </View>
                    ))}
                  </View>
                ) : null}
              </SurfaceCard>
            </>
          ) : null}

          <SectionHeading title="开仓计划" subtitle="参数不是为了好看，是为了让执行动作更短更稳。" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.metricGrid}>
              <View style={styles.metricBlock}>
                <Text style={[styles.metricLabel, { color: palette.subtext }]}>计划入场</Text>
                <Text style={[styles.metricValue, { color: palette.text }]}>{signal.buyPrice.toFixed(2)}</Text>
              </View>
              <View style={styles.metricBlock}>
                <Text style={[styles.metricLabel, { color: palette.subtext }]}>止损缓冲</Text>
                <Text style={[styles.metricValue, { color: palette.danger }]}>
                  {stopBufferPct === null ? '--' : formatPercent(stopBufferPct)}
                </Text>
              </View>
              <View style={styles.metricBlock}>
                <Text style={[styles.metricLabel, { color: palette.subtext }]}>目标空间</Text>
                <Text style={[styles.metricValue, { color: palette.success }]}>
                  {upsidePct === null ? '--' : formatPercent(upsidePct)}
                </Text>
              </View>
              <View style={styles.metricBlock}>
                <Text style={[styles.metricLabel, { color: palette.subtext }]}>盈亏比</Text>
                <Text style={[styles.metricValue, { color: palette.text }]}>
                  {signal.riskReward.toFixed(1)} : 1
                </Text>
              </View>
            </View>

            <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.insightTitle, { color: palette.text }]}>位置说明</Text>
              <Text style={[styles.insightText, { color: palette.subtext }]}>
                {entryGapPct === null
                  ? '暂时拿不到现价与计划价关系。'
                  : entryGapPct > 0
                    ? `当前价比计划入场高 ${formatPercent(entryGapPct)}。`
                    : `当前价比计划入场低 ${formatPercent(Math.abs(entryGapPct))}。`}
                {' '}更新时间 {formatTimestamp(signal.timestamp)}。
              </Text>
            </View>

            <View style={styles.formBlock}>
              <Text style={[styles.inputLabel, { color: palette.subtext }]}>默认买入数量</Text>
              <View style={styles.presetRow}>
                {quantityOptions.map((preset) => (
                  <Pressable
                    key={preset}
                    onPress={() => {
                      setQuantityDraft(String(preset));
                    }}
                    style={[
                      styles.presetChip,
                      {
                        backgroundColor:
                          quantityDraft === String(preset) ? palette.accentSoft : palette.surfaceMuted,
                        borderColor:
                          quantityDraft === String(preset) ? palette.tint : palette.border,
                      },
                    ]}>
                    <Text
                      style={[
                        styles.presetChipText,
                        { color: quantityDraft === String(preset) ? palette.tint : palette.text },
                    ]}>
                      {preset} 股
                      {entryGuide?.suggestedQuantity === preset ? ' · 建议' : ''}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <TextInput
                keyboardType="number-pad"
                onChangeText={setQuantityDraft}
                placeholder="100"
                placeholderTextColor={palette.icon}
                style={[
                  styles.input,
                  {
                    backgroundColor: palette.surfaceMuted,
                    borderColor: palette.border,
                    color: palette.text,
                  },
                ]}
                value={quantityDraft}
              />
            </View>

            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>预计占用资金</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {estimatedCost > 0 ? formatCurrency(estimatedCost) : '--'}
              </Text>
            </View>
            {entryGuide ? (
              <>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>预计单票占比</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {estimatedCost > 0 ? `${estimatedPositionPct.toFixed(1)}%` : '--'}
                  </Text>
                </View>
                {entryGuide.sectorBucket ? (
                  <View style={styles.rowBetween}>
                    <Text style={[styles.rowLabel, { color: palette.subtext }]}>预计主题占比</Text>
                    <Text style={[styles.rowValue, { color: palette.text }]}>
                      {estimatedCost > 0
                        ? `${projectedThemeExposurePct.toFixed(1)}%`
                        : `${entryGuide.currentThemeExposurePct.toFixed(1)}%`}
                    </Text>
                  </View>
                ) : null}
              </>
            ) : null}
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>默认保护</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                止损 {signal.stopLoss.toFixed(2)} / 目标 {signal.targetPrice.toFixed(2)}
              </Text>
            </View>

            {entryGuide ? (
              <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
                <View style={styles.executionHeader}>
                  <Text style={[styles.insightTitle, { color: palette.text }]}>执行校验</Text>
                  <StatusPill label={executionStatusLabel} tone={executionStatusTone} />
                </View>
                {entryGuide.concentrationSummary ? (
                  <Text style={[styles.insightText, { color: palette.subtext }]}>
                    {entryGuide.concentrationSummary}
                  </Text>
                ) : null}
                {executionHardWarnings.length === 0 && executionSoftWarnings.length === 0 ? (
                  <Text style={[styles.insightText, { color: palette.subtext }]}>
                    当前输入数量还在纪律范围内，可以继续按计划执行。
                  </Text>
                ) : null}
                {executionHardWarnings.map((warning) => (
                  <View key={warning} style={styles.listRow}>
                    <View style={[styles.dot, { backgroundColor: palette.danger }]} />
                    <Text style={[styles.listText, { color: palette.text }]}>{warning}</Text>
                  </View>
                ))}
                {executionSoftWarnings.map((warning) => (
                  <View key={warning} style={styles.listRow}>
                    <View style={[styles.dot, { backgroundColor: palette.warning }]} />
                    <Text style={[styles.listText, { color: palette.text }]}>{warning}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            <Pressable
              disabled={isSubmitting || isDisciplineBlocked}
              onPress={() => {
                void handleOpenPosition();
              }}
              style={[
                styles.primaryButton,
                { backgroundColor: isSubmitting || isDisciplineBlocked ? palette.icon : palette.tint },
              ]}>
              {isSubmitting ? (
                <ActivityIndicator color="#FFFFFF" />
              ) : (
                <Text style={styles.primaryButtonText}>按计划模拟开仓</Text>
              )}
            </Pressable>
            {actionError ? (
              <Text style={[styles.feedbackText, { color: palette.danger }]}>{actionError}</Text>
            ) : null}
          </SurfaceCard>

          <SectionHeading title="环境与证据" subtitle="把环境、共识和因子放在一屏，不让你来回跳。" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>市场环境</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>{signal.regime}</Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>策略共识</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {signal.consensusCount} 个 / {signal.strategies.join(' / ') || signal.strategy}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>日内区间</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>
                {signal.low.toFixed(2)} - {signal.high.toFixed(2)}
              </Text>
            </View>
            <View style={styles.rowBetween}>
              <Text style={[styles.rowLabel, { color: palette.subtext }]}>成交额</Text>
              <Text style={[styles.rowValue, { color: palette.text }]}>{formatCurrency(signal.turnover)}</Text>
            </View>

            <View style={styles.factorGroup}>
              <Text style={[styles.listHeading, { color: palette.text }]}>影响最大的因子</Text>
              {topFactors.map(([name, value]) => (
                <View key={name} style={styles.factorRow}>
                  <Text style={[styles.factorName, { color: palette.text }]}>{name}</Text>
                  <View style={[styles.factorTrack, { backgroundColor: palette.surfaceMuted }]}>
                    <View
                      style={[
                        styles.factorFill,
                        {
                          width: `${Math.max(8, (Math.abs(value) / maxFactorValue) * 100)}%`,
                          backgroundColor: value >= 0 ? palette.success : palette.danger,
                        },
                      ]}
                    />
                  </View>
                  <Text
                    style={[
                      styles.factorValue,
                      { color: value >= 0 ? palette.success : palette.danger },
                    ]}>
                    {value.toFixed(2)}
                  </Text>
                </View>
              ))}
            </View>
          </SurfaceCard>

          <SectionHeading title="最近 K 线" subtitle="图形证据放在最后，避免你先被走势带跑。" />
          <SurfaceCard>
            <KlineSnapshot
              bars={klines}
              emptyLabel="历史 K 线暂时不可用，接口已经接通，等行情源可用时这里会直接显示。"
            />
          </SurfaceCard>
        </>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
  },
  feedbackButton: {
    alignSelf: 'flex-start',
    paddingVertical: 4,
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
  feedbackButtonText: {
    fontSize: 13,
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
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  sectionCard: {
    gap: 14,
  },
  summaryHeader: {
    gap: 12,
  },
  summaryCopy: {
    gap: 6,
  },
  summaryTitle: {
    fontSize: 22,
    fontWeight: '800',
    lineHeight: 30,
  },
  summaryText: {
    fontSize: 15,
    lineHeight: 22,
  },
  snapshotGrid: {
    gap: 12,
  },
  snapshotCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  snapshotStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  snapshotTitle: {
    fontSize: 17,
    fontWeight: '800',
    lineHeight: 23,
  },
  snapshotCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  snapshotBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  listGroup: {
    gap: 8,
  },
  listHeading: {
    fontSize: 15,
    fontWeight: '800',
  },
  listRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 999,
    marginTop: 7,
  },
  listText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 22,
  },
  insightBox: {
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  executionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  insightTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  insightText: {
    fontSize: 14,
    lineHeight: 22,
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.gap,
  },
  metricBlock: {
    flexBasis: '47%',
    borderRadius: 18,
    padding: 14,
    backgroundColor: 'rgba(21, 94, 239, 0.07)',
    gap: 4,
  },
  metricLabel: {
    fontSize: 12,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  metricValue: {
    fontSize: 20,
    fontWeight: '800',
  },
  formBlock: {
    gap: 8,
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  presetRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  presetChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  presetChipText: {
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  rowLabel: {
    fontSize: 14,
  },
  rowValue: {
    flex: 1,
    fontSize: 14,
    fontWeight: '700',
    lineHeight: 20,
    textAlign: 'right',
  },
  primaryButton: {
    minHeight: 48,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
  feedbackText: {
    fontSize: 13,
    lineHeight: 20,
  },
  factorGroup: {
    gap: 10,
  },
  factorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  factorName: {
    width: 78,
    fontSize: 13,
    fontWeight: '700',
  },
  factorTrack: {
    flex: 1,
    height: 8,
    borderRadius: 999,
    overflow: 'hidden',
  },
  factorFill: {
    height: '100%',
    borderRadius: 999,
  },
  factorValue: {
    width: 42,
    fontSize: 13,
    textAlign: 'right',
    fontWeight: '700',
  },
});
