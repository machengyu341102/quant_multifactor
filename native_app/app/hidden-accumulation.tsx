import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getHiddenAccumulationOpportunities } from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function HiddenAccumulationScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    () => getHiddenAccumulationOpportunities(token ?? undefined, 6),
    [token, apiBaseUrl],
    { refreshOnFocus: true }
  );

  const opportunities = data ?? [];
  const top = opportunities[0] ?? null;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回</Text>
      </Pressable>

      <SectionHeading title="隐蔽吸筹" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取吸筹机会" />

      {data ? (
        <>
          <SurfaceCard style={styles.cardGap}>
            <Text style={[styles.cardTitle, { color: palette.text }]}>
              {top ? `${top.code} ${top.name}` : '当前没有命中的小阳吸筹票'}
            </Text>
            <Text style={[styles.cardBody, { color: palette.subtext }]}>
              {top
                ? `${top.marketPhaseLabel} 下，连续 ${top.streakDays} 天小阳，盘整宽度 ${top.consolidationWidthPct.toFixed(2)}%，最近累计 ${top.streakGainPct.toFixed(2)}%。`
                : '当前市场没有筛出满足条件的弱市隐蔽吸筹票。'}
            </Text>
            {top ? (
              <>
                <Text style={[styles.tipText, { color: palette.text }]}>{top.thesis}</Text>
                <Text style={[styles.tipText, { color: palette.subtext }]}>动作：{top.action}</Text>
              </>
            ) : null}
            {top ? (
              <Text style={[styles.tipText, { color: palette.text }]}>连阳 {top.streakDays} 天</Text>
            ) : null}
          </SurfaceCard>

          <SurfaceCard style={styles.cardGap}>
            {opportunities.slice(0, 1).map((item) => (
              <View
                key={item.id}
                style={[
                  styles.itemRow,
                  {
                    borderBottomColor: palette.border,
                    backgroundColor: item.id === top?.id ? palette.accentSoft : 'transparent',
                    borderColor: item.id === top?.id ? palette.tint : 'transparent',
                  },
                ]}>
                <View style={styles.itemMain}>
                  <Text style={[styles.itemTitle, { color: palette.text }]}>
                    {item.code} {item.name}
                  </Text>
                  <Text style={[styles.itemBody, { color: palette.subtext }]}>
                    连续 {item.streakDays} 天小阳 / 流通 {item.floatMvYi.toFixed(1)} 亿 / 盘整宽度 {item.consolidationWidthPct.toFixed(2)}%
                  </Text>
                  <Text style={[styles.itemBody, { color: palette.text }]}>{item.action}</Text>
                </View>
                <Text style={[styles.itemBody, { color: palette.subtext }]}>{Math.round(item.accumulationScore)} 分</Text>
              </View>
            ))}
            {!opportunities.length ? (
              <Text style={[styles.cardBody, { color: palette.subtext }]}>当前没有满足硬条件的候选。</Text>
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
  cardGap: {
    gap: 12,
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  cardBody: {
    fontSize: 14,
    lineHeight: 21,
  },
  sectionLabel: {
    display: 'none',
  },
  tipText: {
    fontSize: 13,
    lineHeight: 20,
  },
  itemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingHorizontal: 12,
    paddingTop: 12,
    paddingBottom: 12,
    marginBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderWidth: 1,
    borderRadius: 14,
  },
  itemMain: {
    flex: 1,
    gap: 4,
  },
  itemTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  itemBody: {
    fontSize: 13,
    lineHeight: 19,
  },
});
