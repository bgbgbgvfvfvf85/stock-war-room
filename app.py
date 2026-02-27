import streamlit as st
import pandas as pd
import requests
import twstock
import yfinance as yf
import ssl
import urllib3
import os
import streamlit.components.v1 as components  # 新增：用來注入前端程式碼

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

# ==========================================
# 🌟 UX 優化：點擊輸入框自動全選 (手機版必備)
# ==========================================
components.html(
    """
    <script>
    const doc = window.parent.document;
    function addSelectOnFocus() {
        const inputs = doc.querySelectorAll('input[type="number"], input[type="text"]');
        inputs.forEach(input => {
            if (!input.dataset.autoSelectBound) {
                // 當獲得焦點或被點擊時，自動全選內容
                input.addEventListener('focus', function() { this.select(); });
                input.addEventListener('click', function() { this.select(); });
                input.dataset.autoSelectBound = 'true';
            }
        });
    }
    // 初始執行
    addSelectOnFocus();
    // 監聽網頁更新 (解決 Streamlit 重新渲染後失效的問題)
    const observer = new MutationObserver(addSelectOnFocus);
    observer.observe(doc.body, { childList: true, subtree: true });
    </script>
    """,
    height=0
)

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
        q_in = c1.text_input("輸入代號 (按 Enter):", value="2330")
        lookback = c2.slider("斐波那契區間", 30, 120, 60)
        run_1 = st.form_submit_button("計算關鍵點位") 

    if run_1 or q_in:
        df, ticker, code, name = get_stock_data_smart(q_in)
        if not df.empty:
            lv = calculate_tech_levels(df)
            recent = df[-lookback:]
            mx, mn = float(recent['High'].max()), float(recent['Low'].min())
            diff = mx - mn
            st.success(f"📊 {code} {name} (收盤: {format_price(lv['close'])})")
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.markdown("### 1. CDP 逆勢操作")
                st.metric("第二壓力 (AH)", format_price(lv['ah']))
                st.metric("第一壓力 (NH)", format_price(lv['nh']))
                st.metric("第一支撐 (NL)", format_price(lv['nl']))
                st.metric("第二支撐 (AL)", format_price(lv['al']))
            with rc2:
                st.markdown("### 2. 布林通道")
                st.metric("上軌", format_price(
