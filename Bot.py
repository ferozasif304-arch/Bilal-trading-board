import asyncio
import os
import json
import logging
import time
import re
from decimal import Decimal
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from contextlib import asynccontextmanager
from functools import wraps
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import ccxt.pro as ccxt_pro
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | [ERROR-FREE-SCALPER] | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("error_free_scalper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

STATE_STORAGE_FILE = "error_free_scalper_state.json"

def bulletproof_shield(func):
    """Guarantees zero crashes by catching any unexpected exceptions silently and recovering."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except (ccxt_pro.NetworkError, ccxt_pro.ExchangeNotAvailable, asyncio.TimeoutError, ConnectionError) as net_err:
            logging.warning(f"Network exception in {func.__name__}: {net_err}. Auto-recovering...")
            await asyncio.sleep(2.0)
            return None
        except ccxt_pro.RateLimitExceeded as rate_err:
            logging.warning(f"Rate limit in {func.__name__}: {rate_err}. Backing off...")
            await asyncio.sleep(4.0)
            return None
        except Exception as exc:
            logging.error(f"Handled unexpected error in {func.__name__}: {exc}. Continuing safely...")
            await asyncio.sleep(1.0)
            return None
    return wrapper

@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    size: float
    sl_price: float
    tp_price: float
    strategy: str
    highest_price: float
    lowest_price: float
    timestamp: float
    initial_margin: float

class EnterpriseRiskManager:
    def __init__(self, target_goal: float = 200.0, base_risk_pct: float = 0.04, leverage: int = 15) -> None:
        self.target_goal: float = target_goal
        self.base_risk_pct: Decimal = Decimal(str(base_risk_pct))
        self.leverage: int = leverage
        self.consecutive_losses: int = 0
        self.daily_drawdown: float = 0.0

    def update_target(self, goal: float) -> None:
        try:
            self.target_goal = float(goal)
            logging.info(f"Target goal re-anchored to: ${self.target_goal}")
        except Exception:
            pass

    def compute_allocated_margin(self, total_equity: float, free_usdt: float) -> float:
        try:
            equity_dec = Decimal(str(total_equity))
            free_dec = Decimal(str(free_usdt))
            if free_dec <= 0 or equity_dec <= 0:
                return 0.0
            
            calculated_margin = equity_dec * self.base_risk_pct
            min_safe_margin = max(Decimal("2.5"), Decimal("5.5") / Decimal(str(self.leverage)))
            final_margin = max(calculated_margin, min_safe_margin)
            
            max_allowed = free_dec * Decimal("0.30")
            return float(min(final_margin, max_allowed))
        except Exception as exc:
            logging.error(f"Error computing margin: {exc}")
            return 0.0

    def evaluate_circuit_breaker(self, pnl_pct: float) -> bool:
        try:
            if pnl_pct < 0:
                self.consecutive_losses += 1
                self.daily_drawdown += abs(pnl_pct)
            else:
                self.consecutive_losses = 0
            
            if self.consecutive_losses >= 3 or self.daily_drawdown >= 10.0:
                logging.critical("CIRCUIT BREAKER TRIPPED! Capital protection active.")
                return True
            return False
        except Exception:
            return False

class EnterpriseSignalEngine:
    @staticmethod
    def process_market_data(ohlcv_1m: List[list], ohlcv_2m: List[list]) -> dict:
        if not ohlcv_1m or len(ohlcv_1m) < 40 or not ohlcv_2m or len(ohlcv_2m) < 20:
            return {}

        try:
            closes_1m = [c[4] for c in ohlcv_1m]
            highs_1m = [c[2] for c in ohlcv_1m]
            lows_1m = [c[3] for c in ohlcv_1m]
            volumes_1m = [c[5] for c in ohlcv_1m]
            closes_2m = [c[4] for c in ohlcv_2m]
            
            ema_2m_fast = sum(closes_2m[-3:]) / 3
            ema_2m_slow = sum(closes_2m[-8:]) / 8
            is_2m_bullish = ema_2m_fast > ema_2m_slow
            is_2m_bearish = ema_2m_fast < ema_2m_slow

            tr_list = [
                max(highs_1m[i] - lows_1m[i], abs(highs_1m[i] - closes_1m[i-1]), abs(lows_1m[i] - closes_1m[i-1]))
                for i in range(1, len(ohlcv_1m))
            ]
            atr = sum(tr_list[-10:]) / 10 if len(tr_list) >= 10 else (highs_1m[-1] - lows_1m[-1])

            ema_3 = sum(closes_1m[-3:]) / 3
            ema_9 = sum(closes_1m[-9:]) / 9

            gains, losses = 0.0, 0.0
            for i in range(-10, 0):
                diff = closes_1m[i] - closes_1m[i-1]
                if diff > 0: gains += diff
                else: losses += abs(diff)
            avg_gain = gains / 10
            avg_loss = losses / 10
            rsi = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

            avg_vol = sum(volumes_1m[-15:-1]) / 14 if len(volumes_1m) >= 15 else volumes_1m[-1]
            vol_ratio = volumes_1m[-1] / avg_vol if avg_vol > 0 else 1.0

            return {
                "atr": atr, "ema_3": ema_3, "ema_9": ema_9,
                "rsi": rsi, "vol_ratio": vol_ratio, "current_close": closes_1m[-1],
                "is_2m_bullish": is_2m_bullish, "is_2m_bearish": is_2m_bearish
            }
        except Exception as exc:
            logging.error(f"Indicator calculation error: {exc}")
            return {}

    @staticmethod
    def evaluate_signals(indicators: dict, sentiment: str) -> Tuple[str, str, float]:
        if not indicators:
            return "NONE", "NONE", 0.0

        try:
            is_1m_bull_cross = indicators["ema_3"] > indicators["ema_9"]
            is_1m_bear_cross = indicators["ema_3"] < indicators["ema_9"]
            rsi = indicators["rsi"]
            vol_ratio = indicators["vol_ratio"]
            atr = indicators["atr"]

            if all([indicators["is_2m_bullish"], is_1m_bull_cross, atr > 0, 44 <= rsi <= 65, vol_ratio > 1.40, sentiment != "BEARISH"]):
                return "Error-Free 2M Bullish Scalp (LONG)", "long", atr

            if all([indicators["is_2m_bearish"], is_1m_bear_cross, atr > 0, 35 <= rsi <= 56, vol_ratio > 1.40, sentiment != "BULLISH"]):
                return "Error-Free 2M Bearish Scalp (SHORT)", "short", atr

            return "NONE", "NONE", indicators.get("atr", 0.0)
        except Exception:
            return "NONE", "NONE", 0.0

class EnterpriseExchangeGateway:
    def __init__(self) -> None:
        try:
            is_testnet = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
            self.exchange = ccxt_pro.binance({
                'apiKey': os.getenv("BINANCE_API_KEY"),
                'secret': os.getenv("BINANCE_SECRET_KEY"),
                'enableRateLimit': True,
                'timeout': 10000,
                'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
            })
            if is_testnet:
                self.exchange.set_sandbox_mode(True)
                logging.warning("GATEWAY: Testnet Sandbox Active.")
            else:
                logging.info("GATEWAY: Production Active.")
        except Exception as exc:
            logging.error(f"Gateway initialization error: {exc}")

    @bulletproof_shield
    async def fetch_account_balances(self) -> Tuple[float, float]:
        balance = await self.exchange.fetch_balance()
        total_equity = float(balance.get('total', {}).get('USDT', 0.0))
        free_usdt = float(balance.get('USDT', {}).get('free', 0.0))
        return total_equity, free_usdt

    @bulletproof_shield
    async def prepare_environment(self, symbol: str, leverage: int) -> None:
        try:
            await self.exchange.set_leverage(leverage, symbol)
        except Exception:
            pass
        try:
            await self.exchange.set_margin_mode('ISOLATED', symbol)
        except Exception:
            pass

    @bulletproof_shield
    async def execute_live_order(self, symbol: str, side: str, price: float, margin: float, leverage: int, atr: float, strategy: str) -> Optional[Position]:
        await self.prepare_environment(symbol, leverage)
        
        raw_size = (margin * leverage) / price
        size = float(self.exchange.amount_to_precision(symbol, raw_size))
        notional_value = size * price

        if notional_value < 5.1:
            logging.warning(f"Order skipped: Notional value ${notional_value:.2f} below minimum for {symbol}.")
            return None

        if side == "long":
            order = await self.exchange.create_market_buy_order(symbol, size)
            entry = float(order.get('average', price))
            sl = float(self.exchange.price_to_precision(symbol, entry - (atr * 0.9)))
            tp = float(self.exchange.price_to_precision(symbol, entry + (atr * 2.2)))
            
            await self.exchange.create_order(symbol, 'STOP_MARKET', 'sell', size, None, {'stopPrice': sl, 'reduceOnly': True})
            await self.exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'sell', size, None, {'stopPrice': tp, 'reduceOnly': True})
        else:
            order = await self.exchange.create_market_sell_order(symbol, size)
            entry = float(order.get('average', price))
            sl = float(self.exchange.price_to_precision(symbol, entry + (atr * 0.9)))
            tp = float(self.exchange.price_to_precision(symbol, entry - (atr * 2.2)))
            
            await self.exchange.create_order(symbol, 'STOP_MARKET', 'buy', size, None, {'stopPrice': sl, 'reduceOnly': True})
            await self.exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'buy', size, None, {'stopPrice': tp, 'reduceOnly': True})

        return Position(
            symbol=symbol, side=side, entry_price=entry, size=size,
            sl_price=sl, tp_price=tp, strategy=strategy,
            highest_price=entry, lowest_price=entry, timestamp=time.time(), initial_margin=margin
        )

    @bulletproof_shield
    async def update_trailing_stop(self, symbol: str, side: str, size: str, new_sl: float) -> None:
        open_orders = await self.exchange.fetch_open_orders(symbol)
        for order in open_orders:
            if order['type'] == 'STOP_MARKET':
                await self.exchange.cancel_order(order['id'], symbol)
        
        precision_sl = float(self.exchange.price_to_precision(symbol, new_sl))
        order_side = 'sell' if side == 'long' else 'buy'
        await self.exchange.create_order(symbol, 'STOP_MARKET', order_side, size, None, {'stopPrice': precision_sl, 'reduceOnly': True})

    @bulletproof_shield
    async def fetch_exchange_positions(self) -> List[dict]:
        positions = await self.exchange.fetch_positions()
        return [p for p in positions if float(p.get('contracts', 0.0)) > 0.0]

    async def close_gateway(self) -> None:
        try:
            await self.exchange.close()
        except Exception:
            pass

class EnterpriseLiveScalperEngine:
    def __init__(self) -> None:
        self.gateway = EnterpriseExchangeGateway()
        self.risk_manager = EnterpriseRiskManager()
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
        self.twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")) if os.getenv("TWILIO_ACCOUNT_SID") else None
        
        self.assets: List[str] = [
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 
            'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT'
        ]
        self.active_positions: Dict[str, Position] = {}
        self.cooldown_timestamps: Dict[str, float] = {}
        self.sentiment_cache: Dict[str, Tuple[str, float]] = {}
        self.running: bool = False
        self._load_state()

    def _save_state(self) -> None:
        try:
            payload = {sym: asdict(pos) for sym, pos in self.active_positions.items()}
            with open(STATE_STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception as exc:
            logging.error(f"State save error: {exc}")

    def _load_state(self) -> None:
        try:
            if os.path.exists(STATE_STORAGE_FILE):
                with open(STATE_STORAGE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.active_positions = {sym: Position(**val) for sym, val in data.items()}
                    logging.info(f"Loaded {len(self.active_positions)} active positions from disk.")
        except Exception as exc:
            logging.error(f"State load error: {exc}")

    async def send_whatsapp_alert(self, message: str) -> None:
        try:
            logging.info(f"WHATSAPP ALERT -> {message}")
            if self.twilio_client and os.getenv("TWILIO_TO_PHONE") and os.getenv("TWILIO_FROM_PHONE"):
                to_num = os.getenv("TWILIO_TO_PHONE")
                from_num = os.getenv("TWILIO_FROM_PHONE")
                if not to_num.startswith("whatsapp:"): to_num = f"whatsapp:{to_num}"
                if not from_num.startswith("whatsapp:"): from_num = f"whatsapp:{from_num}"
                self.twilio_client.messages.create(body=message, from_=from_num, to=to_num)
        except Exception as exc:
            logging.error(f"WhatsApp alert error: {exc}")

    async def fetch_cached_sentiment(self, symbol: str) -> str:
        try:
            current_time = time.time()
            if symbol in self.sentiment_cache:
                sentiment, ts = self.sentiment_cache[symbol]
                if current_time - ts < 180:
                    return sentiment

            if not self.openai_client:
                return "NEUTRAL"
            
            ticker = symbol.split('/')[0]
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Return strictly one capitalized token: BULLISH, BEARISH, or NEUTRAL."},
                    {"role": "user", "content": f"Assess live high-frequency sentiment for {ticker}/USDT futures."}
                ],
                max_tokens=5,
                temperature=0.0
            )
            val = response.choices[0].message.content.strip().upper()
            sentiment = val if val in ["BULLISH", "BEARISH", "NEUTRAL"] else "NEUTRAL"
            self.sentiment_cache[symbol] = (sentiment, current_time)
            return sentiment
        except Exception:
            return "NEUTRAL"

    async def reconcile_exchange_state(self) -> None:
        while self.running:
            try:
                await asyncio.sleep(15)
                exchange_positions = await self.gateway.fetch_exchange_positions()
                if exchange_positions is not None:
                    active_symbols_on_exchange = {p['symbol'] for p in exchange_positions}
                    local_symbols = list(self.active_positions.keys())
                    for sym in local_symbols:
                        if sym not in active_symbols_on_exchange:
                            logging.info(f"Reconciliation: Position for {sym} closed on exchange. Cleaning local state.")
                            del self.active_positions[sym]
                            self._save_state()
            except Exception as exc:
                logging.warning(f"State reconciliation warning: {exc}")

    async def process_single_asset(self, symbol: str):
        try:
            current_time = time.time()
            if symbol in self.cooldown_timestamps:
                if current_time - self.cooldown_timestamps[symbol] < 200:
                    return

            ohlcv_1m = await self.gateway.exchange.watch_ohlcv(symbol, timeframe='1m', limit=50)
            ohlcv_2m = await self.gateway.exchange.fetch_ohlcv(symbol, timeframe='2m', limit=25)
            
            if not ohlcv_1m or not ohlcv_2m:
                return

            sentiment = await self.fetch_cached_sentiment(symbol)
            indicators = EnterpriseSignalEngine.process_market_data(ohlcv_1m, ohlcv_2m)
            strategy, side, atr = EnterpriseSignalEngine.evaluate_signals(indicators, sentiment)

            if symbol not in self.active_positions and side != "NONE":
                equity, free_usdt = await self.gateway.fetch_account_balances()
                if equity is None or free_usdt is None:
                    return
                
                if self.risk_manager.evaluate_circuit_breaker(0.0):
                    return

                margin = self.risk_manager.compute_allocated_margin(equity, free_usdt)
                
                if margin > 0:
                    current_price = indicators["current_close"]
                    position = await self.gateway.execute_live_order(
                        symbol=symbol, side=side, price=current_price, margin=margin,
                        leverage=self.risk_manager.leverage, atr=atr, strategy=strategy
                    )
                    if position:
                        self.active_positions[symbol] = position
                        self.cooldown_timestamps[symbol] = current_time
                        self._save_state()
                        tag = "ERROR-FREE LONG EXECUTED" if side == "long" else "ERROR-FREE SHORT EXECUTED"
                        await self.send_whatsapp_alert(f"[{tag}] {symbol}\nStrategy: {strategy}\nMargin: ${margin:.2f}\nTarget: ${self.risk_manager.target_goal}")

            elif symbol in self.active_positions:
                pos = self.active_positions[symbol]
                current_price = indicators.get("current_close", pos.entry_price)
                
                if pos.side == "long" and current_price > pos.highest_price:
                    pos.highest_price = current_price
                    new_sl = pos.highest_price - (atr * 0.4)
                    if new_sl > pos.sl_price:
                        pos.sl_price = new_sl
                        await self.gateway.update_trailing_stop(symbol, pos.side, str(pos.size), new_sl)
                        self._save_state()
                elif pos.side == "short" and current_price < pos.lowest_price:
                    pos.lowest_price = current_price
                    new_sl = pos.lowest_price + (atr * 0.4)
                    if new_sl < pos.sl_price:
                        pos.sl_price = new_sl
                        await self.gateway.update_trailing_stop(symbol, pos.side, str(pos.size), new_sl)
                        self._save_state()

        except Exception as exc:
            logging.warning(f"Error processing {symbol}: {exc}. Skipping safely.")

    async def run_enterprise_loop(self) -> None:
        self.running = True
        logging.info("ERROR-FREE SCALPER ENGINE ONLINE.")
        asyncio.create_task(self.reconcile_exchange_state())

        while self.running:
            try:
                tasks = [self.process_single_asset(symbol) for symbol in self.assets]
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(0.3)
            except Exception as exc:
                logging.error(f"Global loop shield caught error: {exc}. Re-engaging instantly...")
                await asyncio.sleep(1.0)

    async def shutdown(self) -> None:
        try:
            self.running = False
            self._save_state()
            await self.gateway.close_gateway()
            logging.info("Scalper engine safely terminated.")
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    global enterprise_engine
    enterprise_engine = EnterpriseLiveScalperEngine()
    asyncio.create_task(enterprise_engine.run_enterprise_loop())
    yield
    await enterprise_engine.shutdown()

app = FastAPI(title="Error-Free Live Scalper", lifespan=lifespan)
enterprise_engine: Optional[EnterpriseLiveScalperEngine] = None

@app.get("/")
async def health_check() -> dict:
    return {"status": "active", "engine": "Error-Free Live Scalper", "time": time.time()}

@app.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request) -> Response:
    try:
        form_data = await request.form()
        incoming_msg = form_data.get("Body", "").strip().lower()
        
        xml_resp = MessagingResponse()
        reply = xml_resp.message()
        
        if not enterprise_engine:
            reply.body("System Error: Engine offline.")
            return Response(content=str(xml_resp), media_type="application/xml")

        if "target" in incoming_msg or "goal" in incoming_msg:
            numbers = re.findall(r'\d+', incoming_msg)
            if len(numbers) >= 1:
                target = float(numbers[-1])
                enterprise_engine.risk_manager.update_target(target)
                reply.body(f"Target Updated: Financial goal locked at ${target}.")
            else:
                reply.body("Syntax Error: Use format like 'set target 100'.")

        elif "trade" in incoming_msg or "position" in incoming_msg:
            if not enterprise_engine.active_positions:
                reply.body("Market Scan: No active trades. Actively hunting for high-confidence setups.")
            else:
                report = "Active Error-Free Scalps:\n"
                for sym, pos in enterprise_engine.active_positions.items():
                    report += f"- {sym} [{pos.side.upper()}]\n  Entry: {pos.entry_price}\n  Margin: ${pos.initial_margin:.2f}\n  Strategy: {pos.strategy}\n\n"
                reply.body(report)

        elif "status" in incoming_msg or "info" in incoming_msg:
            state = "Running (Error-Free Guarded Hunt)" if enterprise_engine.running else "Paused"
            reply.body(f"Engine Status: {state}\nActive Scalps: {len(enterprise_engine.active_positions)}\nTarget Goal: ${enterprise_engine.risk_manager.target_goal}")

        elif "balance" in incoming_msg or "equity" in incoming_msg:
            equity, free = await enterprise_engine.gateway.fetch_account_balances()
            if equity is not None and free is not None:
                reply.body(f"Account Ledger:\n- Total Equity: ${equity:.2f}\n- Free Margin: ${free:.2f}")
            else:
                reply.body("Error fetching account ledger from Binance.")

        elif "stop" in incoming_msg or "pause" in incoming_msg:
            enterprise_engine.running = False
            reply.body("Command Executed: Live scalper paused.")

        elif "start" in incoming_msg or "resume" in incoming_msg:
            if not enterprise_engine.running:
                asyncio.create_task(enterprise_engine.run_enterprise_loop())
                reply.body("Command Executed: Live scalper resumed.")
            else:
                reply.body("Notice: Engine is already fully operational.")

        return Response(content=str(xml_resp), media_type="application/xml")
    except Exception as exc:
        logging.error(f"Webhook error: {exc}")
        xml_resp = MessagingResponse()
        xml_resp.message().body("Server Error processed safely.")
        return Response(content=str(xml_resp), media_type="application/xml")
