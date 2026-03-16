import { StyleSheet, Text, View } from 'react-native';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

interface StatusPillProps {
  label: string;
  tone?: Tone;
}

const tones: Record<Tone, { backgroundColor: string; color: string }> = {
  neutral: { backgroundColor: '#E7EDF4', color: '#0B1728' },
  info: { backgroundColor: '#DCE8FF', color: '#155EEF' },
  success: { backgroundColor: '#DDF5EA', color: '#0E9F6E' },
  warning: { backgroundColor: '#FFF0D6', color: '#B45309' },
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
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
  },
  text: {
    fontSize: 12,
    fontWeight: '700',
  },
});
