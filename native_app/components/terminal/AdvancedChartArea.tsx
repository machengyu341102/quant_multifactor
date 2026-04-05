import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useState } from 'react';

import { terminalTheme } from '@/constants/terminal-theme';
import type { ChartType, DataState, DrawToolKey, IndicatorKey, TerminalChartSeries, TerminalSymbol, UtilityToolKey } from '@/mocks/terminal-data';

const GRID_ROWS = 5;
const GRID_COLS = 6;
const VOLUME_HEIGHT = 92;
const CHART_PADDING = 24;
const TOOLTIP_INDEX = 18;

interface AdvancedChartAreaProps {
  symbol: TerminalSymbol;
  series: TerminalChartSeries;
  chartType: ChartType;
  indicators: IndicatorKey[];
  drawTool: DrawToolKey;
  utilityTools: UtilityToolKey[];
  dataState: DataState;
  height: number;
}

export function AdvancedChartArea({
  symbol,
  series,
  chartType,
  indicators,
  drawTool,
  utilityTools,
  dataState,
  height,
}: AdvancedChartAreaProps) {
  const [chartWidth, setChartWidth] = useState(0);
  const [crosshairVisible, setCrosshairVisible] = useState(false);
  const crosshairEnabled = utilityTools.includes('crosshair');

  if (dataState === 'loading') {
    return <ChartState label="正在同步图表数据…" height={height} />;
  }

  if (dataState === 'empty') {
    return <ChartState label="当前品种没有图表数据。" height={height} />;
  }

  if (dataState === 'error') {
    return <ChartState label="图表数据暂时不可用。" height={height} tone="error" />;
  }

  const candleCount = series.candles.length;
  const contentWidth = Math.max(320, chartWidth || 920);
  const chartHeight = height - VOLUME_HEIGHT - CHART_PADDING * 2;
  const minLow = Math.min(...series.candles.map((item) => item.low));
  const maxHigh = Math.max(...series.candles.map((item) => item.high));
  const range = Math.max(1, maxHigh - minLow);
  const stepX = candleCount > 1 ? (contentWidth - CHART_PADDING * 2) / (candleCount - 1) : 1;
  const tooltipIndex = Math.min(candleCount - 1, TOOLTIP_INDEX);
  const tooltipCandle = series.candles[tooltipIndex];

  const priceToY = (value: number) =>
    CHART_PADDING + (1 - (value - minLow) / range) * chartHeight;

  const linePoints = series.candles.map((candle, index) => ({
    x: CHART_PADDING + stepX * index,
    y: priceToY(candle.close),
  }));

  return (
    <View style={[styles.shell, { height }]}>
      <View style={styles.indicatorOverlay}>
        <Text style={styles.overlayTitle}>{symbol.code}</Text>
        <Text style={styles.overlayMeta}>
          {indicators.join(' · ')} {drawTool ? `· 绘图 ${drawTool}` : ''}
        </Text>
      </View>

      <Pressable
        onHoverIn={() => setCrosshairVisible(true)}
        onHoverOut={() => setCrosshairVisible(false)}
        onPressIn={() => setCrosshairVisible(true)}
        onPressOut={() => setCrosshairVisible(false)}
        onLayout={(event) => setChartWidth(event.nativeEvent.layout.width)}
        style={styles.chartArea}>
        <View style={styles.grid}>
          {Array.from({ length: GRID_ROWS }).map((_, row) => (
            <View
              key={`row-${row}`}
              style={[styles.gridRow, { top: CHART_PADDING + (chartHeight / GRID_ROWS) * row }]}
            />
          ))}
          {Array.from({ length: GRID_COLS }).map((_, col) => (
            <View
              key={`col-${col}`}
              style={[styles.gridCol, { left: CHART_PADDING + ((contentWidth - CHART_PADDING * 2) / GRID_COLS) * col }]}
            />
          ))}
        </View>

        {chartType === 'candles' ? (
          <View style={styles.seriesLayer}>
            {series.candles.map((candle, index) => {
              const x = CHART_PADDING + stepX * index;
              const wickTop = priceToY(candle.high);
              const wickBottom = priceToY(candle.low);
              const bodyTop = priceToY(Math.max(candle.open, candle.close));
              const bodyBottom = priceToY(Math.min(candle.open, candle.close));
              const positive = candle.close >= candle.open;
              return (
                <View key={`${candle.time}-candle`}>
                  <View
                    style={[
                      styles.wick,
                      {
                        left: x - 0.5,
                        top: wickTop,
                        height: Math.max(8, wickBottom - wickTop),
                        backgroundColor: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell,
                      },
                    ]}
                  />
                  <View
                    style={[
                      styles.body,
                      {
                        left: x - 4,
                        top: bodyTop,
                        height: Math.max(4, bodyBottom - bodyTop),
                        backgroundColor: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell,
                      },
                    ]}
                  />
                </View>
              );
            })}
          </View>
        ) : (
          <View style={styles.seriesLayer}>
            {linePoints.map((point, index) => {
              const next = linePoints[index + 1];
              return (
                <View key={`line-${index}`}>
                  {chartType === 'area' ? (
                    <View
                      style={[
                        styles.areaColumn,
                        {
                          left: point.x - 4,
                          top: point.y,
                          height: CHART_PADDING + chartHeight - point.y,
                        },
                      ]}
                    />
                  ) : null}
                  {next ? (
                    <Segment
                      from={point}
                      to={next}
                      color={terminalTheme.colors.accent}
                    />
                  ) : null}
                  <View style={[styles.dot, { left: point.x - 2, top: point.y - 2 }]} />
                </View>
              );
            })}
          </View>
        )}

        {indicators.includes('MA') ? (
          <OverlayLine values={series.ma} stepX={stepX} priceToY={priceToY} color={terminalTheme.colors.warning} />
        ) : null}
        {indicators.includes('EMA') ? (
          <OverlayLine values={series.ema} stepX={stepX} priceToY={priceToY} color={terminalTheme.colors.accent} />
        ) : null}

        {series.buyMarkers.map((marker) => (
          <Marker
            key={`${marker.label}-${marker.index}`}
            x={CHART_PADDING + stepX * marker.index}
            y={priceToY(marker.price)}
            label={marker.label}
            side="buy"
          />
        ))}
        {series.sellMarkers.map((marker) => (
          <Marker
            key={`${marker.label}-${marker.index}`}
            x={CHART_PADDING + stepX * marker.index}
            y={priceToY(marker.price)}
            label={marker.label}
            side="sell"
          />
        ))}

        <DrawOverlay drawTool={drawTool} width={contentWidth} chartHeight={chartHeight} />

        {crosshairEnabled && crosshairVisible ? (
          <>
            <View style={[styles.crosshairVertical, { left: linePoints[tooltipIndex]?.x ?? contentWidth / 2 }]} />
            <View style={[styles.crosshairHorizontal, { top: linePoints[tooltipIndex]?.y ?? height / 2 }]} />
            <View style={[styles.tooltip, { left: Math.max(CHART_PADDING, (linePoints[tooltipIndex]?.x ?? 0) - 64) }]}>
              <Text style={styles.tooltipText}>
                {tooltipCandle.time} · {tooltipCandle.close.toFixed(2)}
              </Text>
            </View>
          </>
        ) : null}

        <View style={styles.priceScale}>
          {Array.from({ length: GRID_ROWS + 1 }).map((_, index) => {
            const value = maxHigh - (range / GRID_ROWS) * index;
            return (
              <Text key={`price-${index}`} style={styles.scaleText}>
                {value.toLocaleString('en-US', { maximumFractionDigits: value > 100 ? 2 : 4 })}
              </Text>
            );
          })}
        </View>

        <View style={styles.volumeArea}>
          {series.candles.map((candle, index) => {
            const x = CHART_PADDING + stepX * index;
            const barHeight = Math.max(10, (candle.volume / Math.max(...series.candles.map((item) => item.volume))) * (VOLUME_HEIGHT - 32));
            const positive = candle.close >= candle.open;
            return (
              <View
                key={`${candle.time}-vol`}
                style={[
                  styles.volumeBar,
                  {
                    left: x - 4,
                    height: barHeight,
                    backgroundColor: positive ? terminalTheme.colors.buySoft : terminalTheme.colors.sellSoft,
                  },
                ]}
              />
            );
          })}
        </View>

        <View style={styles.timeScale}>
          {series.candles.filter((_, index) => index % 7 === 0 || index === candleCount - 1).map((candle) => (
            <Text key={`time-${candle.time}`} style={styles.timeText}>
              {candle.time}
            </Text>
          ))}
        </View>
      </Pressable>
    </View>
  );
}

function Segment({
  from,
  to,
  color,
}: {
  from: { x: number; y: number };
  to: { x: number; y: number };
  color: string;
}) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = `${(Math.atan2(dy, dx) * 180) / Math.PI}deg`;
  const midX = (from.x + to.x) / 2 - length / 2;
  const midY = (from.y + to.y) / 2 - 1;

  return (
    <View
      style={[
        styles.segment,
        {
          left: midX,
          top: midY,
          width: length,
          backgroundColor: color,
          transform: [{ rotate: angle }],
        },
      ]}
    />
  );
}

function OverlayLine({
  values,
  stepX,
  priceToY,
  color,
}: {
  values: number[];
  stepX: number;
  priceToY: (value: number) => number;
  color: string;
}) {
  return (
    <View style={styles.seriesLayer}>
      {values.slice(0, -1).map((value, index) => (
        <Segment
          key={`${color}-${index}`}
          from={{ x: CHART_PADDING + stepX * index, y: priceToY(value) }}
          to={{ x: CHART_PADDING + stepX * (index + 1), y: priceToY(values[index + 1] ?? value) }}
          color={color}
        />
      ))}
    </View>
  );
}

function Marker({
  x,
  y,
  label,
  side,
}: {
  x: number;
  y: number;
  label: string;
  side: 'buy' | 'sell';
}) {
  const color = side === 'buy' ? terminalTheme.colors.buy : terminalTheme.colors.sell;
  return (
    <View
      style={[
        styles.marker,
        {
          left: x - 14,
          top: side === 'buy' ? y + 6 : y - 28,
          backgroundColor: side === 'buy' ? terminalTheme.colors.buySoft : terminalTheme.colors.sellSoft,
          borderColor: color,
        },
      ]}>
      <Text style={[styles.markerText, { color }]}>{label}</Text>
    </View>
  );
}

function DrawOverlay({
  drawTool,
  width,
  chartHeight,
}: {
  drawTool: DrawToolKey;
  width: number;
  chartHeight: number;
}) {
  if (drawTool === 'horizontal') {
    return <View style={[styles.horizontalGuide, { top: CHART_PADDING + chartHeight * 0.42, width: width - CHART_PADDING * 2 }]} />;
  }

  if (drawTool === 'fibonacci') {
    return (
      <View style={styles.seriesLayer}>
        {[0.236, 0.382, 0.5, 0.618, 0.786].map((ratio) => (
          <View
            key={`fib-${ratio}`}
            style={[
              styles.fibLine,
              { top: CHART_PADDING + chartHeight * ratio, width: width - CHART_PADDING * 2 },
            ]}
          />
        ))}
      </View>
    );
  }

  if (drawTool === 'note') {
    return (
      <View style={[styles.noteBox, { left: CHART_PADDING + width * 0.55, top: CHART_PADDING + chartHeight * 0.18 }]}>
        <Text style={styles.noteText}>事件关注区</Text>
      </View>
    );
  }

  return (
    <View
      style={[
        styles.trendLine,
        {
          left: CHART_PADDING + 40,
          top: CHART_PADDING + chartHeight * 0.62,
          width: width * 0.38,
        },
      ]}
    />
  );
}

function ChartState({
  label,
  height,
  tone = 'neutral',
}: {
  label: string;
  height: number;
  tone?: 'neutral' | 'error';
}) {
  return (
    <View style={[styles.shell, { height, alignItems: 'center', justifyContent: 'center' }]}>
      <View style={styles.stateCard}>
        <Text style={[styles.stateText, tone === 'error' && styles.stateError]}>{label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.md,
    backgroundColor: terminalTheme.colors.chartBg,
    overflow: 'hidden',
    position: 'relative',
  },
  indicatorOverlay: {
    position: 'absolute',
    zIndex: 4,
    top: 12,
    left: 12,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.chartOverlay,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    gap: 4,
  },
  overlayTitle: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  overlayMeta: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    fontFamily: terminalTheme.fonts.mono,
  },
  chartArea: {
    flex: 1,
  },
  grid: {
    ...StyleSheet.absoluteFillObject,
  },
  gridRow: {
    position: 'absolute',
    left: CHART_PADDING,
    right: 64,
    height: 1,
    backgroundColor: terminalTheme.colors.grid,
  },
  gridCol: {
    position: 'absolute',
    top: CHART_PADDING,
    bottom: VOLUME_HEIGHT + 28,
    width: 1,
    backgroundColor: terminalTheme.colors.grid,
  },
  seriesLayer: {
    ...StyleSheet.absoluteFillObject,
  },
  wick: {
    position: 'absolute',
    width: 1,
  },
  body: {
    position: 'absolute',
    width: 8,
    borderRadius: 2,
  },
  dot: {
    position: 'absolute',
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: terminalTheme.colors.accent,
  },
  segment: {
    position: 'absolute',
    height: 2,
    borderRadius: 2,
  },
  areaColumn: {
    position: 'absolute',
    width: 8,
    backgroundColor: 'rgba(59,130,246,0.10)',
  },
  marker: {
    position: 'absolute',
    minWidth: 28,
    minHeight: 18,
    paddingHorizontal: 6,
    borderRadius: terminalTheme.radius.xs,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markerText: {
    fontSize: 10,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  trendLine: {
    position: 'absolute',
    height: 2,
    backgroundColor: terminalTheme.colors.accent,
    transform: [{ rotate: '-18deg' }],
  },
  horizontalGuide: {
    position: 'absolute',
    left: CHART_PADDING,
    height: 1,
    backgroundColor: terminalTheme.colors.warning,
    borderStyle: 'dashed',
  },
  fibLine: {
    position: 'absolute',
    left: CHART_PADDING,
    height: 1,
    backgroundColor: 'rgba(240,185,11,0.45)',
  },
  noteBox: {
    position: 'absolute',
    minWidth: 90,
    minHeight: 36,
    paddingHorizontal: 10,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.warning,
    backgroundColor: terminalTheme.colors.warningSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noteText: {
    color: terminalTheme.colors.warning,
    fontSize: 11,
    fontWeight: '700',
  },
  crosshairVertical: {
    position: 'absolute',
    top: CHART_PADDING,
    bottom: VOLUME_HEIGHT + 28,
    width: 1,
    backgroundColor: 'rgba(229,237,245,0.28)',
  },
  crosshairHorizontal: {
    position: 'absolute',
    left: CHART_PADDING,
    right: 64,
    height: 1,
    backgroundColor: 'rgba(229,237,245,0.28)',
  },
  tooltip: {
    position: 'absolute',
    top: 52,
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.panel,
    borderWidth: 1,
    borderColor: terminalTheme.colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tooltipText: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.mono,
  },
  priceScale: {
    position: 'absolute',
    top: CHART_PADDING - 6,
    right: 10,
    bottom: VOLUME_HEIGHT + 18,
    justifyContent: 'space-between',
    alignItems: 'flex-end',
  },
  scaleText: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    fontFamily: terminalTheme.fonts.mono,
  },
  volumeArea: {
    position: 'absolute',
    left: 0,
    right: 56,
    bottom: 26,
    height: VOLUME_HEIGHT,
  },
  volumeBar: {
    position: 'absolute',
    bottom: 0,
    width: 8,
    borderTopLeftRadius: 3,
    borderTopRightRadius: 3,
  },
  timeScale: {
    position: 'absolute',
    left: CHART_PADDING,
    right: 64,
    bottom: 8,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  timeText: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    fontFamily: terminalTheme.fonts.mono,
  },
  stateCard: {
    minWidth: 260,
    minHeight: 120,
    borderRadius: terminalTheme.radius.md,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  stateText: {
    color: terminalTheme.colors.subtext,
    fontSize: 13,
    textAlign: 'center',
  },
  stateError: {
    color: terminalTheme.colors.sell,
  },
});
