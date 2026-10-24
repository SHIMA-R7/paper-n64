"""A4 duplex capacity budget; geometry, not a demonstrated printable density."""
from pathlib import Path
import math,json
root=Path(__file__).resolve().parent
target=(root/'sm64-shindou.z64.xz').stat().st_size
w,h=204.,291.
def capacity(cpi,bits,reserve):
    pitch=25.4/cpi
    nx=math.floor(w/(35*pitch));ny=math.floor(h/(35*pitch))
    usable=math.floor(2*nx*ny*(1-reserve))
    groups=usable//4
    return groups*3*90*bits,nx,ny,usable
def threshold(bits,reserve):
    low,high=1.,2000.
    for _ in range(70):
        mid=(low+high)/2
        if capacity(mid,bits,reserve)[0]>=target:high=mid
        else:low=mid
    cap,nx,ny,usable=capacity(high+1e-8,bits,reserve)
    return dict(cells_per_inch=high,max_pitch_um=25400/high,
                dot_width_70pct_um=25400/high*.7,scan_pixels_per_cell_1200dpi=1200/high,
                bytes=cap,tiles_x=nx,tiles_y=ny,usable_tiles_duplex=usable)
report=dict(target_bytes=target,target_MiB=target/2**20,area_per_face_mm=[w,h],faces=2,
    notes=['3 mm margins; borderless duplex unavailable.',
           'Core v4 geometry: tile pitch 35 cells, 32x32 bits/layer, 90 data bytes per 128-byte RS codeword, 3+1 XOR.',
           'Dense tiled production layout, not the large markers/labels/whitespace of diagnostic v4.',
           'Reserve is area/tile allowance for extra metadata, color calibration, alignment and fold gutters; it is not an empirical durability guarantee.',
           'Exact tile count uses two faces pooled into groups of four; side-local grouping may slightly reduce capacity.',
           'ROM emulator/decoder are external. SHA256 and headers need to fit within reserve.'],rows=[])
for colors,bits in [(2,1),(4,2),(8,3)]:
    rawcpi=25.4*math.sqrt(target*8/(2*w*h*bits))
    row=dict(colors=colors,bits_per_cell=bits,raw_no_overhead=dict(cells_per_inch=rawcpi,max_pitch_um=25400/rawcpi),
             hypothetical_70pct_net_efficiency=dict(cells_per_inch=rawcpi/math.sqrt(.7),max_pitch_um=25400/rawcpi*math.sqrt(.7)),
             v4_no_extra_reserve=threshold(bits,0),v4_with_10pct_extra_reserve=threshold(bits,.1),
             duplex_capacity_at_200cpi=capacity(200,bits,.1)[0],
             duplex_capacity_at_300cpi=capacity(300,bits,.1)[0])
    report['rows'].append(row)
    print(json.dumps(row,indent=2))
(root/'capacity-budget.json').write_text(json.dumps(report,indent=2))
