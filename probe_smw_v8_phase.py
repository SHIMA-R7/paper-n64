from pathlib import Path
import sys,json
import numpy as np
from read_smw_v8 import Paper,calibrate
from codec_v8 import pilots,decode_blocks,finish_tile
from probe_smw_v8 import adapt
root=Path(__file__).resolve().parent
path=Path(sys.argv[1]);paper=Paper(path);out=path.parent/(path.stem+'-phase-probe');out.mkdir(exist_ok=True)
for tile in map(int,sys.argv[2:]):
    matrix=paper.matrix(tile);cr=paper.grid(tile,matrix,True);dr=paper.grid(tile,matrix)
    shift,models=calibrate(cr,pilots(tile));training=cr(shift);decoded={};attempts=[]
    for dy in (.4,.55,.7,.25,0.,-.25,-.5):
        phase=shift+np.array([0.,dy]);values=dr(phase)
        for accuracy,cancel,model in models:
            prediction,confidence=adapt(values,training,model,'none');decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
            payload,xor=finish_tile(decoded);attempts.append(dict(phase=phase.tolist(),neighbor=cancel,new_blocks=len(detail)))
            if payload is not None:break
        if payload is not None:break
    if payload is not None:(out/f'tile-{tile:03d}.bin').write_bytes(payload)
    result=dict(tile=tile,complete=payload is not None,valid_blocks=len(decoded),attempts=attempts,partial_blocks={str(k):v.hex() for k,v in decoded.items()})
    (out/f'tile-{tile:03d}.json').write_text(json.dumps(result,indent=2))
    print(tile,payload is not None,len(decoded),attempts,flush=True)
