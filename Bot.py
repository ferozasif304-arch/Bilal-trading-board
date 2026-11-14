import asyncio
‎import os
‎import json
‎import logging
‎import time
‎import re
‎from decimal import Decimal
‎from dataclasses import dataclass, asdict
‎from typing import Dict, List, Optional, Tuple
‎from contextlib import asynccontextmanager
‎from dotenv import load_dotenv
‎from fastapi import FastAPI, Request, Response
‎from twilio.twiml.messaging_response import MessagingResponse
‎from twilio.rest import Client
‎import uvicorn
‎import ccxt.pro as ccxt_pro
‎from openai import OpenAI
‎
‎load_dotenv()
‎
‎# --- ENTERPRISE PRODUCTION LOGGING ---
‎logging.basicConfig(
‎    level=logging.INFO,
‎    format='%(asctime)s | [ULTIMATE-PRO-SCALPER] | %(levelname)s | %(message)s',
‎    handlers=[
‎        logging.FileHandler("elite_trading_engine.log", encoding="utf-8"),
‎        logging.StreamHandler()
‎    ]
‎)
‎
‎STATE_FILE = "trading_state.json"
‎
‎@dataclass
‎class Position:
‎    symbol: str
‎    side: str  # "long" या "short"
‎    entry_price: float
‎    size: float
‎    sl_price: float
‎    tp_price: float
‎    strategy: str
‎    highest_price: float
‎    lowest_price: float
‎    timestamp: float
‎    initial_margin: float
‎
‎
‎class CompoundingRiskManager:
‎    """$10 से $100 तक तेजी से और सुरक्षित तरीके से कंपाउंडिंग करने के लिए एडवांस्ड रिस्क सिस्टम"""
‎    def __init__(self, target_goal: float = 100.0, base_risk_pct: float = 0.05, leverage: int = 10):
‎        self.target_goal = target_goal
‎        self.base_risk_pct = Decimal(str(base_risk_pct))
‎        self.leverage = leverage
‎        self.consecutive_losses = 0
‎        self.daily_drawdown = 0.0
‎
‎    def set_target_goal(self, goal: float):
‎        self.target_goal = goal
‎        logging.info(f"🎯 Target Goal Updated to: ${goal}")
‎
‎    def calculate_compound_margin(self, total_equity: float, free_usdt: float) -> float:
‎        try:
‎            equity_dec = Decimal(str(total_equity))
‎            free_dec = Decimal(str(free_usdt))
‎            if free_dec <= 0 or equity_dec <= 0:
‎                return 0.0
‎            
‎            # कंपाउंडिंग लॉजिक: जैसे-जैसे फंड बढ़ेगा, पोजीशन साइज स्मार्टली स्केल होगा
‎            calculated_margin = equity_dec * self.base_risk_pct
‎            min_safe_margin = max(Decimal("1.5"), Decimal("5.2") / Decimal(str(self.leverage)))
‎            final_margin = max(calculated_margin, min_safe_margin)
‎            
‎            # छोटे अकाउंट के लिए सेफ कैप (फ्री USDT का अधिकतम 35%)
‎            max_allowed = free_dec * Decimal("0.35")
‎            return float(min(final_margin, max_allowed))
‎        except Exception as e:
‎            logging.error(f"Compound Margin Calculation Error: {e}")
‎            return 0.0
‎
‎    def evaluate_circuit_breaker(self, pnl_pct: float) -> bool:
‎        if pnl_pct < 0:
‎            self.consecutive_losses += 1
‎            self.daily_drawdown += abs(pnl_pct)
‎        else:
‎            self.consecutive_losses = 0
‎        
‎        if self.consecutive_losses >= 3 or self.daily_drawdown >= 12.0:
‎            logging.critical("🚨 CIRCUIT BREAKER TRIPPED! Protecting capital from drawdown.")
‎            return True
‎        return False
‎
‎
‎class InstitutionalSignalEngine:
‎    """1M और 5M मल्टी-टाइमफ्रेम और फेकआउट प्रूफ इंडिकेटर इंजन"""
‎    @staticmethod
‎    def compute_indicators(ohlcv_1m: List[list], ohlcv_5m: List[list]) -> dict:
‎        if not ohlcv_1m or len(ohlcv_1m) < 30 or not ohlcv_5m or len(ohlcv_5m) < 12:
‎            return {}
‎
‎        try:
‎            closes_1m = [c[4] for c in ohlcv_1m]
‎            highs_1m = [c[2] for c in ohlcv_1m]
‎            lows_1m = [c[3] for c in ohlcv_1m]
‎            volumes_1m = [c[5] for c in ohlcv_1m]
‎
‎            closes_5m = [c[4] for c in ohlcv_5m]
‎            ema_5m_fast = sum(closes_5m[-3:]) / 3
‎            ema_5m_slow = sum(closes_5m[-8:]) / 8
‎            is_5m_bullish = ema_5m_fast > ema_5m_slow
‎            is_5m_bearish = ema_5m_fast < ema_5m_slow
‎
‎            tr_list = [max(highs_1m[i]-lows_1m[i], abs(highs_1m[i]-closes_1m[i-1]), abs(lows_1m[i]-closes_1m[i-1])) for i in range(1, len(ohlcv_1m))]
‎            atr = sum(tr_list[-8:]) / 8 if len(tr_list) >= 8 else (highs_1m[-1] - lows_1m[-1])
‎
‎            ema_3 = sum(closes_1m[-3:]) / 3
‎            ema_9 = sum(closes_1m[-9:]) / 9
‎
‎            gains, losses = 0.0, 0.0
‎            for i in range(-8, 0):
‎                diff = closes_1m[i] - closes_1m[i-1]
‎                if diff > 0: gains += diff
‎                else: losses += abs(diff)
‎            avg_gain = gains / 8
‎            avg_loss = losses / 8
‎            rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
‎
‎            avg_vol = sum(volumes_1m[-12:-1]) / 11 if len(volumes_1m) >= 12 else volumes_1m[-1]
‎            vol_ratio = volumes_1m[-1] / avg_vol if avg_vol > 0 else 1.0
‎
‎            return {
‎                "atr": atr, "ema_3": ema_3, "ema_9": ema_9,
‎                "rsi": rsi, "vol_ratio": vol_ratio, "current_close": closes_1m[-1],
‎                "is_5m_bullish": is_5m_bullish, "is_5m_bearish": is_5m_bearish
‎            }
‎        except Exception as e:
‎            logging.error(f"Indicator Calculation Error: {e}")
‎            return {}
‎
‎    @staticmethod
‎    def evaluate_market_direction(ind: dict, news_sentiment: str) -> Tuple[str, str, float]:
‎        if not ind:
‎            return "NONE", "NONE", 0.0
‎
‎        is_1m_bullish = ind["ema_3"] > ind["ema_9"]
‎        is_1m_bearish = ind["ema_3"] < ind["ema_9"]
‎        is_volume_confirmed = ind["vol_ratio"] > 1.35
‎
‎        # Long Strategy
‎        if is_1m_bullish and ind["is_5m_bullish"] and 40 <= ind["rsi"] <= 68 and is_volume_confirmed and news_sentiment != "BEARISH":
‎            return "Professional 1M Momentum Long ⚡", "long", ind["atr"]
‎
‎        # Short Strategy
‎        if is_1m_bearish and ind["is_5m_bearish"] and 32 <= ind["rsi"] <= 60 and is_volume_confirmed and news_sentiment != "BULLISH":
‎            return "Professional 1M Breakdown Short 📉", "short", ind["atr"]
‎
‎        return "NONE", "NONE", ind.get("atr", 0.0)
‎
‎
‎class BinanceExchangeHandler:
‎    def __init__(self):
‎        is_testnet = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
‎        self.exchange = ccxt_pro.binance({
‎            'apiKey': os.getenv("BINANCE_API_KEY"),
‎            'secret': os.getenv("BINANCE_SECRET_KEY"),
‎            'enableRateLimit': True,
‎            'timeout': 15000,
‎            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
‎        })
‎        if is_testnet:
‎            self.exchange.set_sandbox_mode(True)
‎            logging.warning("⚠️ [MODE] Running on BINANCE TESTNET.")
‎        else:
‎            logging.info("🟢 [MODE] Running on BINANCE LIVE.")
‎
‎    async def get_account_summary(self) -> Tuple[float, float]:
‎        try:
‎            balance = await self.exchange.fetch_balance()
‎            total_equity = float(balance.get('total', {}).get('USDT', 0.0))
‎            free_usdt = float(balance.get('USDT', {}).get('free', 0.0))
‎            return total_equity, free_usdt
‎        except Exception as e:
‎            logging.error(f"Balance Fetch Error: {e}")
‎            return 0.0, 0.0
‎
‎    async def execute_order(self, symbol: str, side: str, price: float, margin: float, leverage: int, atr: float, strategy: str) -> Optional[Position]:
‎        try:
‎            raw_size = (margin * leverage) / price
‎            size = float(self.exchange.amount_to_precision(symbol, raw_size))
‎            
‎            notional_value = size * price
‎            if notional_value < 5.2:
‎                logging.warning(f"⚠️ Notional value {notional_value} below exchange minimum for {symbol}.")
‎                return None
‎
‎            try:
‎                await self.exchange.set_leverage(leverage, symbol)
‎            except Exception:
‎                pass
‎
‎            if side == "long":
‎                order = await self.exchange.create_market_buy_order(symbol, size)
‎                entry = float(order.get('average', price))
‎                sl = float(self.exchange.price_to_precision(symbol, entry - (atr * 1.1)))
‎                tp = float(self.exchange.price_to_precision(symbol, entry + (atr * 2.8)))
‎                
‎                # Server-Side Bracket Orders
‎                await self.exchange.create_order(symbol, 'STOP_MARKET', 'sell', size, None, {'stopPrice': sl, 'reduceOnly': True})
‎                await self.exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'sell', size, None, {'stopPrice': tp, 'reduceOnly': True})
‎            else:
‎                order = await self.exchange.create_market_sell_order(symbol, size)
‎                entry = float(order.get('average', price))
‎                sl = float(self.exchange.price_to_precision(symbol, entry + (atr * 1.1)))
‎                tp = float(self.exchange.price_to_precision(symbol, entry - (atr * 2.8)))
‎                
‎                # Server-Side Bracket Orders
‎                await self.exchange.create_order(symbol, 'STOP_MARKET', 'buy', size, None, {'stopPrice': sl, 'reduceOnly': True})
‎                await self.exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'buy', size, None, {'stopPrice': tp, 'reduceOnly': True})
‎
‎            return Position(
‎                symbol=symbol, side=side, entry_price=entry, size=size, 
‎                sl_price=sl, tp_price=tp, strategy=strategy, 
‎                highest_price=entry, lowest_price=entry, timestamp=time.time(), initial_margin=margin
‎            )
‎        except Exception as e:
‎            logging.error(f"Execution Error ({side}) on {symbol}: {e}")
‎            return None
‎
‎    async def update_stop_loss(self, symbol: str, side: str, size: str, new_sl: float):
‎        try:
‎            orders = await self.exchange.fetch_open_orders(symbol)
‎            for o in orders:
‎                if o['type'] == 'STOP_MARKET':
‎                    await self.exchange.cancel_order(o['id'], symbol)
‎            precision_sl = float(self.exchange.price_to_precision(symbol, new_sl))
‎            order_side = 'sell' if side == 'long' else 'buy'
‎            await self.exchange.create_order(symbol, 'STOP_MARKET', order_side, size, None, {'stopPrice': precision_sl, 'reduceOnly': True})
‎        except Exception as e:
‎            logging.error(f"Trailing SL Update Error {symbol}: {e}")
‎
‎    async def close(self):
‎        try:
‎            await self.exchange.close()
‎        except Exception:
‎            pass
‎
‎
‎class UltimateTradingEngine:
‎    def __init__(self):
‎        self.exchange_handler = BinanceExchangeHandler()
‎        self.risk_manager = CompoundingRiskManager()
‎        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
‎        self.twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")) if os.getenv("TWILIO_ACCOUNT_SID") else None
‎        
‎        self.symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT']
‎        self.active_positions: Dict[str, Position] = {}
‎        self.is_running = False
‎        self.load_state()
‎
‎    def save_state(self):
‎        try:
‎            state_data = {sym: asdict(pos) for sym, pos in self.active_positions.items()}
‎            with open(STATE_FILE, "w") as f:
‎                json.dump(state_data, f)
‎        except Exception as e:
‎            logging.error(f"State Save Error: {e}")
‎
‎    def load_state(self):
‎        try:
‎            if os.path.exists(STATE_FILE):
‎                with open(STATE_FILE, "r") as f:
‎                    data = json.load(f)
‎                    self.active_positions = {sym: Position(**p) for sym, p in data.items()}
‎                    logging.info(f"📂 Restored {len(self.active_positions)} active positions from state.")
‎        except Exception as e:
‎            logging.error(f"State Load Error: {e}")
‎
‎    async def send_whatsapp(self, message: str):
‎        logging.info(f"WHATSAPP: {message}")
‎        if self.twilio_client and os.getenv("TWILIO_TO_PHONE") and os.getenv("TWILIO_FROM_PHONE"):
‎            try:
‎                to_phone = os.getenv("TWILIO_TO_PHONE")
‎                from_phone = os.getenv("TWILIO_FROM_PHONE")
‎                if not to_phone.startswith("whatsapp:"): to_phone = f"whatsapp:{to_phone}"
‎                if not from_phone.startswith("whatsapp:"): from_phone = f"whatsapp:{from_phone}"
‎                self.twilio_client.messages.create(body=message, from_=from_phone, to=to_phone)
‎            except Exception as e:
‎                logging.error(f"WhatsApp Dispatch Error: {e}")
‎
‎    async def fetch_news_sentiment(self, symbol: str) -> str:
‎        if not self.openai_client:
‎            return "NEUTRAL"
‎        try:
‎            coin = symbol.split('/')[0]
‎            response = self.openai_client.chat.completions.create(
‎                model="gpt-4o-mini",
‎                messages=[
‎                    {"role": "system", "content": "Output only one word: BULLISH, BEARISH, or NEUTRAL."},
‎                    {"role": "user", "content": f"Assess instant 1-minute sentiment for {coin}/USDT futures."}
‎                ],
‎                max_tokens=6,
‎                temperature=0.1
‎            )
‎            val = response.choices[0].message.content.strip().upper()
‎            return val if val in ["BULLISH", "BEARISH", "NEUTRAL"] else "NEUTRAL"
‎        except Exception:
‎            return "NEUTRAL"
‎
‎    async def run_loop(self):
‎        self.is_running = True
‎        logging.info("🚀 [FINAL ENGINE] Autonomous 1M Scalping Loop Online.")
‎
‎        while self.is_running:
‎            try:
‎                for symbol in self.symbols:
‎                    if not self.is_running: break
‎
‎                    # रेट लिमिट से बचने और स्मूथ डेटा फेचिंग के लिए हल्का डिले
‎                    await asyncio.sleep(1.0)
‎
‎                    ohlcv_1m = await self.exchange_handler.exchange.fetch_ohlcv(symbol, timeframe='1m', limit=35)
‎                    ohlcv_5m = await self.exchange_handler.exchange.fetch_ohlcv(symbol, timeframe='5m', limit=15)
‎                    
‎                    news_sentiment = await self.fetch_news_sentiment(symbol)
‎                    indicators = InstitutionalSignalEngine.compute_indicators(ohlcv_1m, ohlcv_5m)
‎                    strategy, side, atr = InstitutionalSignalEngine.evaluate_market_direction(indicators, news_sentiment)
‎
‎                    # 1. ट्रेड खोलना
‎                    if symbol not in self.active_positions and side != "NONE":
‎                        total_eq, free_usdt = await self.exchange_handler.get_account_summary()
‎                        
‎                        if self.risk_manager.evaluate_circuit_breaker(0.0):
‎                            continue
‎
‎                        margin = self.risk_manager.calculate_compound_margin(total_eq, free_usdt)
‎                        
‎                        if margin > 0:
‎                            current_price = indicators["current_close"]
‎                            new_pos = await self.exchange_handler.execute_order(
‎                                symbol=symbol, side=side, price=current_price, margin=margin,
‎                                leverage=self.risk_manager.leverage, atr=atr, strategy=strategy
‎                            )
‎                            if new_pos:
‎                                self.active_positions[symbol] = new_pos
‎                                self.save_state()
‎                                emoji = "🟢 [LONG POSITION OPENED]" if side == "long" else "🔴 [SHORT POSITION OPENED]"
‎                                await self.send_whatsapp(f"{emoji} {symbol}\nStrategy: {strategy}\nMargin: ${margin:.2f}\nTarget Goal: ${self.risk_manager.target_goal}")
‎
‎                    # 2. ट्रेलिंग स्टॉप-लॉस अपडेट करना
‎                    elif symbol in self.active_positions:
‎                        pos = self.active_positions[symbol]
‎                        current_price = indicators.get("current_close", pos.entry_price)
‎                        
‎                        if pos.side == "long" and current_price > pos.highest_price:
‎                            pos.highest_price = current_price
‎                            new_sl = pos.highest_price - (atr * 0.6)
‎                            if new_sl > pos.sl_price:
‎                                pos.sl_price = new_sl
‎                                await self.exchange_handler.update_stop_loss(symbol, pos.side, str(pos.size), new_sl)
‎                                self.save_state()
‎                        elif pos.side == "short" and current_price < pos.lowest_price:
‎                            pos.lowest_price = current_price
‎                            new_sl = pos.lowest_price + (atr * 0.6)
‎                            if new_sl < pos.sl_price:
‎                                pos.sl_price = new_sl
‎                                await self.exchange_handler.update_stop_loss(symbol, pos.side, str(pos.size), new_sl)
‎                                self.save_state()
‎
‎                await asyncio.sleep(4)
‎            except Exception as e:
‎                logging.error(f"Main Loop Exception: {e}")
‎                await asyncio.sleep(5)
‎
‎    async def stop(self):
‎        self.is_running = False
‎        self.save_state()
‎        await self.exchange_handler.close()
‎        logging.info("🛑 [ENGINE] Stopped Safely.")
‎
‎
‎# --- FastAPI & WhatsApp Webhook ---
‎@asynccontextmanager
‎async def lifespan(app: FastAPI):
‎    global engine
‎    engine = UltimateTradingEngine()
‎    asyncio.create_task(engine.run_loop())
‎    yield
‎    await engine.stop()
‎
‎app = FastAPI(title="Ultimate $10 to $100 Scalper", lifespan=lifespan)
‎engine: Optional[UltimateTradingEngine] = None
‎
‎@app.get("/")
‎async def health_check():
‎    return {"status": "active", "mode": "Autonomous 1M Scalper", "time": time.time()}
‎
‎
‎@app.post("/whatsapp-webhook")
‎async def whatsapp_webhook(request: Request):
‎    form_data = await request.form()
‎    incoming_msg = form_data.get("Body", "").strip().lower()
‎    
‎    resp = MessagingResponse()
‎    reply = resp.message()
‎    
‎    if not engine:
‎        reply.body("⚠️ Engine is currently offline.")
‎        return Response(content=str(resp), media_type="application/xml")
‎
‎    # 1. टारगेट कमांड (जैसे: "10 se 100 banao")
‎    if "banao" in incoming_msg or "target" in incoming_msg:
‎        numbers = re.findall(r'\d+', incoming_msg)
‎        if len(numbers) >= 2:
‎            target = float(numbers[1])
‎            engine.risk_manager.set_target_goal(target)
‎            reply.body(f"🎯 *Target Locked!* बॉट अब ${target} का गोल पूरा करने के लिए एक्टिव हो गया है। 🚀")
‎        else:
‎            reply.body("🎯 कृपया टारगेट इस तरह लिखें: *10 se 100 banao*")
‎
‎    # 2. ट्रेड पूछने की कमांड (जैसे: "konsi trade li hai?")
‎    elif "trade" in incoming_msg or "position" in incoming_msg or "li hai" in incoming_msg:
‎        if not engine.active_positions:
‎            reply.body("📭 अभी कोई ट्रेड खुली नहीं है। बॉट मार्केट स्कैन कर रहा है, सिग्नल मिलते ही तुरंत ट्रेड लेगा।")
‎        else:
‎            msg = "📊 *यहाँ आपकी खुली हुई ट्रेड्स की डिटेल है*:\n"
‎            for sym, p in engine.active_positions.items():
‎                msg += f"• *{sym}* [{p.side.upper()}]\n  Entry: {p.entry_price}\n  Margin: ${p.initial_margin:.2f}\n  Strategy: {p.strategy}\n\n"
‎            reply.body(msg)
‎
‎    # 3. स्टेटस चेक
‎    elif "status" in incoming_msg or "info" in incoming_msg:
‎        state = "🟢 Autonomous Running" if engine.is_running else "🔴 Paused"
‎        reply.body(f"🤖 *AI Bot Status*\nState: {state}\nActive Trades: {len(engine.active_positions)}\nTarget Goal: ${engine.risk_manager.target_goal}")
‎
‎    # 4. बैलेंस चेक
‎    elif "balance" in incoming_msg or "paisa" in incoming_msg:
‎        equity, free = await engine.exchange_handler.get_account_summary()
‎        reply.body(f"💼 *Total Equity*: ${equity:.2f}\n💰 *Free USDT*: ${free:.2f}")
‎
‎    # 5. बन्द करना
‎    elif "stop" in incoming_msg or "roko" in incoming_msg:
‎        engine.is_running = False
‎        reply.body("🛑 ट्रेडिंग इंजन व्हाट्सएप कमांड से रोक दिया गया है।")
‎
‎    # 6. चालू करना
‎    elif "start" in incoming_msg or "chalu karo" in incoming_msg:
‎        if not engine.is_running:
‎            asyncio.create_task(engine.run_loop())
‎            reply.body
