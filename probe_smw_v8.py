"""Unlabeled distribution adaptation, validated by transmitted RS/address/CRC.
Never reads the original payload, encoded container, shards or source image.
"""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from read_smw_v8 import Paper,calibrate
from decode_calibrated_v7 import classify,neighbors
from codec_v8 import pilots,decode_blocks,finish_tile
root=Path(__file__).resolve().parent

def power(cov,p):
    d,u=np.linalg.eigh(cov);return (u*np.maximum(d,1.)**p)@u.T

def adapt(values,training,model,kind):
    means,beta,covs=model
    z=values.reshape(-1,3)-neighbors(values)@beta
    reference=training.reshape(-1,3)-neighbors(training)@beta
    if kind=='none':corrected=z
    elif kind=='diagonal':corrected=(z-z.mean(0))*(reference.std(0)/np.maximum(z.std(0),1.))+reference.mean(0)
    else:
        dc=np.cov(z.T);rc=np.cov(reference.T);dh=power(dc,.5);dih=power(dc,-.5)
        mapping=dih@power(dh@rc@dh,.5)@dih
        corrected=(z-z.mean(0))@mapping+reference.mean(0)
    return classify(corrected.reshape(values.shape),(means,np.zeros((12,3)),covs))

def probe(paper,tile,out):
    matrix=paper.matrix(tile);calread=paper.grid(tile,matrix,True);dataread=paper.grid(tile,matrix)
    shift,models=calibrate(calread,pilots(tile));training=calread(shift)
    arrays=dict(calibration=training,values_zero=dataread(),values_cal=dataread(shift))
    np.savez_compressed(out/f'tile-{tile:03d}-samples.npz',**arrays)
    decoded={};attempts=[]
    for phase in (shift,np.zeros(2),shift+[0,-.25],shift+[0,.25],shift+[-.25,0],shift+[.25,0]):
        values=dataread(phase)
        for accuracy,cancel,model in models:
            for kind in ('none','diagonal','covariance'):
                prediction,confidence=adapt(values,training,model,kind)
                decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
                attempts.append(dict(phase=phase.tolist(),model='neighbor' if cancel else 'center',kind=kind,new_blocks=len(detail)))
                payload,xor=finish_tile(decoded)
                if payload is not None:break
            if payload is not None:break
        if payload is not None:break
    report=dict(tile=tile,complete=payload is not None,valid_blocks=len(decoded),xor=xor,attempts=attempts,
        partial_blocks={str(k):v.hex() for k,v in decoded.items()})
    (out/f'tile-{tile:03d}-probe.json').write_text(json.dumps(report,indent=2))
    if payload is not None:(out/f'tile-{tile:03d}.bin').write_bytes(payload)
    print(tile,report['complete'],len(decoded),[(x['phase'],x['model'],x['kind'],x['new_blocks']) for x in attempts if x['new_blocks']],flush=True)

def main():
    path=Path(sys.argv[1]);out=path.parent/(path.stem+'-adaptation-probe');out.mkdir(exist_ok=True);paper=Paper(path)
    for tile in map(int,sys.argv[2:]):probe(paper,tile,out)

if __name__=='__main__':main()
