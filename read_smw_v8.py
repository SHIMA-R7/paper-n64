"""Read a complete v8 paper archive without the original file or manifest.
The optional --verify path is accessed only AFTER the paper container and both
embedded SHA256 checks have passed. No payload reference guides recovery.
"""
from pathlib import Path
import sys,json,hashlib,time
import numpy as np
from PIL import Image
from codec_v8 import *
from analyze_calibration_v6 import homography
from decode_calibrated_v7 import fit,classify

root=Path(__file__).resolve().parent;Image.MAX_IMAGE_PIXELS=200_000_000

class Paper:
    def __init__(self,path):
        im=Image.open(path).convert('RGB');thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
        def orientation(g):
            h,w=g.shape
            return (g[int(h*13/297):int(h*19/297),int(w*10/210):int(w*56/210)]<180).mean()
        self.rotated=bool(orientation(gray[::-1,::-1])>orientation(gray))
        if self.rotated:im=im.transpose(Image.Transpose.ROTATE_180);gray=gray[::-1,::-1].copy()
        self.a=np.asarray(im);self.gray=gray;h,w=gray.shape;self.sx=im.width/w;self.sy=im.height/h
        corners=[]
        for x,y in PAGE_MARKERS:
            # Bottom outer rings may be clipped by the printer's hard margin.
            # Their full top edge still gives both width and center location.
            clipped=bool(y>150)
            cx,cy=self.thumb_marker(w*x/210,h*y/297,85,clipped)
            corners.append(self.full_marker((cx+.5)*self.sx-.5,(cy+.5)*self.sy-.5,85,clipped))
        self.page_matrix=homography(PAGE_MARKERS,np.array(corners));self.nodes={}
        for row in range(ROWS+1):
            for col in range(COLS+1):
                p=np.array([X0+col*PW*STEP,Y0+row*PH*STEP,1])@self.page_matrix.T;u,v=p[:2]/p[2]
                try:self.nodes[row,col]=self.full_marker(u,v,26)
                except ValueError:self.nodes[row,col]=None
    @staticmethod
    def component_center(mask,x0,y0,allow_bottom_clipped=False):
        unseen=set(zip(*np.where(mask)));best=[]
        while unseen:
            q=unseen.pop();stack=[q];part=[q]
            while stack:
                yy,xx=stack.pop()
                for near in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                    if near in unseen:unseen.remove(near);stack.append(near);part.append(near)
            # A paper/scanner edge can be a larger component than the ring.
            # Reject incompatible components before selecting the largest.
            p=np.array(part);width=np.ptp(p[:,1]);height=np.ptp(p[:,0])
            square=min(width,height)>=3 and max(width,height)<=min(width,height)*1.7
            clipped=allow_bottom_clipped and width>height*1.7 and width>5
            if (square or clipped) and len(part)>len(best):best=part
        if len(best)<8:raise ValueError('No registration ring')
        p=np.array(best);width=np.ptp(p[:,1]);height=np.ptp(p[:,0])
        if allow_bottom_clipped and width>height*1.7 and width>5:
            return [x0+(p[:,1].min()+p[:,1].max())/2,y0+p[:,0].min()+width/2]
        if min(width,height)<3 or max(width,height)>min(width,height)*1.7:raise ValueError('Bad registration ring shape')
        return [x0+(p[:,1].min()+p[:,1].max())/2,y0+(p[:,0].min()+p[:,0].max())/2]
    def thumb_marker(self,x,y,r,allow_bottom_clipped=False):
        h,w=self.gray.shape;x0=max(0,int(x-r));y0=max(0,int(y-r));x1=min(w,int(x+r+1));y1=min(h,int(y+r+1))
        return self.component_center(self.gray[y0:y1,x0:x1]<110,x0,y0,allow_bottom_clipped)
    def full_marker(self,x,y,r,allow_bottom_clipped=False):
        h,w=self.a.shape[:2];x0=max(0,round(x-r));y0=max(0,round(y-r));x1=min(w,round(x+r)+1);y1=min(h,round(y+r)+1)
        return self.component_center(self.a[y0:y1,x0:x1].max(2)<110,x0,y0,allow_bottom_clipped)
    def matrix(self,tile):
        g=tile_geometry(tile);r,c=g['row'],g['col'];dst=[self.nodes[p] for p in [(r,c),(r,c+1),(r+1,c),(r+1,c+1)]]
        if any(p is None for p in dst):raise ValueError('Tile has missing registration ring')
        return homography(np.array(g['markers']),np.array(dst))
    def grid(self,tile,matrix,calibration=False):
        g=tile_geometry(tile);height=64;width=16 if calibration else 96
        x=g['cal_x'] if calibration else g['data_x'];y=g['cal_y'] if calibration else g['data_y']
        xx,yy=np.meshgrid(np.arange(width)+.5,np.arange(height)+.5);a=self.a
        def read(shift=(0,0),nearest=False):
            p=np.stack([x+(xx+shift[0])*STEP,y+(yy+shift[1])*STEP,np.ones_like(xx)],-1)@matrix.T
            u=p[...,0]/p[...,2];v=p[...,1]/p[...,2]
            if nearest:return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
            xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
            return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        return read

def calibrate(read,labels):
    yy,xx=np.indices(labels.shape);inside=((xx>0)&(xx<labels.shape[1]-1)&(yy>0)&(yy<labels.shape[0]-1)).ravel()
    validation=(np.arange(labels.size)%5==0)&inside;train=inside&~validation
    def score(shift):
        values=read(shift).reshape(-1,3)[train];label=labels.ravel()[train];counts=np.bincount(label,minlength=16)
        means=np.column_stack([np.bincount(label,weights=values[:,c],minlength=16) for c in range(3)])/counts[:,None]
        total=float(((values-values.mean(0))**2).sum());error=float(((values-means[label])**2).sum())
        return (total-error)/max(total,len(values)*25.)
    choices=[(score((x,y)),np.array([x,y])) for x in (-.3,0,.3) for y in (-.3,0,.3)]
    shift=max(choices,key=lambda q:q[0])[1]
    for radius in (.12,.04):
        for axis in (0,1):
            choices=[]
            for delta in np.linspace(-radius,radius,7):
                q=shift.copy();q[axis]+=delta
                if np.max(abs(q))<=.45:choices.append((score(q),q))
            shift=max(choices,key=lambda q:q[0])[1]
    training=read(shift);models=[]
    for cancel in (False,True):
        pred,_=classify(training,fit(training,labels,16,cancel,train))
        accuracy=float((pred[validation]==labels.ravel()[validation]).mean())
        models.append((accuracy,cancel,fit(training,labels,16,cancel,inside)))
    return shift,sorted(models,key=lambda q:q[0],reverse=True)

def read_tile(paper,tile):
    matrix=paper.matrix(tile);calread=paper.grid(tile,matrix,True);dataread=paper.grid(tile,matrix)
    calibration=calread(nearest=True);palette=np.array(PALETTE)
    residual=((calibration.reshape(-1,1,3)-palette[None,:,:])**2).sum(2).min(1)
    exact=bool((residual<.25).all());decoded={};details=[];attempts=[]
    if exact:
        values=dataread(nearest=True);dist=((values.reshape(-1,1,3)-palette[None,:,:])**2).sum(2)
        if not (dist.min(1)<.25).all():exact=False
        else:
            prediction=dist.argmin(1);decoded,d=decode_blocks(prediction,np.ones(6144),tile);details+=d
            attempts.append(dict(model='exact_measured_palette',blocks=len(d)))
    if not exact:
        shift,models=calibrate(calread,pilots(tile));p=shift.copy()
        # Image-only refinement of data phase, bounded around its pilot phase.
        for radius in (.16,.05):
            for axis in (0,1):
                choices=[]
                for delta in np.linspace(-radius,radius,7):
                    q=p.copy();q[axis]+=delta
                    if np.max(abs(q-shift))>.25 or np.max(abs(q))>.48:continue
                    choices.append((float(dataread(q).var(axis=(0,1)).sum()),q))
                p=max(choices,key=lambda q:q[0])[1]
        for phase in (p,shift,np.zeros(2)):
            values=dataread(phase)
            for accuracy,cancel,model in models:
                prediction,confidence=classify(values,model);decoded,d=decode_blocks(prediction,confidence,tile,decoded);details+=d
                attempts.append(dict(model='neighbor_qda' if cancel else 'center_qda',calibration_accuracy=accuracy,shift=phase.tolist(),new_blocks=len(d)))
                payload,_=finish_tile(decoded)
                if payload is not None:break
            if payload is not None:break
    payload,xor=finish_tile(decoded)
    return payload,dict(tile=tile,complete=payload is not None,rs_crc_blocks=len(decoded),xor_repaired=xor,attempts=attempts,details=details)

def main():
    path=Path(sys.argv[1]);out=path.parent/(path.stem+'-read-v8');out.mkdir(exist_ok=True)
    paper=Paper(path);print('Registered page. Missing small markers:',sum(p is None for p in paper.nodes.values()),flush=True)
    shards={};reports=[];started=time.monotonic()
    for tile in range(TILES):
        try:payload,detail=read_tile(paper,tile)
        except (ValueError,IndexError,np.linalg.LinAlgError) as exc:payload=None;detail=dict(tile=tile,complete=False,error=str(exc))
        if payload is not None:shards[tile]=payload;(out/f'tile-{tile:03d}.bin').write_bytes(payload)
        reports.append(detail)
        if (tile+1)%13==0 or tile+1==TILES:
            state=dict(image=str(path),rotation_180=paper.rotated,tiles_processed=tile+1,tiles_recovered=len(shards),total_tiles=TILES,details=reports,elapsed_seconds=time.monotonic()-started)
            (out/'report.json').write_text(json.dumps(state,indent=2));print('Tiles',tile+1,'/',TILES,'recovered',len(shards),'elapsed',round(time.monotonic()-started,1),'s',flush=True)
    container,outer=outer_recover(shards);state['outer']=outer;state['complete']=False
    if container is not None:
        try:
            raw,metadata=unpack_container(container);state['file']=metadata
            # File name comes from the paper, but constrain the filesystem path.
            name=Path(metadata['name'].replace('\\','/')).name
            if not name or ':' in name or name in ('.','..'):raise ValueError('Invalid archive file name')
            target=out/('restored-'+name);target.write_bytes(raw);state['restored_file']=str(target);state['complete']=True
            if '--verify' in sys.argv:
                reference=Path(sys.argv[sys.argv.index('--verify')+1]).read_bytes();state['original_exact_match']=raw==reference
                if raw!=reference:raise ValueError('Original file comparison failed')
            print('RESTORED',len(raw),'bytes SHA256',metadata['raw_sha256'],flush=True)
        except (ValueError,lzma.LZMAError,KeyError,TypeError) as exc:state['complete']=False;state['container_error']=str(exc)
    (out/'report.json').write_text(json.dumps(state,indent=2));print(out,flush=True)
    if not state['complete']:sys.exit(2)

if __name__=='__main__':main()
