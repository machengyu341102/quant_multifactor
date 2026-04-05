import { StyleSheet, Text, View } from 'react-native';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

interface StatusPillProps {
  label: string;
  tone?: Tone;
}

const tones: Record<Tone, { backgroundColor: string; color: string }> = {
  neutral: { backgroundColor: '#E7EFEA', color: '#183225' },
  info: { backgroundColor: '#DFF4E7', color: '#14804A' },
  success: { backgroundColor: '#D9F1E2', color: '#157347' },
  warning: { backgroundColor: '#F8EED6', color: '#A16207' },
  danger: { backgroundColor: '#FEE2E2', color: '#B42318' },
};

export function StatusPill({ label, tone = 'neutral' }: StatusPillProps) {
  return (
    <View style={[styles.wrap, { backgroundColor: tones[tone].backgroundColor }]}>
      <Text style={[styles.text, { color: tones[tone].color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  text: {
    fontSize: 11,
    fontWeight: '700',
  },
});
