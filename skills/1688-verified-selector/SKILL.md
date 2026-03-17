---
name: 1688-verified-selector
description: |
  1688商品筛选与铺货工作流技能。用于：(1) 先按用户原始自然语言搜索1688商品，再用
  Playwright打开详情页校验“1件包邮”、单件真实售价、2件价和页面权益文案，并将筛选
  结果保存为 data_id；(2) 根据 data_id 或用户指定的商品ID，直接执行铺货到目标店铺。
  适合拼多多/抖音/小红书/淘宝等一件代发场景，尤其适合需要排除搜索接口低价误导并衔
  接后续铺货的选品任务。
metadata:
  openclaw:
    emoji: "🔎"
    requires:
      env: ["ALI_1688_AK"]
      bins: ["python3", "playwright"]
    primaryEnv: "ALI_1688_AK"
---

# 1688-verified-selector

统一入口：

`python3 {baseDir}/scripts/verified_search.py <select|publish> ...`

这个 skill 同时负责“筛货校验”和“铺货”。

## 什么时候用

- 用户需要“单件包邮”的真实售价，而不是搜索接口里的最低价
- 用户要按详情页最终展示文案筛货
- 用户要在筛完商品后立即铺货
- 用户要从本地保存的筛选结果继续铺货

## 执行前置

- 先阅读 `references/search-strategy.md`
- 确认 `ALI_1688_AK` 已配置
- 本机可运行 Playwright Chromium

## 标准流程

1. 第一轮必须直接使用用户原始需求作为第一条 `--query`
2. 运行 `select`
3. 如果数量不够，再补 1 到 2 条更具体或更宽松的 `--query`
4. `select` 会保存结果并返回 `data_id`
5. 用户确认后，运行 `publish`

## 命令速查

| 命令 | 说明 |
| --- | --- |
| `python3 {baseDir}/scripts/verified_search.py select --query "..." --channel pinduoduo --count 20` | 搜索、详情校验、保存结果 |
| `python3 {baseDir}/scripts/verified_search.py select --query "用户原始需求" --query "补充搜索词" --channel pinduoduo --count 20` | 多轮搜索合并后校验 |
| `python3 {baseDir}/scripts/verified_search.py publish --shop-code CODE --data-id ID` | 直接铺货已保存结果 |
| `python3 {baseDir}/scripts/verified_search.py publish --shop-code CODE --item-ids a,b,c` | 直接铺货指定商品 |

## 参数规则

- `select --query`：必填，可重复 1 到 5 次，第一条必须是用户原始需求
- `--channel`：可选，默认 `pinduoduo`
- `--count`：目标商品数量，默认 `20`
- `--max-validate`：最多校验多少个候选详情页，默认 `60`
- `--require-one-piece-free-shipping`：默认开启，只保留明确出现 `1件包邮` 的商品
- `publish --data-id`：从本地筛选结果取商品ID
- `publish --item-ids`：用户直接指定商品ID
- `publish --shop-code`：目标店铺代码

## 输出规则

脚本输出统一 JSON：

- `success`: 是否成功
- `markdown`: 直接展示给用户的表格
- `data.data_id`: 本次筛选结果保存ID
- `data.products`: 已校验商品列表

## 回答约束

- 第一轮搜索必须使用用户原话，不要擅自改写
- 如果第一次数量不足，再补搜索词
- 搜索接口里的 `price` 只能叫“搜索价”或“粗筛价”
- 详情页抓到的 `one_piece_price` 才能叫“1件包邮价”或“单件真实售价”
- 没抓到 `1件包邮` 的商品，不要猜测它是否包邮
- 要明确告诉用户筛选结果已保存，可直接用 `data_id` 铺货
