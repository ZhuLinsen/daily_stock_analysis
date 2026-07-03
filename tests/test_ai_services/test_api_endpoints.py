# -*- coding: utf-8 -*-
"""AI 服务 API 端点冒烟测试（独立测试，直接导入模块避免包链加载）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 直接加载 ai_services 端点模块，避免触发 api.v1 包链
_spec = importlib.util.spec_from_file_location(
    "ai_services_endpoint",
    Path(__file__).parent.parent.parent / "api" / "v1" / "endpoints" / "ai_services.py",
)
assert _spec is not None, "无法找到 ai_services.py 模块"
_ai_svc_mod = importlib.util.module_from_spec(_spec)
sys.modules["ai_services_endpoint"] = _ai_svc_mod
_spec.loader.exec_module(_ai_svc_mod)  # type: ignore[union-attr]

from fastapi import FastAPI
from fastapi.testclient import TestClient

router = _ai_svc_mod.router
# 创建仅包含 ai_services 路由的最小测试应用
app = FastAPI()
app.include_router(router, prefix="/api/v1/ai-services")

client = TestClient(app)


class TestAIServicesAPI:
    """AI 服务 API 端点冒烟测试。"""

    def test_list_services(self) -> None:
        resp = client.get("/api/v1/ai-services/services")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        names = [s["name"] for s in data]
        assert "deepseek" in names
        assert "hongdie" in names

        # 验证红蝶AI 官网链接
        hongdie = [s for s in data if s["name"] == "hongdie"][0]
        assert hongdie["homepage"] == "https://tokento.vip"
        assert hongdie["default_base_url"] == "https://tokento.vip/v1"

    def test_list_models(self) -> None:
        resp = client.get("/api/v1/ai-services/models")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        models_by_service = {m["service"]: m["models"] for m in data}
        assert "deepseek" in models_by_service
        assert "hongdie" in models_by_service
        assert len(models_by_service["deepseek"]) >= 3
        assert len(models_by_service["hongdie"]) >= 3

    def test_test_connection_invalid_service(self) -> None:
        resp = client.post(
            "/api/v1/ai-services/test",
            json={"service_name": "invalid", "api_key": "sk-test"},
        )
        assert resp.status_code == 400

    def test_test_connection_deepseek_missing_key(self) -> None:
        resp = client.post(
            "/api/v1/ai-services/test",
            json={"service_name": "deepseek", "api_key": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["service"] == "deepseek"

    def test_test_connection_hongdie_missing_key(self) -> None:
        resp = client.post(
            "/api/v1/ai-services/test",
            json={"service_name": "hongdie", "api_key": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["service"] == "hongdie"

    def test_generate_invalid_service(self) -> None:
        resp = client.post(
            "/api/v1/ai-services/generate",
            json={"service_name": "invalid", "api_key": "sk-test", "prompt": "Hi"},
        )
        assert resp.status_code == 400

    def test_generate_with_empty_key(self) -> None:
        """空 API Key 应返回失败响应。"""
        resp = client.post(
            "/api/v1/ai-services/generate",
            json={"service_name": "deepseek", "api_key": "", "prompt": "Hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["service"] == "deepseek"

    def test_generate_with_params(self) -> None:
        """验证 full params 能正确传递给后端。"""
        resp = client.post(
            "/api/v1/ai-services/generate",
            json={
                "service_name": "deepseek",
                "api_key": "sk-test-key",
                "prompt": "Hello",
                "system_prompt": "Be helpful",
                "model": "deepseek-chat",
                "temperature": 0.5,
                "max_tokens": 100,
                "base_url": "https://api.deepseek.com",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False  # 空 Key 会触发认证失败
        assert data["service"] == "deepseek"
        assert data["model"] == "deepseek-chat"
        assert data["elapsed_ms"] > 0
