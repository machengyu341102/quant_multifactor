import type { Href } from 'expo-router';

import type { PortfolioActionResult } from '@/types/trading';

type ReceiptSource = 'signal' | 'position';

export interface ActionReceiptData {
  action: string;
  code: string;
  name: string;
  message: string;
  executedAt: string;
  quantity: number;
  executionPrice: number;
  cashBalance: number;
  totalAssets: number;
  realizedProfitLoss: number | null;
  hasActivePosition: boolean;
  source: ReceiptSource;
  signalId: string | null;
  positionCode: string | null;
}

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
}

function parseNumber(value: string, fallback = 0) {
  const numeric = Number.parseFloat(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function buildActionReceiptHref(
  result: PortfolioActionResult,
  options: {
    source: ReceiptSource;
    signalId?: string | null;
    positionCode?: string | null;
  }
): Href {
  return {
    pathname: '/receipt',
    params: {
      action: result.action,
      code: result.code,
      name: result.name,
      message: result.message,
      executedAt: result.executedAt,
      quantity: `${result.quantity}`,
      executionPrice: `${result.executionPrice}`,
      cashBalance: `${result.cashBalance}`,
      totalAssets: `${result.totalAssets}`,
      realizedProfitLoss:
        result.realizedProfitLoss === null ? '' : `${result.realizedProfitLoss}`,
      hasActivePosition: result.position ? '1' : '0',
      source: options.source,
      signalId: options.signalId ?? '',
      positionCode: options.positionCode ?? result.position?.code ?? result.code,
    },
  };
}

export function parseActionReceiptParams(
  params: Record<string, string | string[] | undefined>
): ActionReceiptData {
  const realizedProfitLossValue = firstParam(params.realizedProfitLoss);
  return {
    action: firstParam(params.action),
    code: firstParam(params.code),
    name: firstParam(params.name),
    message: firstParam(params.message),
    executedAt: firstParam(params.executedAt),
    quantity: parseNumber(firstParam(params.quantity)),
    executionPrice: parseNumber(firstParam(params.executionPrice)),
    cashBalance: parseNumber(firstParam(params.cashBalance)),
    totalAssets: parseNumber(firstParam(params.totalAssets)),
    realizedProfitLoss: realizedProfitLossValue ? parseNumber(realizedProfitLossValue) : null,
    hasActivePosition: firstParam(params.hasActivePosition) === '1',
    source: firstParam(params.source) === 'signal' ? 'signal' : 'position',
    signalId: firstParam(params.signalId) || null,
    positionCode: firstParam(params.positionCode) || null,
  };
}

export function actionReceiptTitle(action: string) {
  if (action === 'open') {
    return '开仓回执';
  }
  if (action === 'risk_update') {
    return '风控回执';
  }
  if (action === 'close') {
    return '减仓 / 平仓回执';
  }
  return '动作回执';
}

export function actionReceiptTone(action: string): 'info' | 'warning' | 'success' {
  if (action === 'close') {
    return 'warning';
  }
  if (action === 'risk_update') {
    return 'info';
  }
  return 'success';
}
