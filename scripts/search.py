#!/usr/bin/env python3
"""
选品模块 - 商品搜索和结果处理
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from api import search_products, Product


def save_search_result(products: List[Product], query: str, channel: str) -> str:
    """
    保存搜索结果到文件
    
    Args:
        products: 商品列表
        query: 搜索关键词
        channel: 渠道
    
    Returns:
        data_id (时间戳格式)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(os.path.dirname(script_dir), "data", "products")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    
    data_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(data_dir, f"1688_{data_id}.json")
    
    # 转换为Map格式存储（与API返回一致）
    products_map = {}
    for p in products:
        products_map[p.id] = {
            "title": p.title,
            "price": p.price,
            "image": p.image
        }
    
    data = {
        "query": query,
        "channel": channel,
        "timestamp": datetime.now().isoformat(),
        "data_id": data_id,
        "products": products_map
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return data_id


def format_product_list(products: List[Product], max_show: int = 10) -> str:
    """
    格式化商品列表为 Markdown
    
    Args:
        products: 商品列表
        max_show: 最多显示数量
    
    Returns:
        Markdown 格式字符串
    """
    if not products:
        return "未找到符合条件的商品。"
    
    lines = [f"## 商品列表（共 {len(products)} 个）\n"]
    
    for i, p in enumerate(products[:max_show], 1):
        lines.append(f"### {i}. {p.title}")
        if p.image:
            lines.append(f"![商品图]({p.image})")
        lines.append(f"- **价格**: ¥{p.price}")
        if p.sales:
            lines.append(f"- **销量**: {p.sales}")
        if p.shop_name:
            lines.append(f"- **店铺**: {p.shop_name}")
        if p.url:
            lines.append(f"- **链接**: [查看详情]({p.url})")
        if p.id:
            lines.append(f"- **商品ID**: `{p.id}`")
        lines.append("")
    
    if len(products) > max_show:
        lines.append(f"*... 还有 {len(products) - max_show} 个商品未显示*")
    
    return "\n".join(lines)


def search_and_save(query: str, channel: str = "douyin", count: int = 10) -> dict:
    """
    搜索并保存结果（便捷函数）
    
    Args:
        query: 搜索关键词
        channel: 渠道
        count: 数量
    
    Returns:
        {"products": List[Product], "data_id": str, "markdown": str}
    """
    products = search_products(query, channel, count)
    
    if not products:
        return {
            "products": [],
            "data_id": "",
            "markdown": "未找到商品，请尝试更换关键词。"
        }
    
    data_id = save_search_result(products, query, channel)
    markdown = format_product_list(products)
    
    return {
        "products": products,
        "data_id": data_id,
        "markdown": markdown
    }