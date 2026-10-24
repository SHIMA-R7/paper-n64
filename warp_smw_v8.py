"""Fit smooth intra-tile displacement using this scan's validated words only."""
from pathlib import Path
import sys,json
import numpy as np
from read_smw_v8 import Paper
from decision_smw_v8 import known_labels,reader,align
from decode_calibrated_v7 import fit,classify
from codec_v8 import tile_geometry,STEP,decode_blocks,finish_tile
from assemble_smw_v8 import load

def recover(paper,tile,decoded):
    matrix=paper.matrix(tile);g=tile_geometry(tile);xx,yy=np.meshgrid(np.arange(96)+.5,np.arange(64)+.5)
    x=(xx-48)/48;y=(yy-32)/32
    basis=np.stack([np.ones_like(x),x,y,x*y,x*x,y*y,x*x*y,x*y*y,x*x*x,y*y*y],-1)
    a=paper.a;attempts=[]
    def read(p):
        delta=basis@p.T
        q=np.stack([g['data_x']+(xx+delta[...,0])*STEP,g['data_y']+(yy+delta[...,1])*STEP,np.ones_like(xx)],-1)@matrix.T
        u=q[...,0]/q[...,2];v=q[...,1]/q[...,2];xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
        return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
    for iteration in range(3):
        labels,known=known_labels(decoded,tile)
        if known.sum()<512:return None,decoded,attempts
        train=known&(np.arange(6144)%5!=0);val=known&~train
        old=align(reader(paper,tile),labels,train)
        p=np.zeros((2,10));p[:,0]=old[:2];p[0,1]=48*(old[2]-1);p[1,2]=32*(old[3]-1)
        lab=labels.ravel()[train];counts=np.bincount(lab,minlength=16)
        def score(params):
            values=read(params).reshape(-1,3)[train]
            means=np.column_stack([np.bincount(lab,weights=values[:,c],minlength=16) for c in range(3)])/np.maximum(counts[:,None],1)
            total=float(((values-values.mean(0))**2).sum());error=float(((values-means[lab])**2).sum())
            return (total-error)/max(total,len(values)*25.)
        for radius in (.24,.12,.05,.02):
            for term in (0,1,2,3,4,5,6,7,8,9):
                for axis in (0,1):
                    choices=[]
                    for delta in (-radius,-radius/2,0,radius/2,radius):
                        q=p.copy();q[axis,term]+=delta
                        if np.max(abs(basis@q.T))>2.5:continue
                        choices.append((score(q),q))
                    p=max(choices,key=lambda z:z[0])[1]
        values=read(p);before=len(decoded)
        for cancel in (True,False):
            model=fit(values,labels,16,cancel,train);prediction,_=classify(values,model)
            accuracy=float((prediction[val]==labels.ravel()[val]).mean())
            model=fit(values,labels,16,cancel,known)
            for shift in ((0,0),(-.08,0),(.08,0),(0,-.08),(0,.08)):
                q=p.copy();q[:,0]+=shift
                prediction,confidence=classify(read(q),model)
                decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
                attempts.append(dict(iteration=iteration,neighbor=cancel,parameters=q.tolist(),validation_accuracy=accuracy,new_blocks=len(detail)))
                payload,_=finish_tile(decoded)
                if payload is not None:return payload,decoded,attempts
        if len(decoded)==before:break
    return None,decoded,attempts

def main():
    path=Path(sys.argv[1]);paper=Paper(path);_,blocks=load(path);out=path.parent/(path.stem+'-decision-v8');out.mkdir(exist_ok=True)
    for tile in map(int,sys.argv[2:]):
        payload,decoded,attempts=recover(paper,tile,blocks[tile])
        record=dict(tile=tile,complete=payload is not None,valid_blocks=len(decoded),attempts=attempts,partial_blocks={str(k):v.hex() for k,v in decoded.items()})
        (out/f'tile-{tile:03d}.json').write_text(json.dumps(record,indent=2))
        if payload is not None:(out/f'tile-{tile:03d}.bin').write_bytes(payload)
        print('Warp',tile,payload is not None,'blocks',len(decoded),'validation',[round(a['validation_accuracy'],4) for a in attempts[:1]],flush=True)

if __name__=='__main__':main()
