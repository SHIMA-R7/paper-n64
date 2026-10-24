"""Full-page v8: 16-color nibbles, inner RS/CRC/XOR, outer tile erasures.
All geometry, pilots, palette and interleaving are format constants. Decoding
does not require the original ROM, its compressed copy or an encoding manifest.
"""
from pathlib import Path
import sys,json,struct,hashlib,lzma
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
from reedsolo import RSCodec,ReedSolomonError
INNER=RSCodec(64);OUTER=RSCodec(2)
STEP=25.4/200;COLS=13;ROWS=27;PW=120;PH=80
X0=(210-COLS*PW*STEP)/2;Y0=(297-ROWS*PH*STEP)/2
GROUPS=19;DATA_SHARDS=16;TOTAL_SHARDS=18;SHARD_BYTES=1044;TILES=GROUPS*TOTAL_SHARDS
MAGIC=b'PAPR8\x00\x00\x00'
PALETTE=[(0,0,0),(255,255,255),(238,0,0),(238,221,17),(0,85,255),(0,136,51),(153,0,238),(136,102,0),(238,153,170),(17,238,204),(187,238,119),(255,136,51),(85,102,102),(0,0,102),(119,17,34),(170,119,238)]
PAGE_MARKERS=np.array([[8.,5.],[202.,5.],[8.,292.],[202.,292.]])

class RNG:
    def __init__(self,seed):self.state=(seed&0xffffffff) or 1
    def next(self):
        x=self.state;x^=(x<<13)&0xffffffff;x^=x>>17;x^=(x<<5)&0xffffffff;self.state=x&0xffffffff
        return self.state
    def shuffle(self,values):
        for j in range(len(values)-1,0,-1):
            k=self.next()%(j+1);values[j],values[k]=values[k],values[j]

def layout(tile):
    rng=RNG(648100+tile*0x9e3779b9);order=list(range(6144));rng.shuffle(order)
    mask=np.array([rng.next()%16 for _ in order],dtype='uint8')
    return np.array(order),mask

def pilots(tile):
    labels=list(np.arange(1024,dtype=int)%16);RNG(648300+tile*0x9e3779b9).shuffle(labels)
    return np.array(labels,dtype='uint8').reshape(64,16)

def tile_geometry(tile):
    row,col=divmod(tile,COLS);x=X0+col*PW*STEP;y=Y0+row*PH*STEP
    return dict(row=row,col=col,x=x,y=y,data_x=x+4*STEP,data_y=y+8*STEP,cal_x=x+102*STEP,cal_y=y+8*STEP,
        markers=[[x,y],[x+PW*STEP,y],[x,y+PH*STEP],[x+PW*STEP,y+PH*STEP]])

def container_from_file(path):
    path=Path(path);raw=path.read_bytes();compressed=lzma.compress(raw,preset=9)
    metadata=dict(format=8,name=path.name,raw_bytes=len(raw),raw_sha256=hashlib.sha256(raw).hexdigest(),
        compression='xz',compressed_bytes=len(compressed),compressed_sha256=hashlib.sha256(compressed).hexdigest())
    header=json.dumps(metadata,separators=(',',':'),ensure_ascii=True).encode('ascii')
    container=MAGIC+struct.pack('<I',len(header))+header+compressed
    if len(container)>GROUPS*DATA_SHARDS*SHARD_BYTES:raise ValueError('File exceeds one-page v8 capacity')
    return container,metadata,compressed

def unpack_container(data):
    if data[:8]!=MAGIC:raise ValueError('Invalid paper archive magic')
    size=struct.unpack('<I',data[8:12])[0]
    if size>8192:raise ValueError('Invalid metadata length')
    metadata=json.loads(data[12:12+size].decode('ascii'))
    if metadata.get('format')!=8 or metadata.get('compression')!='xz':raise ValueError('Unsupported archive')
    length=metadata['compressed_bytes']
    if not isinstance(length,int) or not 0<length<=len(data)-12-size:raise ValueError('Invalid compressed size')
    compressed=data[12+size:12+size+length]
    if hashlib.sha256(compressed).hexdigest()!=metadata['compressed_sha256']:raise ValueError('Compressed SHA256 mismatch')
    decoder=lzma.LZMADecompressor();raw=decoder.decompress(compressed,max_length=metadata['raw_bytes']+1)
    if not decoder.eof or len(raw)!=metadata['raw_bytes']:raise ValueError('Decompression length mismatch')
    if hashlib.sha256(raw).hexdigest()!=metadata['raw_sha256']:raise ValueError('ROM SHA256 mismatch')
    return raw,metadata

def outer_encode(container):
    padded=container.ljust(GROUPS*DATA_SHARDS*SHARD_BYTES,b'\0')
    data=np.frombuffer(padded,dtype='uint8').reshape(GROUPS,DATA_SHARDS,SHARD_BYTES)
    tiles=[None]*TILES
    for group in range(GROUPS):
        code=np.array([list(OUTER.encode(bytes(data[group,:,j]))) for j in range(SHARD_BYTES)],dtype='uint8').T
        for slot in range(TOTAL_SHARDS):tiles[slot*GROUPS+group]=bytes(code[slot])
    return tiles

def outer_recover(tiles):
    groups=[];repaired=[];failed=[]
    for group in range(GROUPS):
        shards=[tiles.get(slot*GROUPS+group) for slot in range(TOTAL_SHARDS)]
        missing=[i for i,s in enumerate(shards) if s is None]
        if len(missing)>2:failed.append(dict(group=group,missing_slots=missing));continue
        if any(shards[i] is None for i in range(DATA_SHARDS)):
            code=np.array([list(s) if s is not None else [0]*SHARD_BYTES for s in shards],dtype='uint8')
            restored=np.array([list(OUTER.decode(bytes(code[:,j]),erase_pos=missing)[0]) for j in range(SHARD_BYTES)],dtype='uint8')
            groups.append(restored.T.tobytes());repaired.extend(slot*GROUPS+group for slot in missing)
        else:groups.append(b''.join(shards[:DATA_SHARDS]))
    return (b''.join(groups) if not failed else None),dict(repaired_tiles=repaired,failed_groups=failed)

def inner_encode(payload,tile):
    import binascii
    if len(payload)!=SHARD_BYTES:raise ValueError('Wrong tile payload size')
    chunks=[payload[i:i+58] for i in range(0,len(payload),58)];codes=[]
    for group in range(6):
        data=chunks[group*3:group*3+3];xor=bytes(a^b^c for a,b,c in zip(*data))
        for k,chunk in enumerate(data+[xor]):
            block=group*4+k;msg=struct.pack('<I',tile*32+block)+chunk
            msg+=struct.pack('<H',binascii.crc_hqx(msg,0xFFFF));codes.append(bytes(INNER.encode(msg)))
    packed=np.frombuffer(b''.join(codes),dtype='uint8');digits=np.column_stack([packed>>4,packed&15]).ravel()
    order,mask=layout(tile);raw=np.empty(6144,dtype='uint8');raw[order]=digits
    return ((raw+mask)%16).reshape(64,96)

def decode_blocks(symbols,confidence,tile,decoded=None):
    import binascii
    decoded={} if decoded is None else dict(decoded);order,mask=layout(tile)
    digits=((np.asarray(symbols).ravel().astype(int)-mask)%16)[order]
    quality=np.asarray(confidence).ravel()[order].reshape(24,128,2).min(2)
    codes=((digits[::2]<<4)|digits[1::2]).astype('uint8').reshape(24,128);details=[]
    for block,code in enumerate(codes):
        if block in decoded:continue
        ranking=np.argsort(quality[block])
        for erased in (0,8,16,24,32,48,64):
            try:
                msg,_,errors=INNER.decode(bytes(code),erase_pos=ranking[:erased].tolist());msg=bytes(msg)
                if len(msg)!=64 or struct.unpack('<I',msg[:4])[0]!=tile*32+block:continue
                if binascii.crc_hqx(msg[:62],0xFFFF)!=struct.unpack('<H',msg[62:])[0]:continue
                decoded[block]=msg[4:62];details.append(dict(block=block,erased_bytes=erased,errata_bytes=len(errors)));break
            except (ReedSolomonError,ValueError,IndexError):pass
    return decoded,details

def finish_tile(decoded):
    decoded=dict(decoded);repaired=[]
    for group in range(6):
        missing=[group*4+b for b in range(4) if group*4+b not in decoded]
        if len(missing)==1:
            lost=missing[0];decoded[lost]=bytes(a^b^c for a,b,c in zip(*(decoded[group*4+b] for b in range(4) if group*4+b!=lost)));repaired.append(lost)
    complete=all(g*4+b in decoded for g in range(6) for b in range(3))
    payload=b''.join(decoded[g*4+b] for g in range(6) for b in range(3)) if complete else None
    return payload,repaired

def self_test(container,metadata):
    import random
    shards=outer_encode(container)
    for tile in (0,169,341):
        symbols=inner_encode(shards[tile],tile);decoded,_=decode_blocks(symbols,np.ones_like(symbols),tile)
        payload,_=finish_tile(decoded);assert payload==shards[tile]
        # One fully lost inner codeword per XOR group.
        decoded={k:v for k,v in decoded.items() if k%4!=0};payload,xor=finish_tile(decoded);assert payload==shards[tile] and len(xor)==6
        damaged=symbols.ravel().copy();order,_=layout(tile)
        for block in range(24):
            for byte in range(32):
                index=order[(block*128+byte)*2];damaged[index]=(damaged[index]+1)%16
        decoded,_=decode_blocks(damaged,np.ones_like(damaged),tile);payload,_=finish_tile(decoded);assert payload==shards[tile]
    # Every horizontal tile row and every vertical tile column can disappear.
    for kind,limit in (('row',ROWS),('column',COLS)):
        for lost in range(limit):
            kept={i:s for i,s in enumerate(shards) if (i//COLS if kind=='row' else i%COLS)!=lost}
            got,detail=outer_recover(kept);assert got is not None,(kind,lost,detail)
            raw,meta=unpack_container(got);assert meta==metadata
    return shards
