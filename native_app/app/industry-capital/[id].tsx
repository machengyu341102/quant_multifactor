import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';

import { AppScreen } from '@/components/app/app-screen';
import { MetricCard } from '@/components/app/metric-card';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { formatTimestamp } from '@/lib/format';
import { getIndustryCapitalDetail, getIndustryCapitalResearchLog, submitIndustryCapitalResearchLog } from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { IndustryCapitalDirection, IndustryCapitalResearchItem } from '@/types/trading';

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function getTone(item: IndustryCapitalDirection): Tone {
  if (item.strategicLabel === '逆风跟踪') {
    return 'warning';
  }
  if (item.participationLabel === '中期波段' || item.participationLabel === '连涨接力') {
    return 'success';
  }
  return 'info';
}

function getResearchTone(label: string): Tone {
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

function getTimelineTone(emphasis: string): Tone {
  if (emphasis === 'success') {
    return 'success';
  }
  if (emphasis === 'warning') {
    return 'warning';
  }
  if (emphasis === 'danger') {
    return 'danger';
  }
  if (emphasis === 'info') {
    return 'info';
  }
  return 'neutral';
}

function getDirectionCallout(direction: IndustryCapitalDirection): {
  title: string;
  summary: string;
  tone: Tone;
} {
  if (direction.participationLabel === '中期波段' || direction.participationLabel === '连涨接力') {
    return {
      title: '可以提高跟踪强度',
      summary: '政策、产业和资本三层已经开始共振，可以把它当成重点方向持续盯。',
      tone: 'success',
    };
  }

  if (direction.strategicLabel === '逆风跟踪' || direction.participationLabel === '先观察') {
    return {
      title: '现在先观察，不急着上强度',
      summary: '先把官方催化、调研回写和资金承接补齐，再决定要不要切换成强进攻方向。',
      tone: 'warning',
    };
  }

  return {
    title: '继续验证，等待确认',
    summary: '方向已经成立一半，但还需要更多兑现和研究回写，才能从看法变成动作。',
    tone: 'info',
  };
}

function DetailList({
  title,
  items,
  palette,
  dotColor,
}: {
  title: string;
  items: string[];
  palette: (typeof Colors)['light'];
  dotColor: string;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <View style={styles.listGroup}>
      <Text style={[styles.subTitle, { color: palette.text }]}>{title}</Text>
      {items.map((item) => (
        <View key={`${title}-${item}`} style={styles.rowWithDot}>
          <View style={[styles.dot, { backgroundColor: dotColor }]} />
          <Text style={[styles.bodyText, { color: palette.text }]}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

export default function IndustryCapitalDetailScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const [titleDraft, setTitleDraft] = useState('');
  const [noteDraft, setNoteDraft] = useState('');
  const [companyDraft, setCompanyDraft] = useState('');
  const [sourceDraft, setSourceDraft] = useState('产业调研');
  const [statusDraft, setStatusDraft] = useState('待验证');
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    async () => {
      if (!id) {
        throw new Error('缺少产业资本方向 ID');
      }

      return getIndustryCapitalDetail(id, token ?? undefined);
    },
    [id, token, apiBaseUrl]
  );
  const {
    data: researchLog = [],
    error: researchError,
    isPending: researchPending,
    refreshing: researchRefreshing,
    refresh: refreshResearch,
  } = useRemoteResource<IndustryCapitalResearchItem[]>(
    async () => {
      if (!id) {
        return [];
      }
      return getIndustryCapitalResearchLog(id, token ?? undefined);
    },
    [id, token, apiBaseUrl]
  );

  const direction = data;
  const researchItems = researchLog ?? [];
  const directionCallout = direction ? getDirectionCallout(direction) : null;

  async function handleRefresh() {
    await Promise.all([refresh(), refreshResearch()]);
  }

  async function handleSubmitResearch() {
    if (!id || !token) {
      return;
    }
    const title = titleDraft.trim();
    const note = noteDraft.trim();
    if (!title || !note) {
      setSubmitMessage('先把调研标题和内容填完整。');
      return;
    }
    setIsSubmitting(true);
    setSubmitMessage(null);
    try {
      const result = await submitIndustryCapitalResearchLog(
        id,
        {
          title,
          note,
          source: sourceDraft.trim() || '产业调研',
          status: statusDraft.trim() || '待验证',
          companyCode: companyDraft.trim() || null,
          companyName: null,
        },
        token
      );
      setTitleDraft('');
      setNoteDraft('');
      setCompanyDraft('');
      setSubmitMessage(result.message);
      await refreshResearch();
    } catch (submitError) {
      const detail = submitError instanceof Error ? submitError.message : '调研记录提交失败';
      setSubmitMessage(detail);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AppScreen refreshing={refreshing || researchRefreshing} onRefresh={handleRefresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回上一页</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Industry Capital"
        title="方向深页"
        subtitle="把政策、供需、产业链和资金偏好拆开看，先确认这是事业机会、资本机会，还是只该跟踪。"
      />

      <StateBanner error={error} isPending={isPending && !direction} loadingLabel="正在同步方向深页" />

      {direction ? (
        <>
          <View style={[styles.hero, { backgroundColor: palette.hero }]}>
            <Text style={styles.heroEyebrow}>STRATEGIC DIRECTION</Text>
            <Text style={styles.heroTitle}>{direction.direction}</Text>
            <Text style={styles.heroCopy}>{direction.summary}</Text>
            <View style={styles.heroPills}>
              <StatusPill label={direction.policyBucket} tone="neutral" />
              <StatusPill label={direction.focusSector} tone="info" />
              <StatusPill label={direction.strategicLabel} tone={getTone(direction)} />
              <StatusPill label={direction.participationLabel} tone={getTone(direction)} />
            </View>
          </View>

          <SectionHeading
            title="一页决策摘要"
            subtitle="先用一页把方向口径、动作和验证门槛讲清楚，再往下看详细证据。"
          />
          <SurfaceCard style={styles.cardGap}>
            <View style={styles.summaryHead}>
              <View style={styles.summaryMain}>
                <Text style={[styles.sectionTitle, { color: palette.text }]}>{directionCallout?.title}</Text>
                <Text style={[styles.bodyText, { color: palette.subtext }]}>
                  {directionCallout?.summary}
                </Text>
              </View>
              <StatusPill
                label={`${direction.strategicLabel} / ${direction.participationLabel}`}
                tone={directionCallout?.tone ?? getTone(direction)}
              />
            </View>

            <View style={styles.summaryGrid}>
              <View style={[styles.summaryCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.summaryStep, { color: palette.tint }]}>01 官方定调</Text>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>
                  {direction.latestCatalystTitle}
                </Text>
                <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
                  {direction.currentTimelineStage}
                  {direction.officialSourceEntries[0]?.publishedAt
                    ? ` / ${direction.officialSourceEntries[0].publishedAt}`
                    : ''}
                </Text>
                <Text style={[styles.summaryBody, { color: palette.text }]}>
                  {direction.latestCatalystSummary}
                </Text>
              </View>

              <View style={[styles.summaryCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.summaryStep, { color: palette.tint }]}>02 事业动作</Text>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>
                  {direction.businessHorizon}
                </Text>
                <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
                  {direction.focusSector} / {direction.industryPhase}
                </Text>
                <Text style={[styles.summaryBody, { color: palette.text }]}>
                  {direction.businessAction}
                </Text>
              </View>

              <View style={[styles.summaryCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.summaryStep, { color: palette.tint }]}>03 资本动作</Text>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>
                  {direction.capitalHorizon}
                </Text>
                <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
                  优先级 {direction.priorityScore.toFixed(1)} / 资金偏好 {direction.capitalPreferenceScore.toFixed(1)}
                </Text>
                <Text style={[styles.summaryBody, { color: palette.text }]}>
                  {direction.capitalAction}
                </Text>
              </View>

              <View style={[styles.summaryCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <Text style={[styles.summaryStep, { color: palette.tint }]}>04 验证门槛</Text>
                <Text style={[styles.summaryTitle, { color: palette.text }]}>
                  {direction.researchSignalLabel}
                </Text>
                <Text style={[styles.summaryCopy, { color: palette.subtext }]}>
                  官方新鲜度 {direction.officialFreshnessScore.toFixed(1)} / 调研 {direction.researchSignalScore.toFixed(1)}
                </Text>
                <Text style={[styles.summaryBody, { color: palette.text }]}>
                  {direction.researchNextAction}
                </Text>
              </View>
            </View>

            <View style={styles.heroPills}>
              <StatusPill label={`政策 ${direction.policyScore.toFixed(1)}`} tone="neutral" />
              <StatusPill label={`需求 ${direction.demandScore.toFixed(1)}`} tone="success" />
              <StatusPill label={`供给 ${direction.supplyScore.toFixed(1)}`} tone="warning" />
              <StatusPill label={`战略 ${direction.strategicScore.toFixed(1)}`} tone="info" />
            </View>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <View style={styles.headlineRow}>
              <View style={styles.headlineMain}>
                <Text style={[styles.headlineTitle, { color: palette.text }]}>方向判断</Text>
                <Text style={[styles.headlineMeta, { color: palette.subtext }]}>
                  {direction.industryPhase} / 事业 {direction.businessHorizon} / 资本 {direction.capitalHorizon}
                </Text>
              </View>
              <StatusPill label={direction.capitalHorizon} tone={getTone(direction)} />
            </View>

            <Text style={[styles.bodyText, { color: palette.text }]}>{direction.businessAction}</Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>{direction.capitalAction}</Text>
            <Text style={[styles.bodyText, { color: palette.danger }]}>{direction.riskNote}</Text>
            <View style={styles.heroPills}>
              <StatusPill label={`阶段 ${direction.currentTimelineStage}`} tone="neutral" />
              <StatusPill label={direction.researchSignalLabel} tone={getResearchTone(direction.researchSignalLabel)} />
              <StatusPill label={`调研 ${direction.researchSignalScore.toFixed(1)}`} tone="neutral" />
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{direction.researchSummary}</Text>
            <Text style={[styles.bodyText, { color: palette.tint }]}>{direction.researchNextAction}</Text>
            <View
              style={[styles.officialCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
              <View style={styles.companyHeader}>
                <View style={styles.companyMain}>
                  <Text style={[styles.companyTitle, { color: palette.text }]}>最新催化</Text>
                  <Text style={[styles.companyMeta, { color: palette.subtext }]}>{direction.latestCatalystTitle}</Text>
                </View>
                <StatusPill label={direction.currentTimelineStage} tone="info" />
              </View>
              <Text style={[styles.bodyText, { color: palette.text }]}>{direction.latestCatalystSummary}</Text>
            </View>

            <View style={styles.metricGrid}>
              <MetricCard label="优先级" value={direction.priorityScore.toFixed(1)} tone="info" />
              <MetricCard label="战略" value={direction.strategicScore.toFixed(1)} tone="info" />
              <MetricCard label="政策" value={direction.policyScore.toFixed(1)} tone="neutral" />
              <MetricCard label="需求" value={direction.demandScore.toFixed(1)} tone="success" />
              <MetricCard label="供给" value={direction.supplyScore.toFixed(1)} tone="warning" />
              <MetricCard label="资金偏好" value={direction.capitalPreferenceScore.toFixed(1)} tone="info" />
              <MetricCard label="官方新鲜度" value={direction.officialFreshnessScore.toFixed(1)} tone="warning" />
            </View>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>官方原文与兑现时间轴</Text>
            {direction.officialCards.length > 0 ? (
              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>官方原文卡片</Text>
                {direction.officialCards.map((card) => (
                  <View
                    key={`${direction.id}-${card.title}`}
                    style={[styles.officialCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <View style={styles.companyHeader}>
                      <View style={styles.companyMain}>
                        <Text style={[styles.companyTitle, { color: palette.text }]}>{card.title}</Text>
                        <Text style={[styles.companyMeta, { color: palette.subtext }]}>{card.source}</Text>
                      </View>
                      <StatusPill label="官方卡片" tone="neutral" />
                    </View>
                    <Text style={[styles.bodyText, { color: palette.text }]}>{card.excerpt}</Text>
                    <Text style={[styles.bodyText, { color: palette.subtext }]}>为什么重要：{card.whyItMatters}</Text>
                    <Text style={[styles.bodyText, { color: palette.tint }]}>下一步：{card.nextWatch}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {direction.officialSourceEntries.length > 0 ? (
              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>官方原文 ingest</Text>
                {direction.officialSourceEntries.map((item) => (
                  <View
                    key={`${direction.id}-${item.title}`}
                    style={[styles.officialCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <View style={styles.companyHeader}>
                      <View style={styles.companyMain}>
                        <Text style={[styles.companyTitle, { color: palette.text }]}>{item.title}</Text>
                        <Text style={[styles.companyMeta, { color: palette.subtext }]}>
                          {item.issuer}
                          {item.publishedAt ? ` / ${item.publishedAt}` : ''}
                        </Text>
                      </View>
                      <StatusPill label={item.sourceType} tone="neutral" />
                    </View>
                    <Text style={[styles.bodyText, { color: palette.text }]}>{item.excerpt}</Text>
                    {item.reference ? (
                      <Text style={[styles.bodyText, { color: palette.subtext }]}>参考：{item.reference}</Text>
                    ) : null}
                    {item.referenceUrl ? (
                      <Text style={[styles.bodyText, { color: palette.tint }]}>链接：{item.referenceUrl}</Text>
                    ) : null}
                    {item.keyPoints.map((point) => (
                      <View key={`${item.title}-${point}`} style={styles.rowWithDot}>
                        <View style={[styles.dot, { backgroundColor: palette.success }]} />
                        <Text style={[styles.bodyText, { color: palette.text }]}>{point}</Text>
                      </View>
                    ))}
                    {item.watchTags.length > 0 ? (
                      <View style={styles.heroPills}>
                        {item.watchTags.map((tag) => (
                          <StatusPill key={`${item.title}-${tag}`} label={tag} tone="info" />
                        ))}
                      </View>
                    ) : null}
                  </View>
                ))}
              </View>
            ) : null}
            <DetailList
              title="官方原文线索"
              items={direction.officialDocuments}
              palette={palette}
              dotColor={palette.tint}
            />
            <DetailList
              title="官方观察点"
              items={direction.officialWatchpoints}
              palette={palette}
              dotColor={palette.success}
            />
            <DetailList
              title="兑现时间轴"
              items={direction.timelineCheckpoints}
              palette={palette}
              dotColor={palette.warning}
            />
            {direction.timelineEvents.length > 0 ? (
              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>方向时间轴</Text>
                {direction.timelineEvents.map((item) => (
                  <View
                    key={item.id}
                    style={[styles.companyCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <View style={styles.companyHeader}>
                      <View style={styles.companyMain}>
                        <Text style={[styles.companyTitle, { color: palette.text }]}>{item.title}</Text>
                        <Text style={[styles.companyMeta, { color: palette.subtext }]}>
                          {item.source ?? item.lane}
                          {item.timestamp ? ` / ${formatTimestamp(item.timestamp)}` : ''}
                        </Text>
                      </View>
                      <StatusPill label={item.signalLabel} tone={getTimelineTone(item.emphasis)} />
                    </View>
                    <View style={styles.heroPills}>
                      <StatusPill label={item.stage} tone="neutral" />
                      <StatusPill label={item.lane === 'research' ? '调研节点' : item.lane === 'official' ? '官方节点' : '兑现节点'} tone="info" />
                    </View>
                    <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
                    {item.nextAction ? (
                      <Text style={[styles.bodyText, { color: palette.tint }]}>下一步：{item.nextAction}</Text>
                    ) : null}
                  </View>
                ))}
              </View>
            ) : null}
            <DetailList
              title="官方来源"
              items={direction.officialSources}
              palette={palette}
              dotColor={palette.tint}
            />
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>产业链与机会落点</Text>
            <DetailList title="上游" items={direction.upstream} palette={palette} dotColor={palette.tint} />
            <DetailList title="中游" items={direction.midstream} palette={palette} dotColor={palette.success} />
            <DetailList title="下游" items={direction.downstream} palette={palette} dotColor={palette.warning} />
            <DetailList
              title="传导路径"
              items={direction.transmissionPaths}
              palette={palette}
              dotColor={palette.tint}
            />
            <DetailList
              title="机会落点"
              items={direction.opportunities}
              palette={palette}
              dotColor={palette.success}
            />
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>事业调研与合作清单</Text>
            {direction.companyWatchlist.length > 0 ? (
              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>公司映射与跟踪名单</Text>
                {direction.companyWatchlist.map((item) => (
                  <View
                    key={`${direction.id}-${item.code || item.name}`}
                    style={[styles.companyCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <View style={styles.companyHeader}>
                      <View style={styles.companyMain}>
                        <Text style={[styles.companyTitle, { color: palette.text }]}>
                          {item.code ? `${item.code} ` : ''}
                          {item.name}
                        </Text>
                        <Text style={[styles.companyMeta, { color: palette.subtext }]}>
                          {item.role} / {item.chainPosition}
                        </Text>
                      </View>
                      <StatusPill label={item.priorityLabel} tone="info" />
                    </View>
                    <View style={styles.heroPills}>
                      <StatusPill label={`跟踪分 ${item.trackingScore.toFixed(1)}`} tone="success" />
                      <StatusPill label={item.marketAlignment} tone="neutral" />
                      <StatusPill label={item.timelineAlignment} tone="warning" />
                      <StatusPill label={item.researchSignalLabel} tone={getResearchTone(item.researchSignalLabel)} />
                      {item.linkedSetupLabel ? <StatusPill label={item.linkedSetupLabel} tone="warning" /> : null}
                    </View>
                    <Text style={[styles.bodyText, { color: palette.text }]}>{item.trackingReason}</Text>
                    <Text style={[styles.bodyText, { color: palette.subtext }]}>{item.action}</Text>
                    {item.catalystHint ? (
                      <Text style={[styles.bodyText, { color: palette.subtext }]}>最新催化：{item.catalystHint}</Text>
                    ) : null}
                    {item.recentResearchNote ? (
                      <Text style={[styles.bodyText, { color: palette.tint }]}>最近调研：{item.recentResearchNote}</Text>
                    ) : null}
                    <Text style={[styles.bodyText, { color: palette.tint }]}>下一步验证：{item.nextCheck}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            <DetailList
              title="事业调研清单"
              items={direction.businessChecklist}
              palette={palette}
              dotColor={palette.warning}
            />
            <DetailList
              title="重点调研对象"
              items={direction.researchTargets}
              palette={palette}
              dotColor={palette.tint}
            />
            <DetailList
              title="合作对象"
              items={direction.cooperationTargets}
              palette={palette}
              dotColor={palette.success}
            />
            <DetailList
              title="合作方式"
              items={direction.cooperationModes}
              palette={palette}
              dotColor={palette.tint}
            />
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>资本验证与驱动</Text>
            <DetailList
              title="资本验证清单"
              items={direction.capitalChecklist}
              palette={palette}
              dotColor={palette.danger}
            />
            <DetailList
              title="关键验证信号"
              items={direction.validationSignals}
              palette={palette}
              dotColor={palette.warning}
            />
            <DetailList title="核心驱动" items={direction.drivers} palette={palette} dotColor={palette.tint} />
            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  if (direction.linkedSignalId && !direction.linkedSignalId.startsWith('theme-seed-')) {
                    router.push({ pathname: '/signal/[id]', params: { id: direction.linkedSignalId } });
                    return;
                  }
                  router.push('/(tabs)/brain');
                }}
                style={[styles.primaryAction, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryActionText}>
                  {direction.linkedSignalId && !direction.linkedSignalId.startsWith('theme-seed-')
                    ? '看交易焦点'
                    : '回决策台复核'}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  router.push('/(tabs)/brain');
                }}
                style={[styles.secondaryAction, { borderColor: palette.border }]}>
                <Text style={[styles.secondaryActionText, { color: palette.tint }]}>回决策台</Text>
              </Pressable>
            </View>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>方向调研记录</Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>
              把政策、客户、供应链、订单和价格验证记录回写，方向深页才会越来越像真正的智库档案。
            </Text>
            <TextInput
              value={titleDraft}
              onChangeText={setTitleDraft}
              placeholder="调研标题，例如：客户替代验证进展"
              placeholderTextColor={palette.subtext}
              style={[
                styles.input,
                { color: palette.text, borderColor: palette.border, backgroundColor: palette.surfaceMuted },
              ]}
            />
            <TextInput
              value={companyDraft}
              onChangeText={setCompanyDraft}
              placeholder="关联公司代码，可选，例如：688981"
              placeholderTextColor={palette.subtext}
              style={[
                styles.input,
                { color: palette.text, borderColor: palette.border, backgroundColor: palette.surfaceMuted },
              ]}
            />
            <View style={styles.heroPills}>
              {['产业调研', '客户反馈', '供应链验证', '政策跟踪'].map((item) => (
                <Pressable
                  key={item}
                  onPress={() => setSourceDraft(item)}
                  style={[
                    styles.filterChip,
                    {
                      borderColor: sourceDraft === item ? palette.tint : palette.border,
                      backgroundColor: sourceDraft === item ? palette.accentSoft : palette.surfaceMuted,
                    },
                  ]}>
                  <Text style={[styles.filterChipText, { color: palette.text }]}>{item}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.heroPills}>
              {['待验证', '已验证', '有阻力'].map((item) => (
                <Pressable
                  key={item}
                  onPress={() => setStatusDraft(item)}
                  style={[
                    styles.filterChip,
                    {
                      borderColor: statusDraft === item ? palette.tint : palette.border,
                      backgroundColor: statusDraft === item ? palette.accentSoft : palette.surfaceMuted,
                    },
                  ]}>
                  <Text style={[styles.filterChipText, { color: palette.text }]}>{item}</Text>
                </Pressable>
              ))}
            </View>
            <TextInput
              value={noteDraft}
              onChangeText={setNoteDraft}
              placeholder="记录本次调研结论、验证信号、卡点和下一步"
              placeholderTextColor={palette.subtext}
              multiline
              textAlignVertical="top"
              style={[
                styles.textarea,
                { color: palette.text, borderColor: palette.border, backgroundColor: palette.surfaceMuted },
              ]}
            />
            {submitMessage ? (
              <Text style={[styles.bodyText, { color: palette.tint }]}>{submitMessage}</Text>
            ) : null}
            <View style={styles.actionRow}>
              <Pressable
                onPress={() => {
                  void handleSubmitResearch();
                }}
                disabled={isSubmitting}
                style={[styles.primaryAction, { backgroundColor: palette.tint, opacity: isSubmitting ? 0.7 : 1 }]}>
                <Text style={styles.primaryActionText}>{isSubmitting ? '正在回写...' : '回写调研记录'}</Text>
              </Pressable>
            </View>
            <StateBanner
              error={researchError}
              isPending={researchPending && researchItems.length === 0}
              loadingLabel="正在同步调研记录"
            />
            {researchItems.length > 0 ? (
              <View style={styles.listGroup}>
                <Text style={[styles.subTitle, { color: palette.text }]}>最近调研</Text>
                {researchItems.map((item) => (
                  <View
                    key={item.id}
                    style={[styles.companyCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                    <View style={styles.companyHeader}>
                      <View style={styles.companyMain}>
                        <Text style={[styles.companyTitle, { color: palette.text }]}>{item.title}</Text>
                        <Text style={[styles.companyMeta, { color: palette.subtext }]}>
                          {item.source} / {item.author} / {item.updatedAt.replace('T', ' ').slice(0, 16)}
                        </Text>
                      </View>
                      <StatusPill label={item.status} tone="info" />
                    </View>
                    {item.companyCode || item.companyName ? (
                      <Text style={[styles.bodyText, { color: palette.tint }]}>
                        关联对象：{item.companyCode ? `${item.companyCode} ` : ''}
                        {item.companyName ?? ''}
                      </Text>
                    ) : null}
                    <Text style={[styles.bodyText, { color: palette.text }]}>{item.note}</Text>
                  </View>
                ))}
              </View>
            ) : (
              <Text style={[styles.bodyText, { color: palette.subtext }]}>
                这条方向还没有调研记录，先把第一次验证结论写进来。
              </Text>
            )}
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
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  cardGap: {
    gap: 14,
  },
  summaryHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
  },
  summaryMain: {
    flex: 1,
    gap: 6,
  },
  summaryGrid: {
    gap: 12,
  },
  summaryCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  summaryStep: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  summaryTitle: {
    fontSize: 17,
    fontWeight: '800',
    lineHeight: 23,
  },
  summaryCopy: {
    fontSize: 13,
    lineHeight: 20,
  },
  summaryBody: {
    fontSize: 14,
    lineHeight: 22,
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
    fontSize: 22,
    fontWeight: '800',
    lineHeight: 28,
  },
  headlineMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  bodyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  metricGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  subTitle: {
    fontSize: 14,
    fontWeight: '800',
    lineHeight: 20,
  },
  listGroup: {
    gap: 8,
  },
  rowWithDot: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
  },
  companyCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  officialCard: {
    borderWidth: 1,
    borderRadius: 20,
    padding: 14,
    gap: 8,
  },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
  },
  textarea: {
    minHeight: 120,
    borderWidth: 1,
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    lineHeight: 22,
  },
  filterChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  filterChipText: {
    fontSize: 12,
    fontWeight: '700',
  },
  companyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 10,
    alignItems: 'flex-start',
  },
  companyMain: {
    flex: 1,
    gap: 4,
  },
  companyTitle: {
    fontSize: 15,
    fontWeight: '800',
    lineHeight: 22,
  },
  companyMeta: {
    fontSize: 12,
    lineHeight: 18,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 99,
    marginTop: 7,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  primaryAction: {
    minHeight: 46,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  primaryActionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  secondaryAction: {
    minHeight: 46,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  secondaryActionText: {
    fontSize: 14,
    fontWeight: '800',
  },
});
