"""Decode one scan independently; bootstrap from its CRC-validated words only."""
from pathlib import Path
import sys,json,time
import numpy as np
from read_smw_v8 import Paper,calibrate
from recover_smw_v8 import adapt
from decision_smw_v8 import decision
from codec_v8 import TILES,pilots,decode_blocks,finish_tile

def bootstrap(paper,tile,budget=8):
    matrix=paper.matrix(tile);cr=paper.grid(tile,matrix,True);dr=paper.grid(tile,matrix)
    shift,models=calibrate(cr,pilots(tile));training=cr(shift);candidates=[]
    for dx,dy in ((0,0),(0,.25),(0,-.25),(-.25,0),(.25,0),(-.25,.25),(.25,.25),(-.25,-.25),(.25,-.25)):
        phase=shift+np.array([dx,dy]);values=dr(phase)
        for accuracy,cancel,model in models:
            for kind in ('none','diagonal','covariance'):
                prediction,confidence=adapt(values,training,model,kind)
                frequency=np.bincount(prediction,minlength=16)/len(prediction)
                score=float(confidence.mean()-.5*abs(frequency-1/16).sum())
                candidates.append((score,prediction,confidence,dict(phase=phase.tolist(),neighbor=cancel,adaptation=kind)))
    candidates.sort(key=lambda q:q[0],reverse=True);decoded={};attempts=[];last_decision=0
    for score,prediction,confidence,description in candidates[:budget]:
        decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
        attempts.append(dict(**description,quality_score=score,new_blocks=len(detail)))
        payload,_=finish_tile(decoded)
        if payload is not None:return payload,decoded,attempts
        if len(decoded)>last_decision:
            payload,decoded,extra=decision(paper,tile,decoded);attempts+=extra;last_decision=len(decoded)
            if payload is not None:return payload,decoded,attempts
    if len(decoded)>=2:
        from warp_smw_v8 import recover as recover_warp
        payload,decoded,extra=recover_warp(paper,tile,decoded);attempts+=extra
        if payload is not None:return payload,decoded,attempts
    return None,decoded,attempts

def main():
    path=Path(sys.argv[1]).resolve();start=int(sys.argv[2]) if len(sys.argv)>2 else 0;stop=int(sys.argv[3]) if len(sys.argv)>3 else TILES;budget=int(sys.argv[4]) if len(sys.argv)>4 else 8
    out=path.parent/(path.stem+'-enhanced-v8');out.mkdir(exist_ok=True)
    paper=Paper(path);print('Registered',len(paper.nodes),'missing',sum(p is None for p in paper.nodes.values()),flush=True)
    began=time.monotonic();complete=0
    for tile in range(start,stop):
        target=out/f'tile-{tile:03d}.json'
        if target.exists():continue
        try:payload,decoded,attempts=bootstrap(paper,tile,budget)
        except (ValueError,IndexError,np.linalg.LinAlgError) as exc:payload=None;decoded={};attempts=[dict(error=str(exc))]
        record=dict(tile=tile,complete=payload is not None,valid_blocks=len(decoded),attempts=attempts,partial_blocks={str(k):v.hex() for k,v in decoded.items()})
        target.write_text(json.dumps(record,indent=2))
        if payload is not None:(out/f'tile-{tile:03d}.bin').write_bytes(payload);complete+=1
        print('Tile',tile,'complete',payload is not None,'blocks',len(decoded),'worker_complete',complete,'seconds',round(time.monotonic()-began,1),flush=True)

if __name__=='__main__':main()
