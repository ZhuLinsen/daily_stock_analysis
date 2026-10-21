#!/usr/bin/env python3
# coding: utf-8
"""指数价格日线资料整合与完整性审计 V1.5 — 离线、可复现（stdlib + exchange_calendars）。
只接受真实输入文件，绝不填充未观察到的价格。
执行：python merge_audit_创业板指_中证红利_V1.5.py --workdir /mnt/data
"""
import argparse
import csv
import json
import hashlib
import sys
from pathlib import Path
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

START='2010-06-01'; BOUNDARY='2026-07-29'; PATCH_START='2026-07-30'; END='2026-10-13'
BASE_CY='创业板指历史日线.csv'; BASE_RED='中证红利历史日线.csv'
PATCH='创业板指_中证红利_20260730-20261013_完整增量日线_V1.3.csv'
CORR='20130806_创业板指_收盘价勘误_V1.2.csv'
OUT='创业板指_中证红利_20100601-20261013_统一历史日线_V1.5.csv'
JSON_OUT='创业板指_中证红利_全量审计_V1.5.json'
MD_OUT='创业板指_中证红利_全量审计报告_V1.5.md'
URL_CY='https://github.com/ZF1Huang/growth_dividend_rotation_research/blob/main/data_cache/399006.csv'
URL_RED='https://github.com/ZF1Huang/growth_dividend_rotation_research/blob/main/data_cache/000922.csv'
URL_CY_PATCH='https://github.com/cmdSTARMO/market_repo/blob/main/market_data/创业板指-399006.csv'
Q8=Decimal('0.00000001')
D100=Decimal('100')

def require(expr, desc):
    if not expr:raise ValueError('全量审计不通过：'+str(desc))

def h(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def dnum(s,field,dt):
    require(str(s).strip()!='',f'{dt} {field} 为空')
    try:v=Decimal(str(s).strip())
    except InvalidOperation:raise ValueError(f'{dt} {field} 非数字：{s!r}')
    require(v.is_finite() and v>0, f'{dt} {field} 非正或非有限：{s!r}')
    require(v.as_tuple().exponent>=-8, f'{dt} {field} 有过多小数位')
    return v

def money(x):return format(x.quantize(Decimal('.01'),rounding=ROUND_HALF_UP),'.2f')

def ratio(a,b):return format((a/b).quantize(Q8,rounding=ROUND_HALF_UP),'.8f')

def parse_base(rows,label):
    require(rows,f'{label} 基础文件为空')
    require(all(set(('date','open','close'))<=set(z) for z in rows),f'{label} 数据字段缺失')
    ret={}
    for r in rows:
        dt=r['date'].strip()
        require(dt not in ret,f'{label} 重复日期 {dt}')
        require(date.fromisoformat(dt).isoformat()==dt,f'{label} 日期格式异常 {dt}')
        ret[dt]={'open':dnum(r['open'],'open',dt),'close':dnum(r['close'],'close',dt)}
    require(list(ret)==sorted(ret),f'{label} 源数据并非严格升序')
    return ret

def main(root):
    filenames=[BASE_CY,BASE_RED,PATCH,CORR]
    paths={name:root/name for name in filenames}
    for name,p in paths.items():require(p.is_file(),f'输入不存在：{p}')
    expected={PATCH:'be2bdd82a100fee19877c8be5d16166f4371847f9d56f7fa401b5db0bbd26fdf',
              CORR:'cb5120f8a42d1f9d1def8996366a9089eed9c7a45645f2a626724a680495a841'}
    for name,sha in expected.items():require(h(paths[name])==sha,f'{name} 不等于已冻结的V1.3/V1.2输入哈希')
    cy=parse_base(read(paths[BASE_CY]),'创业板'); red=parse_base(read(paths[BASE_RED]),'中证红利')
    require(len(cy)==3924 and min(cy)==START and max(cy)==BOUNDARY,'创业板历史窗口/条数不符合冻结基准')
    require(len(red)==4663 and min(red)=='2007-05-28' and max(red)==BOUNDARY,'红利历史窗口/条数不符合冻结基准')
    require(set(cy)<=set(red),'旧主数据指数收盘无法逐日配对')
    corrections=read(paths[CORR]);require(len(corrections)==1,'预期恰好1条价格勘误')
    e=corrections[0]
    require((e['date'],e['symbol'],e['field'],e['original'],e['corrected'])==('2013-08-06','399006','close','1211.69','1211.78'),'勘误内容被更改')
    require(cy['2013-08-06']['close']==Decimal('1211.69'),'历史基线无法与勘误前值匹配')
    cy['2013-08-06']['close']=Decimal('1211.78')
    combined=[]
    for dt,r in cy.items():
        p=red[dt]
        combined.append({'date':dt,'cyb_open':money(r['open']),'cyb_high':'','cyb_low':'','cyb_close':money(r['close']),
          'red_open':money(p['open']),'red_close':money(p['close']),'cyb_red_ratio':ratio(r['close'],p['close']),
          'source_segment':'historical_2010_2026','cyb_source_url':URL_CY,'red_source_url':URL_RED,
          'audit_note':'2013-08-06 cyb_close 1211.69 -> 1211.78 (Tonghuashun screenshot + TDX)' if dt=='2013-08-06' else ''})
    inc=read(paths[PATCH]);require(len(inc)==48,'V1.3增量不是48行')
    require(all(set(('date','cyb_open','cyb_high','cyb_low','cyb_close','red_close','cyb_red_ratio','red_source_url','status'))<=set(z) for z in inc),'V1.3字段不完整')
    inc_dates=[]
    patch_source_status=Counter()
    for z in inc:
        dt=z['date'].strip();date.fromisoformat(dt)
        require(PATCH_START<=dt<=END and dt not in cy,f'增量日期越界或冲突 {dt}')
        inc_dates.append(dt)
        prices={k:dnum(z[k],k,dt) for k in ['cyb_open','cyb_high','cyb_low','cyb_close','red_close']}
        require(prices['cyb_high']>=max(prices['cyb_open'],prices['cyb_close']) and prices['cyb_low']<=min(prices['cyb_open'],prices['cyb_close']) and prices['cyb_low']<=prices['cyb_high'],f'增量OHLC不合法 {dt}')
        require(Decimal(ratio(prices['cyb_close'],prices['red_close']))==Decimal(z['cyb_red_ratio']),f'V1.3比值不一致 {dt}')
        if dt=='2026-08-05':
            require(prices['red_close']==Decimal('5447.98') and z['status']=='user_Tonghuashun_confirmed','2026-08-05 人工确认错误')
        patch_source_status[z['status']]+=1
        combined.append({'date':dt,'cyb_open':money(prices['cyb_open']),'cyb_high':money(prices['cyb_high']),
            'cyb_low':money(prices['cyb_low']),'cyb_close':money(prices['cyb_close']),
            'red_open':'','red_close':money(prices['red_close']),
            'cyb_red_ratio':ratio(prices['cyb_close'],prices['red_close']),
            'source_segment':'increment_2026_V1.3','cyb_source_url':URL_CY_PATCH,
            'red_source_url':z['red_source_url'],
            'audit_note':'2026-08-05 red_close=5447.98 confirmed by user Tonghuashun' if dt=='2026-08-05' else ''})
    require(inc_dates==sorted(set(inc_dates)),'V1.3增量排序/唯一性有问题')
    combined.sort(key=lambda z:z['date'])
    alldates=[z['date'] for z in combined]
    require(len(combined)==3972 and len(set(alldates))==3972,f'总量异常：{len(combined)} 行')
    require(alldates[0]==START and alldates[-1]==END,'全量日期范围异常')
    require(combined[3923]['date']==BOUNDARY and combined[3924]['date']==PATCH_START,'新旧接缝日期不正确')
    require((combined[3923]['cyb_close'],combined[3923]['red_close'])==('3378.70','5519.12'),'历史接缝收盘值异常')
    require((combined[3924]['cyb_close'],combined[3924]['red_close'])==('3244.62','5579.60'),'增量接缝收盘值异常')
    require((combined[-1]['cyb_close'],combined[-1]['red_close'])==('2958.34','5635.07'),'截至10/13最终收盘值异常')
    # 用与股价序列来源独立的上海证券交易所公开日历规则实现库对日期集合逐一审计。
    import exchange_calendars
    calendar=exchange_calendars.get_calendar('XSHG')
    expected_dates=[x.strftime('%Y-%m-%d') for x in calendar.sessions_in_range(START,END)]
    missing=sorted(set(expected_dates)-set(alldates)); extra=sorted(set(alldates)-set(expected_dates))
    require(not missing and not extra and len(expected_dates)==3972,'独立XSHG日历与实际交易日集合不一致')
    invalid=[]; total_ratios=0
    for i,z in enumerate(combined):
        c=dnum(z['cyb_close'],'cyb_close',z['date']);v=dnum(z['red_close'],'red_close',z['date'])
        dnum(z['cyb_open'],'cyb_open',z['date'])
        if z['red_open']:dnum(z['red_open'],'red_open',z['date'])
        if z['cyb_high'] or z['cyb_low']:
            require(z['cyb_high'] and z['cyb_low'],'增量开高低不是配套存在：'+z['date'])
            hi=dnum(z['cyb_high'],'cyb_high',z['date']); lo=dnum(z['cyb_low'],'cyb_low',z['date'])
            require(hi>=max(c,Decimal(z['cyb_open'])) and lo<=min(c,Decimal(z['cyb_open'])),'OHLC无法包络开收：'+z['date'])
        require(z['cyb_red_ratio']==ratio(c,v),f'主表第{i+1}行比值不吻合')
        total_ratios+=1
    require(total_ratios==3972,'没有完成全比值重算')
    # 源文件冻结及字段只修改一处的严格一致性：基础数据逐行对旧值；增量与V1.3逐行对齐。
    base_orig=parse_base(read(paths[BASE_CY]),'创业板原始审计用')
    red_orig=parse_base(read(paths[BASE_RED]),'红利原始审计用')
    for z in combined[:3924]:
        dt=z['date'];original=base_orig[dt]; src=red_orig[dt]
        require(z['cyb_open']==money(original['open']) and z['red_open']==money(src['open']) and z['red_close']==money(src['close']),f'旧数据被非法修改 {dt}')
        require(z['cyb_close']==money(Decimal('1211.78') if dt=='2013-08-06' else original['close']),f'旧收盘数据额外变更 {dt}')
        require(z['cyb_high']==z['cyb_low']=='','历史段高低价应保留空白而不能伪造')
    for j,z in enumerate(combined[3924:]):
        orig=inc[j]; require(z['date']==orig['date'],'增量配对顺序错误')
        for fld in ['cyb_open','cyb_high','cyb_low','cyb_close','red_close']:
            require(Decimal(z[fld])==Decimal(orig[fld]),f'增量原数据被变更：{z["date"]} {fld}')
        require(z['red_open']=='','V1.3没有红利开盘价，禁止伪造')
    years=Counter(d[:4] for d in alldates)
    extremes={}
    anomaly=[]
    for name,col in [('创业板指','cyb_close'),('中证红利','red_close')]:
        seq=[Decimal(z[col]) for z in combined]
        changes=[(combined[i]['date'],(seq[i]/seq[i-1]-1)*100) for i in range(1,len(seq))]
        extremes[name]={
         'min_close':str(min(seq)),'min_close_date':combined[seq.index(min(seq))]['date'],
         'max_close':str(max(seq)),'max_close_date':combined[seq.index(max(seq))]['date'],
         'biggest_up':{'date':max(changes,key=lambda x:x[1])[0],'pct':float(max(changes,key=lambda x:x[1])[1])},
         'biggest_down':{'date':min(changes,key=lambda x:x[1])[0],'pct':float(min(changes,key=lambda x:x[1])[1])},
         'abs_gt_10pct_count':sum(abs(v)>10 for _,v in changes)}
        anomaly.extend({'symbol':name,'date':dt,'pct':round(float(val),4)} for dt,val in changes if abs(val)>Decimal('10'))
    rr=[Decimal(z['cyb_red_ratio']) for z in combined]
    firstlast={'first':combined[0], 'historic_last':combined[3923], 'new_first':combined[3924], 'last':combined[-1]}
    field_coverage={f:sum(bool(z[f]) for z in combined) for f in ['cyb_open','cyb_high','cyb_low','cyb_close','red_open','red_close','cyb_red_ratio','red_source_url']}
    out=root/OUT
    fields=['date','cyb_open','cyb_high','cyb_low','cyb_close','red_open','red_close','cyb_red_ratio','source_segment','cyb_source_url','red_source_url','audit_note']
    with out.open('w',encoding='utf-8-sig',newline='') as fp:
        wr=csv.DictWriter(fp,fieldnames=fields,lineterminator='\n');wr.writeheader();wr.writerows(combined)
    # 落盘后重新读入验证：使文件编码/CSV序列化损坏不能蒙混过关。
    disk=read(out)
    require(len(disk)==len(combined) and disk==combined,'写入磁盘后回读数据与内存主数据不一致')
    audit={
      'version':'V1.5','audit_date':'2026-10-15','result':'核心结构、日历、数据继承与公式审计通过；全历史未逐日官方点位认证',
      'data_type':'价格指数，不包含股息再投资','date_range':[START,END],
      'rows':3972,'old_rows':3924,'increment_rows':48,'historical_red_raw_rows':len(red),
      'historical_red_outside_common_window':len(red)-3924,
      'unique_dates':len(set(alldates)),'duplicate_dates':len(alldates)-len(set(alldates)),
      'calendar':{'provider':'exchange_calendars','name':'XSHG','version':exchange_calendars.__version__,
                  'expected_trading_days':len(expected_dates),'missing_dates':missing,'extra_dates':extra,
                  'comparison':'exact_set_equality'},
      'mandatory_close_pair_valid':3972,'ratio_recalculated':total_ratios,
      'null_mandatory_price_or_ratio':0,'field_coverage':field_coverage,'ratio_extremes':{
         'min_ratio':str(min(rr)),'min_date':combined[rr.index(min(rr))]['date'],
         'max_ratio':str(max(rr)),'max_date':combined[rr.index(max(rr))]['date']},
      'price_extremes':extremes,'daily_close_moves_abs_gt_10pct':anomaly,
      'year_counts':dict(sorted(years.items())),'seam':firstlast,
      'manual_fix_2013':{'date':'2013-08-06','code':'399006','before':'1211.69','after':'1211.78','applied':True},
      'manual_fix_2026':{'date':'2026-08-05','code':'000922','close':'5447.98','present':True},
      'patch_source_status':dict(patch_source_status),'data_integrity':{
          'historical_prices_unchanged_except_2013_fix':True,'patch_prices_unchanged':True,
          'historical_high_low_missing_by_source':3924,
          'red_open_missing_by_source':48,
          'no_imputation':True,'disk_roundtrip_verified':True},
      'input_files_sha256':{name:h(paths[name]) for name in filenames},
      'output_filename':OUT,'output_sha256':h(out),
      'limitations':['未对3972个收盘点位逐一进行中证/国证官方原始响应认证',
        '2010至2026历史源为GitHub第三方缓存，源中未保存逐日上游API身份',
        '增量中证红利点位来自多处第三方网页+用户对单点同花顺确认',
        '独立交易日历基于exchange_calendars XSHG，并非交易所官方签名文件',
        '价格指数比值不包含中证红利分红再投资的收益影响',
        '历史段只有开收盘；增量中证红利只有收盘。空的可选字段不是缺失交易日']}
    (root/JSON_OUT).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def pctfmt(v):return f'{v:+.4f}%'
    note=f'''# 创业板指（399006）/ 中证红利（000922）历史行情全量审计报告 V1.5

**执行日期：2026-10-15；已实际在本地执行3972行真实历史数据合并、CSV落盘回读、全比值复算、独立交易日历核验。**

## 1. 验收结论

**核心数据结构与可复算性审计通过。** 新生成的 `{OUT}` 含 **3,972条唯一交易日**，覆盖 **{START}—{END}**；有效收盘价和比值均为 **3,972/3,972**；与独立XSHG交易日历 **3,972/3,972 完全一致**，缺少/多余交易日都是 **0**。但未对全部点位获得交易所/指数公司正式数据回执，准确性验证仍受第三方源口径限制。

## 2. 合并构成

| 来源 | 行数 | 日期区间 | 处理 |
|---|---:|---|---|
| 创业板历史CSV | 3,924 | 2010-06-01—2026-07-29 | 完整保留开/收，仅2013-08-06收盘1211.69→1211.78 |
| 中证红利历史CSV | 原始4,663；有效交集3,924 | 2007-05-28—2026-07-29 | 取共同窗口，较早739条不并入 |
| V1.3增量补丁 | 48 | 2026-07-30—2026-10-13 | 价格不变，核验2026-08-05收盘5447.98 |
| **统一主表** | **3,972** | **2010-06-01—2026-10-13** | 逐日收盘价比值，Decimal四舍五入8位 |

计算：`cyb_red_ratio = Decimal(cyb_close / red_close)`，`ROUND_HALF_UP` 精度8位；原始价格统一格式为2位小数，所有计算字段均经独立回读复算。

## 3. 全量审计明细

| 审计项目 | 实际结果 |
|---|---|
| 输入源V1.3、勘误SHA256锁定 | 通过；两者哈希与既有交接清单一致 |
| 旧双指数日期交集 | 3,924/3,924 |
| 新旧边界 | 2026-07-29→2026-07-30，日期无重叠、衔接正确 |
| 源文件继承检查 | 旧基线除唯一授权勘误外无变动；增量48日全部原始行情无变动 |
| 日期升序、无重复、全部合法日期 | 通过；0个重复 |
| 独立XSHG交易日历 | 3,972个预期交易日，缺0、多0（exchange_calendars v{exchange_calendars.__version__}） |
| 两指数有效收盘配对 | 3,972/3,972 |
| 收盘价格和比值非正/NaN/无限大 | 0 |
| 每日比值Decimal独立复算 | 3,972/3,972，0处不一致 |
| 增量创业板高低价包络开收盘 | 48/48 |
| 输出主CSV落盘后重新读取 | 3,972/3,972，与内存数据逐字段一致 |
| 历史可选高低价缺失 | 历史源未提供，3924天合法留空 |
| 增量红利开盘价缺失 | V1.3只提供收盘，48天合法留空 |

## 4. 人工勘误和关键锚点

| 日期 | 创业板收盘 | 中证红利收盘 | 比值 | 核查 |
|---|---:|---:|---:|---|
'''
    select_dates=['2010-06-01','2013-08-06','2018-10-19','2020-07-01','2024-09-30','2025-12-31','2026-07-29','2026-07-30','2026-08-05','2026-10-13']
    lookup={r['date']:r for r in combined}
    for dt in select_dates:
        r=lookup[dt]
        note+=f"| {dt} | {r['cyb_close']} | {r['red_close']} | {r['cyb_red_ratio']} | {'2013勘误' if dt=='2013-08-06' else ('8/5同花顺补点' if dt=='2026-08-05' else '原数据/此前抽查')} |\n"
    note+='''
**时间轴说明：**新增48天已完整归档，日历与行情源独立一致；2026-08-05中证红利收盘5447.98来自用户同花顺核实，不伪造来源网址。

## 5. 价格异常监控（异常不等于错误）

'''
    for k,v in extremes.items():
        note+=f"- {k}：历史最大单日涨幅 {pctfmt(v['biggest_up']['pct'])}（{v['biggest_up']['date']}），最大单日跌幅 {pctfmt(v['biggest_down']['pct'])}（{v['biggest_down']['date']}），单日绝对波动大于10%的天数 **{v['abs_gt_10pct_count']}**。\n"
    note+=f"- 历史比值范围：最小 **{audit['ratio_extremes']['min_ratio']}**（{audit['ratio_extremes']['min_date']}），最大 **{audit['ratio_extremes']['max_ratio']}**（{audit['ratio_extremes']['max_date']}）。\n"
    note+='''
这些波动已被记录在机器可读JSON中，仅作后续人工价格核验优先名单，不按涨跌幅阈值自动删除行情日。

## 6. 年度交易日覆盖

| 年份 | 记录数 |
|---|---:|
'''
    for yy,n in sorted(years.items()):note+=f'| {yy} | {n} |\n'
    note+='''
## 7. 来源、质量边界和数据研究限制

- 历史创业板：'''+URL_CY+'\n- 历史中证红利：'+URL_RED+'\n- 增量创业板：'+URL_CY_PATCH+'''\n- 增量中证红利：详见主表每行`red_source_url`；2026-08-05由用户人工核准，无URL。
- 交叉来源：此前V1.4预检记录通达信历史数据交叉校验结果（创业板3397日重合原41差异，校正2013-08-06后余40处相差0.01点；中证红利102日重合2处相差0.01点）。这些是**先前预检证据继承**，本轮未在本地下载通达信源重做逐行比对，不将其冒充本轮新增实测。
- 本轮独立交易日历使用本地 `exchange_calendars` XSHG库，不等于交易所正式盖章校验；日期覆盖通过也不等于全部历史收盘价已经得到官方认证。
- 两者是不同指数编制规则的**价格指数**；比值只能表示成长相对于红利价格指数的相对强弱，并不完整反映长期含分红再投资的投资回报。
- 对于历史部分没有高低价、增量中证红利没有开盘价的字段，本次保留空值，不得把这些合法的可选空值误报为日线缺失；分析应以收盘价及比值为主。

## 8. 哈希与可复现性

主表SHA256：`'''+audit['output_sha256']+'''`

复现：把4份输入文件与本程序放置同一目录，运行 `python merge_audit_创业板指_中证红利_V1.5.py --workdir .`。如需完全冻结依赖，应固定 `exchange_calendars==4.13.1`。本程序使用Python内置`csv`和`decimal`，不使用数据插值或价格估算。

机器审计见 `'''+JSON_OUT+'''`，包含逐年度行数、源文件SHA256、全部异常单日波动、字段完整性、边界记录及价格极值。
'''
    (root/MD_OUT).write_text(note,encoding='utf-8')
    print(json.dumps({'status':'PASSED_CORE','rows':len(combined),'files':[OUT,MD_OUT,JSON_OUT],
       'sha256':audit['output_sha256'],'date_range':[START,END],
       'year_counts':audit['year_counts'],'calendar_expected':len(expected_dates),'calendar_missing':len(missing),
       'calendar_extra':len(extra),'field_coverage':field_coverage,'price_extremes':extremes,
       'ratio_extremes':audit['ratio_extremes'],'patch_source_status':dict(patch_source_status)},ensure_ascii=False,indent=2))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--workdir',type=Path,default=Path(__file__).parent);main(a.parse_args().workdir.resolve())
