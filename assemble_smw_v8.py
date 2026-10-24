"""Iterate per-byte outer erasures and already-CRC-validated XOR equations.
Uses only files recovered from this scan. No source ROM, print PNG, encoding
manifest, compressed copy or precomputed encoded shards are read.
"""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from codec_v8 import GROUPS,DATA_SHARDS,TOTAL_SHARDS,SHARD_BYTES,TILES,OUTER,MAGIC,unpack_container
from recover_smw_v8 import partial
root=Path(__file__).resolve().parent

def iterate(parts,blocks):
    data=np.zeros((TILES,SHARD_BYTES),dtype='uint8');known=np.zeros_like(data,dtype=bool)
    for tile,(values,mask) in parts.items():data[tile]=values;known[tile]=mask
    history=[]
    for iteration in range(12):
        before=int(known.sum());xor_count=0;outer_count=0;padding_count=0
        for tile,decoded in blocks.items():
            values=data[tile].reshape(18,58);mask=known[tile].reshape(18,58)
            for group in range(6):
                if group*4+3 not in decoded:continue
                parity=np.frombuffer(decoded[group*4+3],dtype='uint8');chunk=values[group*3:group*3+3];valid=mask[group*3:group*3+3]
                columns=np.flatnonzero(valid.sum(0)==2)
                for j in columns:
                    missing=int(np.flatnonzero(~valid[:,j])[0]);chunk[missing,j]=parity[j]^np.bitwise_xor.reduce(chunk[valid[:,j],j]);valid[missing,j]=True;xor_count+=1
        for group in range(GROUPS):
            indices=np.arange(TOTAL_SHARDS)*GROUPS+group;values=data[indices];mask=known[indices]
            for j in np.flatnonzero((~mask).sum(0)<=2):
                missing=np.flatnonzero(~mask[:,j])
                if not len(missing):continue
                if mask[:DATA_SHARDS,j].all():
                    corrected=OUTER.encode(bytes(values[:DATA_SHARDS,j]))
                else:corrected=OUTER.decode(bytes(values[:,j]),erase_pos=missing.tolist())[1]
                values[:,j]=list(corrected);mask[:,j]=True;outer_count+=len(missing)
            data[indices]=values;known[indices]=mask
        # Defined zero-padding length is recovered from the paper's own header.
        flat=np.stack([data[np.arange(DATA_SHARDS)*GROUPS+g] for g in range(GROUPS)]).reshape(-1)
        valid=np.stack([known[np.arange(DATA_SHARDS)*GROUPS+g] for g in range(GROUPS)]).reshape(-1)
        if valid[:12].all() and bytes(flat[:8])==MAGIC:
            size=int.from_bytes(bytes(flat[8:12]),'little')
            if 0<size<8192 and valid[12:12+size].all():
                try:
                    metadata=json.loads(bytes(flat[12:12+size]));end=12+size+int(metadata['compressed_bytes'])
                    if 12+size<end<=len(flat):
                        for position in range(end,len(flat)):
                            shard,offset=divmod(position,SHARD_BYTES);group,slot=divmod(shard,DATA_SHARDS);tile=slot*GROUPS+group
                            if not known[tile,offset]:data[tile,offset]=0;known[tile,offset]=True;padding_count+=1
                except (ValueError,KeyError,TypeError):pass
        after=int(known.sum());history.append(dict(iteration=iteration,known_bytes=after,xor_bytes=xor_count,outer_bytes=outer_count,padding_bytes=padding_count))
        if after==before:break
    output=np.stack([data[np.arange(DATA_SHARDS)*GROUPS+g] for g in range(GROUPS)]).reshape(-1)
    valid=np.stack([known[np.arange(DATA_SHARDS)*GROUPS+g] for g in range(GROUPS)]).reshape(-1)
    return bytes(output),valid,history

def load(path):
    parts={};blocks={}
    dirs=[path.parent/(path.stem+s) for s in ('-read-v8','-adaptation-probe','-phase-probe','-enhanced-v8','-decision-v8')]
    for tile in range(TILES):
        decoded={};payload=None
        for folder in dirs:
            file=folder/f'tile-{tile:03d}.bin'
            if file.exists() and file.stat().st_size==SHARD_BYTES:payload=file.read_bytes()
            for name in (f'tile-{tile:03d}-probe.json',f'tile-{tile:03d}.json'):
                file=folder/name
                if file.exists():decoded.update({int(k):bytes.fromhex(v) for k,v in json.loads(file.read_text()).get('partial_blocks',{}).items()})
        blocks[tile]=decoded
        parts[tile]=(np.frombuffer(payload,dtype='uint8'),np.ones(SHARD_BYTES,dtype=bool)) if payload is not None else partial(decoded)
    return parts,blocks

def main():
    path=Path(sys.argv[1]);out=path.parent/(path.stem+'-assembled-v8');out.mkdir(exist_ok=True)
    parts,blocks=load(path);container,valid,history=iterate(parts,blocks)
    report=dict(image=str(path),whole_tiles=sum(mask.all() for values,mask in parts.values()),unknown_data_bytes=int((~valid).sum()),iterations=history,complete=False)
    report['whole_tiles']=int(report['whole_tiles'])
    try:
        raw,metadata=unpack_container(container);report['complete']=True;report['file']=metadata
        name=Path(metadata['name'].replace('\\','/')).name
        if ':' in name or name in ('','.','..'):raise ValueError('Invalid name')
        target=out/('restored-'+name);target.write_bytes(raw);report['restored_file']=str(target)
        if '--verify' in sys.argv:
            reference=Path(sys.argv[sys.argv.index('--verify')+1]).read_bytes();report['original_exact_match']=raw==reference
            if raw!=reference:raise ValueError('Original byte comparison failed')
        print('RESTORED',len(raw),metadata['raw_sha256'],flush=True)
    except (ValueError,KeyError,TypeError) as exc:report['complete']=False;report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()
