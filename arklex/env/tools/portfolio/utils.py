import os
import sqlite3
import uuid
from datetime import datetime
import pandas as pd
from typing import Dict, Any, Tuple, List

from arklex.utils.graph_state import MessageState, StatusEnum

DBNAME = "portfolio.sqlite"


class PortfolioActions:
    def __init__(self) -> None:
        self.db_path = os.path.join(os.environ.get("DATA_DIR"), DBNAME)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
    def init_slots(self, slots, bot_config):
        return slots


    def add_trade(self, msg_state: MessageState) -> MessageState:
        slots = {slot.name: slot.verified_value for slot in msg_state.slots}
        symbol = slots.get("symbol")
        qty = float(slots.get("quantity", 0))
        price = float(slots.get("price", 0))
        side = slots.get("side", "buy")
        trade_id = "trade_" + str(uuid.uuid4())
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO trades(id, trade_date, symbol, quantity, price, side) VALUES(?,?,?,?,?,?)",
            (trade_id, datetime.utcnow().isoformat(), symbol, qty, price, side),
        )
        # update positions
        cursor.execute("SELECT id, quantity, avg_price FROM positions WHERE symbol=?", (symbol,))
        row = cursor.fetchone()
        if row:
            pid, quantity, avg_price = row
            new_qty = quantity + qty if side.lower() == "buy" else quantity - qty
            new_avg = (
                ((quantity * avg_price) + (qty * price)) / new_qty if new_qty != 0 else 0
            )
            cursor.execute(
                "UPDATE positions SET quantity=?, avg_price=? WHERE id=?",
                (new_qty, new_avg, pid),
            )
        else:
            cursor.execute(
                "INSERT INTO positions(id, symbol, quantity, avg_price) VALUES(?,?,?,?)",
                ("pos_" + str(uuid.uuid4()), symbol, qty if side.lower() == "buy" else -qty, price),
            )
        conn.commit()
        conn.close()
        msg_state.status = StatusEnum.COMPLETE
        msg_state.message_flow = f"Recorded trade {trade_id} for {symbol}"
        return msg_state

    def get_portfolio(self, msg_state: MessageState) -> MessageState:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, quantity, avg_price FROM positions")
        rows = cursor.fetchall()
        df = pd.DataFrame(rows, columns=["symbol", "quantity", "avg_price"])
        conn.close()
        msg_state.status = StatusEnum.COMPLETE
        msg_state.message_flow = df.to_string(index=False) if not df.empty else "No positions"
        return msg_state

    def add_note(self, msg_state: MessageState) -> MessageState:
        slots = {slot.name: slot.verified_value for slot in msg_state.slots}
        note = slots.get("note", "")
        note_id = "note_" + str(uuid.uuid4())
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notes(id, timestamp, note) VALUES(?,?,?)",
            (note_id, datetime.utcnow().isoformat(), note),
        )
        conn.commit()
        conn.close()
        msg_state.status = StatusEnum.COMPLETE
        msg_state.message_flow = f"Saved note {note_id}"
        return msg_state

    def view_notes(self, msg_state: MessageState) -> MessageState:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, note FROM notes ORDER BY timestamp DESC LIMIT 5")
        rows = cursor.fetchall()
        conn.close()
        df = pd.DataFrame(rows, columns=["timestamp", "note"])
        msg_state.status = StatusEnum.COMPLETE
        msg_state.message_flow = df.to_string(index=False) if not df.empty else "No notes"
        return msg_state