"""Exercise the review page's actual media-clock boundary helper in JavaScript."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest


class ReviewTimingTests(unittest.TestCase):
    def test_preview_sizes_only_change_layout_and_leave_the_same_media_playing(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is required to exercise the browser preview helper")
        template = (Path(__file__).resolve().parents[1] / "tools" / "review_template.html").read_text()
        helper = re.search(r'<script id="review-preview">(.*?)</script>', template, re.S)
        self.assertIsNotNone(helper)
        program = helper[1] + r'''
const assert=require('node:assert/strict');
const properties={};
const video={currentTime:23.2,paused:false,src:'demo-final.mp4'};
const screen={video,style:{setProperty:(key,value)=>{properties[key]=value}}};
const buttons=[0,390,320].map(width=>({dataset:{previewWidth:String(width)},
  setAttribute:function(key,value){this[key]=value}}));
for(const [width,expected] of [[320,'320px'],[390,'390px'],[0,'100%'],[900,'100%']]){
  const selected=applyReviewPreviewWidth(screen,buttons,width);
  assert.equal(properties['--preview-width'],expected);
  assert.equal(buttons.filter(button=>button['aria-pressed']==='true').length,1);
  assert.equal(buttons.find(button=>button['aria-pressed']==='true').dataset.previewWidth,String(selected));
  assert.equal(screen.video,video);
  assert.deepEqual(video,{currentTime:23.2,paused:false,src:'demo-final.mp4'});
}
'''
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fractional_seek_and_loop_boundaries_do_not_advance_half_a_frame_early(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is required to exercise the browser timing helper")
        template = (Path(__file__).resolve().parents[1] / "tools" / "review_template.html").read_text()
        helper = re.search(r'<script id="review-timing">(.*?)</script>', template, re.S)
        self.assertIsNotNone(helper)
        program = helper[1] + r'''
const assert=require('node:assert/strict');
const shots=[{startSec:0,endSec:694/30},{startSec:694/30,endSec:1019/30},
             {startSec:1019/30,endSec:67.3}];
// Chrome exposes the exact 694/30 seek as 23.133333 seconds. Selection must
// remain in this shot, and a loop must not seek repeatedly back to its start.
assert.equal(reviewShotIndex(shots,23.133333,30),1);
assert.equal(reviewShotIndex(shots,694/30,30),1);
assert.equal(reviewShotIndex(shots,694/30-0.5/30,30),0);
assert.equal(reviewShotIndex(shots,694/30-0.000002,30),0);
// The same helper owns loop exit: the final picture stays, the boundary exits.
assert.equal(reviewShotIndex(shots,1019/30-0.5/30,30),1);
assert.equal(reviewShotIndex(shots,Number((1019/30).toFixed(6)),30),2);
assert.equal(reviewShotIndex(shots,67.3,30),-1);
// Chromium truncates the actual final-cut frame 1079 to six decimal places.
// A half-microsecond repair is too small and incorrectly selects frame 1078.
const decision=[{startSec:694/30,endSec:1079/30},{startSec:1079/30,endSec:44}];
assert.equal(reviewShotIndex(decision,35.966666,30),1);
assert.equal(reviewShotIndex(decision,1079/30-0.49/30,30),0);
assert.equal(reviewShotIndex(decision,1079/30-0.000002,30),0);
for(const fps of [24,25,30,50,60,30000/1001]){
  for(const boundary of [1,2,7,694,1079,10001,340012]){
    const time=boundary/fps;
    const range=[{startSec:0,endSec:time},{startSec:time,endSec:time+1}];
    assert.equal(reviewShotIndex(range,Number(time.toFixed(6)),fps),1);
    assert.equal(reviewShotIndex(range,Math.floor(time*1e6)/1e6,fps),1);
    assert.equal(reviewShotIndex(range,time-0.49/fps,fps),0);
    assert.equal(reviewShotIndex(range,time-0.000002,fps),0);
  }
}
'''
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pending_media_updates_cannot_undo_the_latest_explicit_shot_selection(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is required to exercise the browser seek guard")
        template = (Path(__file__).resolve().parents[1] / "tools" / "review_template.html").read_text()
        helper = re.search(r'<script id="review-timing">(.*?)</script>', template, re.S)
        self.assertIsNotNone(helper)
        program = helper[1] + r'''
const assert=require('node:assert/strict');
const shots=[{startSec:0,endSec:694/30},{startSec:694/30,endSec:1079/30},
             {startSec:1079/30,endSec:44},{startSec:44,endSec:60}];
const guard=createReviewSeekGuard(shots,30);
let selected=0;
function select(index){selected=index;guard.begin(index)}
function update(time,seeking){if(guard.allow(time,seeking))selected=reviewShotIndex(shots,time,30)}
select(1);
select(2); // The second click owns the intended selection even if the first seek finishes late.
update(23.133333,true);assert.equal(selected,2);
update(23.133333,false);assert.equal(selected,2);
update(35.966666,true);assert.equal(selected,2);
update(35.966666,false);assert.equal(selected,2);
// Once the seek lands, normal playback follows the actual picture boundaries.
update(44,false);assert.equal(selected,3);
// A loop restart uses the same guard; an old end-of-shot update cannot redirect it.
select(2);
update(44,false);assert.equal(selected,2);
update(35.966666,false);assert.equal(selected,2);
// Deliberately using native controls supersedes a queued app seek.
select(2);guard.cancel();update(1,false);assert.equal(selected,0);
'''
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_shot_buttons_loop_and_native_seek_survive_queued_media_events(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is required to exercise the review's media event handlers")
        template = (Path(__file__).resolve().parents[1] / "tools" / "review_template.html").read_text()
        scripts = [body for body in re.findall(r'<script(?: [^>]*)?>(.*?)</script>', template, re.S)
                   if "__REVIEW_DATA__" not in body]
        program = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
class Node {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.events={};this.dataset={};
    this.style={setProperty(){}};this.classList={add(){},toggle(){}};this.textContent='';this.value=''}
  append(...nodes){this.children.push(...nodes)}
  replaceChildren(...nodes){this.children=[...nodes]}
  setAttribute(key,value){this[key]=value}
  addEventListener(name,callback){(this.events[name]??=[]).push(callback)}
  emit(name){for(const callback of this.events[name]??[])callback({type:name})}
  getBoundingClientRect(){return {width:320}}
  scrollIntoView(){}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
const preview=[0,390,320].map(width=>{const node=new Node('button');node.dataset.previewWidth=String(width);return node});
const starts=[0,694/30,1079/30,44],ends=[694/30,1079/30,44,60];
const shots=starts.map((startSec,index)=>({n:index+1,startSec,endSec:ends[index],title:`shot ${index+1}`,
  durationSec:ends[index]-startSec,frames:Math.round((ends[index]-startSec)*30),source:'source.mp4',
  inSec:0,beat:'test',narration:'A complete thought.',transition:'',findings:[]}));
get('review-data').textContent=JSON.stringify({name:'Fixture',profile:'test',shots,fps:30,verified:true,
  status:'Verified delivery',durationSec:60,totalFrames:1800,timing:'Rendered frame plan',errors:0,warnings:0,
  generatedAt:'2026-09-16T12:00:00Z',video:'demo-final.mp4',canSeek:true,issues:[],audio:{},links:[]});
const video=get('video');let clock=0;
Object.defineProperty(video,'currentTime',{get(){return clock},set(value){this.requestedTime=value;
  clock=Math.floor(value*1e6)/1e6;this.seeking=true}});
video.paused=true;video.seeking=false;video.play=()=>{video.paused=false;return Promise.resolve()};
function media(name,time,seeking=false){clock=time;video.seeking=seeking;video.emit(name)}
const context=vm.createContext({document:{getElementById:get,createElement:tag=>new Node(tag),querySelectorAll:()=>preview},
  window:{addEventListener(){}},console});
'''
        program += "\nvm.runInContext(" + json.dumps("\n".join(scripts)) + ",context);\n"
        program += r'''
const choose=index=>get('timeline').children[index].emit('click');
const selected=()=>get('shot-title').textContent;
choose(1);choose(2);
assert.equal(selected(),'shot 3');
media('timeupdate',23.133333,true);assert.equal(selected(),'shot 3');
media('seeked',23.133333,true);assert.equal(selected(),'shot 3','old completion cannot undo a newer in-flight seek');
media('seeked',35.966666,false);assert.equal(selected(),'shot 3','truncated clock stays in frame 1079');
get('loop').emit('click');
assert.equal(video.requestedTime,1079/30);assert.equal(video.paused,false);
media('seeked',35.966666,false);
media('timeupdate',44,false);
assert.equal(video.requestedTime,1079/30,'loop returns to the selected shot, not its predecessor');
assert.equal(selected(),'shot 3');
media('seeked',35.966666,false);
get('loop').emit('click'); // Disable looping before exercising normal native scrubbing.
choose(3);video.emit('pointerdown');
media('seeked',1,false);assert.equal(selected(),'shot 1','native scrub supersedes pending app seek');
media('timeupdate',23.2,false);assert.equal(selected(),'shot 2','normal playback resumes');
choose(3);video.emit('error');
media('timeupdate',35.97,false);assert.equal(selected(),'shot 3','media errors clear pending seek state');
// The engine supports a one-frame shot. Playback may pass it while seeked waits
// in the event queue; finishing that seek must release the selection guard.
const shortEnd=1079/30+1/30;
vm.runInContext(`data.shots[2].endSec=${shortEnd};data.shots[3].startSec=${shortEnd}`,context);
choose(2);
media('timeupdate',shortEnd+.05,false);assert.equal(selected(),'shot 3');
media('seeked',shortEnd+.05,false);assert.equal(selected(),'shot 4','completed one-frame seek must not deadlock');
media('timeupdate',shortEnd+.1,false);assert.equal(selected(),'shot 4');
'''
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
