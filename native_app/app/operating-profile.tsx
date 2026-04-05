import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getOperatingProfile, updateOperatingProfile } from '@/lib/api';
import { formatTimestamp } from '@/lib/format';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { OperatingProfile } from '@/types/trading';

interface OperatingProfileDraft {
  companyName: string;
  primaryIndustries: string;
  operatingMode: string;
  orderVisibilityMonths: string;
  capacityUtilizationPct: string;
  inventoryDays: string;
  supplierConcentrationPct: string;
  customerConcentrationPct: string;
  overseasRevenuePct: string;
  sensitiveRegionExposurePct: string;
  cashBufferMonths: string;
  capexFlexibility: string;
  inventoryStrategy: string;
  keyInputs: string;
  keyRoutes: string;
  strategicProjects: string;
}

interface DraftSectionSummary {
  key: string;
  label: string;
  completed: number;
  total: number;
}

interface DraftWorkspaceSummary {
  completenessScore: number;
  completenessLabel: string;
  missingFields: string[];
  recommendedActions: string[];
  sections: DraftSectionSummary[];
}

function toDraft(profile: OperatingProfile | null): OperatingProfileDraft {
  return {
    companyName: profile?.companyName ?? '',
    primaryIndustries: (profile?.primaryIndustries ?? []).join(' / '),
    operatingMode: profile?.operatingMode ?? 'balanced',
    orderVisibilityMonths: profile ? String(profile.orderVisibilityMonths) : '',
    capacityUtilizationPct: profile ? String(profile.capacityUtilizationPct) : '',
    inventoryDays: profile ? String(profile.inventoryDays) : '',
    supplierConcentrationPct: profile ? String(profile.supplierConcentrationPct) : '',
    customerConcentrationPct: profile ? String(profile.customerConcentrationPct) : '',
    overseasRevenuePct: profile ? String(profile.overseasRevenuePct) : '',
    sensitiveRegionExposurePct: profile ? String(profile.sensitiveRegionExposurePct) : '',
    cashBufferMonths: profile ? String(profile.cashBufferMonths) : '',
    capexFlexibility: profile?.capexFlexibility ?? 'medium',
    inventoryStrategy: profile?.inventoryStrategy ?? 'balanced',
    keyInputs: (profile?.keyInputs ?? []).join(' / '),
    keyRoutes: (profile?.keyRoutes ?? []).join(' / '),
    strategicProjects: (profile?.strategicProjects ?? []).join(' / '),
  };
}

function parseTags(raw: string) {
  return raw
    .split(/[\/,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseNumber(raw: string) {
  const value = Number.parseFloat(raw.trim());
  return Number.isFinite(value) ? value : 0;
}

function hasText(raw: string) {
  return raw.trim().length > 0;
}

function buildDraftWorkspaceSummary(draft: OperatingProfileDraft): DraftWorkspaceSummary {
  const missingFields: string[] = [];
  const recommendedActions: string[] = [];

  const fieldFilled = {
    companyName: hasText(draft.companyName),
    primaryIndustries: hasText(draft.primaryIndustries),
    operatingMode: hasText(draft.operatingMode),
    orderVisibilityMonths: hasText(draft.orderVisibilityMonths),
    capacityUtilizationPct: hasText(draft.capacityUtilizationPct),
    inventoryDays: hasText(draft.inventoryDays),
    cashBufferMonths: hasText(draft.cashBufferMonths),
    supplierConcentrationPct: hasText(draft.supplierConcentrationPct),
    customerConcentrationPct: hasText(draft.customerConcentrationPct),
    overseasRevenuePct: hasText(draft.overseasRevenuePct),
    sensitiveRegionExposurePct: hasText(draft.sensitiveRegionExposurePct),
    capexFlexibility: hasText(draft.capexFlexibility),
    inventoryStrategy: hasText(draft.inventoryStrategy),
    keyInputs: hasText(draft.keyInputs),
    keyRoutes: hasText(draft.keyRoutes),
    strategicProjects: hasText(draft.strategicProjects),
  };

  if (!fieldFilled.companyName) {
    missingFields.push('主体名称');
  }
  if (!fieldFilled.primaryIndustries) {
    missingFields.push('主营行业');
  }
  if (!fieldFilled.orderVisibilityMonths) {
    missingFields.push('订单可见度');
  }
  if (!fieldFilled.capacityUtilizationPct) {
    missingFields.push('产能利用率');
  }
  if (!fieldFilled.inventoryDays) {
    missingFields.push('库存天数');
  }
  if (!fieldFilled.cashBufferMonths) {
    missingFields.push('现金缓冲');
  }
  if (!fieldFilled.supplierConcentrationPct) {
    missingFields.push('供应商集中度');
  }
  if (!fieldFilled.customerConcentrationPct) {
    missingFields.push('客户集中度');
  }
  if (!fieldFilled.keyInputs) {
    missingFields.push('关键原料');
  }
  if (!fieldFilled.keyRoutes) {
    missingFields.push('关键航线/区域');
  }

  if (!fieldFilled.companyName || !fieldFilled.primaryIndustries) {
    recommendedActions.push('先补主体名称和主营行业，让世界引擎能把你放进正确产业链。');
  }
  if (!fieldFilled.orderVisibilityMonths || !fieldFilled.capacityUtilizationPct) {
    recommendedActions.push('先补订单可见度和产能利用率，让经营动作不再只按外部事件猜。');
  }
  if (!fieldFilled.inventoryDays || !fieldFilled.cashBufferMonths) {
    recommendedActions.push('先补库存天数和现金缓冲，系统才能更准判断该囤货还是保守。');
  }
  if (!fieldFilled.supplierConcentrationPct || !fieldFilled.customerConcentrationPct) {
    recommendedActions.push('先补供应商/客户集中度，系统才能更准评估单点依赖风险。');
  }
  if (!fieldFilled.keyInputs || !fieldFilled.keyRoutes) {
    recommendedActions.push('先补关键原料和关键航线，世界引擎才知道哪些地缘事件会先打到你。');
  }
  if (!recommendedActions.length) {
    recommendedActions.push('当前草稿已经可用，继续细化战略项目和区域暴露，能让经营动作更准。');
  }

  const sections: DraftSectionSummary[] = [
    {
      key: 'identity',
      label: '主体与方向',
      completed: [fieldFilled.companyName, fieldFilled.primaryIndustries, fieldFilled.operatingMode].filter(Boolean).length,
      total: 3,
    },
    {
      key: 'operations',
      label: '经营强度',
      completed: [
        fieldFilled.orderVisibilityMonths,
        fieldFilled.capacityUtilizationPct,
        fieldFilled.inventoryDays,
        fieldFilled.cashBufferMonths,
      ].filter(Boolean).length,
      total: 4,
    },
    {
      key: 'exposure',
      label: '风险暴露',
      completed: [
        fieldFilled.supplierConcentrationPct,
        fieldFilled.customerConcentrationPct,
        fieldFilled.overseasRevenuePct,
        fieldFilled.sensitiveRegionExposurePct,
      ].filter(Boolean).length,
      total: 4,
    },
    {
      key: 'dependencies',
      label: '依赖与约束',
      completed: [
        fieldFilled.capexFlexibility,
        fieldFilled.inventoryStrategy,
        fieldFilled.keyInputs,
        fieldFilled.keyRoutes,
        fieldFilled.strategicProjects,
      ].filter(Boolean).length,
      total: 5,
    },
  ];

  const completed = sections.reduce((sum, item) => sum + item.completed, 0);
  const total = sections.reduce((sum, item) => sum + item.total, 0);
  const completenessScore = total > 0 ? Math.round((completed / total) * 100) : 0;
  const completenessLabel =
    completenessScore >= 85 ? '草稿完整' : completenessScore >= 65 ? '草稿可用' : completenessScore >= 40 ? '待补核心参数' : '草稿过弱';

  return {
    completenessScore,
    completenessLabel,
    missingFields,
    recommendedActions: Array.from(new Set(recommendedActions)).slice(0, 5),
    sections,
  };
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  palette,
  multiline = false,
}: {
  label: string;
  value: string;
  onChangeText: (next: string) => void;
  placeholder?: string;
  palette: typeof Colors.light;
  multiline?: boolean;
}) {
  return (
    <View style={styles.fieldBlock}>
      <Text style={[styles.fieldLabel, { color: palette.text }]}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={palette.subtext}
        multiline={multiline}
        style={[
          styles.input,
          multiline && styles.inputMultiline,
          { borderColor: palette.border, color: palette.text, backgroundColor: palette.surfaceMuted },
        ]}
      />
    </View>
  );
}

export default function OperatingProfileScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const [draft, setDraft] = useState<OperatingProfileDraft>(toDraft(null));
  const [baselineDraft, setBaselineDraft] = useState<OperatingProfileDraft>(toDraft(null));
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getOperatingProfile(token ?? undefined),
    [token, apiBaseUrl]
    ,
    { refreshOnFocus: true }
  );

  const isDirty = JSON.stringify(draft) !== JSON.stringify(baselineDraft);
  const draftSummary = buildDraftWorkspaceSummary(draft);

  useEffect(() => {
    if (data) {
      const nextDraft = toDraft(data);
      setDraft(nextDraft);
      setBaselineDraft(nextDraft);
    }
  }, [data]);

  function handleBack() {
    if (!isDirty) {
      router.back();
      return;
    }

    Alert.alert('草稿还没保存', '当前经营画像有未保存修改，离开会丢失本地草稿。', [
      { text: '继续编辑', style: 'cancel' },
      {
        text: '放弃修改',
        style: 'destructive',
        onPress: () => {
          router.back();
        },
      },
    ]);
  }

  function handleResetDraft() {
    setDraft(baselineDraft);
    setSaveMessage(null);
  }

  async function handleSave() {
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const saved = await updateOperatingProfile(
        {
          companyName: draft.companyName.trim(),
          primaryIndustries: parseTags(draft.primaryIndustries),
          operatingMode: draft.operatingMode.trim() || 'balanced',
          orderVisibilityMonths: parseNumber(draft.orderVisibilityMonths),
          capacityUtilizationPct: parseNumber(draft.capacityUtilizationPct),
          inventoryDays: parseNumber(draft.inventoryDays),
          supplierConcentrationPct: parseNumber(draft.supplierConcentrationPct),
          customerConcentrationPct: parseNumber(draft.customerConcentrationPct),
          overseasRevenuePct: parseNumber(draft.overseasRevenuePct),
          sensitiveRegionExposurePct: parseNumber(draft.sensitiveRegionExposurePct),
          cashBufferMonths: parseNumber(draft.cashBufferMonths),
          capexFlexibility: draft.capexFlexibility.trim() || 'medium',
          inventoryStrategy: draft.inventoryStrategy.trim() || 'balanced',
          keyInputs: parseTags(draft.keyInputs),
          keyRoutes: parseTags(draft.keyRoutes),
          strategicProjects: parseTags(draft.strategicProjects),
        },
        token ?? undefined
      );
      const nextDraft = toDraft(saved);
      setDraft(nextDraft);
      setBaselineDraft(nextDraft);
      setSaveMessage(`已更新，生效时间 ${saved.updatedAt ? formatTimestamp(saved.updatedAt) : '刚刚'}`);
      await refresh();
    } catch (saveError) {
      Alert.alert('保存失败', saveError instanceof Error ? saveError.message : '经营画像保存失败');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={handleBack}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回世界引擎</Text>
      </Pressable>

      <SectionHeading title="经营画像" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取经营画像" />

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.cardTitle, { color: palette.text }]}>经营画像</Text>
        <Text style={[styles.cardBody, { color: palette.text }]}>{data?.companyName ?? '经营主体'}</Text>
        <Text style={[styles.cardBody, { color: palette.text }]}>
          {data ? `完整度 ${Math.round(data.completenessScore)} 分 / ${data.freshnessLabel}` : '画像待同步'} / {isDirty ? '未保存' : '已同步'}
        </Text>
        <Text style={[styles.cardBody, { color: palette.subtext }]}>
          {data?.updatedAt ? `最近更新 ${formatTimestamp(data.updatedAt)}` : '保存后系统会自动重算经营画像摘要。'}
        </Text>
        {draftSummary.missingFields.length ? (
          <Text style={[styles.cardBody, { color: palette.warning }]}>
            草稿缺口：{draftSummary.missingFields.slice(0, 3).join(' / ')}
          </Text>
        ) : null}
        <Text style={[styles.cardBody, { color: palette.subtext }]}>
          {draftSummary.recommendedActions[0]}
        </Text>
        {saveMessage ? <Text style={[styles.cardBody, { color: palette.success }]}>{saveMessage}</Text> : null}
        <Field
          label="主体名称"
          value={draft.companyName}
          onChangeText={(companyName) => setDraft((prev) => ({ ...prev, companyName }))}
          palette={palette}
        />
        <Field
          label="主营行业"
          value={draft.primaryIndustries}
          onChangeText={(primaryIndustries) => setDraft((prev) => ({ ...prev, primaryIndustries }))}
          placeholder="例如：能源化工 / 工业软件 / 高端装备"
          palette={palette}
        />
        <View style={styles.grid}>
          <Field
            label="订单可见度(月)"
            value={draft.orderVisibilityMonths}
            onChangeText={(orderVisibilityMonths) => setDraft((prev) => ({ ...prev, orderVisibilityMonths }))}
            palette={palette}
          />
          <Field
            label="产能利用率(%)"
            value={draft.capacityUtilizationPct}
            onChangeText={(capacityUtilizationPct) => setDraft((prev) => ({ ...prev, capacityUtilizationPct }))}
            palette={palette}
          />
          <Field
            label="库存天数"
            value={draft.inventoryDays}
            onChangeText={(inventoryDays) => setDraft((prev) => ({ ...prev, inventoryDays }))}
            palette={palette}
          />
          <Field
            label="现金缓冲(月)"
            value={draft.cashBufferMonths}
            onChangeText={(cashBufferMonths) => setDraft((prev) => ({ ...prev, cashBufferMonths }))}
            palette={palette}
          />
        </View>
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <View style={styles.inlineHeader}>
          <Text style={[styles.cardTitle, { color: palette.text }]}>关键依赖</Text>
          <Pressable
            onPress={() => {
              setShowAdvanced((current) => !current);
            }}
            style={[styles.toggleButton, { borderColor: palette.border, backgroundColor: palette.surfaceMuted }]}>
            <Text style={[styles.toggleButtonText, { color: palette.tint }]}>
              {showAdvanced ? '收起高级' : '展开高级'}
            </Text>
          </Pressable>
        </View>
        <Field
          label="关键原料"
          value={draft.keyInputs}
          onChangeText={(keyInputs) => setDraft((prev) => ({ ...prev, keyInputs }))}
          placeholder="例如：原油 / 乙烯 / GPU / 工控芯片"
          palette={palette}
          multiline
        />
        <Field
          label="关键航线/区域"
          value={draft.keyRoutes}
          onChangeText={(keyRoutes) => setDraft((prev) => ({ ...prev, keyRoutes }))}
          placeholder="例如：中东航线 / 东南亚 / 北美"
          palette={palette}
          multiline
        />
        {showAdvanced ? (
          <>
            <Field
              label="战略项目"
              value={draft.strategicProjects}
              onChangeText={(strategicProjects) => setDraft((prev) => ({ ...prev, strategicProjects }))}
              placeholder="例如：算力中心扩建 / 新产线"
              palette={palette}
              multiline
            />
            <View style={styles.grid}>
              <Field
                label="海外收入占比(%)"
                value={draft.overseasRevenuePct}
                onChangeText={(overseasRevenuePct) => setDraft((prev) => ({ ...prev, overseasRevenuePct }))}
                palette={palette}
              />
              <Field
                label="敏感区域暴露(%)"
                value={draft.sensitiveRegionExposurePct}
                onChangeText={(sensitiveRegionExposurePct) => setDraft((prev) => ({ ...prev, sensitiveRegionExposurePct }))}
                palette={palette}
              />
            </View>
            <Field
              label="CAPEX 弹性"
              value={draft.capexFlexibility}
              onChangeText={(capexFlexibility) => setDraft((prev) => ({ ...prev, capexFlexibility }))}
              placeholder="low / medium / high"
              palette={palette}
            />
            <Field
              label="库存策略"
              value={draft.inventoryStrategy}
              onChangeText={(inventoryStrategy) => setDraft((prev) => ({ ...prev, inventoryStrategy }))}
              placeholder="balanced / just-in-time / safety-stock"
              palette={palette}
            />
            <View style={styles.grid}>
              <Field
                label="供应商集中度(%)"
                value={draft.supplierConcentrationPct}
                onChangeText={(supplierConcentrationPct) => setDraft((prev) => ({ ...prev, supplierConcentrationPct }))}
                palette={palette}
              />
              <Field
                label="客户集中度(%)"
                value={draft.customerConcentrationPct}
                onChangeText={(customerConcentrationPct) => setDraft((prev) => ({ ...prev, customerConcentrationPct }))}
                palette={palette}
              />
            </View>
            <Field
              label="经营模式"
              value={draft.operatingMode}
              onChangeText={(operatingMode) => setDraft((prev) => ({ ...prev, operatingMode }))}
              placeholder="balanced / growth / project-driven"
              palette={palette}
            />
          </>
        ) : null}
      </SurfaceCard>

      <View style={styles.footerActions}>
        <Pressable
          onPress={handleResetDraft}
          disabled={!isDirty || isSaving}
          style={[
            styles.secondaryAction,
            { borderColor: palette.border, opacity: !isDirty || isSaving ? 0.55 : 1 },
          ]}>
          <Text style={[styles.secondaryActionText, { color: palette.text }]}>重置</Text>
        </Pressable>
        <Pressable
          onPress={() => {
            void handleSave();
          }}
          disabled={isSaving || !isDirty}
          style={[styles.primaryAction, { backgroundColor: palette.tint, opacity: isSaving || !isDirty ? 0.7 : 1 }]}>
          {isSaving ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.primaryActionText}>{isDirty ? '保存' : '已同步'}</Text>
          )}
        </Pressable>
      </View>
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
  cardGap: {
    gap: 12,
  },
  inlineHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
  },
  fieldBlock: {
    flex: 1,
    gap: 6,
  },
  fieldLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
  },
  inputMultiline: {
    minHeight: 84,
    textAlignVertical: 'top',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  toggleButton: {
    minHeight: 36,
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  toggleButtonText: {
    fontSize: 12,
    fontWeight: '700',
  },
  footerActions: {
    gap: 10,
  },
  primaryAction: {
    borderRadius: 18,
    paddingHorizontal: 18,
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryActionText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
  secondaryAction: {
    borderRadius: 18,
    borderWidth: 1,
    paddingHorizontal: 18,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryActionText: {
    fontSize: 14,
    fontWeight: '700',
  },
});
