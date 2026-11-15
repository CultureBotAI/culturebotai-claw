"""Check packaged review helpers without validation reruns; 2026-11-15.
Purpose: helper-provenance readback for issues 1252/1253 and source-review results.
Inputs: this public helper directory. Output: explicit exclusive JSON receipt.
Syntax/help and private-path/email checks only; no remote calls or runtime input.
The separately owned cycle-preliminary directory is excluded explicitly.
"""
import argparse,ast,hashlib,json,re,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parent;rows=[]
    for path in sorted(root.rglob("*.py")):
        if "cycle-preliminary" in path.parts:continue
        ast.parse(path.read_text())
        result=subprocess.run([sys.executable,str(path),"--help"],capture_output=True,text=True,timeout=10)
        if result.returncode:raise ValueError("Help failed: "+str(path.relative_to(root)))
        rows.append({"file":str(path.relative_to(root)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"syntax":True,"help_exit":result.returncode})
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or "cycle-preliminary" in path.parts:continue
        text=path.read_text()
        if re.search(r"/(?:Users|home)/[A-Za-z0-9]",text) or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",text):
            raise ValueError("Public hygiene review required: "+str(path.relative_to(root)))
    result={"helpers":rows,"public_path_email_scan_passed":True,"excluded_other_owner_directory":"cycle-preliminary"}
    with a.output.open("x") as stream:json.dump(result,stream,indent=2);stream.write("\n")
    print("Syntax/help and public-path/email scan passed for",len(rows),"helpers.")
if __name__=="__main__":main()
