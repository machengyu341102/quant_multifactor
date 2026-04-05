import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors, Spacing } from '@/constants/theme';
import { buildActionReceiptHref } from '@/lib/action-receipt';
import { formatCurrency, formatPercent, formatTimestamp } from '@/lib/format';
import { getSignalDetail, openSignalPosition } from '@/lib/api';
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
      return { signal };
    },
    [id, token, apiBaseUrl]
  );

  const signal = data?.signal;
  const decision = signal ? buildSignalDecision(signal) : null;
  const signalCallout = signal && decision ? getSignalCallout(signal, decision) : null;
  const entryGuide = signal?.entryGuide ?? null;
  const suggestedQuantity = entryGuide?.suggestedQuantity ?? 0;
  const topFactors = signal
    ? Object.entries(signal.factorScores)
        .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]))
        .slice(0, 4)
    : [];
  const intendedQuantity = Number.parseInt(quantityDraft, 10);
  const estimatedCost =
    signal && Number.isInteger(intendedQuantity) && intendedQuantity > 0
      ? signal.buyPrice * intendedQuantity
      : 0;
  const quantityPresets = [100, 200, 500];
  const quantityOptions = Array.from(
    new Set([entryGuide?.suggestedQuantity ?? 0, ...quantityPresets].filter((value) => value > 0))
  ).slice(0, 3);
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
      <SurfaceCard style={styles.sectionCard}>
        <View style={styles.summaryHeader}>
          <View style={styles.summaryCopy}>
            <Text style={[styles.summaryTitle, { color: palette.text }]}>
              {signal?.code ?? '--'} {signal?.name ?? ''}
            </Text>
            <Text style={[styles.summaryText, { color: palette.subtext }]}>
              {signalCallout?.summary ?? decision?.summary ?? '先看结论和纪律，再决定要不要动。'}
            </Text>
            <Text style={[styles.summaryHint, { color: palette.text }]}>
              {decision?.verdict ?? '等待数据'}
            </Text>
          </View>
        </View>
        <Text style={[styles.summaryHint, { color: palette.subtext }]}>
          {signal?.strategy ?? '暂无策略'}{entryGuide ? ` / ${entryGuide.mode}` : ''} / {signal ? `现价 ${signal.price.toFixed(2)}` : '现价 --'}
        </Text>
        {decision?.executionHint ? (
          <Text style={[styles.summaryHint, { color: palette.subtext }]}>{decision.executionHint}</Text>
        ) : null}
      </SurfaceCard>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取推荐详情" />

      {signal && decision ? (
        <>
          <SectionHeading title="执行判断" />
          <SurfaceCard style={styles.sectionCard}>
            <View style={styles.summaryHeader}>
              <View style={styles.summaryCopy}>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>{decision.verdict}</Text>
                <Text style={[styles.summaryText, { color: palette.subtext }]}>{decision.summary}</Text>
                <Text style={[styles.summaryHint, { color: palette.text }]}>
                  评分 {signal.score.toFixed(3)}
                </Text>
              </View>
            </View>

            <Text style={[styles.summaryHint, { color: palette.subtext }]}>{decision.reasons[0]}</Text>

            {entryGuide ? (
              <>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>开仓模式</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>{entryGuide.mode}</Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>建议首仓</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    {entryGuide.recommendedFirstPositionPct}% / {entryGuide.suggestedQuantity > 0 ? `${entryGuide.suggestedQuantity} 股` : '不足一手'}
                  </Text>
                </View>
                <View style={styles.rowBetween}>
                  <Text style={[styles.rowLabel, { color: palette.subtext }]}>组合上限</Text>
                  <Text style={[styles.rowValue, { color: palette.text }]}>
                    单票 {entryGuide.maxSinglePositionPct}% / 主题 {entryGuide.maxThemeExposurePct}%
                  </Text>
                </View>
                <Text style={[styles.summaryHint, { color: palette.text }]}>{entryGuide.action}</Text>
              </>
            ) : null}

            <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.insightTitle, { color: palette.text }]}>先手提醒</Text>
              <Text style={[styles.insightText, { color: palette.subtext }]}>
                {decision.executionHint}
                {decision.warnings[0] ? ` ${decision.warnings[0]}` : ''}
              </Text>
            </View>
          </SurfaceCard>

          <SectionHeading title="开仓计划" />
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
                {quantityOptions.slice(0, 1).map((preset) => (
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
            {entryGuide ? (
              <View style={[styles.insightBox, { backgroundColor: palette.surfaceMuted }]}>
                <View style={styles.executionHeader}>
                  <Text style={[styles.insightTitle, { color: palette.text }]}>执行校验</Text>
                  <Text style={[styles.rowLabel, { color: palette.text }]}>{executionStatusLabel}</Text>
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

          <SectionHeading title="环境与证据" />
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

            {topFactors.slice(0, 1).map(([name, value]) => (
              <View key={name} style={styles.rowBetween}>
                <Text style={[styles.rowLabel, { color: palette.subtext }]}>{name}</Text>
                <Text
                  style={[
                    styles.rowValue,
                    { color: value >= 0 ? palette.success : palette.danger },
                  ]}>
                  {value.toFixed(2)}
                </Text>
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
  summaryPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  summaryHint: {
    fontSize: 13,
    lineHeight: 20,
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
});
