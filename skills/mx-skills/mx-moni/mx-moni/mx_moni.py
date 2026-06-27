#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mx_moni.py - 妙想模拟组合管理 skill
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime

# 获取环境变量
MX_APIKEY = os.environ.get('MX_APIKEY', '')
MX_API_URL = os.environ.get('MX_API_URL', 'https://mkapi2.dfcfs.com/finskillshub')

# 默认输出目录
OUTPUT_DIR = '/root/.openclaw/workspace/mx_data/output'
os.makedirs(OUTPUT_DIR, exist_ok=True)

def api_request(endpoint, payload):
    """发送 API 请求到妙想服务器"""
    url = f"{MX_API_URL}{endpoint}"
    cmd = [
        'curl', '-s', '-X', 'POST', url,
        '-H', f'apikey: {MX_APIKEY}',
        '-H', 'Content-Type: application/json; charset=UTF-8',
        '-d', json.dumps(payload)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"[ERROR] curl failed: {result.stderr}")
            return None
        # 尝试解析 JSON
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON decode failed: {e}")
            print(f"[DEBUG] raw output: {result.stdout[:200]}...")
            return None
    except Exception as e:
        print(f"[ERROR] API request failed: {e}")
        return None

def parse_query(query_text):
    """解析自然语言查询，识别意图"""
    query_lower = query_text.lower()
    
    # 发帖总结意图
    if any(keyword in query_lower for keyword in ['总结', '发帖', '操作总结', '发布操作帖', '发一下操作帖', '经验交流']):
        return 'newPost'
    
    # 持仓查询
    if any(keyword in query_lower for keyword in ['持仓', '我的持仓', '持仓情况', '查询持仓']):
        return 'positions'
    
    # 资金查询
    if any(keyword in query_lower for keyword in ['资金', '我的资金', '账户资金', '查询资金', '资金情况']):
        return 'balance'
    
    # 委托查询
    if any(keyword in query_lower for keyword in ['委托', '我的委托', '委托查询', '订单', '我的订单', '成交记录', '历史成交']):
        return 'orders'
    
    # 撤单
    if any(keyword in query_lower for keyword in ['撤单', '撤销', 'cancel', '一键撤单', '撤销所有']):
        return 'cancel'
    
    # 买入
    if any(keyword in query_lower for keyword in ['买入', 'buy', '建仓']):
        return 'buy'
    
    # 卖出
    if any(keyword in query_lower for keyword in ['卖出', 'sell', '减仓', '清仓']):
        return 'sell'
    
    # 默认未知
    return None

def extract_trade_info(query_text, intent):
    """从查询文本中提取交易信息"""
    import re
    
    # 提取股票代码 - 支持 0/3/6/9 开头的6位代码
    code_matches = re.findall(r'([0369]\d{5})', query_text)
    stock_code = code_matches[0] if code_matches else None
    
    # 提取数量
    quantity_matches = re.findall(r'(\d+)\s*(股|手)', query_text)
    quantity = None
    if quantity_matches:
        qty = int(quantity_matches[0][0])
        if quantity_matches[0][1] == '手':
            qty *= 100
        quantity = qty
    # 如果没找到单位，尝试直接找数字
    if not quantity:
        num_matches = re.findall(r'\b(\d+)\b', query_text)
        # 排除代码，取最后一个数字作为数量
        nums = [int(n) for n in num_matches if len(n) != 6]
        if nums:
            quantity = nums[-1]
    
    # 提取价格
    price_matches = re.findall(r'(价格|@)\s*(\d+\.?\d*)', query_text)
    price = None
    if price_matches:
        price = float(price_matches[0][1])
    else:
        # 尝试直接找数字
        num_matches = re.findall(r'\b(\d+\.?\d*)\b', query_text)
        # 排除代码和数量
        nums = [float(n) for n in num_matches if len(n) != 6]
        if nums:
            price = nums[-1]
    
    # 判断是否市价
    use_market = any(keyword in query_text.lower() for keyword in ['市价', 'market', '现价'])
    
    # 提取委托编号（撤单用）
    order_id_matches = re.findall(r'(\d{16,})', query_text)
    order_id = order_id_matches[0] if order_id_matches else None
    
    return {
        'stock_code': stock_code,
        'quantity': quantity,
        'price': price,
        'use_market': use_market,
        'order_id': order_id,
        'is_all': '一键' in query_text or '所有' in query_text
    }

def auto_post_at_close():
    """自动收盘发帖：检查今日是否有操作，有则生成总结并发帖"""
    print("🔍 检查今日是否有调仓操作...")
    result = api_request('/api/claw/mockTrading/orders', {
        'fltOrderDrt': 0,
        'fltOrderStatus': 0
    })
    
    if not result:
        print("[ERROR] 获取订单列表失败，无法检测今日操作")
        return False
    
    code = result.get('code')
    if code != '0' and code != 200 and code != '200':
        print(f"[ERROR] 获取订单失败: {result.get('message', '')}")
        return False
    
    data = result.get('data', {})
    orders = data.get('orders', [])
    
    # 统计今日订单，只要有订单就认为有操作
    today_orders = [o for o in orders if o.get('status') != 0]
    if len(today_orders) == 0:
        print("✓ 今日没有调仓操作，自动跳过发帖")
        return True
    
    print(f"✓ 检测到今日有 {len(today_orders)} 个委托订单，请手动输入发帖内容")
    print("\n请输入发帖内容：", end=' ', flush=True)
    text = sys.stdin.readline().strip()
    if not text:
        print("[ERROR] 发帖内容不能为空")
        return False
    
    result = api_request('/api/claw/mockTrading/newPost', {'text': text})
    if result and (result.get('code') == '0' or result.get('code') == 200):
        print("\n🎉 发帖成功！")
        if result.get('data') and result.get('data').get('postId'):
            print(f"帖子ID: {result['data']['postId']}")
        return True
    else:
        msg = result.get('message', '未知错误') if result else '网络错误'
        print(f"\n❌ 发帖失败：{msg}")
        return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='mx-moni 妙想模拟组合管理')
    parser.add_argument('query', nargs='*', help='查询文本/自然语言指令')
    parser.add_argument('--auto-post', action='store_true', help='自动收盘发帖：今日有操作则请输入内容发帖')
    args = parser.parse_args()
    
    # 检查 API Key
    if not MX_APIKEY:
        print("[ERROR] MX_APIKEY 环境变量未配置，请先配置妙想API密钥")
        print("请执行：export MX_APIKEY=your_api_key_here")
        sys.exit(1)
    
    # 自动发帖模式
    if args.auto_post:
        auto_post_at_close()
        sys.exit(0)
    
    # 拼接查询文本
    query_text = ' '.join(args.query)
    if not query_text:
        print("[ERROR] 请输入查询指令，例如：")
        print("  python mx_moni.py \"我的持仓\"")
        print("  python mx_moni.py \"买入 600519 1700 100\"")
        print("  python mx_moni.py \"总结一下今日操作\"")
        print("  python mx_moni.py --auto-post")
        sys.exit(1)
    
    # 识别意图
    intent = parse_query(query_text)
    if not intent:
        print(f"[ERROR] 无法识别查询意图：{query_text}")
        print("支持的意图：持仓查询、资金查询、买入、卖出、撤单、委托查询、总结发帖")
        sys.exit(1)
    
    # 保存查询结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_query = query_text.replace('/', '_')[:30]
    
    # 根据意图处理
    if intent == 'positions':
        result = api_request('/api/claw/mockTrading/positions', {'moneyUnit': 1})
    elif intent == 'balance':
        result = api_request('/api/claw/mockTrading/balance', {'moneyUnit': 1})
    elif intent == 'orders':
        result = api_request('/api/claw/mockTrading/orders', {'fltOrderDrt': 0, 'fltOrderStatus': 0})
    elif intent == 'newPost':
        print("\n请输入发帖内容：", end=' ', flush=True)
        text = sys.stdin.readline().strip()
        if not text:
            print("[ERROR] 发帖内容不能为空")
            sys.exit(1)
        result = api_request('/api/claw/mockTrading/newPost', {'text': text})
    elif intent in ['buy', 'sell']:
        info = extract_trade_info(query_text, intent)
        if not info['stock_code'] or not info['quantity']:
            print("[ERROR] 无法识别股票代码或数量，请检查输入")
            print("示例：买入 600519 1700 100 股")
            print("示例：市价买入 000001 100 股")
            sys.exit(1)
        
        payload = {
            'type': intent,
            'stockCode': info['stock_code'],
            'quantity': info['quantity'],
            'useMarketPrice': info['use_market'],
        }
        if not info['use_market'] and info['price'] is not None:
            # 价格需要放大: 价格 * 10^decimal_places
            # 接口要求整数按放大后的价格传入
            decimal_places = 2 if info['stock_code'][0] in ['6', '9'] else 3
            payload['price'] = int(round(info['price'] * (10 ** decimal_places)))
        
        result = api_request('/api/claw/mockTrading/trade', payload)
    elif intent == 'cancel':
        info = extract_trade_info(query_text, intent)
        if info['is_all'] or not info['order_id']:
            # 一键撤单
            payload = {'type': 'all'}
        else:
            payload = {'type': 'order', 'orderId': info['order_id'], 'stockCode': info['stock_code']}
        result = api_request('/api/claw/mockTrading/cancel', payload)
    else:
        result = None
    
    # 保存原始结果
    if result:
        output_json = os.path.join(OUTPUT_DIR, f"mx_moni_{safe_query}_{timestamp}.json")
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # 输出格式化结果
        output_txt = os.path.join(OUTPUT_DIR, f"mx_moni_{safe_query}_{timestamp}.txt")
        formatted_text = format_result(intent, result)
        with open(output_txt, 'w', encoding='utf-8') as f:
            f.write(formatted_text)
        
        print("\n" + formatted_text)
        print(f"\n💾 结果已保存到：")
        print(f"   JSON: {output_json}")
        print(f"   TXT: {output_txt}")
    else:
        print("[ERROR] API 请求失败，请检查网络和配置")
        sys.exit(1)

def format_result(intent, result):
    """格式化输出结果"""
    code = result.get('code')
    message = result.get('message', '')
    data = result.get('data', {})
    
    output = []
    output.append("=" * 50)
    
    if code not in ['0', 0, '200', 200]:
        output.append(f"❌ 请求失败")
        output.append(f"代码: {code}")
        output.append(f"信息: {message}")
        output.append("=" * 50)
        return '\n'.join(output)
    
    output.append(f"✅ 请求成功")
    output.append("")
    
    if intent == 'balance':
        # 资金查询结果
        rc = data.get('rc', 0)
        if rc != 0:
            output.append(f"⚠️  返回码: {rc}")
        total_assets = data.get('totalAssets', 0) / 1000  # 单位是厘，转换为元
        avail_balance = data.get('availBalance', 0) / 1000
        frozen_money = data.get('frozenMoney', 0) / 1000
        total_pos_value = data.get('totalPosValue', 0) / 1000
        total_pos_pct = data.get('totalPosPct', 0)
        nav = data.get('nav', 0)
        init_money = data.get('initMoney', 0) / 1000
        opr_days = data.get('oprDays', 0)
        acc_name = data.get('accName', '')
        acc_id = data.get('accID', '')
        
        output.append("===== 账户资金 =====")
        if acc_name:
            output.append(f"账户名称: {acc_name}")
        if acc_id:
            output.append(f"账户ID:    {acc_id}")
        output.append(f"总资产:     {total_assets:,.2f} 元")
        output.append(f"可用资金:   {avail_balance:,.2f} 元")
        output.append(f"冻结金额:   {frozen_money:,.2f} 元")
        output.append(f"总持仓市值: {total_pos_value:,.2f} 元")
        output.append(f"仓位比例:   {total_pos_pct:.2f}%")
        output.append(f"初始资金:   {init_money:,.2f} 元")
        if nav:
            output.append(f"单位净值:   {nav:.4f}")
        if opr_days:
            output.append(f"运作天数:   {opr_days}")
    
    elif intent == 'positions':
        # 持仓查询结果
        total_assets = data.get('totalAssets', 0) / 1000
        avail_balance = data.get('availBalance', 0) / 1000
        total_pos_value = data.get('totalPosValue', 0) / 1000
        pos_count = data.get('posCount', 0)
        total_profit = data.get('totalProfit', 0) / 1000
        
        output.append("===== 账户持仓 =====")
        output.append(f"总资产:     {total_assets:,.2f} 元")
        output.append(f"可用资金:   {avail_balance:,.2f} 元")
        output.append(f"总持仓市值: {total_pos_value:,.2f} 元")
        output.append(f"总盈亏:     {total_profit:,.2f} 元")
        output.append(f"持仓股票数量: {pos_count}")
        output.append("")
        
        pos_list = data.get('posList', [])
        if pos_list:
            output.append("===== 持仓明细 =====")
            output.append(f"{'股票名称':<10} {'代码':<6} {'持仓':>8} {'可用':>8} {'现价':>10} {'市值':>12} {'仓位%':>8} {'盈亏':>10}")
            output.append("-" * 80)
            for pos in pos_list:
                name = pos.get('secName', '')[:10]
                code = pos.get('secCode', '')
                count = pos.get('count', 0)
                avail = pos.get('availCount', 0)
                price = pos.get('price', 0) / (10 ** pos.get('priceDec', 2))
                value = pos.get('value', 0) / 1000
                pos_pct = pos.get('posPct', 0)
                profit = pos.get('profit', 0) / 1000
                output.append(f"{name:<10} {code:<6} {count:>8} {avail:>8} {price:>10.2f} {value:>12.2f} {pos_pct:>8.2f} {profit:>10.2f}")
    
    elif intent == 'orders':
        # 委托查询结果
        rc = data.get('rc', 0)
        total_num = data.get('totalNum', 0)
        orders = data.get('orders', [])
        
        output.append(f"===== 委托列表 =====")
        output.append(f"总委托数: {total_num}")
        output.append("")
        
        if orders:
            output.append(f"{'委托编号':<18} {'股票名称':<10} {'方向':<4} {'价格':>8} {'数量':>6} {'状态':<6}")
            output.append("-" * 60)
            status_map = {
                1: "未报", 2: "已报", 3: "部成", 4: "已成",
                5: "部成待撤", 6: "已报待撤", 7: "部撤", 8: "已撤",
                9: "废单", 10: "撤单失败"
            }
            drt_map = {1: "买入", 2: "卖出"}
            for order in orders[:20]:  # 只显示最近20条
                order_id = order.get('id', '')[:18]
                name = order.get('secName', '')[:10]
                drt = order.get('drt', 0)
                price = order.get('price', 0) / (10 ** order.get('priceDec', 2))
                count = order.get('count', 0)
                status = order.get('status', 0)
                output.append(f"{order_id:<18} {name:<10} {drt_map.get(drt, '?'):<4} {price:>8.2f} {count:>6} {status_map.get(status, '?'):<6}")
            if len(orders) > 20:
                output.append(f"... 还有 {len(orders) - 20} 条委托未显示")
    
    elif intent == 'newPost':
        if code in ['0', 0, '200', 200]:
            output.append("🎉 发帖成功！")
            if isinstance(data, int) or isinstance(data, str):
                output.append(f"帖子ID: {data}")
            elif isinstance(data, dict) and data.get('postId'):
                output.append(f"帖子ID: {data['postId']}")
        else:
            output.append(f"❌ 发帖失败: {message}")
    
    elif intent in ['buy', 'sell']:
        if code in ['0', 0, '200', 200]:
            direction = "买入" if intent == 'buy' else "卖出"
            output.append(f"✅ {direction}委托已成功提交！")
            if data.get('orderId'):
                output.append(f"委托编号: {data['orderId']}")
        else:
            direction = "买入" if intent == 'buy' else "卖出"
            output.append(f"❌ {direction}委托失败: {message}")
    
    elif intent == 'cancel':
        if code in ['0', 0, '200', 200]:
            rc = data.get('rc', 0)
            rmsg = data.get('rmsg', '')
            cancel_count = data.get('cancelCount', 0)
            fail_count = data.get('failCount', 0)
            output.append(f"✅ 撤单完成: {rmsg}")
            output.append(f"成功撤单: {cancel_count} 笔")
            if fail_count > 0:
                output.append(f"失败: {fail_count} 笔")
                fail_list = data.get('failList', [])
                for fail in fail_list:
                    output.append(f"   {fail.get('orderID')}: {fail.get('rmsg')}")
        else:
            output.append(f"❌ 撤单失败: {message}")
    
    output.append("=" * 50)
    return '\n'.join(output)

if __name__ == '__main__':
    main()
