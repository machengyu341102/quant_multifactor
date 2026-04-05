import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';

import { AppScreen } from '@/components/app/app-screen';
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

      <SectionHeading title="方向" />

      <StateBanner error={error} isPending={isPending && !direction} loadingLabel="正在同步方向深页" />

      {direction ? (
        <>
          <SurfaceCard style={styles.cardGap}>
            <View style={styles.summaryHead}>
              <View style={styles.summaryMain}>
                <Text style={[styles.sectionTitle, { color: palette.text }]}>{direction.direction}</Text>
                <Text style={[styles.bodyText, { color: palette.subtext }]}>
                  {directionCallout?.summary ?? direction.summary}
                </Text>
                <Text style={[styles.bodyText, { color: palette.text }]}>
                  {direction.strategicLabel} / {direction.participationLabel}
                </Text>
              </View>
            </View>

            <Text style={[styles.bodyText, { color: palette.subtext }]}>
              {direction.policyBucket} / {direction.focusSector} / {direction.latestCatalystTitle} / {direction.researchSignalLabel}
            </Text>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>方向动作</Text>
            <Text style={[styles.bodyText, { color: palette.text }]}>{direction.businessAction}</Text>
            <Text style={[styles.bodyText, { color: palette.subtext }]}>{direction.capitalAction}</Text>
            <Text style={[styles.bodyText, { color: palette.danger }]}>{direction.riskNote}</Text>
            <Text style={[styles.bodyText, { color: palette.text }]}>{direction.researchSummary}</Text>
            <Text style={[styles.bodyText, { color: palette.tint }]}>{direction.researchNextAction}</Text>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>证据与时间轴</Text>
            <Text style={[styles.bodyText, { color: palette.text }]}>
              最新催化：{direction.latestCatalystTitle} / {direction.latestCatalystSummary}
            </Text>
            {direction.officialSourceEntries[0] ? (
              <Text style={[styles.bodyText, { color: palette.subtext }]}>
                官方：{direction.officialSourceEntries[0].issuer}
                {direction.officialSourceEntries[0].publishedAt ? ` / ${direction.officialSourceEntries[0].publishedAt}` : ''}
              </Text>
            ) : null}
            <DetailList title="官方观察点" items={direction.officialWatchpoints.slice(0, 2)} palette={palette} dotColor={palette.success} />
            <DetailList title="兑现时间轴" items={direction.timelineCheckpoints.slice(0, 2)} palette={palette} dotColor={palette.warning} />
            {direction.timelineEvents.slice(0, 1).map((item) => (
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
                <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
              </View>
            ))}
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>对象与清单</Text>
            {direction.companyWatchlist[0] ? (
              <View
                style={[styles.companyCard, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
                <View style={styles.companyHeader}>
                  <View style={styles.companyMain}>
                    <Text style={[styles.companyTitle, { color: palette.text }]}>
                      {direction.companyWatchlist[0].code ? `${direction.companyWatchlist[0].code} ` : ''}
                      {direction.companyWatchlist[0].name}
                    </Text>
                    <Text style={[styles.companyMeta, { color: palette.subtext }]}>
                      {direction.companyWatchlist[0].role} / {direction.companyWatchlist[0].chainPosition}
                    </Text>
                  </View>
                  <StatusPill label={direction.companyWatchlist[0].priorityLabel} tone="info" />
                </View>
                <Text style={[styles.bodyText, { color: palette.text }]}>{direction.companyWatchlist[0].trackingReason}</Text>
                <Text style={[styles.bodyText, { color: palette.tint }]}>下一步：{direction.companyWatchlist[0].nextCheck}</Text>
              </View>
            ) : null}
            <DetailList title="机会落点" items={direction.opportunities.slice(0, 1)} palette={palette} dotColor={palette.success} />
            <DetailList title="关键驱动" items={direction.drivers.slice(0, 1)} palette={palette} dotColor={palette.tint} />
            <DetailList title="资本验证" items={direction.validationSignals.slice(0, 1)} palette={palette} dotColor={palette.warning} />
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
                {direction.linkedSignalId && !direction.linkedSignalId.startsWith('theme-seed-') ? '看交易焦点' : '回决策台'}
              </Text>
            </Pressable>
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.sectionTitle, { color: palette.text }]}>方向调研记录</Text>
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
              {['产业调研', '客户反馈', '供应链验证'].map((item) => (
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
                {researchItems.slice(0, 1).map((item) => (
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
  bodyText: {
    fontSize: 14,
    lineHeight: 22,
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
