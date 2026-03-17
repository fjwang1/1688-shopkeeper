#!/usr/bin/env python3
"""Verified 1688 selection workflow: search, validate, save, and publish."""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
ROOT_SCRIPTS = REPO_ROOT / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))

from _api import search_products  # type: ignore
from _const import WORKSPACE_DIR, PUBLISH_LIMIT  # type: ignore
from publish import publish_with_check, normalize_item_ids  # type: ignore


PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)")
BENEFIT_KEYWORDS = ("官方仓退货", "晚揽必赔", "退货包运费", "48小时发货", "7天无理由退货")
DEFAULT_CHANNEL = "pinduoduo"
DATA_DIR = Path(WORKSPACE_DIR) / "1688-verified-selector-data" / "products"


@dataclass
class VerifiedProduct:
    id: str
    title: str
    url: str
    search_price: Optional[float]
    one_piece_price: Optional[float]
    multi_piece_price: Optional[float]
    one_piece_free_shipping: bool
    benefits: List[str]
    snippet: List[str]
    stats: Optional[Dict[str, Any]] = None


def _parse_price(text: str) -> Optional[float]:
    match = PRICE_RE.search(text or "")
    return float(match.group(1)) if match else None


def _extract_verified_data(lines: List[str]) -> Dict[str, Any]:
    for index, line in enumerate(lines):
        if "1件包邮" not in line:
            continue

        snippet = lines[index:index + 8]
        one_piece_price = _parse_price(lines[index + 1]) if index + 1 < len(lines) else None
        multi_piece_price = None

        for probe in range(index + 2, min(index + 8, len(lines))):
            if "≥2件" in lines[probe] or "2件起批" in lines[probe]:
                if probe + 1 < len(lines):
                    multi_piece_price = _parse_price(lines[probe + 1])
                break

        benefits = [item for item in snippet if item in BENEFIT_KEYWORDS]
        return {
            "one_piece_free_shipping": True,
            "one_piece_price": one_piece_price,
            "multi_piece_price": multi_piece_price,
            "benefits": benefits,
            "snippet": snippet,
        }

    return {
        "one_piece_free_shipping": False,
        "one_piece_price": None,
        "multi_piece_price": None,
        "benefits": [],
        "snippet": [],
    }


def _product_sort_key(product: VerifiedProduct) -> Any:
    return (
        product.one_piece_price is None,
        product.one_piece_price if product.one_piece_price is not None else float("inf"),
        product.search_price if product.search_price is not None else float("inf"),
    )


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _save_products(
    *,
    raw_query: str,
    queries: List[str],
    channel: str,
    requested_count: int,
    candidate_count: int,
    validated_count: int,
    products: List[VerifiedProduct],
) -> str:
    _ensure_data_dir()
    data_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "data_id": data_id,
        "raw_query": raw_query,
        "queries": queries,
        "channel": channel,
        "requested_count": requested_count,
        "candidate_count": candidate_count,
        "validated_count": validated_count,
        "timestamp": datetime.now().isoformat(),
        "products": {item.id: asdict(item) for item in products},
    }
    filepath = DATA_DIR / f"verified_{data_id}.json"
    with filepath.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return data_id


def _load_products_by_data_id(data_id: str) -> Optional[List[str]]:
    filepath = DATA_DIR / f"verified_{data_id}.json"
    if not filepath.exists():
        return None
    try:
        with filepath.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        products = payload.get("products", {})
        if isinstance(products, dict):
            return list(products.keys())
        return None
    except Exception:
        return None


def _validate_product(page: Any, product: VerifiedProduct) -> VerifiedProduct:
    page.goto(product.url, wait_until="domcontentloaded")
    page.wait_for_timeout(4500)
    text = page.locator("body").inner_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    extracted = _extract_verified_data(lines)
    product.one_piece_free_shipping = extracted["one_piece_free_shipping"]
    product.one_piece_price = extracted["one_piece_price"]
    product.multi_piece_price = extracted["multi_piece_price"]
    product.benefits = extracted["benefits"]
    product.snippet = extracted["snippet"]
    return product


def run_select(
    *,
    raw_query: str,
    queries: List[str],
    channel: str,
    count: int,
    max_validate: int,
    require_one_piece_free_shipping: bool,
) -> Dict[str, Any]:
    candidate_map: Dict[str, VerifiedProduct] = {}
    validated_count = 0
    query_runs = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1800})
        page.set_default_timeout(60000)

        for query in queries:
            query_runs += 1
            new_candidates: List[VerifiedProduct] = []
            for result in search_products(query, channel):
                if result.id in candidate_map:
                    continue
                new_candidates.append(
                    VerifiedProduct(
                        id=result.id,
                        title=result.title,
                        url=result.url,
                        search_price=_parse_price(result.price),
                        one_piece_price=None,
                        multi_piece_price=None,
                        one_piece_free_shipping=False,
                        benefits=[],
                        snippet=[],
                        stats=result.stats,
                    )
                )
            new_candidates.sort(
                key=lambda item: item.search_price if item.search_price is not None else float("inf")
            )

            for candidate in new_candidates:
                if validated_count >= max_validate:
                    break
                candidate_map[candidate.id] = _validate_product(page, candidate)
                validated_count += 1

            filtered = [
                item for item in candidate_map.values()
                if (not require_one_piece_free_shipping) or item.one_piece_free_shipping
            ]
            filtered.sort(key=_product_sort_key)
            if len(filtered) >= count:
                break

        browser.close()

    filtered = [
        item for item in candidate_map.values()
        if (not require_one_piece_free_shipping) or item.one_piece_free_shipping
    ]
    filtered.sort(key=_product_sort_key)
    final_products = filtered[:count]
    data_id = _save_products(
        raw_query=raw_query,
        queries=queries,
        channel=channel,
        requested_count=count,
        candidate_count=len(candidate_map),
        validated_count=validated_count,
        products=final_products,
    )

    need_refine_query = len(final_products) < count
    markdown = _format_select_markdown(
        raw_query=raw_query,
        queries=queries,
        products=final_products,
        candidate_count=len(candidate_map),
        validated_count=validated_count,
        requested_count=count,
        data_id=data_id,
        need_refine_query=need_refine_query,
    )

    return {
        "success": True,
        "markdown": markdown,
        "data": {
            "data_id": data_id,
            "raw_query": raw_query,
            "queries": queries,
            "channel": channel,
            "requested_count": count,
            "candidate_count": len(candidate_map),
            "validated_count": validated_count,
            "product_count": len(final_products),
            "need_refine_query": need_refine_query,
            "products": [asdict(item) for item in final_products],
        },
    }


def _format_select_markdown(
    *,
    raw_query: str,
    queries: List[str],
    products: List[VerifiedProduct],
    candidate_count: int,
    validated_count: int,
    requested_count: int,
    data_id: str,
    need_refine_query: bool,
) -> str:
    lines = [
        f"原始需求：{raw_query}",
        f"- 搜索轮次：{len(queries)}",
        f"- 合并候选数：{candidate_count}",
        f"- 已校验详情页：{validated_count}",
        f"- 目标数量：{requested_count}",
        f"- 实际保留：{len(products)}",
        f"- data_id：`{data_id}`\n",
    ]

    if products:
        lines.extend([
            "| # | 商品 | 1件包邮价 | ≥2件价 | 搜索价 | 权益 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for idx, product in enumerate(products, 1):
            one_piece = f"¥{product.one_piece_price:.2f}" if product.one_piece_price is not None else "-"
            multi_piece = f"¥{product.multi_piece_price:.2f}" if product.multi_piece_price is not None else "-"
            search_price = f"¥{product.search_price:.2f}" if product.search_price is not None else "-"
            benefits = "、".join(product.benefits) if product.benefits else "-"
            title = product.title.replace("|", "\\|")
            lines.append(
                f"| {idx} | [{title}]({product.url}) | {one_piece} | {multi_piece} | {search_price} | {benefits} |"
            )
    else:
        lines.append("未找到满足条件的商品。")

    if need_refine_query:
        lines.extend([
            "",
            "当前关键词下结果不足。",
            "建议用户换一个更具体或更宽松的关键词后继续筛选。",
        ])

    return "\n".join(lines)


def run_publish(*, data_id: Optional[str], item_ids: Optional[str], shop_code: str, dry_run: bool) -> Dict[str, Any]:
    if not os.environ.get("ALI_1688_AK"):
        return {
            "success": False,
            "markdown": "❌ AK 未配置，无法执行铺货或铺货预检查。",
            "data": {"success": False},
        }

    if data_id:
        loaded_ids = _load_products_by_data_id(data_id)
        if not loaded_ids:
            return {
                "success": False,
                "markdown": f"❌ 未找到 data_id=`{data_id}` 对应的筛选结果。",
                "data": {"success": False},
            }
        final_item_ids = normalize_item_ids(loaded_ids)
    else:
        raw_ids = [item.strip() for item in (item_ids or "").split(",") if item.strip()]
        final_item_ids = normalize_item_ids(raw_ids)

    if not final_item_ids:
        return {
            "success": False,
            "markdown": "❌ 没有可用的商品ID，请检查 `--data-id` 或 `--item-ids`。",
            "data": {"success": False},
        }

    result = publish_with_check(final_item_ids, shop_code, dry_run=dry_run)
    submitted_count = min(result["origin_count"], PUBLISH_LIMIT)
    return {
        "success": result["success"],
        "markdown": result["markdown"],
        "data": {
            "success": result["success"],
            "origin_count": result["origin_count"],
            "submitted_count": submitted_count,
            "dry_run": dry_run,
            "source_data_id": data_id or "",
            "item_ids": final_item_ids,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="1688 verified selection and publish workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select", help="搜索、详情页校验并保存结果")
    select_parser.add_argument("--query", action="append", required=True, help="搜索词。第一条必须是用户原始需求，可重复")
    select_parser.add_argument("--channel", default=DEFAULT_CHANNEL, choices=["", "douyin", "taobao", "pinduoduo", "xiaohongshu"])
    select_parser.add_argument("--count", type=int, default=20, help="目标商品数量")
    select_parser.add_argument("--max-validate", type=int, default=60, help="最多校验详情页数")
    select_parser.add_argument(
        "--require-one-piece-free-shipping",
        action="store_true",
        default=True,
        help="仅保留明确出现 1件包邮 的商品",
    )

    publish_parser = subparsers.add_parser("publish", help="根据 data_id 或 item_ids 执行铺货")
    publish_parser.add_argument("--shop-code", required=True, help="目标店铺代码")
    publish_parser.add_argument("--dry-run", action="store_true", help="仅做预检查，不执行实际铺货")
    publish_group = publish_parser.add_mutually_exclusive_group(required=True)
    publish_group.add_argument("--data-id", help="筛选结果 data_id")
    publish_group.add_argument("--item-ids", help="商品ID列表，逗号分隔")

    args = parser.parse_args()

    if args.command == "select":
        if not os.environ.get("ALI_1688_AK"):
            output = {
                "success": False,
                "markdown": "❌ AK 未配置，无法执行1688详情校验选品。",
                "data": {"products": [], "product_count": 0},
            }
        else:
            output = run_select(
                raw_query=args.query[0],
                queries=args.query,
                channel=args.channel,
                count=args.count,
                max_validate=args.max_validate,
                require_one_piece_free_shipping=args.require_one_piece_free_shipping,
            )
    else:
        output = run_publish(
            data_id=args.data_id,
            item_ids=args.item_ids,
            shop_code=args.shop_code,
            dry_run=args.dry_run,
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
