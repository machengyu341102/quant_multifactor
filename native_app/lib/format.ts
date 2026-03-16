const cnyFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  maximumFractionDigits: 0,
});

export function formatCurrency(value: number) {
  return cnyFormatter.format(value);
}

export function formatPercent(value: number, digits = 1) {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
}

export function formatTimestamp(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes()
  ).padStart(2, '0')}`;
}
