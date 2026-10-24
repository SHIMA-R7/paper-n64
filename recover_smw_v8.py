"""CRC-directed candidate recovery, no original file or encoded shards read.
Known pilots train class identities; unlabeled payload moments can adapt color.
Partial CRC-valid inner blocks are retained for per-byte outer erasure repair.
"""
from pathlib import Path
import sys,json,time,hashlib
import numpy as np
from read_smw_v8 import Paper,calibrate
from decode_calibrated_v7 import classify,neighbors
from probe_smw_v8 import adapt,power
from codec_v8 import TILES,GROUPS,DATA_SHARDS,TOTAL_SHARDS,SHARD_BYTES,OUTER,pilots,decode_blocks,finish_tile,unpack_container
root=Path(__file__).resolve().parent

def partial(decoded):
    decoded=dict(decoded)
    for group in range(6):
        missing=[group*4+k for k in range(4) if group*4+k not in decoded]
        if len(missing)==1:decoded[missing[0]]=bytes(a^b^c for a,b,c in zip(*(decoded[group*4+k] for k in range(4) if group*4+k!=missing[0])))
    data=np.zeros(SHARD_BYTES,dtype='uint8');known=np.zeros(SHARD_BYTES,dtype=bool)
    for group in range(6):
        for k in range(3):
            if group*4+k in decoded:
                start=(group*3+k)*58;data[start:start+58]=list(decoded[group*4+k]);known[start:start+58]=True
    return data,known

def recover_outer_bytes(parts):
    output=np.zeros((GROUPS,DATA_SHARDS,SHARD_BYTES),dtype='uint8');valid=np.zeros_like(output,dtype=bool)
    repaired=0
    for group in range(GROUPS):
        data=np.zeros((TOTAL_SHARDS,SHARD_BYTES),dtype='uint8');known=np.zeros_like(data,dtype=bool)
        for slot in range(TOTAL_SHARDS):
            tile=slot*GROUPS+group
            if tile in parts:data[slot],known[slot]=parts[tile]
        for j in range(SHARD_BYTES):
            missing=np.flatnonzero(~known[:,j])
            if len(missing)<=2 and not known[:DATA_SHARDS,j].all():
                restored=OUTER.decode(bytes(data[:,j]),erase_pos=missing.tolist())[0]
                data[:DATA_SHARDS,j]=list(restored);known[:DATA_SHARDS,j]=True;repaired+=1
        output[group]=data[:DATA_SHARDS];valid[group]=known[:DATA_SHARDS]
    return output.tobytes(),dict(unresolved_data_bytes=int((~valid).sum()),repaired_column_positions=repaired)

def semi_supervised(values,training,labels,model):
    means,beta,covs=model;z=values.reshape(-1,3)-neighbors(values)@beta
    cal=training.reshape(-1,3)-neighbors(training)@beta
    dc=np.cov(z.T);rc=np.cov(cal.T);dh=power(dc,.5);dih=power(dc,-.5)
    z=(z-z.mean(0))@(dih@power(dh@rc@dh,.5)@dih)+cal.mean(0)
    fixed=np.eye(16)[labels.ravel()]*2.;means=means.copy();covs=covs.copy()
    for iteration in range(25):
        log=[]
        for k in range(16):
            d=z-means[k];log.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(covs[k]),d)+np.linalg.slogdet(covs[k])[1]))
        log=np.stack(log,1);log-=log.max(1,keepdims=True);p=np.exp(log);p/=p.sum(1,keepdims=True)
        nk=p.sum(0)+fixed.sum(0);new=(p.T@z+fixed.T@cal)/nk[:,None];newcov=[]
        for k in range(16):
            d=z-new[k];c=cal-new[k];cov=(d.T@(d*p[:,k,None])+c.T@(c*fixed[:,k,None]))/nk[k]
            newcov.append(cov+np.eye(3)*3.)
        if np.max(abs(new-means))<.02:means=new;covs=np.array(newcov);break
        means=new;covs=np.array(newcov)
    return classify(z.reshape(values.shape),(means,np.zeros((12,3)),covs))

def enhanced(paper,tile,decoded,budget=16):
    matrix=paper.matrix(tile);cr=paper.grid(tile,matrix,True);dr=paper.grid(tile,matrix)
    shift,models=calibrate(cr,pilots(tile));training=cr(shift);candidates=[]
    for dx,dy in [(0,0),(0,.25),(0,-.25),(-.25,0),(.25,0),(-.25,.25),(.25,.25),(-.25,-.25),(.25,-.25)]:
        phase=shift+np.array([dx,dy]);values=dr(phase)
        for accuracy,cancel,model in models:
            for kind in ('none','diagonal','covariance'):
                prediction,confidence=adapt(values,training,model,kind)
                frequency=np.bincount(prediction,minlength=16)/len(prediction)
                score=float(confidence.mean()-.5*abs(frequency-1/16).sum())
                candidates.append((score,prediction,confidence,dict(phase=phase.tolist(),neighbor=cancel,adaptation=kind)))
    candidates.sort(key=lambda q:q[0],reverse=True);attempts=[]
    for score,prediction,confidence,description in candidates[:budget]:
        decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
        attempts.append(dict(**description,quality_score=score,new_blocks=len(detail)))
        payload,xor=finish_tile(decoded)
        if payload is not None:return payload,decoded,attempts
    # Final fallback adapts Gaussian clusters while keeping pilots labeled.
    for phase in (shift,shift+[0,.25],shift+[-.25,0],shift+[.25,0]):
        values=dr(phase)
        for accuracy,cancel,model in models:
            prediction,confidence=semi_supervised(values,training,pilots(tile),model)
            decoded,detail=decode_blocks(prediction,confidence,tile,decoded)
            attempts.append(dict(phase=phase.tolist(),neighbor=cancel,adaptation='pilot_anchored_em',new_blocks=len(detail)))
            payload,_=finish_tile(decoded)
            if payload is not None:return payload,decoded,attempts
    return None,decoded,attempts

def main():
    worker='--worker' in sys.argv
    if worker:sys.argv.remove('--worker')
    resume='--resume' in sys.argv
    if resume:sys.argv.remove('--resume')
    budget=16
    if '--budget' in sys.argv:
        index=sys.argv.index('--budget');budget=int(sys.argv[index+1]);del sys.argv[index:index+2]
    path=Path(sys.argv[1]);out=path.parent/(path.stem+'-enhanced-v8');out.mkdir(exist_ok=True)
    cache_dirs=[path.parent/(path.stem+s) for s in ('-read-v8','-adaptation-probe','-phase-probe','-enhanced-v8')]
    paper=Paper(path);parts={};reports=[];complete=0;started=time.monotonic()
    targets=list(map(int,sys.argv[2:])) if len(sys.argv)>2 else list(range(TILES))
    for tile in targets:
        payload=None;decoded={};cached=False;attempts=[]
        for cache in cache_dirs:
            file=cache/f'tile-{tile:03d}.bin'
            if file.exists() and file.stat().st_size==SHARD_BYTES:payload=file.read_bytes();cached=True;break
            for filename in (f'tile-{tile:03d}-probe.json',f'tile-{tile:03d}.json'):
                file=cache/filename
                if file.exists():
                    obj=json.loads(file.read_text());decoded.update({int(k):bytes.fromhex(v) for k,v in obj.get('partial_blocks',{}).items()})
        already_done=resume and (out/f'tile-{tile:03d}.json').exists()
        if payload is None:
            payload,_=finish_tile(decoded)
            if payload is None and not already_done:
                try:payload,decoded,attempts=enhanced(paper,tile,decoded,budget)
                except (ValueError,IndexError,np.linalg.LinAlgError) as exc:attempts=[dict(error=str(exc))]
        if payload is not None:
            complete+=1;(out/f'tile-{tile:03d}.bin').write_bytes(payload)
            parts[tile]=(np.frombuffer(payload,dtype='uint8'),np.ones(SHARD_BYTES,dtype=bool))
        else:parts[tile]=partial(decoded)
        record=dict(tile=tile,complete=payload is not None,cached=cached,valid_blocks=len(decoded),attempts=attempts,
            partial_blocks={str(k):v.hex() for k,v in decoded.items()})
        (out/f'tile-{tile:03d}.json').write_text(json.dumps(record,indent=2));reports.append(record)
        if len(targets)<TILES or (tile+1)%13==0 or tile==TILES-1:
            state=dict(image=str(path),tiles_processed=len(reports),tiles_complete=complete,total_tiles=TILES,elapsed_seconds=time.monotonic()-started,
                details=[{k:v for k,v in r.items() if k not in ('partial_blocks','attempts')} for r in reports])
            (out/('worker-report.json' if worker else 'report.json')).write_text(json.dumps(state,indent=2))
            print('Enhanced',len(reports),'complete',complete,'last',tile,'blocks',len(decoded),'time',round(time.monotonic()-started,1),flush=True)
    if len(targets)==TILES:
        container,detail=recover_outer_bytes(parts);state['outer_partial_recovery']=detail;state['complete']=False
        try:
            raw,metadata=unpack_container(container);state['complete']=True;state['file']=metadata
            target=out/('restored-'+Path(metadata['name'].replace('\\','/')).name);target.write_bytes(raw);state['restored_file']=str(target)
            print('RESTORED',len(raw),'bytes',metadata['raw_sha256'],flush=True)
        except (ValueError,KeyError,TypeError) as exc:state['container_error']=str(exc)
        (out/'report.json').write_text(json.dumps(state,indent=2));print(out,flush=True)

if __name__=='__main__':main()
