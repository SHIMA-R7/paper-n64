"""Use already RS/address/CRC-validated paper blocks as additional pilots.
No original file, print image, container or source shard is ever accessed.
"""
from pathlib import Path
import sys,json,struct,binascii
import numpy as np
from read_smw_v8 import Paper
from decode_calibrated_v7 import fit,classify
from codec_v8 import INNER,layout,decode_blocks,finish_tile,tile_geometry,STEP,TILES
root=Path(__file__).resolve().parent

def known_labels(decoded,tile):
    order,mask=layout(tile);labels=np.zeros(6144,dtype=int);known=np.zeros(6144,dtype=bool)
    for block,payload in decoded.items():
        msg=struct.pack('<I',tile*32+block)+payload;msg+=struct.pack('<H',binascii.crc_hqx(msg,0xFFFF))
        code=np.frombuffer(bytes(INNER.encode(msg)),dtype='uint8');digits=np.column_stack([code>>4,code&15]).ravel()
        where=order[block*256:(block+1)*256];labels[where]=(digits+mask[where])%16;known[where]=True
    return labels.reshape(64,96),known

def reader(paper,tile):
    matrix=paper.matrix(tile);g=tile_geometry(tile);xx,yy=np.meshgrid(np.arange(96)+.5,np.arange(64)+.5);a=paper.a
    def read(p):
        ox,oy,kx,ky=p;gx=(xx-48)*kx+48+ox;gy=(yy-32)*ky+32+oy
        q=np.stack([g['data_x']+gx*STEP,g['data_y']+gy*STEP,np.ones_like(xx)],-1)@matrix.T
        u=q[...,0]/q[...,2];v=q[...,1]/q[...,2];xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
        return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
    return read

def align(read,labels,mask):
    label=labels.ravel()[mask];counts=np.bincount(label,minlength=16)
    def score(params):
        x=read(params).reshape(-1,3)[mask]
        means=np.column_stack([np.bincount(label,weights=x[:,c],minlength=16) for c in range(3)])/np.maximum(counts[:,None],1)
        total=float(((x-x.mean(0))**2).sum());error=float(((x-means[label])**2).sum())
        return (total-error)/max(total,len(x)*25.)
    choices=[(score([x,y,1,1]),np.array([x,y,1.,1.])) for x in np.arange(-.6,.601,.2) for y in np.arange(-.6,.601,.2)]
    p=max(choices,key=lambda q:q[0])[1]
    for radius in (.12,.04,.015):
        for axis in (2,3,0,1):
            choices=[]
            for delta in np.linspace(-radius,radius,9):
                q=p.copy();q[axis]+=delta*(.05 if axis>=2 else 1)
                if np.max(abs(q[:2]))>.85 or np.max(abs(q[2:]-1))>.025:continue
                choices.append((score(q),q))
            p=max(choices,key=lambda q:q[0])[1]
    return p

def decision(paper,tile,decoded):
    read=reader(paper,tile);attempts=[]
    for iteration in range(4):
        before=len(decoded);labels,known=known_labels(decoded,tile)
        if known.sum()<256:return None,decoded,attempts
        validation=known&(np.arange(6144)%5==0);training=known&~validation
        params=align(read,labels,training);values=read(params);models=[]
        for cancel in (False,True):
            prediction,_=classify(values,fit(values,labels,16,cancel,training))
            accuracy=float((prediction[validation]==labels.ravel()[validation]).mean())
            models.append((accuracy,cancel,fit(values,labels,16,cancel,known)))
        models.sort(key=lambda q:q[0],reverse=True)
        for shift in ((0,0),(-.08,0),(.08,0),(0,-.08),(0,.08)):
            q=params.copy();q[:2]+=shift;obs=read(q)
            for accuracy,cancel,model in models:
                prediction,confidence=classify(obs,model);decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
                attempts.append(dict(iteration=iteration,parameters=q.tolist(),neighbor=cancel,known_validation_accuracy=accuracy,new_blocks=len(detail)))
                payload,xor=finish_tile(decoded)
                if payload is not None:return payload,decoded,attempts
        if len(decoded)==before:break
    payload,_=finish_tile(decoded);return payload,decoded,attempts

def main():
    path=Path(sys.argv[1]);out=path.parent/(path.stem+'-decision-v8');out.mkdir(exist_ok=True);paper=Paper(path)
    folders=[path.parent/(path.stem+s) for s in ('-adaptation-probe','-phase-probe','-enhanced-v8','-decision-v8')]
    targets=list(map(int,sys.argv[2:]))
    for tile in targets:
        decoded={};payload=None
        for folder in folders:
            for name in (f'tile-{tile:03d}-probe.json',f'tile-{tile:03d}.json'):
                file=folder/name
                if file.exists():decoded.update({int(k):bytes.fromhex(v) for k,v in json.loads(file.read_text()).get('partial_blocks',{}).items()})
        payload,decoded,attempts=decision(paper,tile,decoded)
        record=dict(tile=tile,complete=payload is not None,valid_blocks=len(decoded),attempts=attempts,partial_blocks={str(k):v.hex() for k,v in decoded.items()})
        (out/f'tile-{tile:03d}.json').write_text(json.dumps(record,indent=2))
        if payload is not None:(out/f'tile-{tile:03d}.bin').write_bytes(payload)
        print('Decision',tile,payload is not None,len(decoded),[(a['iteration'],a['new_blocks'],round(a['known_validation_accuracy'],3)) for a in attempts if a['new_blocks']],flush=True)

if __name__=='__main__':main()
