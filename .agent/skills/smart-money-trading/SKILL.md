---
name: smart-money-trading
description: Advanced trading concepts focusing on Smart Money Concepts (SMC), Liquidity, Order Flow, and Professional Risk Management.
---

# Smart Money & Algorithmic Trading Guide

## 1. Core Concepts (SMC)
- **Market Structure:** Identify trends using Higher Highs (HH) / Higher Lows (HL). Break of Structure (BOS) confirms continuation. Change of Character (CHoCH) signals reversal.
- **Liquidity (The Fuel):** Price moves to sweep liquidity (Stop Losses).
    - **BSL (Buy Side Liquidity):** Above old highs.
    - **SSL (Sell Side Liquidity):** Below old lows.
    - *Bot Logic:* Wait for a sweep of BSL/SSL before entering a reversal.
- **Fair Value Gaps (FVG) / Imbalace:** Ranges where price moved too fast, leaving inefficiency. Price often returns to fill these gaps.
- **Order Blocks (OB):** The last candle before a strong move that broke structure. High probability entry zones.

## 2. Order Flow & Volume Analysis
- **Delta:** Net difference between aggressive buyers and sellers.
    - *Divergence:* Price goes UP, but Delta goes DOWN -> Reversal imminent (Absorption).
- **CVD (Cumulative Volume Delta):** Tracks the total buying/selling pressure over time.
- **Open Interest (OI):**
    - Price UP + OI UP = Strong Trend (New money entering).
    - Price UP + OI DOWN = Weak Trend (Short covering).

## 3. Professional Risk Management
- **Rs (R-Multiples):** Always think in "Risk Units". A trade with 2R profit pays for 2 losing trades.
- **Position Sizing:** `Risk Amount = Account * Risk%`. `Position Size = Risk Amount / (Entry - StopLoss)`.
- **Dynamic Risk:**
    - *Win Streak:* Increase risk slightly (e.g., to 1.5% or 2%).
    - *Drawdown:* Cut risk in half (e.g., to 0.5%) to survive.
- **Pyramiding:** Adding to a winning position ONLY after a new BOS (Break of Structure) and moving SL to breakeven.

## 4. Execution Algorithms
- **TWAP (Time-Weighted Average Price):** Splitting a large order into small chunks over time to avoid slippage.
- **Chase Logic:** If using Limit orders, re-price them dynamically if the price moves away, but only up to a `Max Slippage` limit.

## 5. Market Regimes
- **Trending:** Use Moving Averages (EMA 20/50), BOS logic.
- **Ranging (Flat):** Buy Low / Sell High at range boundaries. Use Oscillators (RSI) and Mean Reversion.
- **Volatile/News:** Reduce position size or pause trading (Wide spreads, unpredictable wicks).

## 6. Bot Implementation Rules
- **Never guess tops/bottoms.** Wait for confirmation (BOS + FVG).
- **Multi-Timeframe Analysis (MTF):**
    - H4/H1: Determine bias (Bullish/Bearish).
    - M15/M5: Find entry zones (OB/FVG).
    - M1: Precision entry (optional).
