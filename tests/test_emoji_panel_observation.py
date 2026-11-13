import numpy as np
from PIL import Image, ImageDraw

from wechat_auto.primitives.composer_templates import EMOJI_FAVORITES_TAB
from wechat_auto.primitives.page_controls import observe_emoji_panel


def fixture(selected=False,labels=True):
    image=Image.new('RGB',(700,700),(30,30,30))
    glyph=Image.fromarray(np.array([[255 if v=='1' else 0 for v in row]
                                   for row in EMOJI_FAVORITES_TAB],dtype=np.uint8))
    if selected:
        ImageDraw.Draw(image).rounded_rectangle((205,614,254,663),radius=8,fill=(48,48,48))
    image.paste((170,170,170),(216,627),glyph)
    boxes=[{'text':text,'x':50,'y':y,'w':80,'h':25,'score':.99}
           for text,y in [('最近使用',50),('所有表情',180)]] if labels else []
    return image,boxes,{'page':'unknown','geometry':{'composer_candidates':[]},'panels':[]}


def test_default_emoji_requires_labels_and_current_footer_glyph():
    image,boxes,state=fixture()
    observe_emoji_panel(image,boxes,state)
    assert [p['key'] for p in state['panels']]==['emoji_panel']
    assert not state['panels'][0]['favorites_selected']
    blank=Image.new('RGB',image.size,(30,30,30))
    unknown={'page':'unknown','geometry':{},'panels':[]}
    observe_emoji_panel(blank,boxes,unknown)
    assert not unknown['panels']


def test_selected_heart_backplate_observes_favorites_without_text_labels():
    image,boxes,state=fixture(selected=True,labels=False)
    observe_emoji_panel(image,boxes,state)
    assert state['panels'][0]['favorites_selected']
    image,boxes,state=fixture(labels=False)
    observe_emoji_panel(image,boxes,state)
    assert not state['panels']
