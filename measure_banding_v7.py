"""Image-only, fixed row-density measurements for paired v7 prints.
The smoothed row-mean variation is a descriptive proxy, not a universal
banding score: random data colors and paper/scan differences also contribute.
"""
from pathlib import Path
import sys,json
import numpy as np
from PIL import Image,ImageDraw
from diagnose_registration_v7 import Page
root=Path(__file__).resolve().parent

def main():
    path=Path(sys.argv[1]);page=Page(path)
    manifest=json.loads((root/'calibrated-v7-manifest.json').read_text())
    out=root/(path.stem+'-band-measurement');out.mkdir(exist_ok=True)
    metrics=[];gallery=Image.new('RGB',(2100,500),'white');draw=ImageDraw.Draw(gallery)
    for panel in manifest['panels']:
        matrix=page.matrix(panel);xx,yy=np.meshgrid((np.arange(384)+.5)/4,(np.arange(384)+.5)/4)
        step=panel['cell_mm'];points=np.stack([panel['x_mm']+xx*step,panel['y_mm']+yy*step,np.ones_like(xx)],-1)@matrix.T
        u=points[...,0]/points[...,2];v=points[...,1]/points[...,2]
        xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None];a=page.a
        rgb=a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        # Interior only; 8 samples = 2 cells omitted at each edge.
        lum=rgb[8:-8,8:-8]@np.array([.2126,.7152,.0722]);row=lum.mean(1)
        smooth=np.convolve(row,np.ones(32)/32,mode='valid') # 8-cell window
        mean=float(row.mean());std=float(smooth.std());percent=100*std/mean
        centered=smooth-smooth.mean();spectrum=abs(np.fft.rfft(centered))**2
        frequency=int(np.argmax(spectrum[1:13])+1)
        metrics.append(dict(density=panel['density'],colors=panel['color_count'],mean_luma=mean,
            smoothed_row_std_luma=std,smoothed_row_std_percent=percent,smoothed_row_peak_to_peak=float(np.ptp(smooth)),
            dominant_low_frequency_cycles_in_window=frequency,row_mean_luma=row.tolist()))
        if panel['density']==300:
            col=(8,10,12,16,20).index(panel['color_count']);patch=Image.fromarray(np.clip(rgb,0,255).astype('uint8'))
            gallery.paste(patch,(col*420,35));draw.text((col*420+5,10),f'{panel["color_count"]} colors / 300 cells/in',fill='black')
            draw.text((col*420+5,435),f'row variation: {percent:.2f}% (proxy)',fill='black')
    gallery.save(out/'300-cells-gallery.png')
    (out/'report.json').write_text(json.dumps(dict(image=str(path),note=__doc__,metrics=metrics),indent=2))
    print([(m['density'],m['colors'],round(m['smoothed_row_std_percent'],3)) for m in metrics if m['density']==300]);print(out)

if __name__=='__main__':main()
