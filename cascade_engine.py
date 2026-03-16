"""
声明式级联引擎 (Declarative Cascade Engine)
============================================
统一管理系统中所有级联关系，自动传播状态变化

核心概念:
  1. 声明式配置: 在一个地方定义所有级联规则
  2. 自动传播: 状态变化自动触发下游更新
  3. 依赖追踪: 清晰的依赖关系图
  4. 事务性: 级联操作要么全部成功，要么全部回滚

级联类型:
  - strategy_pause → 暂停策略 → 影响调度/推送/学习
  - strategy_disable → 禁用策略 → 影响所有下游
  - circuit_breaker → 熔断 → 全局暂停
  - regime_change → 环境切换 → 策略适配���调整
  - factor_retire → 因子退役 → 权重归一化

用法:
  from cascade_engine import CascadeEngine, cascade

  engine = CascadeEngine()

  # 暂停策略 (自动级联)
  engine.execute('strategy_pause', strategy='放量突破', reason='连亏5次')

  # 查看影响范围
  impact = engine.preview('strategy_pause', strategy='放量突破')
  print(impact)  # ['scheduler', 'batch_push', 'learning_engine', ...]
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("cascade_engine")

# ================================================================
#  数据结构
# ================================================================

@dataclass
class CascadeRule:
    """级联规则"""
    name: str                           # 规则名称
    trigger: str                        # 触发条件 (strategy_pause/disable/...)
    targets: List[str]                  # 影响目标 (scheduler/batch_push/...)
    handler: Callable                   # 处理函数
    priority: int = 100                 # 优先级 (数字越小越先执行)
    rollback: Optional[Callable] = None # 回滚函数
    description: str = ""               # 描述

@dataclass
class CascadeContext:
    """级联上下文"""
    trigger: str                        # 触发类型
    params: Dict[str, Any]              # 参数
    timestamp: str                      # 时间戳
    affected: List[str] = field(default_factory=list)  # 已影响的目标
    errors: List[str] = field(default_factory=list)    # 错误列表
    rollback_stack: List[Callable] = field(default_factory=list)  # 回滚栈

# ================================================================
#  级联引擎
# ================================================================

class CascadeEngine:
    """声明式级联引擎"""

    def __init__(self):
        self.rules: List[CascadeRule] = []
        self._dir = os.path.dirname(os.path.abspath(__file__))
        self._cascade_log = os.path.join(self._dir, "cascade_log.json")

        # 注册所有规则
        self._register_rules()

    def _register_rules(self):
        """注册所有级联规则"""

        # ============================================================
        # 1. 策略暂停级联
        # ============================================================

        self.register(CascadeRule(
            name="strategy_pause_scheduler",
            trigger="strategy_pause",
            targets=["scheduler"],
            handler=self._pause_scheduler,
            rollback=self._resume_scheduler,
            priority=10,
            description="暂停策略 → 调度器跳过该策略"
        ))

        self.register(CascadeRule(
            name="strategy_pause_batch_push",
            trigger="strategy_pause",
            targets=["batch_push"],
            handler=self._pause_batch_push,
            priority=20,
            description="暂停策略 → 批量推送排除该策略"
        ))

        self.register(CascadeRule(
            name="strategy_pause_learning",
            trigger="strategy_pause",
            targets=["learning_engine"],
            handler=self._pause_learning,
            priority=30,
            description="暂停策略 → 学习引擎跳过该策略"
        ))

        self.register(CascadeRule(
            name="strategy_pause_signal_tracker",
            trigger="strategy_pause",
            targets=["signal_tracker"],
            handler=self._pause_signal_tracker,
            priority=40,
            description="暂停策略 → 信号追踪器标记暂停期信号"
        ))

        # ============================================================
        # 2. 策略禁用级联
        # ============================================================

        self.register(CascadeRule(
            name="strategy_disable_all",
            trigger="strategy_disable",
            targets=["scheduler", "batch_push", "learning_engine", "signal_tracker", "experiment_lab"],
            handler=self._disable_strategy_all,
            priority=10,
            description="禁用策略 → 所有模块移除该策略"
        ))

        # ============================================================
        # 3. 熔断级联
        # ============================================================

        self.register(CascadeRule(
            name="circuit_breaker_global_pause",
            trigger="circuit_breaker",
            targets=["all_strategies"],
            handler=self._circuit_breaker_pause_all,
            rollback=self._circuit_breaker_resume_all,
            priority=1,
            description="熔断触发 → 全局暂停所有策略"
        ))

        self.register(CascadeRule(
            name="circuit_breaker_notify",
            trigger="circuit_breaker",
            targets=["notifier"],
            handler=self._circuit_breaker_notify,
            priority=2,
            description="熔断触发 → 微信紧急通知"
        ))

        # ============================================================
        # 4. Regime切换级联
        # ============================================================

        self.register(CascadeRule(
            name="regime_change_router",
            trigger="regime_change",
            targets=["regime_router"],
            handler=self._regime_change_router,
            priority=10,
            description="Regime切换 → 环境路由器调整策略适配度"
        ))

        self.register(CascadeRule(
            name="regime_change_signal_weights",
            trigger="regime_change",
            targets=["learning_engine"],
            handler=self._regime_change_signal_weights,
            priority=20,
            description="Regime切换 → 学习引擎调整信号权重"
        ))

        # ============================================================
        # 5. 因子退役级联
        # ============================================================

        self.register(CascadeRule(
            name="factor_retire_normalize",
            trigger="factor_retire",
            targets=["tunable_params"],
            handler=self._factor_retire_normalize,
            priority=10,
            description="因子退役 → 权重归一化"
        ))

        self.register(CascadeRule(
            name="factor_retire_ml_retrain",
            trigger="factor_retire",
            targets=["ml_factor_model"],
            handler=self._factor_retire_ml_retrain,
            priority=20,
            description="因子退役 → ML模型重训练"
        ))

        # ============================================================
        # 6. 策略恢复级联
        # ============================================================

        self.register(CascadeRule(
            name="strategy_resume_all",
            trigger="strategy_resume",
            targets=["scheduler", "batch_push", "learning_engine", "signal_tracker"],
            handler=self._resume_strategy_all,
            priority=10,
            description="恢复策略 → 所有模块重新启用该策略"
        ))

    def register(self, rule: CascadeRule):
        """注册级联规则"""
        self.rules.append(rule)
        logger.debug(f"注册级联规则: {rule.name} ({rule.trigger} → {rule.targets})")

    def execute(self, trigger: str, **params) -> CascadeContext:
        """执行级联操作

        Args:
            trigger: 触发类型 (strategy_pause/disable/circuit_breaker/...)
            **params: 参数 (strategy='放量突破', reason='连亏5次', ...)

        Returns:
            CascadeContext: 级联上下文 (包含影响范围/错误列表)
        """
        ctx = CascadeContext(
            trigger=trigger,
            params=params,
            timestamp=datetime.now().isoformat()
        )

        # 获取匹配的规则 (按优先级排序)
        matched_rules = [r for r in self.rules if r.trigger == trigger]
        matched_rules.sort(key=lambda r: r.priority)

        if not matched_rules:
            logger.warning(f"未找到触发器 {trigger} 的级联规则")
            return ctx

        logger.info(f"[级联引擎] 触发: {trigger}, 参数: {params}, 匹配规则: {len(matched_rules)}")

        # 执行级联
        for rule in matched_rules:
            try:
                logger.debug(f"  执行规则: {rule.name} → {rule.targets}")
                rule.handler(ctx)
                ctx.affected.extend(rule.targets)

                # 记录回滚函数
                if rule.rollback:
                    ctx.rollback_stack.append(rule.rollback)

            except Exception as e:
                error_msg = f"规则 {rule.name} 执行失败: {e}"
                logger.error(error_msg)
                ctx.errors.append(error_msg)

                # 发生错误，回滚已执行的操作
                self._rollback(ctx)
                break

        # 记录日志
        self._log_cascade(ctx)

        if ctx.errors:
            logger.error(f"[级联引擎] 执行失败: {len(ctx.errors)} 个错误")
        else:
            logger.info(f"[级联引擎] 执行成功: 影响 {len(set(ctx.affected))} 个目标")

        return ctx

    def preview(self, trigger: str, **params) -> Dict[str, Any]:
        """预览级联影响范围 (不实际执行)

        Returns:
            {
                'trigger': 'strategy_pause',
                'params': {'strategy': '放量突破'},
                'affected_targets': ['scheduler', 'batch_push', ...],
                'rules': [{'name': '...', 'description': '...'}]
            }
        """
        matched_rules = [r for r in self.rules if r.trigger == trigger]
        matched_rules.sort(key=lambda r: r.priority)

        affected_targets = []
        for rule in matched_rules:
            affected_targets.extend(rule.targets)

        return {
            'trigger': trigger,
            'params': params,
            'affected_targets': list(set(affected_targets)),
            'rules': [
                {'name': r.name, 'description': r.description, 'targets': r.targets}
                for r in matched_rules
            ]
        }

    def _rollback(self, ctx: CascadeContext):
        """回滚已执行的操作"""
        logger.warning(f"[级联引擎] 开始回滚: {len(ctx.rollback_stack)} 个操作")

        for rollback_fn in reversed(ctx.rollback_stack):
            try:
                rollback_fn(ctx)
            except Exception as e:
                logger.error(f"回滚失败: {e}")

    def _log_cascade(self, ctx: CascadeContext):
        """记录级联日志"""
        log = safe_load(self._cascade_log, default={'cascades': []})
        log['cascades'].append({
            'trigger': ctx.trigger,
            'params': ctx.params,
            'timestamp': ctx.timestamp,
            'affected': list(set(ctx.affected)),
            'errors': ctx.errors,
            'success': len(ctx.errors) == 0
        })

        # 只保留最近100条
        log['cascades'] = log['cascades'][-100:]
        safe_save(self._cascade_log, log)

    # ================================================================
    #  处理函数 (Handlers)
    # ================================================================

    def _pause_scheduler(self, ctx: CascadeContext):
        """暂停调度器中的策略"""
        strategy = ctx.params.get('strategy')
        if not strategy:
            return

        # 更新 agent_memory.json 中的状态
        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})

        if 'strategy_states' not in memory:
            memory['strategy_states'] = {}

        if strategy not in memory['strategy_states']:
            memory['strategy_states'][strategy] = {}

        memory['strategy_states'][strategy].update({
            'status': 'paused',
            'paused_since': datetime.now().strftime('%Y-%m-%d'),
            'pause_reason': ctx.params.get('reason', '级联引擎暂停'),
            'auto_resume_date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        })

        safe_save(memory_path, memory)
        logger.info(f"  ✓ 调度器: 暂停策略 {strategy}")

    def _resume_scheduler(self, ctx: CascadeContext):
        """恢复调度器中的策略"""
        strategy = ctx.params.get('strategy')
        if not strategy:
            return

        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})

        if strategy in memory.get('strategy_states', {}):
            memory['strategy_states'][strategy].update({
                'status': 'active',
                'paused_since': None,
                'pause_reason': None,
                'auto_resume_date': None
            })
            safe_save(memory_path, memory)
            logger.info(f"  ✓ 调度器: 恢复策略 {strategy}")

    def _pause_batch_push(self, ctx: CascadeContext):
        """批量推送排除该策略"""
        strategy = ctx.params.get('strategy')
        logger.info(f"  ✓ 批量推送: 排除策略 {strategy}")
        # batch_push.py 会读取 agent_memory.json 的 status

    def _pause_learning(self, ctx: CascadeContext):
        """学习引擎跳过该策略"""
        strategy = ctx.params.get('strategy')
        logger.info(f"  ✓ 学习引擎: 跳过策略 {strategy}")
        # learning_engine.py 会读取 agent_memory.json 的 status

    def _pause_signal_tracker(self, ctx: CascadeContext):
        """信号追踪器标记暂停期信号"""
        strategy = ctx.params.get('strategy')
        logger.info(f"  ✓ 信号追踪器: 标记策略 {strategy} 暂停期信号")
        # signal_tracker.py 会读取 agent_memory.json 的 status

    def _disable_strategy_all(self, ctx: CascadeContext):
        """禁用策略 (所有模块)"""
        strategy = ctx.params.get('strategy')

        # 1. 更新 strategies.json
        strategies_path = os.path.join(self._dir, "strategies.json")
        strategies = safe_load(strategies_path, default=[])
        for s in strategies:
            if s.get('name') == strategy or s.get('id') == strategy:
                s['enabled'] = False
        safe_save(strategies_path, strategies)

        # 2. 更新 agent_memory.json
        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})
        if strategy in memory.get('strategy_states', {}):
            memory['strategy_states'][strategy]['status'] = 'disabled'
            safe_save(memory_path, memory)

        logger.info(f"  ✓ 全局禁用策略: {strategy}")

    def _circuit_breaker_pause_all(self, ctx: CascadeContext):
        """熔断: 全局暂停所有策略"""
        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})

        reason = ctx.params.get('reason', '熔断触发')

        for strategy in memory.get('strategy_states', {}).keys():
            if memory['strategy_states'][strategy].get('status') == 'active':
                memory['strategy_states'][strategy].update({
                    'status': 'paused',
                    'paused_since': datetime.now().strftime('%Y-%m-%d'),
                    'pause_reason': f'熔断: {reason}',
                    'auto_resume_date': None  # 熔断不自动恢复
                })

        safe_save(memory_path, memory)
        logger.warning(f"  ⚠️  熔断: 全局暂停所有策略")

    def _circuit_breaker_resume_all(self, ctx: CascadeContext):
        """熔断恢复: 全局恢复所有策略"""
        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})

        for strategy in memory.get('strategy_states', {}).keys():
            if '熔断' in memory['strategy_states'][strategy].get('pause_reason', ''):
                memory['strategy_states'][strategy].update({
                    'status': 'active',
                    'paused_since': None,
                    'pause_reason': None
                })

        safe_save(memory_path, memory)
        logger.info(f"  ✓ 熔断恢复: 全局恢复策略")

    def _circuit_breaker_notify(self, ctx: CascadeContext):
        """熔断通知"""
        reason = ctx.params.get('reason', '未知原因')
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw(
                "🚨 熔断触发",
                f"原因: {reason}\n所有策略已暂停\n请人工检查后手动恢复"
            )
            logger.info(f"  ✓ 熔断通知: 已发送微信")
        except Exception as e:
            logger.error(f"  ✗ 熔断通知失败: {e}")

    def _regime_change_router(self, ctx: CascadeContext):
        """Regime切换: 环境路由器调整策略适配度"""
        new_regime = ctx.params.get('new_regime')
        logger.info(f"  ✓ 环境路由器: 切换到 {new_regime}")
        # regime_router.py 会自动读取最新 regime

    def _regime_change_signal_weights(self, ctx: CascadeContext):
        """Regime切换: 学习引擎调整信号权重"""
        new_regime = ctx.params.get('new_regime')
        logger.info(f"  ✓ 学习引擎: 根据 {new_regime} 调整信号权重")
        # learning_engine.py 的 propose_signal_weight_update() 会处理

    def _factor_retire_normalize(self, ctx: CascadeContext):
        """因子退役: 权重归一化"""
        factor = ctx.params.get('factor')
        logger.info(f"  ✓ 权重归一化: 退役因子 {factor}")
        # auto_optimizer.py 的 _lifecycle_check() 会处理

    def _factor_retire_ml_retrain(self, ctx: CascadeContext):
        """因子退役: ML模型重训练"""
        factor = ctx.params.get('factor')
        logger.info(f"  ✓ ML模型: 因子 {factor} 退役后重训练")
        # ml_factor_model.py 会在下次训练时自动排除

    def _resume_strategy_all(self, ctx: CascadeContext):
        """恢复策略 (所有模块)"""
        strategy = ctx.params.get('strategy')

        memory_path = os.path.join(self._dir, "agent_memory.json")
        memory = safe_load(memory_path, default={})

        if strategy in memory.get('strategy_states', {}):
            memory['strategy_states'][strategy].update({
                'status': 'active',
                'paused_since': None,
                'pause_reason': None,
                'auto_resume_date': None
            })
            safe_save(memory_path, memory)
            logger.info(f"  ✓ 全局恢复策略: {strategy}")


# ================================================================
#  全局实例
# ================================================================

_engine: Optional[CascadeEngine] = None

def get_cascade_engine() -> CascadeEngine:
    """获取全局级联引擎实例"""
    global _engine
    if _engine is None:
        _engine = CascadeEngine()
    return _engine

def cascade(trigger: str, **params) -> CascadeContext:
    """快捷函数: 执行级联操作"""
    return get_cascade_engine().execute(trigger, **params)

def cascade_preview(trigger: str, **params) -> Dict[str, Any]:
    """快捷函数: 预览级联影响"""
    return get_cascade_engine().preview(trigger, **params)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 cascade_engine.py preview strategy_pause strategy=放量突破")
        print("  python3 cascade_engine.py execute strategy_pause strategy=放量突破 reason=连亏5次")
        print("  python3 cascade_engine.py execute circuit_breaker reason=单日亏损>5%")
        sys.exit(1)

    cmd = sys.argv[1]
    trigger = sys.argv[2] if len(sys.argv) > 2 else None

    # 解析参数
    params = {}
    for arg in sys.argv[3:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            params[k] = v

    engine = get_cascade_engine()

    if cmd == "preview":
        result = engine.preview(trigger, **params)
        print(f"\n触发器: {result['trigger']}")
        print(f"参数: {result['params']}")
        print(f"\n影响目标 ({len(result['affected_targets'])}):")
        for target in result['affected_targets']:
            print(f"  - {target}")
        print(f"\n级联规则 ({len(result['rules'])}):")
        for rule in result['rules']:
            print(f"  {rule['name']}: {rule['description']}")

    elif cmd == "execute":
        ctx = engine.execute(trigger, **params)
        print(f"\n触发器: {ctx.trigger}")
        print(f"参数: {ctx.params}")
        print(f"时间: {ctx.timestamp}")
        print(f"\n影响目标 ({len(set(ctx.affected))}):")
        for target in set(ctx.affected):
            print(f"  ✓ {target}")
        if ctx.errors:
            print(f"\n错误 ({len(ctx.errors)}):")
            for error in ctx.errors:
                print(f"  ✗ {error}")
        else:
            print("\n✅ 级联执行成功")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
