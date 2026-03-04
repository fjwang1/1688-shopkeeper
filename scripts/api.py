#!/usr/bin/env python3
"""
1688 API 封装模块 - 核心接口

提供三个原子能力：
1. search_products - 商品搜索
2. list_bound_shops - 查询绑定店铺
3. publish_items - 铺货

认证：自动从 ALI_1688_AK 环境变量获取并签名
"""

import json
import os
import time
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from functools import wraps

import requests
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import get_auth_headers

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('1688_api')

BASE_URL = "https://ainextpre.1688.com"
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1


@dataclass
class Product:
    """商品信息"""
    id: str
    title: str
    price: str
    image: str
    url: str
    shop_name: str = ""


@dataclass
class Shop:
    """店铺信息"""
    code: str
    name: str
    channel: str
    is_authorized: bool


@dataclass
class PublishResult:
    """铺货结果"""
    success: bool
    published_count: int
    failed_items: List[Dict[str, Any]]


def with_retry(max_retries: int = MAX_RETRIES):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    last_exception = e
                    delay = min(RETRY_DELAY_BASE * (2 ** attempt), 10)
                    logger.warning(f"请求失败(尝试{attempt+1}/{max_retries}): {e}, {delay}s后重试")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            return {"success": False, "error": f"请求失败（已重试{max_retries}次）: {last_exception}"}
        return wrapper
    return decorator


@with_retry()
def search_products(query: str, channel: str = "douyin", max_results: int = 10) -> List[Product]:
    """
    搜索商品
    
    Args:
        query: 搜索关键词
        channel: 下游渠道 (taobao/douyin/pinduoduo/xiaohongshu)
        max_results: 最大返回数量 (1-50)
    
    Returns:
        Product对象列表
    """
    url = f"{BASE_URL}/1688claw/skill/searchoffer"
    body = json.dumps({
        "query": query,
        "channel": channel,
        "count": str(min(max_results, 50))
    })
    
    headers = get_auth_headers("POST", "/1688claw/skill/searchoffer", body)
    if not headers:
        logger.error("AK未配置 - 请通过以下方式配置:\n"
                    "1. 设置环境变量: export ALI_1688_AK=your_ak\n"
                    "2. 或在 ~/.openclaw/openclaw.json 中添加 env.ALI_1688_AK\n"
                    "3. 重启 Gateway 使配置生效")
        return []
    
    try:
        response = requests.post(url, headers=headers, data=body, timeout=30)
        response.raise_for_status()
        result = response.json()

        if not result.get("success"):
            logger.error(f"API返回错误: {result.get('error', '未知错误')}")
            return []
        
        # 解析商品列表（Map结构：{id: {title, price, image}, ...}）
        data = result.get("data", {})
        products = []
        for item_id, item in data.items():
            products.append(Product(
                id=item_id,
                title=item.get("title") or "未知商品",
                price=str(item.get("price") or "-"),
                image=item.get("image") or "",
                url=f"https://detail.1688.com/offer/{item_id}.html",
                shop_name=""
            ))
        
        logger.info(f"搜索成功: {query}, 返回 {len(products)} 个商品")
        return products
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"搜索失败 - HTTP错误 {e.response.status_code}: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"搜索失败 - 网络错误: {e}")
        return []
    except (KeyError, TypeError) as e:
        logger.error(f"搜索失败 - 数据解析错误: {e}")
        return []


@with_retry()
def list_bound_shops() -> List[Shop]:
    """
    查询已绑定的店铺列表
    
    Returns:
        Shop对象列表
    """
    url = f"{BASE_URL}/1688claw/skill/searchshop"
    body = "{}"
    
    headers = get_auth_headers("POST", "/1688claw/skill/searchshop", body)
    if not headers:
        logger.error("AK未配置")
        return []
    
    try:
        response = requests.post(url, headers=headers, data=body, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if isinstance(result, dict) and "data" in result:
            shops_data = result["data"]
        elif isinstance(result, list):
            shops_data = result[0] if len(result) > 0 and isinstance(result[0], list) else result
        else:
            shops_data = []
        
        shops = []
        for s in shops_data:
            tool_expired = s.get("toolExpired", False)
            shop_expired = s.get("shopExpired", False)
            shops.append(Shop(
                code=s.get("shopCode", ""),
                name=s.get("shopName", "未知店铺"),
                channel=s.get("channelDesc") or s.get("channel", "未知平台"),
                is_authorized=not (tool_expired or shop_expired)
            ))
        
        logger.info(f"查询店铺成功: {len(shops)} 个")
        return shops
        
    except Exception as e:
        logger.error(f"查询店铺失败: {e}")
        return []


@with_retry()
def publish_items(item_ids: List[str], shop_code: str) -> PublishResult:
    """
    铺货到指定店铺
    
    Args:
        item_ids: 商品ID列表
        shop_code: 店铺代码
    
    Returns:
        PublishResult对象
    """
    url = f"{BASE_URL}/1688claw/skill/distributingoffer"
    
    # 查询店铺信息获取渠道
    shops = list_bound_shops()
    target_shop = next((s for s in shops if s.code == shop_code), None)
    if not target_shop:
        return PublishResult(success=False, published_count=0, failed_items=[{"error": "店铺不存在"}])
    
    channel_map = {
        "淘宝": "taobao",
        "抖店": "douyin",
        "拼多多": "pinduoduo",
        "小红书": "xiaohongshu"
    }
    channel = channel_map.get(target_shop.channel, "douyin")
    
    body = json.dumps({
        "itemList": ",".join(item_ids[:50]),  # 限制50个
        "channel": channel,
        "shopCode": shop_code
    })
    
    headers = get_auth_headers("POST", "/1688claw/skill/distributingoffer", body)
    if not headers:
        return PublishResult(success=False, published_count=0, failed_items=[{"error": "AK未配置"}])
    
    try:
        response = requests.post(url, headers=headers, data=body, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        # 解析结果
        success = result.get("success", False) or result.get("code") == 200
        
        return PublishResult(
            success=success,
            published_count=len(item_ids) if success else 0,
            failed_items=[] if success else [{"error": result.get("error", "未知错误")}]
        )
        
    except Exception as e:
        logger.error(f"铺货失败: {e}")
        return PublishResult(success=False, published_count=0, failed_items=[{"error": str(e)}])