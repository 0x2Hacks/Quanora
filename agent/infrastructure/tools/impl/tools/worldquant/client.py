"""WorldQuant Brain 平台底层 HTTP 客户端。

参考:
- https://api.worldquantbrain.com/  (Brain 官方 REST API)
- 认证: HTTP Basic -> POST /authentication -> Cookies (t)
- 模拟: POST /simulations -> Location header -> GET <Location> (轮询)
- 数据字段: GET /data-fields?delay=1&region=USA&universe=TOP3000&dataset.id=...
- 算子: GET /operators
- 我的因子: GET /users/self/alphas
- 提交: POST /alphas/{id}/submit

线程安全:本客户端**非**线程安全。多并发请使用多实例或外加锁。
认证 Cookie 会在 4 小时左右过期,客户端会自动检测 401/403 并重登。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import urllib3
from requests.auth import HTTPBasicAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BRAIN_BASE_URL = "https://api.worldquantbrain.com"
DEFAULT_TIMEOUT = 60
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_POLL_MAX_SECONDS = 600  # 单次模拟最长等待 10 分钟


class WQAuthError(RuntimeError):
    """认证失败。"""


class WQRateLimitError(RuntimeError):
    """触发了平台速率限制。"""


class WQAPIError(RuntimeError):
    """通用 API 错误。"""


@dataclass(slots=True)
class WQCredentials:
    """凭证封装。优先级:显式 > 环境变量 > credential.txt。"""

    email: str = ""
    password: str = ""

    @classmethod
    def resolve(cls, email: str | None = None, password: str | None = None) -> "WQCredentials":
        if email and password:
            return cls(email=email, password=password)
        env_email = os.getenv("WQ_BRAIN_EMAIL", "").strip()
        env_pwd = os.getenv("WQ_BRAIN_PASSWORD", "").strip()
        if env_email and env_pwd:
            return cls(email=env_email, password=env_pwd)
        # 尝试读取 ./credential.txt(兼容 worldquant-miner 项目格式)
        candidates = [Path("./credential.txt"), Path("./wq_credential.txt")]
        for candidate in candidates:
            if candidate.exists():
                try:
                    text = candidate.read_text(encoding="utf-8").strip()
                    data = json.loads(text)
                    if isinstance(data, list) and len(data) == 2:
                        return cls(email=str(data[0]), password=str(data[1]))
                except Exception:
                    continue
        raise WQAuthError(
            "无法解析 WorldQuant Brain 凭证。请设置 WQ_BRAIN_EMAIL / WQ_BRAIN_PASSWORD 环境变量,"
            "或在工作目录放置 credential.txt(格式: [\"email\",\"password\"])"
        )


@dataclass(slots=True)
class SimulationSettings:
    """模拟参数 (一组合理的默认值,对应 Brain 平台主流 USA TOP3000 配置)。"""

    instrument_type: str = "EQUITY"
    region: str = "USA"
    universe: str = "TOP3000"
    delay: int = 1
    decay: int = 0
    neutralization: str = "INDUSTRY"
    truncation: float = 0.08
    pasteurization: str = "ON"
    unit_handling: str = "VERIFY"
    nan_handling: str = "OFF"
    language: str = "FASTEXPR"
    visualization: bool = False
    test_period: str = "P0Y"  # 默认 In-sample 全周期回测

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrumentType": self.instrument_type,
            "region": self.region,
            "universe": self.universe,
            "delay": self.delay,
            "decay": self.decay,
            "neutralization": self.neutralization,
            "truncation": self.truncation,
            "pasteurization": self.pasteurization,
            "unitHandling": self.unit_handling,
            "nanHandling": self.nan_handling,
            "language": self.language,
            "visualization": self.visualization,
            "testPeriod": self.test_period,
        }


class WQBrainClient:
    """WorldQuant Brain 平台 REST API 客户端。"""

    def __init__(
        self,
        credentials: WQCredentials | None = None,
        base_url: str = BRAIN_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        verify_ssl: bool = True,
    ) -> None:
        self._credentials = credentials or WQCredentials.resolve()
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._verify = verify_ssl
        self._session = requests.Session()
        self._authed = False
        self._last_login_ts: float = 0.0

    # ──────────────────────────────────────────────────────────────────
    # 认证
    # ──────────────────────────────────────────────────────────────────
    def login(self) -> dict[str, Any]:
        """完成 HTTP Basic 认证,设置会话 Cookie。"""
        self._session.auth = HTTPBasicAuth(self._credentials.email, self._credentials.password)
        resp = self._session.post(
            f"{self._base}/authentication",
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code in (200, 201):
            self._authed = True
            self._last_login_ts = time.time()
            try:
                payload = resp.json()
            except Exception:
                payload = {"status": resp.status_code}
            return {"ok": True, "user": payload}
        if resp.status_code in (401, 403):
            raise WQAuthError(
                f"认证失败 ({resp.status_code}): 请检查 Brain 邮箱/密码。响应: {resp.text[:300]}"
            )
        raise WQAPIError(f"登录异常 ({resp.status_code}): {resp.text[:300]}")

    def ensure_logged_in(self) -> None:
        # 简单的"两小时强制续认证"。Brain 实际 Cookie ~ 4h。
        if not self._authed or (time.time() - self._last_login_ts) > 2 * 3600:
            self.login()

    # ──────────────────────────────────────────────────────────────────
    # 元数据查询
    # ──────────────────────────────────────────────────────────────────
    def list_operators(self) -> list[dict[str, Any]]:
        self.ensure_logged_in()
        resp = self._session.get(f"{self._base}/operators", timeout=self._timeout, verify=self._verify)
        if resp.status_code == 200:
            return resp.json()
        raise WQAPIError(f"list_operators 失败 ({resp.status_code}): {resp.text[:300]}")

    def list_data_fields(
        self,
        region: str = "USA",
        universe: str = "TOP3000",
        delay: int = 1,
        dataset_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_logged_in()
        params: dict[str, Any] = {
            "region": region,
            "universe": universe,
            "delay": delay,
            "limit": limit,
            "offset": offset,
            "instrumentType": "EQUITY",
        }
        if dataset_id:
            params["dataset.id"] = dataset_id
        if search:
            params["search"] = search
        resp = self._session.get(
            f"{self._base}/data-fields",
            params=params,
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code == 200:
            return resp.json()
        raise WQAPIError(f"list_data_fields 失败 ({resp.status_code}): {resp.text[:300]}")

    # ──────────────────────────────────────────────────────────────────
    # 模拟(回测)
    # ──────────────────────────────────────────────────────────────────
    def simulate(
        self,
        expression: str,
        settings: SimulationSettings | None = None,
        wait: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_wait_seconds: int = DEFAULT_POLL_MAX_SECONDS,
    ) -> dict[str, Any]:
        """提交单条 alpha 模拟。

        返回:
            wait=True:  {"ok": True, "alpha_id": "...", "is": {...}, "checks": [...]}
            wait=False: {"ok": True, "progress_url": "<Location>"}
        """
        self.ensure_logged_in()
        settings = settings or SimulationSettings()
        body = {
            "type": "REGULAR",
            "settings": settings.to_dict(),
            "regular": expression,
        }
        resp = self._session.post(
            f"{self._base}/simulations",
            json=body,
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code == 429:
            raise WQRateLimitError("simulate 触发速率限制 (429)。建议降低并发或加 sleep。")
        if resp.status_code in (401, 403):
            self._authed = False
            self.ensure_logged_in()
            return self.simulate(expression, settings, wait, poll_interval, max_wait_seconds)
        if resp.status_code not in (200, 201):
            raise WQAPIError(f"simulate 提交失败 ({resp.status_code}): {resp.text[:500]}")
        progress_url = resp.headers.get("Location")
        if not progress_url:
            raise WQAPIError(f"simulate 响应缺少 Location: {resp.text[:300]}")
        if not wait:
            return {"ok": True, "progress_url": progress_url}
        return self._poll_simulation(progress_url, poll_interval, max_wait_seconds)

    def _poll_simulation(
        self,
        progress_url: str,
        poll_interval: float,
        max_wait_seconds: int,
    ) -> dict[str, Any]:
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            self.ensure_logged_in()
            resp = self._session.get(progress_url, timeout=self._timeout, verify=self._verify)
            if resp.status_code in (401, 403):
                self._authed = False
                continue
            if resp.status_code not in (200, 201):
                raise WQAPIError(f"轮询失败 ({resp.status_code}): {resp.text[:300]}")
            # Brain 在进行中时会返回 Retry-After header,完成后 body 包含 alpha 与 IS 指标
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    sleep_for = float(retry_after)
                except ValueError:
                    sleep_for = poll_interval
                time.sleep(max(sleep_for, 1.0))
                continue
            data = resp.json() if resp.text else {}
            alpha_id = data.get("alpha")
            status = data.get("status")
            if alpha_id:
                # 拉取完整 alpha 详情
                detail = self.get_alpha(alpha_id)
                return {
                    "ok": True,
                    "alpha_id": alpha_id,
                    "status": status,
                    "is": detail.get("is", {}),
                    "checks": detail.get("is", {}).get("checks", []),
                    "detail": detail,
                }
            if status in ("ERROR", "FAILED"):
                return {
                    "ok": False,
                    "status": status,
                    "message": data.get("message", "Simulation failed"),
                    "raw": data,
                }
            time.sleep(poll_interval)
        return {"ok": False, "status": "TIMEOUT", "message": f"轮询超时 ({max_wait_seconds}s)"}

    # ──────────────────────────────────────────────────────────────────
    # Alpha 详情/提交
    # ──────────────────────────────────────────────────────────────────
    def get_alpha(self, alpha_id: str) -> dict[str, Any]:
        self.ensure_logged_in()
        resp = self._session.get(
            f"{self._base}/alphas/{alpha_id}",
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code == 200:
            return resp.json()
        raise WQAPIError(f"get_alpha 失败 ({resp.status_code}): {resp.text[:300]}")

    def list_my_alphas(self, limit: int = 50, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        self.ensure_logged_in()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        resp = self._session.get(
            f"{self._base}/users/self/alphas",
            params=params,
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code == 200:
            return resp.json()
        raise WQAPIError(f"list_my_alphas 失败 ({resp.status_code}): {resp.text[:300]}")

    def submit_alpha(self, alpha_id: str) -> dict[str, Any]:
        """提交 alpha 到 Brain 比赛(Pre-Consultant/Consultant 每天有提交配额限制)。"""
        self.ensure_logged_in()
        resp = self._session.post(
            f"{self._base}/alphas/{alpha_id}/submit",
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code in (200, 201, 202):
            try:
                return {"ok": True, "result": resp.json()}
            except Exception:
                return {"ok": True, "result": {"status": resp.status_code}}
        if resp.status_code == 403:
            return {"ok": False, "error": "RATE_LIMIT_OR_FAILED_CHECK", "detail": resp.text[:300]}
        raise WQAPIError(f"submit_alpha 失败 ({resp.status_code}): {resp.text[:300]}")

    def check_correlation(self, alpha_id: str) -> dict[str, Any]:
        """获取 alpha 与现有库的自相关性(平台已经在 IS checks 里返回过,这里做显式查询)。"""
        self.ensure_logged_in()
        resp = self._session.get(
            f"{self._base}/alphas/{alpha_id}/correlations/self",
            timeout=self._timeout,
            verify=self._verify,
        )
        if resp.status_code == 200:
            return resp.json()
        # 部分账户没有此权限,容错降级
        return {"warning": f"correlation 接口不可用 ({resp.status_code})", "raw": resp.text[:200]}


# ──────────────────────────────────────────────────────────────────────
# 全局单例(避免每个工具都重新登录)
# ──────────────────────────────────────────────────────────────────────
_GLOBAL_CLIENT: WQBrainClient | None = None


def get_global_client() -> WQBrainClient:
    global _GLOBAL_CLIENT
    if _GLOBAL_CLIENT is None:
        _GLOBAL_CLIENT = WQBrainClient()
        _GLOBAL_CLIENT.login()
    return _GLOBAL_CLIENT


def reset_global_client() -> None:
    global _GLOBAL_CLIENT
    _GLOBAL_CLIENT = None
