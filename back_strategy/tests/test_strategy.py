"""
庄币启动前捕捉策略 — 单元测试

覆盖:
1. 信号评分计算 (S1-S7)
2. 进场时机判断 (T1-T3)
3. 风控规则 (止盈/止损/信号止损)
4. 配置加载
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import (
    DataSource, FetchedData, Provenance, SignalName,
    CompositeScore, SignalScore, Position, PositionAction,
    RiskAction, TimingType, TimingSignal,
)
from src.config_loader import Settings, CoinConfig
from src.utils import normalize_symbol, compute_pct_change, safe_float
from src.signals.s1_circulating_ratio import CirculatingRatioSignal
from src.signals.s2_futures_expectation import FuturesExpectationSignal
from src.signals.s3_volume_ratio import VolumeRatioSignal
from src.signals.s4_oi_surge import OISurgeSignal
from src.signals.s5_negative_funding import NegativeFundingSignal
from src.signals.s6_spot_accumulation import SpotAccumulationSignal
from src.signals.s7_social_hype import SocialHypeSignal
from src.signals.signal_engine import SignalEngine
from src.timing.t1_pre_futures import PreFuturesTiming
from src.timing.t2_oi_funding_extreme import OIFundingExtremeTiming
from src.timing.t3_breakout_confirmation import BreakoutConfirmationTiming
from src.risk.take_profit import TakeProfitManager
from src.risk.stop_loss import StopLossManager
from src.risk.signal_exit import SignalExitManager
from src.risk.risk_engine import RiskEngine


# ============================================================
# 测试辅助函数
# ============================================================

def make_fetched_data(df, symbol="TEST", source=DataSource.COINGECKO):
    """创建测试用 FetchedData"""
    prov = Provenance(source=source, symbol=symbol, rows=len(df), fetched_at=datetime.now(timezone.utc))
    return FetchedData(df=df, provenance=prov)


def make_market_data(circulating=1000000, total=10000000, max_supply=10000000, fdv=5000000, mcap=500000):
    """创建CoinGecko市场数据"""
    df = pd.DataFrame([{
        "coin_id": "testcoin",
        "symbol": "TEST",
        "current_price_usd": 0.5,
        "market_cap_usd": mcap,
        "fully_diluted_valuation_usd": fdv,
        "circulating_supply": circulating,
        "total_supply": total,
        "max_supply": max_supply,
    }])
    return make_fetched_data(df, symbol="testcoin", source=DataSource.COINGECKO)


def make_klines(n=100, base_price=1.0, base_volume=1000, trend=0.0):
    """创建K线测试数据"""
    dates = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    prices = [base_price * (1 + trend * i / n) for i in range(n)]
    df = pd.DataFrame({
        "open_time": dates,
        "close_time": dates + pd.Timedelta(hours=1),
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [base_volume * (1 + 0.1 * (i % 10)) for i in range(n)],
        "quote_volume": [base_volume * p for p, i in zip(prices, range(n))],
    })
    return make_fetched_data(df, source=DataSource.BINANCE_SPOT)


# ============================================================
# S1: 超低流通率信号测试
# ============================================================

class TestCirculatingRatioSignal:
    def setup_method(self):
        self.signal = CirculatingRatioSignal()

    def test_excellent(self):
        """流通率8% → 满分25"""
        result = self.signal.score(0.08)
        assert result.score == 25
        assert result.threshold_hit == "excellent"

    def test_good(self):
        """流通率30% → 18分"""
        result = self.signal.score(0.30)
        assert result.score == 18
        assert result.threshold_hit == "good"

    def test_moderate(self):
        """流通率45% → 10分"""
        result = self.signal.score(0.45)
        assert result.score == 10
        assert result.threshold_hit == "moderate"

    def test_poor(self):
        """流通率55% → 5分"""
        result = self.signal.score(0.55)
        assert result.score == 5
        assert result.threshold_hit == "poor"

    def test_none(self):
        """无数据 → 0分"""
        result = self.signal.score(None)
        assert result.score == 0

    def test_from_data(self):
        """从市场数据计算"""
        data = make_market_data(circulating=800000, max_supply=10000000)
        result = self.signal.score_from_data(data)
        assert result.score == 25  # 8%流通率 → excellent

    def test_lab_case(self):
        """LAB案例: 8%流通率 → 25分"""
        result = self.signal.score(0.08)
        assert result.score == 25


# ============================================================
# S2: 合约上线预期信号测试
# ============================================================

class TestFuturesExpectationSignal:
    def setup_method(self):
        self.signal = FuturesExpectationSignal()

    def test_futures_announced(self):
        """合约已官宣 → 20分"""
        result = self.signal.score(is_futures_announced=True)
        assert result.score == 20
        assert result.threshold_hit == "futures_announced"

    def test_alpha_listed(self):
        """Alpha区上线 → 12分"""
        result = self.signal.score(is_alpha_listed=True)
        assert result.score == 12

    def test_pattern_match(self):
        """路径匹配 → 最多8分"""
        result = self.signal.score(pattern_match_score=6)
        assert result.score == 6
        assert result.threshold_hit == "similar_pattern"

    def test_no_signal(self):
        """无信号 → 0分"""
        result = self.signal.score()
        assert result.score == 0


# ============================================================
# S3: 合约/现货交易量比测试
# ============================================================

class TestVolumeRatioSignal:
    def setup_method(self):
        self.signal = VolumeRatioSignal()

    def test_extreme(self):
        """比率6x → 15分"""
        result = self.signal.score(6.0)
        assert result.score == 15
        assert result.threshold_hit == "extreme"

    def test_high(self):
        """比率4x → 10分"""
        result = self.signal.score(4.0)
        assert result.score == 10

    def test_from_data(self):
        """从K线数据计算"""
        spot = make_klines(n=100, base_volume=1000)
        futures = make_klines(n=100, base_volume=5000)
        result = self.signal.score_from_data(spot, futures)
        assert result.raw_value > 1.0  # 合约量应该大于现货


# ============================================================
# S4: OI快速累积测试
# ============================================================

class TestOISurgeSignal:
    def setup_method(self):
        self.signal = OISurgeSignal()

    def test_extreme(self):
        """OI增幅120% → 15分"""
        result = self.signal.score(2.2)  # 当前/过去=2.2 → 增幅120%
        assert result.score == 15
        assert result.threshold_hit == "extreme"

    def test_high(self):
        """OI增幅60% → 10分"""
        result = self.signal.score(1.6)
        assert result.score == 10

    def test_from_data(self):
        """从OI历史数据计算"""
        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=30, freq="D", tz="UTC"),
            "sumOpenInterestValue": [1000 * (1 + 0.05 * i) for i in range(30)],
        })
        data = make_fetched_data(df, source=DataSource.BINANCE_FUTURES)
        result = self.signal.score_from_data(data)
        assert result.raw_value > 1.0  # OI在增长


# ============================================================
# S5: 资金费率测试
# ============================================================

class TestNegativeFundingSignal:
    def setup_method(self):
        self.signal = NegativeFundingSignal()

    def test_extreme(self):
        """费率-0.06%连续3期 → 10分"""
        result = self.signal.score(-0.0006, consecutive_negative=3)
        assert result.score == 10
        assert result.threshold_hit == "extreme"

    def test_high(self):
        """费率-0.04%连续2期 → 7分"""
        result = self.signal.score(-0.0004, consecutive_negative=2)
        assert result.score == 7

    def test_positive_rate(self):
        """正费率 → 0分"""
        result = self.signal.score(0.0001, consecutive_negative=0)
        assert result.score == 0

    def test_from_data(self):
        """从费率历史计算"""
        df = pd.DataFrame({
            "fundingRate": [0.0001, -0.0003, -0.0005, -0.0006, -0.0007],
            "fundingTime": pd.date_range("2025-01-01", periods=5, freq="8h", tz="UTC"),
        })
        data = make_fetched_data(df, source=DataSource.BINANCE_FUTURES)
        result = self.signal.score_from_data(data)
        assert result.score > 0  # 连续负费率


# ============================================================
# S6: 现货吸筹测试
# ============================================================

class TestSpotAccumulationSignal:
    def setup_method(self):
        self.signal = SpotAccumulationSignal()

    def test_extreme(self):
        """量比4x → 10分"""
        result = self.signal.score(4.0)
        assert result.score == 10

    def test_from_data(self):
        """从K线数据计算量比"""
        # 构造后期放量数据
        df = pd.DataFrame({
            "open_time": pd.date_range("2025-01-01", periods=100, freq="h", tz="UTC"),
            "close_time": pd.date_range("2025-01-01", periods=100, freq="h", tz="UTC") + pd.Timedelta(hours=1),
            "volume": [100] * 66 + [400] * 34,  # 后1/3放量4x
            "close": [1.0] * 100,
            "high": [1.01] * 100,
            "low": [0.99] * 100,
            "open": [1.0] * 100,
            "quote_volume": [100] * 100,
        })
        data = make_fetched_data(df, source=DataSource.BINANCE_SPOT)
        result = self.signal.score_from_data(data)
        assert result.raw_value > 1.5


# ============================================================
# S7: 社交异动测试
# ============================================================

class TestSocialHypeSignal:
    def setup_method(self):
        self.signal = SocialHypeSignal()

    def test_extreme(self):
        """6x → 5分"""
        result = self.signal.score(6.0)
        assert result.score == 5

    def test_no_data(self):
        """无数据 → 0分"""
        result = self.score = self.signal.score(None)
        assert result.score == 0


# ============================================================
# 进场时机测试
# ============================================================

class TestPreFuturesTiming:
    def setup_method(self):
        self.timing = PreFuturesTiming()

    def _make_composite(self, total=70, s1_raw=0.08, s2_hit="futures_announced"):
        scores = [
            SignalScore(SignalName.S1_CIRCULATING_RATIO, 25, s1_raw, 25 if s1_raw < 0.2 else 10, "excellent", ""),
            SignalScore(SignalName.S2_FUTURES_EXPECTATION, 20, {}, 20 if s2_hit == "futures_announced" else 0, s2_hit, ""),
            SignalScore(SignalName.S3_VOLUME_RATIO, 15, 4.0, 10, "high", ""),
            SignalScore(SignalName.S4_OI_SURGE, 15, 2.0, 15, "extreme", ""),
            SignalScore(SignalName.S5_NEGATIVE_FUNDING, 10, -0.0006, 10, "extreme", ""),
            SignalScore(SignalName.S6_SPOT_ACCUMULATION, 10, 3.0, 10, "extreme", ""),
            SignalScore(SignalName.S7_SOCIAL_HYPE, 5, 4.0, 3, "high", ""),
        ]
        # 调整总分
        actual_total = sum(s.score for s in scores)
        return CompositeScore(symbol="TEST", scores=scores, total_score=actual_total)

    def test_trigger(self):
        """满足所有条件 → 触发"""
        composite = self._make_composite()
        result = self.timing.check("TEST", composite)
        assert result.triggered

    def test_low_score(self):
        """总分不足 → 不触发"""
        composite = self._make_composite()
        composite = CompositeScore(symbol="TEST", scores=composite.scores, total_score=40)
        result = self.timing.check("TEST", composite)
        assert not result.triggered

    def test_high_circulating(self):
        """流通率过高 → 不触发"""
        composite = self._make_composite(s1_raw=0.50)
        # 需要重建评分
        result = self.timing.check("TEST", composite)
        # 流通率50% > 40%上限，不应触发
        assert not result.triggered


class TestOIFundingExtremeTiming:
    def setup_method(self):
        self.timing = OIFundingExtremeTiming()

    def test_trigger(self):
        """OI暴增+费率极端 → 触发"""
        scores = [
            SignalScore(SignalName.S1_CIRCULATING_RATIO, 25, 0.08, 25, "excellent", ""),
            SignalScore(SignalName.S2_FUTURES_EXPECTATION, 20, {}, 12, "alpha_zone_listed", ""),
            SignalScore(SignalName.S3_VOLUME_RATIO, 15, 5.0, 15, "extreme", ""),
            SignalScore(SignalName.S4_OI_SURGE, 15, 2.5, 15, "extreme", ""),  # OI增150%
            SignalScore(SignalName.S5_NEGATIVE_FUNDING, 10, {"funding_rate": -0.0006, "consecutive_negative": 3}, 10, "extreme", ""),
            SignalScore(SignalName.S6_SPOT_ACCUMULATION, 10, 3.0, 10, "extreme", ""),
            SignalScore(SignalName.S7_SOCIAL_HYPE, 5, 4.0, 3, "high", ""),
        ]
        composite = CompositeScore(symbol="TEST", scores=scores, total_score=90)
        result = self.timing.check("TEST", composite)
        assert result.triggered


# ============================================================
# 风控测试
# ============================================================

class TestStopLoss:
    def setup_method(self):
        self.manager = StopLossManager()

    def test_red_line_1(self):
        """亏损15% → 触发"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=0.85,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos)
        assert result is not None
        assert result.action == PositionAction.FULL_EXIT
        assert result.urgency == "critical"

    def test_no_trigger(self):
        """亏损5% → 不触发"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=0.95,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos)
        assert result is None


class TestTakeProfit:
    def setup_method(self):
        self.manager = TakeProfitManager()

    def test_level_1(self):
        """盈利50% → Level1止盈"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=1.50,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos)
        assert result is not None
        assert result.action == PositionAction.PARTIAL_EXIT
        assert result.quantity == 30  # 100 * 0.30

    def test_level_2(self):
        """盈利150% → Level2止盈"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=2.50,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos)
        assert result is not None


class TestSignalExit:
    def setup_method(self):
        self.manager = SignalExitManager()

    def test_funding_turns_positive(self):
        """费率转正 → 立即离场"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=1.5,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos, funding_rate=0.0002)
        assert result is not None
        assert result.action == PositionAction.FULL_EXIT
        assert "费率转正" in result.reason

    def test_oi_drops(self):
        """OI骤降 → 立即离场"""
        pos = Position(
            symbol="TEST", entry_price=1.0, current_price=1.5,
            quantity=100, entry_time=datetime.now(timezone.utc),
            timing_type=TimingType.T1_PRE_FUTURES, composite_score_at_entry=70,
        )
        result = self.manager.check(pos, oi_current=600, oi_peak=1000)
        assert result is not None
        assert "OI骤降" in result.reason


# ============================================================
# 工具函数测试
# ============================================================

class TestUtils:
    def test_normalize_symbol(self):
        assert normalize_symbol("BTCUSDT") == "BTC"
        assert normalize_symbol("ETH") == "ETH"
        assert normalize_symbol("labusdt") == "LAB"

    def test_compute_pct_change(self):
        assert compute_pct_change(150, 100) == 0.5
        assert compute_pct_change(50, 100) == -0.5
        assert compute_pct_change(100, 0) == 0.0

    def test_safe_float(self):
        assert safe_float("1.5") == 1.5
        assert safe_float(None) == 0.0
        assert safe_float("abc", default=-1) == -1.0


# ============================================================
# 配置加载测试
# ============================================================

class TestConfig:
    def test_settings_load(self):
        """配置文件可加载"""
        settings = Settings()
        assert settings.scan is not None
        assert settings.signals is not None
        assert settings.timing is not None
        assert settings.risk is not None

    def test_settings_get(self):
        """点号路径访问"""
        settings = Settings()
        url = settings.get("data_sources.binance.base_url")
        assert url is not None
        assert "binance" in url.lower()

    def test_coin_config(self):
        """币种配置加载"""
        config = CoinConfig()
        assert config.is_blacklisted("SIREN")
        assert config.is_blacklisted("LAB")
        assert not config.is_blacklisted("BTC")


# ============================================================
# LAB案例验证
# ============================================================

class TestLABCase:
    """LAB案例回测验证 — 与文档数据对照"""

    def test_lab_score_85(self):
        """
        LAB案例: 流通率8% + Alpha上线 + 合约预期 + OI暴增 + 费率极端负
        期望总分 ≈ 85/100
        """
        s1 = CirculatingRatioSignal()
        s2 = FuturesExpectationSignal()
        s3 = VolumeRatioSignal()
        s4 = OISurgeSignal()
        s5 = NegativeFundingSignal()
        s6 = SpotAccumulationSignal()
        s7 = SocialHypeSignal()

        # LAB数据 (文档中描述)
        r1 = s1.score(0.08)          # 流通率8% → 25
        r2 = s2.score(is_alpha_listed=True, is_futures_announced=True, pattern_match_score=8)  # 合约官宣 → 20
        r3 = s3.score(4.5)           # 合约/现货=4.5x → 10
        r4 = s4.score(2.0)           # OI增100% → 15
        r5 = s5.score(-0.0008, consecutive_negative=4)  # -0.08%连续4期 → 10
        r6 = s6.score(3.5)           # 现货3.5x → 10
        r7 = s7.score(5.0)           # 社交5x → 5

        total = r1.score + r2.score + r3.score + r4.score + r5.score + r6.score + r7.score
        
        # 预期约85分
        assert total >= 80, f"LAB案例总分{total}低于80，预期≥80"
        assert total <= 100, f"LAB案例总分{total}超过100"

        # 各信号验证
        assert r1.score == 25, f"S1流通率: {r1.score}, 预期25"
        assert r2.score == 20, f"S2合约预期: {r2.score}, 预期20"
        assert r4.score == 15, f"S4 OI: {r4.score}, 预期15"
        assert r5.score == 10, f"S5费率: {r5.score}, 预期10"

        print(f"\nLAB案例总分: {total}/100")
        for r in [r1, r2, r3, r4, r5, r6, r7]:
            print(f"  {r.signal_name.value}: {r.score}/{r.weight} {r.description}")

    def test_lab_timing_trigger(self):
        """LAB案例应触发T1和T2时机"""
        scores = [
            SignalScore(SignalName.S1_CIRCULATING_RATIO, 25, 0.08, 25, "excellent", ""),
            SignalScore(SignalName.S2_FUTURES_EXPECTATION, 20, {}, 20, "futures_announced", ""),
            SignalScore(SignalName.S3_VOLUME_RATIO, 15, 4.5, 10, "high", ""),
            SignalScore(SignalName.S4_OI_SURGE, 15, 2.0, 15, "extreme", ""),
            SignalScore(SignalName.S5_NEGATIVE_FUNDING, 10, {"funding_rate": -0.0008, "consecutive_negative": 4}, 10, "extreme", ""),
            SignalScore(SignalName.S6_SPOT_ACCUMULATION, 10, 3.5, 10, "extreme", ""),
            SignalScore(SignalName.S7_SOCIAL_HYPE, 5, 5.0, 5, "extreme", ""),
        ]
        composite = CompositeScore(symbol="LAB", scores=scores, total_score=95)

        t1 = PreFuturesTiming()
        t2 = OIFundingExtremeTiming()

        r1 = t1.check("LAB", composite)
        r2 = t2.check("LAB", composite)

        assert r1.triggered, f"T1未触发: {r1.reason}"
        assert r2.triggered, f"T2未触发: {r2.reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
