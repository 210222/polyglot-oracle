# -*- coding: utf-8 -*-
import os, chromadb
from collections import Counter

os.environ['ANONYMIZED_TELEMETRY'] = 'False'
DB = r'D:\Claudedaoy\DMyProject\AI_Editor_System\data\vector_store'

c = chromadb.PersistentClient(path=DB)
cols = c.list_collections()

lines = [f'集合总数: {len(cols)}', '=' * 60]
for col in cols:
    metas = col.get(include=['metadatas'])['metadatas']
    srcs = Counter()
    for m in (metas or []):
        s = m.get('source') or m.get('title') or m.get('filename') or '未知'
        s = os.path.basename(str(s))
        srcs[s] += 1
    lines.append(f'[{col.name}]  切片数: {col.count()}')
    for s, n in srcs.most_common():
        lines.append(f'  {s[:70]} x{n}')
    lines.append('-' * 60)

result = '\n'.join(lines)
out_path = r'D:\Claudedaoy\DMyProject\AI_Editor_System\_db_result.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(result)

