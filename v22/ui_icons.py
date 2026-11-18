"""Small consistent line icons; rendered locally, no font or network dependency."""
from PIL import Image, ImageDraw, ImageTk

def icon(root,name,color='#dce8f5'):
    im=Image.new('RGBA',(72,72));d=ImageDraw.Draw(im)
    def line(points):d.line([(x*3,y*3) for x,y in points],fill=color,width=5,joint='curve')
    def rect(x,y,w,h):line([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)])
    if name=='library':
        rect(3,3,18,18);line([(3,16),(9,10),(14,15),(17,12),(21,16)]);d.ellipse((45,18,51,24),fill=color)
    elif name=='tag':
        line([(3,3),(12,3),(21,12),(12,21),(3,12),(3,3)]);d.ellipse((17,17,25,25),outline=color,width=4)
    elif name=='import':
        line([(12,3),(12,15),(7,10)]);line([(12,15),(17,10)]);line([(3,15),(3,21),(21,21),(21,15)])
    elif name=='backup':
        rect(3,5,18,14);line([(3,14),(21,14)]);line([(6,17),(8,17)])
    elif name=='folder':line([(3,6),(10,6),(12,9),(21,9),(21,20),(3,20),(3,6)])
    elif name=='zoom':
        d.ellipse((9,9,48,48),outline=color,width=5);line([(15,15),(21,21)]);line([(7,10),(13,10)]);line([(10,7),(10,13)])
    elif name=='file':line([(5,3),(14,3),(20,9),(20,21),(5,21),(5,3)]);line([(14,3),(14,9),(20,9)])
    elif name=='settings':
        for y,x in [(6,8),(12,16),(18,10)]:line([(3,y),(21,y)]);d.ellipse((x*3-5,y*3-5,x*3+5,y*3+5),fill=color)
    elif name=='search':d.ellipse((9,9,48,48),outline=color,width=5);line([(15,15),(21,21)])
    else:line([(4,12),(20,12),(15,7)]);line([(20,12),(15,17)])
    return ImageTk.PhotoImage(im.resize((20,20),Image.Resampling.LANCZOS),master=root)
