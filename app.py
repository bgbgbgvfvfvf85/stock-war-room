import streamlit as st
import pandas as pd
import requests
import twstock
import yfinance as yf
import ssl
import urllib3
import os
import streamlit.components.v1 as components
from datetime import datetime, timedelta, timezone
import plotly.graph_objects as go

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
# 🌟 UX 優化：點擊輸入框自動全選
# ==========================================
components.html(
    """
    <script>
    const doc = window.parent.document;
    function addSelectOnFocus() {
        const inputs = doc.querySelectorAll('input[type="number"], input[type="text"]');
        inputs.forEach(input => {
            if (!input.dataset.autoSelectBound) {
                input.addEventListener('focus', function() { this.select(); });
                input.addEventListener('click', function() { this.select(); });
                input.dataset.autoSelectBound = 'true';
            }
        });
    }
    addSelectOnFocus();
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
# 核心輔助函式
# ==========================================

def get_snapped_price(price):
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
    if pd.isna(price): return "-"
    p = get_snapped_price(float(price))
    if p < 50: fmt = "{:.2f}"
    elif p < 500: fmt = "{:.1f}"
    else: fmt = "{:.0f}"
    return fmt.format(p)

def get_tick_step(price):
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
        # 處理 yfinance 新版的 MultiIndex 問題
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
            
        # 🌟 核心修復：強制剔除含有 NaN (幽靈資料) 的 K 線
        if not df.empty:
            df = df.dropna(subset=['Close', 'High', 'Low'])
            
        if df.empty and ticker.endswith('.TW'):
            ticker_two = f"{code}.TWO"
            df_two = yf.download(ticker_two, period=period, progress=False)
            if isinstance(df_two.columns, pd.MultiIndex): 
                df_two.columns = df_two.columns.get_level_values(0)
                
            # 🌟 核心修復：上櫃股票一樣要剔除空值
            if not df_two.empty:
                df_two = df_two.dropna(subset=['Close', 'High', 'Low'])
                
            if not df_two.empty: 
                new_name = twstock.codes[code].name if code in twstock.codes else name
                return df_two, ticker_two, code, new_name
    except:
        return pd.DataFrame(), ticker, code, name
    return df, ticker, code, name

def calculate_tech_levels(df):
    if df.empty or len(df) < 2: return {}
    
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    today_str = now_tw.strftime('%Y-%m-%d')
    
    df['date_str'] = df.index.astype(str).str[:10]
    
    if now_tw.hour < 14:
        df_cdp = df[df['date_str'] < today_str]
    else:
        df_cdp = df[df['date_str'] <= today_str]
        
    if not df_cdp.empty:
        cdp_candle = df_cdp.iloc[-1]
        cdp_date = df_cdp['date_str'].iloc[-1]
    else:
        cdp_candle = df.iloc[-1]
        cdp_date = df['date_str'].iloc[-1]
        
    c_cdp = float(cdp_candle['Close'])
    h_cdp = float(cdp_candle['High'])
    l_cdp = float(cdp_candle['Low'])
    
    cdp = (h_cdp + l_cdp + 2 * c_cdp) / 4
    ah = cdp + (h_cdp - l_cdp)
    nh = cdp * 2 - l_cdp
    nl = cdp * 2 - h_cdp
    al = cdp - (h_cdp - l_cdp)

    last_live = df.iloc[-1]
    c_live = float(last_live['Close'])
    
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    std = df['Close'].rolling(20).std().iloc[-1]
    ma20 = c_live if pd.isna(ma20) else ma20
    std = 0 if pd.isna(std) else std
    
    return {
        'close': c_live, 
        'cdp_date': cdp_date,
        'cdp': cdp, 'ah': ah, 'nh': nh, 'nl': nl, 'al': al,
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
            
            st.success(f"📊 {code} {name} (即時現價/收盤: {format_price(lv['close'])})")
            
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.markdown(f"### 1. CDP 逆勢操作\n*(基準日: {lv.get('cdp_date', '')})*")
                st.metric("第二壓力 (AH)", format_price(lv['ah']))
                st.metric("第一壓力 (NH)", format_price(lv['nh']))
                st.metric("第一支撐 (NL)", format_price(lv['nl']))
                st.metric("第二支撐 (AL)", format_price(lv['al']))
            with rc2:
                st.markdown("### 2. 布林通道\n*(即時連動)*")
                st.metric("上軌", format_price(lv['bb_up']))
                st.metric("中軌", format_price(lv['ma20']))
                st.metric("下軌", format_price(lv['bb_low']))
            with rc3:
                st.markdown("### 3. 斐波那契\n*(區間最高/最低)*")
                st.write(f"區間高: {format_price(mx)} / 低: {format_price(mn)}")
                st.metric("回檔 0.382", format_price(mx - diff*0.382))
                st.metric("回檔 0.618", format_price(mx - diff*0.618))

# ==========================================
# Tab 2: ⚖️ 停損停利試算
# ==========================================
with tab2:
    st.subheader("⚖️ 停損停利試算 (% 數換算價格)")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        trade_dir = st.radio("方向", ["做多", "做空"], horizontal=True)
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
    st.header("💰 風控試算")
    tc1, tc2 = st.columns([1, 4])
    t3_in = tc1.text_input("代號 (按 Enter 讀取)", value="2330", key="t3_input_real")
    
    df, _, c, n = get_stock_data_smart(t3_in)
    
    if not df.empty:
        curr_price = float(df.iloc[-1]['Close'])
        lv = calculate_tech_levels(df)
        if 'last_code' not in st.session_state or st.session_state['last_code'] != c:
            st.session_state['levels'] = lv
            st.session_state['curr'] = curr_price
            st.session_state['last_code'] = c
            st.success(f"已載入 {c} {n} 現價: {format_price(curr_price)}")

    if 'levels' not in st.session_state: 
        st.session_state.update({'levels': {}, 'curr': 100.0})

    step_val = get_tick_step(st.session_state.get('curr', 100.0))
    fmt_str = "%.2f"
    if step_val >= 1: fmt_str = "%.0f"
    elif step_val == 0.5: fmt_str = "%.1f"
    
    lv = st.session_state.get('levels', {})
    opts_dict = {}
    if lv:
        opts_dict = {
            f"現價 ({format_price(lv['close'])})": lv['close'],
            f"CDP 2壓 ({format_price(lv['ah'])})": lv['ah'],
            f"CDP 1壓 ({format_price(lv['nh'])})": lv['nh'],
            f"CDP 中軸 ({format_price(lv['cdp'])})": lv['cdp'],
            f"CDP 1撐 ({format_price(lv['nl'])})": lv['nl'],
            f"CDP 2撐 ({format_price(lv['al'])})": lv['al'],
            f"布林上軌 ({format_price(lv['bb_up'])})": lv['bb_up'],
            f"布林中軌 ({format_price(lv['ma20'])})": lv['ma20'],
            f"布林下軌 ({format_price(lv['bb_low'])})": lv['bb_low'],
        }
    
    opts = ["(請選擇...)"] + list(opts_dict.keys())

    def set_price(k, target_k):
        label = st.session_state[k]
        if label in opts_dict:
            st.session_state[target_k] = get_snapped_price(opts_dict[label])

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
# Tab 4: 盤後情報 (戰情連結 + 恐懼貪婪指數)
# ==========================================
with tab4:
    st.header("🔍 大盤天氣與盤後情報")
    
    # --- 🌟 恐懼與貪婪指數儀表板 ---
    st.subheader("🌐 巨觀環境：市場恐懼與貪婪指數 (Fear & Greed)")
    try:
        # 直接抓取 CNN 官方 API 資料
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Referer": "https://edition.cnn.com/"
        }
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data = res.json()
            score = data["fear_and_greed"]["score"]
            prev_score = data["fear_and_greed"]["previous_close"]
            diff = score - prev_score
            
            # 判斷分數落點並給予對應的警示與顏色
            if score <= 24:
                status_text = "🔵 **極度恐懼 (Extreme Fear)**：市場過度悲觀，通常是超跌或潛在買點"
            elif score <= 44:
                status_text = "🟢 **恐懼 (Fear)**：市場情緒保守，資金退潮觀望"
            elif score <= 55:
                status_text = "🟡 **中立 (Neutral)**：多空力道平衡，無明顯偏好"
            elif score <= 75:
                status_text = "🟠 **貪婪 (Greed)**：市場情緒樂觀，動能強勁，適合順勢做多"
            else:
                status_text = "🔴 **極度貪婪 (Extreme Greed)**：市場嚴重過熱，請留意反轉與獲利了結賣壓"
            
            vc1, vc2 = st.columns([1, 2])
            with vc1:
                # 顯示分數 (越高越貪婪，越低越恐懼)
                st.metric("CNN 恐懼與貪婪指數", f"{score:.0f} / 100", f"{diff:.0f}")
                st.info(status_text)
            
            with vc2:
                # 繪製指數歷史走勢圖 (0~100)
                hist_data = data.get("fear_and_greed_historical", {}).get("data", [])
                if hist_data:
                    df_hist = pd.DataFrame(hist_data)
                    df_hist['x'] = pd.to_datetime(df_hist['x'], unit='ms')
                    
                    fig_fg = go.Figure()
                    fig_fg.add_trace(go.Scatter(
                        x=df_hist['x'], y=df_hist['y'], 
                        mode='lines', line=dict(color='#00BFFF', width=2),
                        fill='tozeroy', fillcolor='rgba(0, 191, 255, 0.1)'
                    ))
                    # 畫上區間警戒線 (25 與 75)
                    fig_fg.add_hline(y=25, line_dash="dot", line_color="blue")
                    fig_fg.add_hline(y=75, line_dash="dot", line_color="red")
                    
                    fig_fg.update_layout(
                        height=180, margin=dict(l=0, r=0, t=10, b=10),
                        yaxis=dict(range=[0, 100], tickvals=[0, 25, 50, 75, 100]),
                        xaxis=dict(visible=False),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_fg, use_container_width=True, config={'displayModeBar': False})
        else:
            st.warning("⚠️ 暫時無法連線至 CNN 恐懼貪婪指數資料庫。")
            
    except Exception as e:
        st.warning("⚠️ 讀取恐懼貪婪指數時發生錯誤，請稍後再試。")

    st.markdown("---")
    
    # --- 原本的個股籌碼戰情連結 ---
    st.subheader("🔍 個股籌碼戰情")
    with st.form(key='t4_form'):
        col1, col2 = st.columns([1, 4])
        with col1:
            t4_in = st.text_input("輸入個股代號 (按 Enter):", value="2330")
        with col2:
            st.write("")
            st.write("")
            submit_t4 = st.form_submit_button("搜尋連結")
    
    _, ticker, code, name = get_stock_data_smart(t4_in)
    
    st.markdown(f"**{code} {name}** - 外部戰情連結")
    st.write("") 

    yahoo_sym = f"{code}.TWO" if ".TWO" in ticker else code
    link_yahoo = f"https://tw.stock.yahoo.com/quote/{yahoo_sym}/institutional-trading"
    link_goodinfo = f"https://goodinfo.tw/tw/ShowBuySaleChart.asp?STOCK_ID={code}"
    link_anue = f"https://www.cnyes.com/twstock/{code}/chip/institution"

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
