import pandas_ta as ta
import pandas as pd

def calculate_ema(data, period=200):
    return ta.ema(data['close'], length=period)

def calculate_rsi(data, period=14):
    return ta.rsi(data['close'], length=period)

def calculate_atr(data, period=14):
    return ta.atr(data['high'], data['low'], data['close'], length=period)
