"""Portable XMP sidecar export outside source folders. Does not edit originals."""
from pathlib import Path
from xml.etree import ElementTree as ET
import json
RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#';DC='http://purl.org/dc/elements/1.1/';XMP='http://ns.adobe.com/xap/1.0/';IPTC='http://iptc.org/std/Iptc4xmpExt/2008-02-29/';X='adobe:ns:meta/'
for prefix,ns in [('x',X),('rdf',RDF),('dc',DC),('xmp',XMP),('Iptc4xmpExt',IPTC)]:ET.register_namespace(prefix,ns)
def q(ns,name):return '{'+ns+'}'+name
def export(c,folder,ids):
    folder=Path(folder).resolve()
    for s in c.sources():
        root=Path(s['root']).resolve()
        if folder==root or root in folder.parents:raise ValueError('輸出必須位於來源之外')
    folder.mkdir(parents=True,exist_ok=True);manifest=[]
    for pid in dict.fromkeys(ids):
        r=c.db.execute('SELECT p.*,s.root FROM photos p JOIN sources s ON s.id=p.source WHERE p.id=?',(pid,)).fetchone()
        if not r:raise ValueError('照片不存在')
        tags=c.photo_tags(pid);root=ET.Element(q(X,'xmpmeta'));rdf=ET.SubElement(root,q(RDF,'RDF'));desc=ET.SubElement(rdf,q(RDF,'Description'),{q(RDF,'about'):''})
        for ns,name,values in [(DC,'subject',[t['name'] for t in tags]),(IPTC,'PersonInImage',[t['name'] for t in tags if t['kind']=='人物'])]:
            bag=ET.SubElement(ET.SubElement(desc,q(ns,name)),q(RDF,'Bag'))
            for value in dict.fromkeys(values):ET.SubElement(bag,q(RDF,'li')).text=value
        if r['capture_date']:ET.SubElement(desc,q(XMP,'CreateDate')).text=r['capture_date']
        p=folder/(pid+'.xmp');tmp=p.with_suffix('.tmp');ET.ElementTree(root).write(tmp,encoding='utf-8',xml_declaration=True);tmp.replace(p);manifest.append(dict(id=pid,original=str(Path(r['root'])/r['rel']),sidecar=p.name,tags=[dict(t) for t in tags]))
    p=folder/'manifest.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p);return len(manifest)
