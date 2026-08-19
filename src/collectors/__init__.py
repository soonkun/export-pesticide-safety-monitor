"""소스별 독립 Collector 모듈 (§7). 국가 추가 시 collector만 추가한다."""
from .rda import RdaCollector
from .eu import EuCollector
from .codex import CodexCollector
from .japan import JapanCollector
from .canada import CanadaCollector
from .hongkong import HongKongCollector
from .indonesia import IndonesiaCollector
from .taiwan import TaiwanCollector
from .watch import AustraliaWatchCollector, ChinaWatchCollector
from .usa import UsaCollector
from .wto_eping import WtoCollector

ALL_COLLECTORS = [RdaCollector, EuCollector, CodexCollector, JapanCollector,
                  TaiwanCollector, UsaCollector, HongKongCollector, CanadaCollector,
                  IndonesiaCollector,
                  ChinaWatchCollector, AustraliaWatchCollector, WtoCollector]
