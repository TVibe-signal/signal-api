"""slim.py - TVibe Signal slim tool (safe, keeps last definition)."""
import ast, re
from collections import defaultdict
def slim_file(src, dst):
    text = open(src, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines(True)
    tree = ast.parse(text)
    def has_app(n):
        return any("app." in ast.unparse(d) for d in getattr(n, "decorator_list", []))
    remove=set()
    by=defaultdict(list)
    for n in tree.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            by[n.name].append(n)
    for name,lst in by.items():
        if len(lst)>1:
            for n in lst[:-1]:
                if not has_app(n):
                    for i in range(n.lineno-1,n.end_lineno): remove.add(i)
    seen=set()
    for i,ln in enumerate(lines):
        s=re.sub(r"\s+"," ",ln.strip())
        if re.match(r"^(import\s|from\s+\S+\s+import\s)",s):
            if s in seen: remove.add(i)
            else: seen.add(s)
    out="".join([ln for idx,ln in enumerate(lines) if idx not in remove])
    out=re.sub(r"\n{4,}","\n\n\n",out)
    open(dst,"w",encoding="utf-8").write(out)
    print(f"{src} -> {dst}: {len(lines)} -> {out.count(chr(10))+1} lines")
if __name__=="__main__":
    import sys
    for f in ["core.py","features.py","extensions.py"]:
        slim_file(f, f.replace(".py","_slim.py"))
