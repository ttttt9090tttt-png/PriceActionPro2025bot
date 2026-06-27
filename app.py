"""
ربات سیگنال‌دهی پرایس اکشن برای ارزهای دیجیتال
بر اساس قوانین فایل پرایس اکشن
نسخه 2.0 - پشتیبانی از ۱۵ ارز برتر
"""

import os
import time
import threading
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask
import json

# ============================================
# بخش ۱: تنظیمات اولیه
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8401730350:AAFDoYw9VF7KnZZzYQF6bGybzAT7vY75fnU")
CHAT_ID = os.getenv("CHAT_ID", "1186512882")

# ۱۵ ارز برتر کریپتو (بر اساس مارکت‌کپ)
TOP_CRYPTO = [
    "BTCUSDT",  # بیت‌کوین
    "ETHUSDT",  # اتریوم
    "BNBUSDT",  # بایننس کوین
    "SOLUSDT",  # سولانا
    "XRPUSDT",  # ریپل
    "ADAUSDT",  # کاردانو
    "DOGEUSDT", # دوج کوین
    "AVAXUSDT", # آوالانچ
    "DOTUSDT",  # پولکادات
    "LINKUSDT", # چین لینک
    "MATICUSDT",# پالیگان
    "LTCUSDT",  # لایت کوین
    "NEARUSDT", # نیار پروتکل
    "ATOMUSDT", # کازموس
    "XLMUSDT"   # استلار
]

TIMEFRAMES = ["15m", "1h", "4h"]  # تایم‌فریم‌های تحلیل
CHECK_INTERVAL = 300  # بررسی هر ۵ دقیقه
LOOKBACK_CANDLES = 100  # تعداد کندل‌های برگشتی برای تحلیل

app = Flask(__name__)
sent_signals = {}  # ذخیره سیگنال‌های ارسال شده

# ============================================
# بخش ۲: توابع کمکی و دریافت داده
# ============================================

def send_msg(text):
    """ارسال پیام به تلگرام"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": text},
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        print(f"❌ خطا در ارسال پیام: {e}")
        return False

def get_price_data(symbol, interval="1h", limit=100):
    """دریافت داده قیمت از Binance"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        response = requests.get(url, timeout=20)
        data = response.json()
        
        candles = []
        for candle in data:
            candles.append({
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "timestamp": datetime.fromtimestamp(candle[0] / 1000)
            })
        return candles
    except Exception as e:
        print(f"⚠️ خطا در دریافت {symbol}: {e}")
        return None

def ema(series, period):
    """محاسبه میانگین متحرک نمایی"""
    return series.ewm(span=period, adjust=False).mean()

def sma(series, period):
    """محاسبه میانگین متحرک ساده"""
    return series.rolling(window=period).mean()

# ============================================
# بخش ۳: تحلیلگر پرایس اکشن
# ============================================

class PriceActionAnalyzer:
    """تحلیلگر پرایس اکشن بر اساس قوانین فایل"""
    
    def __init__(self, candles):
        self.candles = candles
        self.df = pd.DataFrame(candles)
        self.last_price = self.df['close'].iloc[-1]
        
    def find_swing_points(self, lookback=20):
        """یافتن نقاط سوئینگ (سقف و کف)"""
        highs = []
        lows = []
        
        for i in range(3, len(self.df) - 3):
            # سوئینگ های (سقف)
            if (self.df['high'].iloc[i] > self.df['high'].iloc[i-1] and
                self.df['high'].iloc[i] > self.df['high'].iloc[i-2] and
                self.df['high'].iloc[i] > self.df['high'].iloc[i+1] and
                self.df['high'].iloc[i] > self.df['high'].iloc[i+2]):
                highs.append({
                    'level': self.df['high'].iloc[i],
                    'index': i,
                    'type': 'swing_high'
                })
            
            # سوئینگ لو (کف)
            if (self.df['low'].iloc[i] < self.df['low'].iloc[i-1] and
                self.df['low'].iloc[i] < self.df['low'].iloc[i-2] and
                self.df['low'].iloc[i] < self.df['low'].iloc[i+1] and
                self.df['low'].iloc[i] < self.df['low'].iloc[i+2]):
                lows.append({
                    'level': self.df['low'].iloc[i],
                    'index': i,
                    'type': 'swing_low'
                })
        
        return highs, lows
    
    def identify_trend(self):
        """شناسایی روند بازار"""
        highs, lows = self.find_swing_points(10)
        
        if len(highs) >= 2 and len(lows) >= 2:
            # بررسی HH و HL برای روند صعودی
            recent_highs = sorted(highs, key=lambda x: x['index'])[-3:]
            recent_lows = sorted(lows, key=lambda x: x['index'])[-3:]
            
            if len(recent_highs) >= 2 and len(recent_lows) >= 2:
                is_uptrend = (recent_highs[-1]['level'] > recent_highs[-2]['level'] and 
                             recent_lows[-1]['level'] > recent_lows[-2]['level'])
                is_downtrend = (recent_highs[-1]['level'] < recent_highs[-2]['level'] and 
                               recent_lows[-1]['level'] < recent_lows[-2]['level'])
                
                if is_uptrend:
                    return "UP"
                elif is_downtrend:
                    return "DOWN"
        
        return "SIDEWAYS"
    
    def find_support_resistance(self, lookback=20):
        """یافتن سطوح حمایت و مقاومت"""
        highs, lows = self.find_swing_points(lookback)
        
        # سطوح مقاومت (سقف‌های مهم)
        resistance_levels = []
        for h in highs:
            # بررسی اینکه قیمت چند بار به این سطح برخورد کرده
            touches = 0
            for candle in self.df.tail(lookback).iterrows():
                if abs(candle[1]['high'] - h['level']) / h['level'] < 0.003:
                    touches += 1
            if touches >= 2:
                resistance_levels.append({
                    'level': h['level'],
                    'touches': touches,
                    'strength': min(touches * 20, 100)
                })
        
        # سطوح حمایت (کف‌های مهم)
        support_levels = []
        for l in lows:
            touches = 0
            for candle in self.df.tail(lookback).iterrows():
                if abs(candle[1]['low'] - l['level']) / l['level'] < 0.003:
                    touches += 1
            if touches >= 2:
                support_levels.append({
                    'level': l['level'],
                    'touches': touches,
                    'strength': min(touches * 20, 100)
                })
        
        return support_levels, resistance_levels
    
    def check_candle_pattern(self, index=-1):
        """تشخیص الگوهای کندلی"""
        if len(self.df) < abs(index):
            return None
        
        candle = self.df.iloc[index]
        body = abs(candle['close'] - candle['open'])
        upper_shadow = candle['high'] - max(candle['close'], candle['open'])
        lower_shadow = min(candle['close'], candle['open']) - candle['low']
        
        patterns = []
        
        # ۱. چکش (Hammer) - صعودی
        if lower_shadow > 2 * body and upper_shadow < body * 0.3:
            patterns.append({
                'name': 'HAMMER',
                'direction': 'BULLISH',
                'strength': 80 if lower_shadow > 3 * body else 70
            })
        
        # ۲. شوتینگ استار (Shooting Star) - نزولی
        if upper_shadow > 2 * body and lower_shadow < body * 0.3:
            patterns.append({
                'name': 'SHOOTING_STAR',
                'direction': 'BEARISH',
                'strength': 80 if upper_shadow > 3 * body else 70
            })
        
        # ۳. اینگلفینگ صعودی (Bullish Engulfing)
        if index > 0:
            prev = self.df.iloc[index - 1]
            if (candle['close'] > candle['open'] and 
                prev['close'] < prev['open'] and
                candle['close'] > prev['open'] and
                candle['open'] < prev['close']):
                patterns.append({
                    'name': 'BULLISH_ENGULFING',
                    'direction': 'BULLISH',
                    'strength': 85
                })
            
            # ۴. اینگلفینگ نزولی (Bearish Engulfing)
            if (candle['close'] < candle['open'] and 
                prev['close'] > prev['open'] and
                candle['close'] < prev['open'] and
                candle['open'] > prev['close']):
                patterns.append({
                    'name': 'BEARISH_ENGULFING',
                    'direction': 'BEARISH',
                    'strength': 85
                })
        
        # ۵. سه سرباز سفید (Three White Soldiers)
        if index >= 2:
            c1, c2, c3 = self.df.iloc[index-2], self.df.iloc[index-1], candle
            if (c1['close'] > c1['open'] and c2['close'] > c2['open'] and 
                c3['close'] > c3['open'] and
                c2['close'] > c1['close'] and c3['close'] > c2['close']):
                patterns.append({
                    'name': 'THREE_WHITE_SOLDIERS',
                    'direction': 'BULLISH',
                    'strength': 90
                })
        
        # ۶. سه کلاغ سیاه (Three Black Crows)
        if index >= 2:
            c1, c2, c3 = self.df.iloc[index-2], self.df.iloc[index-1], candle
            if (c1['close'] < c1['open'] and c2['close'] < c2['open'] and 
                c3['close'] < c3['open'] and
                c2['close'] < c1['close'] and c3['close'] < c2['close']):
                patterns.append({
                    'name': 'THREE_BLACK_CROWS',
                    'direction': 'BEARISH',
                    'strength': 90
                })
        
        return patterns if patterns else None
    
    def calculate_risk_reward(self, entry_price, direction, support_levels, resistance_levels):
        """محاسبه نسبت ریسک به ریوارد"""
        if direction == "BUY":
            # حد ضرر: زیر نزدیک‌ترین سطح حمایت
            supports_below = [s['level'] for s in support_levels if s['level'] < entry_price]
            if supports_below:
                stop_loss = min(supports_below) * 0.998
            else:
                stop_loss = entry_price * 0.985
            
            # حد سود: نزدیک‌ترین مقاومت
            resistances_above = [r['level'] for r in resistance_levels if r['level'] > entry_price]
            if resistances_above:
                take_profit_1 = min(resistances_above) * 0.998
                take_profit_2 = max(resistances_above) * 0.998 if len(resistances_above) > 1 else take_profit_1 * 1.02
            else:
                take_profit_1 = entry_price * 1.02
                take_profit_2 = entry_price * 1.04
        
        else:  # SELL
            # حد ضرر: بالای نزدیک‌ترین سطح مقاومت
            resistances_above = [r['level'] for r in resistance_levels if r['level'] > entry_price]
            if resistances_above:
                stop_loss = max(resistances_above) * 1.002
            else:
                stop_loss = entry_price * 1.015
            
            # حد سود: نزدیک‌ترین حمایت
            supports_below = [s['level'] for s in support_levels if s['level'] < entry_price]
            if supports_below:
                take_profit_1 = max(supports_below) * 1.002
                take_profit_2 = min(supports_below) * 1.002 if len(supports_below) > 1 else take_profit_1 * 0.98
            else:
                take_profit_1 = entry_price * 0.98
                take_profit_2 = entry_price * 0.96
        
        risk = abs(entry_price - stop_loss)
        reward_1 = abs(take_profit_1 - entry_price)
        reward_2 = abs(take_profit_2 - entry_price)
        
        rr_1 = round(reward_1 / risk, 2) if risk > 0 else 0
        rr_2 = round(reward_2 / risk, 2) if risk > 0 else 0
        
        return {
            'stop_loss': round(stop_loss, 4),
            'take_profit_1': round(take_profit_1, 4),
            'take_profit_2': round(take_profit_2, 4),
            'risk_reward_1': rr_1,
            'risk_reward_2': rr_2,
            'risk_amount': round(risk, 4)
        }

# ============================================
# بخش ۴: شناسایی ستاپ‌های معاملاتی
# ============================================

def find_trading_setup(candles, symbol):
    """شناسایی ستاپ‌های معاملاتی پرایس اکشن"""
    analyzer = PriceActionAnalyzer(candles)
    
    # ۱. شناسایی روند
    trend = analyzer.identify_trend()
    
    # ۲. شناسایی سطوح حمایت و مقاومت
    support_levels, resistance_levels = analyzer.find_support_resistance()
    
    # ۳. بررسی الگوهای کندلی
    patterns = analyzer.check_candle_pattern()
    
    # ۴. قیمت فعلی
    current_price = analyzer.last_price
    
    setups = []
    
    # ==================== ستاپ TST (تست) ====================
    # قیمت به سطح حمایت/مقاومت رسیده و برمی‌گردد
    
    # TST برای خرید (تست حمایت)
    for support in support_levels:
        if abs(current_price - support['level']) / current_price < 0.005:  # نزدیک به حمایت
            # بررسی الگوی برگشتی صعودی
            if patterns:
                for pattern in patterns:
                    if pattern['direction'] == 'BULLISH' and pattern['strength'] >= 70:
                        # محاسبه R:R
                        rr_data = analyzer.calculate_risk_reward(
                            current_price, "BUY", support_levels, resistance_levels
                        )
                        if rr_data['risk_reward_1'] >= 1.5:
                            setups.append({
                                'type': 'TST',
                                'direction': 'BUY',
                                'entry': round(current_price, 4),
                                'setup': 'TST (تست حمایت)',
                                'pattern': pattern['name'],
                                'trend': trend,
                                'support_level': round(support['level'], 4),
                                **rr_data,
                                'strength': support['strength']
                            })
    
    # TST برای فروش (تست مقاومت)
    for resistance in resistance_levels:
        if abs(current_price - resistance['level']) / current_price < 0.005:
            if patterns:
                for pattern in patterns:
                    if pattern['direction'] == 'BEARISH' and pattern['strength'] >= 70:
                        rr_data = analyzer.calculate_risk_reward(
                            current_price, "SELL", support_levels, resistance_levels
                        )
                        if rr_data['risk_reward_1'] >= 1.5:
                            setups.append({
                                'type': 'TST',
                                'direction': 'SELL',
                                'entry': round(current_price, 4),
                                'setup': 'TST (تست مقاومت)',
                                'pattern': pattern['name'],
                                'trend': trend,
                                'resistance_level': round(resistance['level'], 4),
                                **rr_data,
                                'strength': resistance['strength']
                            })
    
    # ==================== ستاپ BOF (شکست و برگشت) ====================
    # قیمت سطح را می‌شکند اما برمی‌گردد
    
    # BOF برای خرید (شکست حمایت و برگشت)
    for support in support_levels:
        if abs(current_price - support['level']) / current_price < 0.002 and current_price < support['level']:
            # قیمت زیر حمایت (شکست) - بررسی برگشت
            if patterns:
                for pattern in patterns:
                    if pattern['direction'] == 'BULLISH':
                        rr_data = analyzer.calculate_risk_reward(
                            current_price, "BUY", support_levels, resistance_levels
                        )
                        if rr_data['risk_reward_1'] >= 2:
                            setups.append({
                                'type': 'BOF',
                                'direction': 'BUY',
                                'entry': round(current_price, 4),
                                'setup': 'BOF (شکست حمایت و برگشت)',
                                'pattern': pattern['name'],
                                'trend': trend,
                                'broken_level': round(support['level'], 4),
                                **rr_data,
                                'strength': support['strength'] + 10
                            })
    
    # BOF برای فروش (شکست مقاومت و برگشت)
    for resistance in resistance_levels:
        if abs(current_price - resistance['level']) / current_price < 0.002 and current_price > resistance['level']:
            if patterns:
                for pattern in patterns:
                    if pattern['direction'] == 'BEARISH':
                        rr_data = analyzer.calculate_risk_reward(
                            current_price, "SELL", support_levels, resistance_levels
                        )
                        if rr_data['risk_reward_1'] >= 2:
                            setups.append({
                                'type': 'BOF',
                                'direction': 'SELL',
                                'entry': round(current_price, 4),
                                'setup': 'BOF (شکست مقاومت و برگشت)',
                                'pattern': pattern['name'],
                                'trend': trend,
                                'broken_level': round(resistance['level'], 4),
                                **rr_data,
                                'strength': resistance['strength'] + 10
                            })
    
    # ==================== ستاپ BPB (پولیک) ====================
    # شکست سطح، پولیک و ادامه روند
    
    if trend == "UP":
        # شکست مقاومت، پولیک و ادامه صعود
        for resistance in resistance_levels:
            if current_price > resistance['level'] and current_price < resistance['level'] * 1.01:
                # قیمت بالای مقاومت - بررسی ادامه روند
                if patterns and any(p['direction'] == 'BULLISH' for p in patterns):
                    rr_data = analyzer.calculate_risk_reward(
                        current_price, "BUY", support_levels, resistance_levels
                    )
                    if rr_data['risk_reward_1'] >= 2:
                        setups.append({
                            'type': 'BPB',
                            'direction': 'BUY',
                            'entry': round(current_price, 4),
                            'setup': 'BPB (شکست مقاومت و پولیک)',
                            'pattern': 'BREAKOUT_RETEST',
                            'trend': trend,
                            'broken_level': round(resistance['level'], 4),
                            **rr_data,
                            'strength': resistance['strength'] + 15
                        })
    
    elif trend == "DOWN":
        # شکست حمایت، پولیک و ادامه نزول
        for support in support_levels:
            if current_price < support['level'] and current_price > support['level'] * 0.99:
                if patterns and any(p['direction'] == 'BEARISH' for p in patterns):
                    rr_data = analyzer.calculate_risk_reward(
                        current_price, "SELL", support_levels, resistance_levels
                    )
                    if rr_data['risk_reward_1'] >= 2:
                        setups.append({
                            'type': 'BPB',
                            'direction': 'SELL',
                            'entry': round(current_price, 4),
                            'setup': 'BPB (شکست حمایت و پولیک)',
                            'pattern': 'BREAKOUT_RETEST',
                            'trend': trend,
                            'broken_level': round(support['level'], 4),
                            **rr_data,
                            'strength': support['strength'] + 15
                        })
    
    return setups

# ============================================
# بخش ۵: مدیریت سیگنال‌ها و ارسال
# ============================================

def generate_signal_message(symbol, timeframe, setup):
    """تولید پیام سیگنال برای تلگرام"""
    direction_icon = "🟢" if setup['direction'] == 'BUY' else "🔴"
    direction_text = "خرید (Long)" if setup['direction'] == 'BUY' else "فروش (Short)"
    
    # شکلک‌های ستاپ
    setup_icons = {
        'TST': '📌',
        'BOF': '🔄',
        'BPB': '🚀'
    }
    setup_icon = setup_icons.get(setup['type'], '📊')
    
    # محاسبه R:R
    rr_display = f"{setup['risk_reward_1']:.2f}"
    if setup['risk_reward_2'] > setup['risk_reward_1']:
        rr_display += f" / {setup['risk_reward_2']:.2f}"
    
    msg = f"""
{setup_icon} **سیگنال پرایس اکشن - {symbol}**

**جهت:** {direction_icon} {direction_text}
**ستاپ:** {setup['setup']}
**تایم‌فریم:** {timeframe}

📊 **نقاط کلیدی:**
💰 **قیمت ورود:** {setup['entry']}
🛑 **حد ضرر (SL):** {setup['stop_loss']}
🎯 **تارگت ۱ (TP1):** {setup['take_profit_1']}
🎯 **تارگت ۲ (TP2):** {setup['take_profit_2']}

⚖️ **نسبت ریسک به ریوارد (R:R):** {rr_display}
📈 **الگوی کندلی:** {setup.get('pattern', 'N/A')}
📉 **روند بازار:** {setup['trend']}
💪 **قدرت سیگنال:** {setup['strength']}%

⚠️ **مدیریت ریسک:**
• حداکثر ریسک: ۲% سرمایه
• حداقل R:R: {setup['risk_reward_1']}
• استفاده از حد ضرر الزامی است

⏰ **زمان سیگنال:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

def scan_and_send_signals():
    """بررسی تمام ارزها و ارسال سیگنال"""
    print(f"🔄 شروع اسکن در {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    for symbol in TOP_CRYPTO:
        for timeframe in TIMEFRAMES:
            try:
                # دریافت داده
                candles = get_price_data(symbol, timeframe, LOOKBACK_CANDLES)
                if not candles:
                    continue
                
                # یافتن ستاپ‌ها
                setups = find_trading_setup(candles, symbol)
                
                for setup in setups:
                    # کلید منحصر‌به‌فرد برای هر سیگنال
                    key = f"{symbol}_{timeframe}_{setup['type']}_{setup['direction']}"
                    
                    # جلوگیری از ارسال سیگنال تکراری
                    if sent_signals.get(key) == setup['entry']:
                        continue
                    
                    # ارسال سیگنال
                    msg = generate_signal_message(symbol, timeframe, setup)
                    if send_msg(msg):
                        sent_signals[key] = setup['entry']
                        print(f"✅ سیگنال ارسال شد: {symbol} - {timeframe} - {setup['type']}")
                        time.sleep(1)  # جلوگیری از اسپم
                        
            except Exception as e:
                print(f"❌ خطا در {symbol} {timeframe}: {e}")
                continue
    
    # پاک کردن سیگنال‌های قدیمی (بیش از ۲۴ ساعت)
    if len(sent_signals) > 100:
        sent_signals.clear()

# ============================================
# بخش ۶: وب‌سرور و اجرای همزمان
# ============================================

@app.route('/')
def home():
    """صفحه اصلی برای زنده نگه‌داشتن ربات"""
    return """
    <h1>🤖 ربات پرایس اکشن ۲۰۲۶</h1>
    <p>وضعیت: <span style="color:green">✅ فعال</span></p>
    <p>ارزهای تحت پوشش: {} ارز</p>
    <p>تایم‌فریم‌ها: {}</p>
    <p>آخرین اسکن: {}</p>
    """.format(
        len(TOP_CRYPTO),
        ', '.join(TIMEFRAMES),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

@app.route('/ping')
def ping():
    """آدرس پینگ برای کران‌جاب‌ها"""
    return "🏓 Pong"

@app.route('/manual/<symbol>')
def manual_signal(symbol):
    """ارسال دستی سیگنال برای یک ارز"""
    if symbol not in TOP_CRYPTO:
        return f"❌ {symbol} در لیست ارزها وجود ندارد"
    
    candles = get_price_data(symbol, "1h", LOOKBACK_CANDLES)
    if not candles:
        return f"❌ خطا در دریافت داده {symbol}"
    
    setups = find_trading_setup(candles, symbol)
    if not setups:
        return f"ℹ️ هیچ سیگنالی برای {symbol} یافت نشد"
    
    for setup in setups[:3]:  # حداکثر ۳ سیگنال
        msg = generate_signal_message(symbol, "1h", setup)
        send_msg(msg)
    
    return f"✅ سیگنال‌های {symbol} ارسال شد"

def run_scan_loop():
    """حلقه اصلی اسکن"""
    print("🚀 ربات پرایس اکشن شروع به کار کرد...")
    print(f"📊 پوشش {len(TOP_CRYPTO)} ارز برتر")
    print(f"⏱️ تایم‌فریم‌ها: {', '.join(TIMEFRAMES)}")
    print(f"🔄 بررسی هر {CHECK_INTERVAL // 60} دقیقه")
    
    while True:
        try:
            scan_and_send_signals()
        except Exception as e:
            print(f"❌ خطا در حلقه اصلی: {e}")
        
        time.sleep(CHECK_INTERVAL)

# ============================================
# بخش ۷: اجرای اصلی
# ============================================

if __name__ == "__main__":
    # اجرای ربات در ترد جداگانه
    worker = threading.Thread(target=run_scan_loop, daemon=True)
    worker.start()
    
    # راه‌اندازی وب‌سرور
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 وب‌سرور روی پورت {port} راه‌اندازی شد...")
    app.run(host="0.0.0.0", port=port)
