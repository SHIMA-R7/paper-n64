"""Bounded radix coding: two bytes per group, RS(128,64), CRC, 3+1 XOR.
No fractional-bit claim for non-power-of-two palettes. A symbol error affects
at most two RS bytes. Deterministic modular whitening balances printed colors.
"""
from pathlib import Path
import sys,random,struct,binascii
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
from reedsolo import RSCodec,ReedSolomonError
codec=RSCodec(64)

def width(nc):
    digits=1
    while nc**digits<65536:digits+=1
    return digits

def layout(nc):
    rng=random.Random(647100+nc);order=list(range(96*96));rng.shuffle(order)
    mask=np.array([rng.randrange(nc) for _ in order],dtype=int)
    return np.array(order),mask

def encode_radix(code,nc):
    digits=width(nc);out=[]
    for i in range(0,len(code),2):
        value=int.from_bytes(code[i:i+2],'big');part=[0]*digits
        for j in range(digits-1,-1,-1):part[j]=value%nc;value//=nc
        assert value==0;out.extend(part)
    return np.array(out)

def decode_radix(symbols,nc):
    digits=width(nc);out=bytearray();invalid=[]
    for i,part in enumerate(np.asarray(symbols).reshape(-1,digits)):
        value=0
        for digit in part:value=value*nc+int(digit)
        if value>=65536:invalid.extend([i*2,i*2+1]);value=0
        out.extend(value.to_bytes(2,'big'))
    return bytes(out),invalid

def make_payload():
    rng=random.Random(647007);groups=[]
    for _ in range(4):
        chunks=[rng.randbytes(58) for _ in range(3)]
        chunks.append(bytes(a^b^c for a,b,c in zip(*chunks)))
        groups.append(chunks)
    return groups

def make_data(nc):
    groups=make_payload();codes=[]
    for group,chunks in enumerate(groups):
        for block,chunk in enumerate(chunks):
            msg=struct.pack('<I',group*4+block)+chunk
            msg+=struct.pack('<H',binascii.crc_hqx(msg,0xFFFF))
            codes.append(bytes(codec.encode(msg)))
    order,mask=layout(nc);rng=random.Random(647200+nc)
    raw=np.array([rng.randrange(nc) for _ in order]);stream=np.concatenate([encode_radix(c,nc) for c in codes])
    raw[order[:len(stream)]]=stream
    symbols=(raw+mask)%nc
    payload=b''.join(groups[g][b] for g in range(4) for b in range(3))
    return symbols.reshape(96,96),payload,len(stream)

def recover(symbols,confidence,nc):
    order,mask=layout(nc);raw=(np.asarray(symbols).ravel()-mask)%nc
    stream=raw[order];quality=np.asarray(confidence).ravel()[order]
    stride=64*width(nc);decoded={};details=[]
    for block in range(16):
        s=stream[block*stride:(block+1)*stride]
        code,invalid=decode_radix(s,nc)
        q=quality[block*stride:(block+1)*stride].reshape(64,width(nc)).min(1)
        ranking=np.argsort(q)
        for erased_pairs in (0,4,8,12,16,24,32):
            erased=sorted(set(invalid+[int(j*2+k) for j in ranking[:erased_pairs] for k in (0,1)]))
            if len(erased)>64:continue
            try:
                msg,_,errata=codec.decode(code,erase_pos=erased);msg=bytes(msg)
                if len(msg)!=64 or struct.unpack('<I',msg[:4])[0]!=block:continue
                if binascii.crc_hqx(msg[:62],0xFFFF)!=struct.unpack('<H',msg[62:])[0]:continue
                decoded[block]=msg[4:62];details.append(dict(block=block,erased_bytes=len(erased),corrected_bytes=len(errata)));break
            except (ReedSolomonError,ValueError,IndexError):pass
    xor=[]
    for group in range(4):
        missing=[group*4+b for b in range(4) if group*4+b not in decoded]
        if len(missing)==1:
            lost=missing[0];decoded[lost]=bytes(a^b^c for a,b,c in zip(*(decoded[group*4+b] for b in range(4) if group*4+b!=lost)))
            xor.append(lost)
    complete=all(g*4+b in decoded for g in range(4) for b in range(3))
    payload=b''.join(decoded[g*4+b] for g in range(4) for b in range(3)) if complete else None
    return payload,dict(rs_crc_blocks=len(details),total_blocks=16,xor_recovered=xor,complete=complete,details=details)

def self_test():
    for nc in (8,10,12,16,20):
        symbols,payload,_=make_data(nc)
        got,_=recover(symbols,np.ones_like(symbols),nc);assert got==payload
        rng=random.Random(nc)
        for _ in range(10):
            code=bytes(rng.randrange(256) for _ in range(128))
            back,invalid=decode_radix(encode_radix(code,nc),nc);assert back==code and not invalid
        msg=bytes(range(64));code=bytearray(codec.encode(msg))
        for j in range(32):code[j*3]^=j+1
        assert bytes(codec.decode(code)[0])==msg
        order,_=layout(nc);stride=64*width(nc)
        damaged=symbols.ravel().copy();confidence=np.ones_like(damaged)
        # A fully destroyed RS block in each XOR group must be recovered.
        for block in (0,4,8,12):
            indices=order[block*stride:(block+1)*stride];damaged[indices]=(damaged[indices]+1)%nc
        got,detail=recover(damaged,confidence,nc);assert got==payload and len(detail['xor_recovered'])==4
    return True
