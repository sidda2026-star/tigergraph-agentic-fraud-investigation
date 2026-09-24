import csv

cases = list(csv.DictReader(open('data/case_pack.csv', encoding='utf-8')))
for c in cases:
    score = c.get('risk_score') or '—'
    print(f"{c['case_id']} | {c['trigger_type']:<15} | score={score:<4} | {c['trigger_text']}")
