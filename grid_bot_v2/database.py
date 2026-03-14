from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    order_id = Column(String, unique=True)
    side = Column(String)
    price = Column(Float)
    qty = Column(Float)
    status = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BotState(Base):
    __tablename__ = 'bot_state'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)
    value = Column(String)

# Initialize Database
from sqlalchemy import create_engine
engine = create_engine('sqlite:///trading_bot.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()
