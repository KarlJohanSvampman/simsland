import hashlib, math
MEMORY_VECTORS=[]
def embed(text, dims=64):
    h=hashlib.sha256(text.encode()).digest()
    vals=[(h[i%len(h)]/255)-0.5 for i in range(dims)]
    norm=math.sqrt(sum(v*v for v in vals)) or 1
    return [v/norm for v in vals]
def cosine(a,b): return sum(x*y for x,y in zip(a,b))
def add_memory_vector(character_id, memory_id, text):
    MEMORY_VECTORS.append({"character_id":character_id,"memory_id":memory_id,"text":text,"vec":embed(text)})
def search(character_id, query, k=5):
    q=embed(query); rows=[r for r in MEMORY_VECTORS if r["character_id"]==character_id]
    rows.sort(key=lambda r: cosine(q,r["vec"]), reverse=True)
    return rows[:k]
