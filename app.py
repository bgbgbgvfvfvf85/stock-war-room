import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import requests
import twstock
import yfinance as yf
import math

# ==========================================
# 頁面設定
# ==========================================
st.set_page_config(page_title="股票戰情室", layout="wide")
st.title("🔥 股票戰情室 (Stock War Room)")

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 關鍵點位 (CDP)", 
    "📈 趨勢分析 (K線)", 
    "💰 策略模擬 (風控)", 
    "🔍 盤後情報 (戰情連結)"
])

# ==========================================
# 核心輔助函式
# ==========================================

def format_price(price):
    """
    依照台股 Tick 跳動規則進行價格修正與格式化
    """
    if pd.isna(price): return "-"
    p = float(price)
    
    # 台股跳動級距規則
    if p < 10: 
        tick = 0.01
        fmt = "{:.2f}"
    elif p < 50: 
        tick = 0.05
        fmt = "{:.2f}"
    elif p < 100: 
        tick = 0.1
        fmt = "{:.1f}"
    elif p < 500: 
        tick = 0.5
        fmt = "{:.1f}"
    elif p < 1000: 
        tick = 1.0
        fmt = "{:.0f}"
    else: 
        tick = 5.0
        fmt = "{:.0f}"
        
    # 將價格校正到最近的 Tick (四捨五入)
    snapped_price = round(p / tick) * tick
    return fmt.format(snapped_price)

def get_tick_step(price):
    """取得 UI 數字輸入框的 step"""
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    if price < 1000: return 1.0
    return 5.0

def load_groups():
    if os.path.exists('groups.json'):
        try:
            with open('groups.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def search_stock_info(query):
    query = str(query).strip().upper()
    if not query: return "2330.TW", "2330", "台積電"

    clean_code = query.split('.')[0]

    # 1. 優先查本地庫
    if clean_code in twstock.codes:
        info = twstock.codes[clean_code]
        suffix = ".TWO" if info.market == "上櫃" else ".TW"
        return f"{clean_code}{suffix}", clean_code, info.name

    # 2. 查 API (備用)
    try:
        url = f"https://typeahead.twse.com.tw/TS/stocksearch.do?key={clean_code}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data:
                entry = data[0]
                mkt = entry.get('market', '')
                suffix = ".TWO" if "上櫃" in mkt or "興櫃" in mkt else ".TW"
                return f"{entry['code']}{suffix}", entry['code'], entry['name']
    except:
        pass

    return f"{clean_code}.TW", clean_code, clean_code

def get_stock_data_smart(query, period="6mo"):
    ticker, code, name = search_stock_info(query)
    try:
        df = yf.download(ticker, period=period, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        if df.empty and ticker.endswith('.TW'):
            ticker_two = f"{code}.TWO"
            df_two = yf.download(ticker_two, period=period, progress=False)
            if isinstance(df_two.columns, pd.MultiIndex): df_two.columns = df_two.columns.get_level_values(0)
            if not df_two.empty: 
                new_name = twstock.codes[code].name if code in twstock.codes else name
                return df_two, ticker_two, code, new_name
    except:
        return pd.DataFrame(), ticker, code, name
    return df, ticker, code, name

def calculate_tech_levels(df):
    if df.empty: return {}
    last = df.iloc[-1]
    
    c = float(last['Close'])
    h = float(last['High'])
    l = float(last['Low'])
    
    # CDP
    cdp = (h + l + 2*c) / 4
    ah = cdp + (h - l)
    nh = cdp * 2 - l
    nl = cdp * 2 - h
    al = cdp - (h - l)

    # 布林 & MA
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    std = df['Close'].rolling(20).std().iloc[-1]
    
    # 若無資料則用現價代替，避免報錯
    ma20 = c if pd.isna(ma20) else ma20
    std = 0 if pd.isna(std) else std
    
    bb_up = ma20 + std * 2
    bb_low = ma20 - std * 2

    # 這裡回傳原始數值，顯示時再 format，方便後續計算
    return {
        'close': c, 'high': h, 'low': l,
        'cdp': cdp, 'ah': ah, 'nh': nh, 'nl': nl, 'al': al,
        'ma20': ma20, 'bb_up': bb_up, 'bb_low': bb_low,
    }

# ==========================================
# Tab 1: 關鍵點位 (修正數值位數)
# ==========================================
with tab1:
    st.subheader("🎯 關鍵點位偵測")
    # Tab 1 使用 form 是好的，因為參數多，一次計算比較整齊
    # 按 Enter 也會觸發 submit
    with st.form(key='t1_form'):
        c1, c2 = st.columns([1, 2])
        q_in = c1.text_input("輸入代號 (按 Enter 計算):", value="2330")
        lookback = c2.slider("斐波那契區間", 30, 120, 60)
        run_1 = st.form_submit_button("計算關鍵點位")

    if run_1 or q_in: # 支援 Enter 直接觸發
        df, ticker, code, name = get_stock_data_smart(q_in)
        if df.empty:
            st.error("查無資料")
        else:
            lv = calculate_tech_levels(df)
            recent = df[-lookback:]
            mx = float(recent['High'].max())
            mn = float(recent['Low'].min())
            diff = mx - mn
            
            st.success(f"📊 {code} {name} (收盤價: {format_price(lv['close'])})")
            
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.markdown("### 1. CDP 逆勢操作")
                # 使用 format_price 修正為台股 Tick
                st.metric("第二壓力 (AH)", format_price(lv['ah']))
                st.metric("第一壓力 (NH)", format_price(lv['nh']))
                st.metric("第一支撐 (NL)", format_price(lv['nl']))
                st.metric("第二支撐 (AL)", format_price(lv['al']))

            with rc2:
                st.markdown("### 2. 布林通道")
                st.metric("上軌", format_price(lv['bb_up']))
                st.metric("中軌", format_price(lv['ma20']))
                st.metric("下軌", format_price(lv['bb_low']))
                
            with rc3:
                st.markdown("### 3. 斐波那契")
                st.write(f"區間高: {format_price(mx)} / 低: {format_price(mn)}")
                st.metric("0.382", format_price(mn + diff*0.382)) # 修正計算邏輯: 低點 + 0.382波幅 (回檔) 或 高點 - 0.382 (反彈)
                # 這裡假設是看回檔支撐，或者是反彈壓力，通常顯示關鍵位即可
                # 通用公式： High - diff * 0.382 (高檔回落) / Low + diff * 0.382 (低檔反彈)
                # 簡單起見，顯示從高點回落的 0.382 和 0.618 位置
                st.metric("回檔 0.382", format_price(mx - diff*0.382))
                st.metric("回檔 0.618", format_price(mx - diff*0.618))

# ==========================================
# Tab 2: 趨勢分析 (移除 Form，實現即時連動)
# ==========================================
with tab2:
    st.subheader("📈 趨勢儀表板")
    groups = load_groups()
    gc1, gc2 = st.columns([1, 3])
    
    with gc1:
        st.info("💡 快速選股")
        # 移除 st.form，這樣選單改變會直接觸發 rerun
        
        group_names = list(groups.keys())
        # 選單 1
        selected_group = st.selectbox("1. 選擇群組", ["自選輸入"] + group_names)
        
        # 根據選單 1 動態產生選單 2 的內容
        stock_list = groups.get(selected_group, [])
        display_opts = []
        for s in stock_list:
            base = s.split('.')[0]
            # 這裡簡單處理，避免每次都查 API 導致卡頓
            n = twstock.codes[base].name if base in twstock.codes else base
            display_opts.append(f"{base} {n}")
        
        # 選單 2 (現在會立刻更新了)
        t2_select = None
        if display_opts:
            t2_select = st.selectbox("2. 選擇個股", display_opts)
        
        st.write("---")
        # 文字輸入框 (按 Enter 會自動 Rerun)
        t2_input = st.text_input("或直接輸入代號 (按 Enter):", value="2330")
        
        rng = st.select_slider("區間", options=["3mo", "6mo", "1y", "2y"], value="6mo")
        # 按鈕保留，作為強制重新整理用
        st.button("查看走勢") 

    # 邏輯判斷：優先使用下拉選單，除非是自選輸入模式且有輸入文字
    target = "2330"
    if selected_group != "自選輸入" and t2_select:
        target = t2_select.split(' ')[0]
    elif t2_input:
        target = t2_input

    # 只要 target 存在就畫圖 (因為沒有 Form 了，所以會即時反應)
    if target:
        df, ticker, code, name = get_stock_data_smart(target, rng)
        if not df.empty:
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.2, 0.7], subplot_titles=(f"{code} {name}", "成交量"))
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange'), name='MA20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='blue'), name='MA60'), row=1, col=1)
            colors = ['red' if c >= o else 'green' for o, c in zip(df['Open'], df['Close'])]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
            fig.update_layout(height=600, xaxis_rangeslider_visible=False)
            with gc2:
                st.plotly_chart(fig, use_container_width=True)

# ==========================================
# Tab 3: 風控 (支援 Enter)
# ==========================================
with tab3:
    st.header("💰 風控試算")
    tc1, tc2 = st.columns([1, 4])
    
    # Text input 按 Enter 會自動更新 state
    t3_in = tc1.text_input("代號 (按 Enter 讀取)", value="2330", key="t3_input_real")
    
    # 這裡保留按鈕，但也允許直接讀取
    # 為了讓流程順暢，我們檢查代號是否有變動或是否剛打開
    df, _, c, n = get_stock_data_smart(t3_in)
    
    # 這裡的邏輯：只要抓得到資料，就更新計算基礎，不依賴按鈕
    if not df.empty:
        curr_price = float(df.iloc[-1]['Close'])
        lv = calculate_tech_levels(df)
        
        # 只在第一次或代號變更時更新 session state，避免影響使用者輸入的 EP/SL/TP
        if 'last_code' not in st.session_state or st.session_state['last_code'] != c:
            st.session_state['levels'] = lv
            st.session_state['curr'] = curr_price
            st.session_state['last_code'] = c
            st.success(f"已載入 {c} {n} 現價: {curr_price}")

    if 'levels' not in st.session_state: 
        st.session_state.update({'levels': {}, 'curr': 100.0})

    # 根據現價決定 UI 的 step
    step_val = get_tick_step(st.session_state.get('curr', 100))
    fmt_str = "%.2f"
    if step_val >= 1: fmt_str = "%.0f"
    elif step_val == 0.5: fmt_str = "%.1f"
    
    lv = st.session_state.get('levels', {})
    opts_dict = {}
    if lv:
        # 使用 format_price 讓選單顯示漂亮的價格
        opts_dict = {
            f"現價 ({format_price(lv['close'])})": lv['close'],
            f"CDP 2壓 ({format_price(lv['ah'])})": lv['ah'],
            f"CDP 1壓 ({format_price(lv['nh'])})": lv['nh'],
            f"CDP 中軸 ({format_price(lv['cdp'])})": lv['cdp'],
            f"CDP 1撐 ({format_price(lv['nl'])})": lv['nl'],
            f"CDP 2撐 ({format_price(lv['al'])})": lv['al'],
            f"布林上 ({format_price(lv['bb_up'])})": lv['bb_up'],
            f"布林中 ({format_price(lv['ma20'])})": lv['ma20'],
            f"布林下 ({format_price(lv['bb_low'])})": lv['bb_low'],
        }
    
    opts = ["(請選擇...)"] + list(opts_dict.keys())

    def set_price(k, target_k):
        label = st.session_state[k]
        if label in opts_dict:
            # 這裡也要幫忙 format 一下，讓輸入框數字漂亮
            val = opts_dict[label]
            st.session_state[target_k] = val

    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        st.selectbox("進場參考", opts, key='s_ep', on_change=set_price, args=('s_ep', 'ep'))
        st.number_input("進場價", key='ep', step=step_val, format=fmt_str)
    with pc2:
        st.selectbox("停損參考", opts, key='s_sl', on_change=set_price, args=('s_sl', 'sl'))
        st.number_input("停損價", key='sl', step=step_val, format=fmt_str)
    with pc3:
        st.selectbox("停利參考", opts, key='s_tp', on_change=set_price, args=('s_tp', 'tp'))
        st.number_input("停利價", key='tp', step=step_val, format=fmt_str)

    st.markdown("---")
    side = st.radio("交易方向", ["做多", "做空"], horizontal=True)
    
    # 這裡用 Form 或是 Button 都可以，Button 比較直覺
    if st.button("計算損益 (張)"):
        ep = st.session_state.get('ep', 0.0)
        sl = st.session_state.get('sl', 0.0)
        tp = st.session_state.get('tp', 0.0)
        
        if ep > 0 and sl > 0 and tp > 0:
            risk = (ep - sl if side == "做多" else sl - ep) * 1000
            reward = (tp - ep if side == "做多" else ep - tp) * 1000
            if risk <= 0: st.error("邏輯錯誤：停損點設置有誤")
            else:
                rr = reward / risk
                rc1, rc2 = st.columns(2)
                rc1.metric("單張虧損風險", f"-${risk:,.0f}")
                rc1.metric("單張預期獲利", f"+${reward:,.0f}")
                rc2.metric("風報比 (RR)", f"1 : {rr:.2f}")
                if rr >= 3: rc2.success("🌟 完美交易")
                elif rr >= 2: rc2.info("✅ 值得嘗試")
                else: rc2.warning("⚠️ 風險過高")

# ==========================================
# Tab 4: 盤後情報 (戰情連結 - 修正版)
# ==========================================
with tab4:
    st.header("🔍 盤後籌碼戰情室")
    
    # 這裡用 Form 支援 Enter
    with st.form(key='t4_form'):
        col1, col2 = st.columns([1, 4])
        with col1:
            t4_in = st.text_input("輸入代號 (按 Enter):", value="2330")
        with col2:
            st.write("")
            st.write("")
            submit_t4 = st.form_submit_button("搜尋連結")
    
    # 處理代號
    _, ticker, code, name = get_stock_data_smart(t4_in)
    
    st.subheader(f"{code} {name} - 外部戰情連結")
    st.write("") 

    # 1. Yahoo: 上櫃需加 .TWO
    yahoo_sym = f"{code}.TWO" if ".TWO" in ticker else code
    link_yahoo = f"https://tw.stock.yahoo.com/quote/{yahoo_sym}/institutional-trading"
    
    # 2. Goodinfo: 法人買賣超統計
    link_goodinfo = f"https://goodinfo.tw/tw/ShowBuySaleChart.asp?STOCK_ID={code}"
    
    # 3. 鉅亨網: 統一格式
    link_anue = f"https://www.cnyes.com/twstock/{code}/chip/institution"

    # 顯示按鈕
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🟣 Yahoo 奇摩")
        st.link_button("Yahoo 三大法人", link_yahoo, use_container_width=True)
        
    with c2:
        st.markdown("### 🔵 Goodinfo")
        st.link_button("法人買賣超統計", link_goodinfo, use_container_width=True)

    with c3:
        st.markdown("### 🟠 鉅亨網")
        st.link_button("鉅亨網 籌碼分析", link_anue, use_container_width=True)