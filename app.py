import streamlit as st
import pandas as pd
import requests
import twstock
import yfinance as yf
import ssl
import urllib3
import os

# --- 1. SSL 與 安全設定 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 頁面設定
# ==========================================
st.set_page_config(page_title="股票戰情室", layout="wide")
st.title("🔥 股票戰情室 (Stock War Room)")

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 關鍵點位 (CDP)", 
    "⚖️ 停損停利試算", 
    "💰 策略模擬 (風控)", 
    "🔍 盤後情報 (戰情連結)"
])

# ==========================================
# 核心輔助函式 (台股 Tick 自動校正)
# ==========================================

def get_snapped_price(price):
    """將價格強制校正到台股合法的跳動檔位 (Tick)"""
    if pd.isna(price) or price <= 0: return 0.0
    p = float(price)
    
    if p < 10: tick = 0.01
    elif p < 50: tick = 0.05
    elif p < 100: tick = 0.1
    elif p < 500: tick = 0.5
    elif p < 1000: tick = 1.0
    else: tick = 5.0
    
    return round(p / tick) * tick

def format_price(price):
    """將價格格式化為漂亮的字串"""
    if pd.isna(price): return "-"
    p = get_snapped_price(float(price))
    if p < 50: fmt = "{:.2f}"
    elif p < 500: fmt = "{:.1f}"
    else: fmt = "{:.0f}"
    return fmt.format(p)

def get_tick_step(price):
    """取得 UI 數字輸入框的 step 大小"""
    if price < 10: return 0.01
    if price < 50: return 0.05
    if price < 100: return 0.1
    if price < 500: return 0.5
    if price < 1000: return 1.0
    return 5.0

def search_stock_info(query):
    query = str(query).strip().upper()
    if not query: return "2330.TW", "2330", "台積電"
    clean_code = query.split('.')[0]
    if clean_code in twstock.codes:
        info = twstock.codes[clean_code]
        suffix = ".TWO" if info.market == "上櫃" else ".TW"
        return f"{clean_code}{suffix}", clean_code, info.name
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
    c, h, l = float(last['Close']), float(last['High']), float(last['Low'])
    cdp = (h + l + 2*c) / 4
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    std = df['Close'].rolling(20).std().iloc[-1]
    ma20 = c if pd.isna(ma20) else ma20
    std = 0 if pd.isna(std) else std
    return {
        'close': c, 'high': h, 'low': l,
        'cdp': cdp, 'ah': cdp + (h - l), 'nh': cdp * 2 - l,
        'nl': cdp * 2 - h, 'al': cdp - (h - l),
        'ma20': ma20, 'bb_up': ma20 + std * 2, 'bb_low': ma20 - std * 2,
    }

# ==========================================
# Tab 1: 關鍵點位 (CDP)
# ==========================================
with tab1:
    st.subheader("🎯 關鍵點位偵測")
    with st.form(key='t1_form'):
        c1, c2 = st.columns([1, 2])
        q_in = c1.text_input("代號 (按 Enter):", value="2330")
        lookback = c2.slider("斐波那契區間", 30, 120, 60)
        st.form_submit_button("計算")

    df, ticker, code, name = get_stock_data_smart(q_in)
    if not df.empty:
        lv = calculate_tech_levels(df)
        recent = df[-lookback:]
        mx, mn = float(recent['High'].max()), float(recent['Low'].min())
        diff = mx - mn
        st.success(f"📊 {code} {name} (收盤: {format_price(lv['close'])})")
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            st.markdown("### 1. CDP 點位")
            st.metric("二壓 (AH)", format_price(lv['ah']))
            st.metric("一壓 (NH)", format_price(lv['nh']))
            st.metric("一撐 (NL)", format_price(lv['nl']))
            st.metric("二撐 (AL)", format_price(lv['al']))
        with rc2:
            st.markdown("### 2. 布林通道")
            st.metric("上軌", format_price(lv['bb_up']))
            st.metric("中軌", format_price(lv['ma20']))
            st.metric("下軌", format_price(lv['bb_low']))
        with rc3:
            st.markdown("### 3. 斐波那契")
            st.metric("回檔 0.382", format_price(mx - diff*0.382))
            st.metric("回檔 0.618", format_price(mx - diff*0.618))

# ==========================================
# Tab 2: ⚖️ 停損停利試算 (取代 K線)
# ==========================================
with tab2:
    st.subheader("⚖️ 停損停利試算 (% 數換算價格)")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        trade_dir = st.radio("方向", ["做多", "做空"], horizontal=True)
        # 動態決定輸入步進值
        cur_p = st.session_state.get('calc_entry', 100.0)
        entry_p = st.number_input("預計進場價", value=cur_p, step=get_tick_step(cur_p), key='calc_entry')
    with sc2:
        tp_pct = st.selectbox("🎯 預期停利 %", [f"{i}%" for i in range(1, 21)], index=4)
    with sc3:
        sl_pct = st.selectbox("🛑 預期停損 %", [f"{i}%" for i in range(1, 21)], index=1)

    tp_v = float(tp_pct.replace("%", "")) / 100
    sl_v = float(sl_pct.replace("%", "")) / 100

    if trade_dir == "做多":
        target_tp = get_snapped_price(entry_p * (1 + tp_v))
        target_sl = get_snapped_price(entry_p * (1 - sl_v))
        profit = (target_tp - entry_p) * 1000
        loss = (entry_p - target_sl) * 1000
    else:
        target_tp = get_snapped_price(entry_p * (1 - tp_v))
        target_sl = get_snapped_price(entry_p * (1 + sl_v))
        profit = (entry_p - target_tp) * 1000
        loss = (target_sl - entry_p) * 1000

    st.markdown("---")
    res1, res2, res3 = st.columns(3)
    res1.metric(f"目標停利 ({tp_pct})", format_price(target_tp), f"+${profit:,.0f}/張")
    res2.metric("進場價", format_price(entry_p))
    res3.metric(f"嚴格停損 ({sl_pct})", format_price(target_sl), f"-${loss:,.0f}/張", delta_color="inverse")
    if loss > 0: st.info(f"💡 實質風報比 (RR) 約 **1 : {profit/loss:.2f}**")

# ==========================================
# Tab 3: 💰 策略模擬 (風控)
# ==========================================
with tab3:
    st.header("💰 策略模擬")
    t3_in = st.text_input("代號 (按 Enter 讀取)", value="2330", key="t3_input")
    df, _, c, n = get_stock_data_smart(t3_in)
    if not df.empty:
        curr_p = float(df.iloc[-1]['Close'])
        lv = calculate_tech_levels(df)
        if st.session_state.get('last_c') != c:
            st.session_state.update({'levels': lv, 'curr': curr_p, 'last_c': c})
            st.success(f"已載入 {c} {n} ({format_price(curr_p)})")

    lv = st.session_state.get('levels', {})
    opts = ["(請選擇...)"] + [f"{k} ({format_price(v)})" for k, v in lv.items() if k != 'close']
    
    def set_p(src, dst):
        label = st.session_state[src]
        for k, v in lv.items():
            if k in label: st.session_state[dst] = get_snapped_price(v)

    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        st.selectbox("進場參考", opts, key='s_ep', on_change=set_p, args=('s_ep', 'ep'))
        ep = st.number_input("進場價", key='ep', step=get_tick_step(st.session_state.get('curr', 100)))
    with pc2:
        st.selectbox("停損參考", opts, key='s_sl', on_change=set_p, args=('s_sl', 'sl'))
        sl = st.number_input("停損價", key='sl', step=get_tick_step(st.session_state.get('curr', 100)))
    with pc3:
        st.selectbox("停利參考", opts, key='s_tp', on_change=set_p, args=('s_tp', 'tp'))
        tp = st.number_input("停利價", key='tp', step=get_tick_step(st.session_state.get('curr', 100)))

    side = st.radio("方向", ["做多", "做空"], horizontal=True, key='t3_side')
    if st.button("計算損益"):
        risk = (ep-sl if side=="做多" else sl-ep)*1000
        gain = (tp-ep if side=="做多" else ep-tp)*1000
        if risk <= 0: st.error("停損設置錯誤")
        else:
            m1, m2 = st.columns(2)
            m1.metric("虧損風險", f"-${risk:,.0f}")
            m1.metric("預期獲利", f"+${gain:,.0f}")
            m2.metric("風報比", f"1 : {gain/risk:.2f}")

# ==========================================
# Tab 4: 🔍 盤後情報 (戰情連結)
# ==========================================
with tab4:
    st.header("🔍 盤後籌碼戰情室")
    t4_in = st.text_input("輸入代號:", value="2330", key="t4_input")
    _, ticker, code, name = get_stock_data_smart(t4_in)
    st.subheader(f"{code} {name} - 戰情連結")
    
    y_sym = f"{code}.TWO" if ".TWO" in ticker else code
    link_y = f"https://tw.stock.yahoo.com/quote/{y_sym}/institutional-trading"
    link_g = f"https://goodinfo.tw/tw/ShowBuySaleChart.asp?STOCK_ID={code}"
    link_a = f"https://www.cnyes.com/twstock/{code}/chip/institution"

    c1, c2, c3 = st.columns(3)
    c1.link_button("🟣 Yahoo 三大法人", link_y, use_container_width=True)
    c2.link_button("🔵 Goodinfo 法人買賣", link_g, use_container_width=True)
    c3.link_button("🟠 鉅亨網 籌碼分析", link_a, use_container_width=True)
