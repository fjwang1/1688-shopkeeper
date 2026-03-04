#!/usr/bin/env python3
"""
店铺管理模块 - 查询和展示绑定店铺
"""

from typing import List
from api import list_bound_shops, Shop


def format_shop_list(shops: List[Shop]) -> str:
    """
    格式化店铺列表为 Markdown
    
    Args:
        shops: 店铺列表
    
    Returns:
        Markdown 格式字符串
    """
    if not shops:
        return "暂无绑定的店铺。"
    
    lines = [f"## 已绑定的店铺（共 {len(shops)} 个）\n"]
    
    for i, s in enumerate(shops, 1):
        status = "✅ 正常" if s.is_authorized else "❌ 授权过期"
        lines.append(f"{i}. **{s.name}** ({s.channel})")
        lines.append(f"   - 店铺代码: `{s.code}`")
        lines.append(f"   - 状态: {status}")
        lines.append("")
    
    return "\n".join(lines)


def get_valid_shops() -> List[Shop]:
    """
    获取授权有效的店铺列表
    
    Returns:
        有效店铺列表
    """
    all_shops = list_bound_shops()
    return [s for s in all_shops if s.is_authorized]


def check_shop_status() -> dict:
    """
    检查店铺状态（便捷函数）
    
    Returns:
        {
            "all": List[Shop],
            "valid": List[Shop],
            "expired": List[Shop],
            "markdown": str
        }
    """
    all_shops = list_bound_shops()
    valid_shops = [s for s in all_shops if s.is_authorized]
    expired_shops = [s for s in all_shops if not s.is_authorized]
    
    return {
        "all": all_shops,
        "valid": valid_shops,
        "expired": expired_shops,
        "markdown": format_shop_list(all_shops)
    }