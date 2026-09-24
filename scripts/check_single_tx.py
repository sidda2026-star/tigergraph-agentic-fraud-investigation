import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.store import get_graph_store
from agent.tools import InvestigationToolkit

store = get_graph_store()
con = store.con
row = con.execute("SELECT * FROM enriched_tx WHERE transaction_id = '3523199'").fetchone()
cols = [d[0] for d in con.execute("SELECT * FROM enriched_tx LIMIT 1").description]
d = dict(zip(cols, row))
print("card_id:", d['card_id'])
print("device_id:", d['device_id'])
print("device_info:", d['device_info'])
print("id_15:", d['id_15'])
print("id_23:", d['id_23'])
print("amount:", d['amount'])
print("channel:", d['channel'])
print("addr1:", d['addr1'])

base = store.card_baseline(d['card_id'], str(d['ts']))
print("base regions:", base['regions'])
