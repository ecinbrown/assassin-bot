import sqlite3
import os
import threading
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'trading_data.db')

# ─── Persistent Connection (thread-safe singleton) ───
_local = threading.local()

def _get_conn():
    """Return a persistent per-thread SQLite connection."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn

def init_db():
    """Initialize the SQLite database with the required schema."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Create ticks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            velocity REAL NOT NULL
        )
    ''')
    
    # Create index for faster querying by symbol and time
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_symbol_time ON ticks (symbol, timestamp)')
    
    conn.commit()
    logger.info("📦 Database initialized (WAL mode, persistent connection)")

# ─── Batch Insert Buffer ───
_tick_buffer = []
_BATCH_SIZE = 20

def insert_tick(timestamp: float, symbol: str, price: float, velocity: float):
    """Buffer ticks and flush in batches for performance."""
    _tick_buffer.append((timestamp, symbol, price, velocity))
    if len(_tick_buffer) >= _BATCH_SIZE:
        flush_ticks()

def flush_ticks():
    """Flush all buffered ticks to the database."""
    global _tick_buffer
    if not _tick_buffer:
        return
    try:
        conn = _get_conn()
        conn.executemany('''
            INSERT INTO ticks (timestamp, symbol, price, velocity)
            VALUES (?, ?, ?, ?)
        ''', _tick_buffer)
        conn.commit()
        _tick_buffer = []
    except Exception as e:
        logger.error(f"DB flush failed: {e}")
        _tick_buffer = []

def get_velocities_last_hour(symbol: str, current_time: float):
    """
    Retrieve velocities for the past hour to calculate std_dev.
    """
    hour_ago = current_time - 3600 # 3600 seconds in an hour
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT velocity FROM ticks 
        WHERE symbol = ? AND timestamp >= ?
    ''', (symbol, hour_ago))
    
    results = cursor.fetchall()
    return [r[0] for r in results]
