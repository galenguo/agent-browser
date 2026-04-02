"""适配器生成器 — 从探索产物生成 YAML 适配器"""
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

from .explorer import ExplorationResult, Endpoint

logger = logging.getLogger(__name__)

# 字段到 JS 选择器的映射提示
_FIELD_TEMPLATES = {
    "title": "item.querySelector('h1, h2, h3, .title')?.textContent?.trim() || ''",
    "url": "item.querySelector('a')?.href || ''",
    "author": "item.querySelector('.author, .user')?.textContent?.trim() || ''",
    "score": "item.querySelector('.score, .hot, .rank')?.textContent?.trim() || ''",
    "description": "item.querySelector('.desc, .summary, .abstract, p')?.textContent?.trim() || ''",
    "image": "item.querySelector('img')?.src || ''",
    "time": "item.querySelector('time, .date')?.textContent?.trim() || ''",
    "id": "item.dataset?.id || item.id?.toString() || ''",
}


def synthesize(
    site: str,
    exploration: ExplorationResult,
    command_name: str = "list",
    adapter_dir: Optional[str] = None,
) -> dict:
    """
    从探索产物生成适配器 YAML 配置。

    根据策略选择不同的 pipeline 模板:
      - public API → fetch → select → map → limit
      - cookie 站点 → navigate → evaluate → map → limit
      - Pinia Store → navigate → tap → map → limit

    Args:
        site: 站点名
        exploration: 探索结果
        command_name: 命令名（默认 "list"）
        adapter_dir: 适配器保存目录

    Returns:
        生成的适配器配置 dict
    """
    # 选择最佳能力
    if not exploration.capabilities:
        # 无 API 端点发现 → 使用 DOM 抓取策略
        adapter = _generate_dom_adapter(site, command_name, exploration)
    else:
        # 有 API 端点 → 选择最佳策略
        best = exploration.capabilities[0]
        strategy = best.get("strategy_guess", "cookie")

        if strategy == "public":
            adapter = _generate_fetch_adapter(site, command_name, best, exploration)
        else:
            adapter = _generate_cookie_adapter(site, command_name, best, exploration)

    # 添加隐匿性配置
    adapter["stealth"] = {
        "warmup": True,
        "human_click": True,
        "human_type": True,
        "request_delay": [0.5, 2.0],
        "scroll_before": True,
        "jitter": True,
    }

    # 保存到文件
    if adapter_dir:
        os.makedirs(adapter_dir, exist_ok=True)
        filepath = os.path.join(adapter_dir, f"{command_name}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(adapter, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Generated adapter: {filepath}")

    return adapter


def _generate_fetch_adapter(
    site: str, name: str, cap: dict, exploration: ExplorationResult
) -> dict:
    """公共 API 策略: fetch → map → limit"""
    fields = cap.get("fields", {})
    columns = list(fields.keys())

    # 构建 map 表达式
    map_expr = {}
    for target, source_key in fields.items():
        map_expr[target] = f"${{ item.{source_key} }}"

    return {
        "site": site,
        "name": name,
        "description": f"自动生成: {site} {name}（公共 API）",
        "strategy": "public",
        "browser": False,
        "args": {
            "limit": {
                "type": "int",
                "default": 10,
                "description": "返回结果数",
            }
        },
        "columns": columns,
        "pipeline": [
            {"fetch": {"url": cap["endpoint"], "method": cap.get("method", "GET"), "browser": False}},
            {"select": {"path": "data"}},
            {"map": map_expr},
            {"limit": "${{ args.limit }}"},
        ],
    }


def _generate_cookie_adapter(
    site: str, name: str, cap: dict, exploration: ExplorationResult
) -> dict:
    """Cookie 站点策略: navigate → evaluate(fetch) → map → limit"""
    fields = cap.get("fields", {})
    columns = list(fields.keys())

    # 在浏览器内 fetch（保持 cookie）
    map_expr = {}
    for target, source_key in fields.items():
        map_expr[target] = f"${{ item.{source_key} }}"

    return {
        "site": site,
        "name": name,
        "description": f"自动生成: {site} {name}（Cookie 模式）",
        "strategy": "cookie",
        "browser": True,
        "args": {
            "limit": {
                "type": "int",
                "default": 10,
                "description": "返回结果数",
            }
        },
        "columns": columns,
        "pipeline": [
            {"navigate": exploration.url},
            {
                "evaluate": f"""
                (() => {{
                    const resp = await fetch('{cap["endpoint"]}', {{credentials: 'include'}});
                    const data = await resp.json();
                    return data.data || data.result || data.items || data.list || [data];
                }})()
                """
            },
            {"map": map_expr},
            {"limit": "${{ args.limit }}"},
        ],
    }


def _generate_dom_adapter(
    site: str, name: str, exploration: ExplorationResult
) -> dict:
    """DOM 抓取策略: navigate → wait → evaluate → limit"""
    parsed = urlparse(exploration.url)

    return {
        "site": site,
        "name": name,
        "description": f"自动生成: {site} {name}（DOM 抓取）",
        "strategy": "ui",
        "browser": True,
        "args": {
            "limit": {
                "type": "int",
                "default": 10,
                "description": "返回结果数",
            }
        },
        "columns": ["title", "url", "text"],
        "pipeline": [
            {"navigate": exploration.url},
            {"wait": {"seconds": 3}},
            {
                "evaluate": """
                (() => {
                    const items = [];
                    document.querySelectorAll('article, .item, .card, li').forEach(el => {
                        const titleEl = el.querySelector('h1, h2, h3, h4, .title');
                        const linkEl = el.querySelector('a');
                        items.push({
                            title: titleEl ? titleEl.textContent.trim() : '',
                            url: linkEl ? linkEl.href : '',
                            text: el.textContent.trim().substring(0, 100)
                        });
                    });
                    return items;
                })()
                """
            },
            {"limit": "${{ args.limit }}"},
        ],
    }
