<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { LINK_COLORS, SELECTED_SECTION_COLOR } from '../roadSections.js'
const props = defineProps({ roads: Array, extent: Array, sectionByLink: Map, selectedSectionKey: String, selectedLinkId: String, endpoints: Boolean, arrows: Boolean })
const emit = defineEmits(['select', 'ready'])
const host = ref(null), canvas = ref(null), hover = ref(null), engine = ref('路网视图'), zoomLevel = ref(8)
let map, observer, frame, width = 1, height = 1, scale = 1, center = [0, 0], dragging, moved = false, destroyed = false
let drawn = [], cache = new WeakMap(), online = false, sdkScript, sdkTimer
const CITIES = [['海口',110.198,20.045],['三亚',109.512,18.252],['儋州',109.58,19.52],['琼海',110.466,19.253],['万宁',110.389,18.796],['东方',108.651,19.096],['五指山',109.517,18.775],['文昌',110.797,19.544],['澄迈',110.007,19.738],['定安',110.359,19.681],['陵水',110.038,18.505],['乐东',109.173,18.75]]
const mercator = ([lon, lat]) => [lon / 360, -Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / (2 * Math.PI)]
const inverse = ([x,y]) => [x * 360, (2 * Math.atan(Math.exp(-y * 2 * Math.PI)) - Math.PI / 2) * 180 / Math.PI]
function geometry(feature) {
  if (!cache.has(feature)) {
    const coords = online ? feature.gcjCoordinates : feature.geometry.coordinates
    const parts = feature.geometry.type === 'LineString' ? [coords] : feature.geometry.type === 'MultiLineString' ? coords : [[coords]]
    cache.set(feature, parts.map(part => part.map(mercator)))
  }
  return cache.get(feature)
}
function bounds(features) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const f of features) for (const part of geometry(f)) for (const [x,y] of part) { minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y) }
  return [minX,minY,maxX,maxY]
}
function fit(features = props.roads, useFullExtent = false) {
  if (!features.length && !props.extent) return
  const [x1,y1,x2,y2] = props.extent && (useFullExtent || !features.length)
    ? (() => { const [west,south,east,north]=props.extent; const [left,top]=mercator([west,north]),[right,bottom]=mercator([east,south]); return [left,top,right,bottom] })()
    : bounds(features)
  center = [(x1+x2)/2,(y1+y2)/2]
  scale = Math.min((width-110)/Math.max(x2-x1,0.00003),(height-110)/Math.max(y2-y1,0.00003))
  scale = Math.max(256*2**6,Math.min(256*2**17,scale))
  if (online) map.setZoomAndCenter(Math.log2(scale/256), inverse(center), true)
  schedule()
}
function zoom(delta) {
  if (online) map.setZoom(map.getZoom()+delta, true)
  else { scale=Math.max(256*2**5,Math.min(256*2**19,scale*2**delta)); schedule() }
}
function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw) }
function draw() {
  if (!canvas.value || !props.roads) return
  const ctx = canvas.value.getContext('2d'), ratio = window.devicePixelRatio || 1
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,width,height)
  let tx=width/2-center[0]*scale, ty=height/2-center[1]*scale
  if (online) {
    // Two projected anchors give the exact affine transform for the north-up 2D map.
    const a=map.lngLatToContainer([109,19]), b=map.lngLatToContainer([110,20])
    const ma=mercator([109,19]), mb=mercator([110,20])
    scale=(b.x-a.x)/(mb[0]-ma[0]);tx=a.x-ma[0]*scale;ty=a.y-ma[1]*scale
  }
  zoomLevel.value=Math.round(Math.log2(scale/256)*10)/10
  const pixel = ([x,y]) => [x*scale+tx,y*scale+ty]
  if (!online) {
    ctx.strokeStyle='#dce9e7';ctx.lineWidth=1
    const step=zoomLevel.value>11?.05:.5
    const bottom=inverse([(width-tx)/scale,(height-ty)/scale]),top=inverse([-tx/scale,-ty/scale])
    ctx.fillStyle='#a2b6b3';ctx.font='10px monospace'
    for(let lng=Math.ceil(top[0]/step)*step;lng<bottom[0];lng+=step) {const x=pixel(mercator([lng,19]))[0];ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();ctx.fillText(lng.toFixed(2)+'° E',x+5,height-35)}
    for(let lat=Math.ceil(bottom[1]/step)*step;lat<top[1];lat+=step) {const y=pixel(mercator([109,lat]))[1];ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()}
  }
  drawn=[]
  const points=new Map()
  const groupOf = feature => props.sectionByLink?.get(feature.properties.link_id)
  const selectedRoads = props.selectedSectionKey
    ? props.roads.filter(f => groupOf(f)?.sectionKey === props.selectedSectionKey)
    : []
  const selectedIds = new Set(selectedRoads.map(f => f.properties.link_id))
  const orderedRoads = [...props.roads.filter(f => !selectedIds.has(f.properties.link_id)),
    ...selectedRoads.filter(f => f.properties.link_id !== props.selectedLinkId),
    ...selectedRoads.filter(f => f.properties.link_id === props.selectedLinkId)]
  for (const feature of orderedRoads) {
    const membership=groupOf(feature)
    const selected=selectedIds.has(feature.properties.link_id)
    const selectedLink=selected && feature.properties.link_id===props.selectedLinkId
    for (const part of geometry(feature)) {
      const path=part.map(pixel)
      const xs=path.map(p=>p[0]),ys=path.map(p=>p[1]),box=[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]
      if(box[2]<-20||box[0]>width+20||box[3]<-20||box[1]>height+20)continue
      drawn.push({feature,path,box})
      ctx.beginPath();path.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.lineJoin='round';ctx.lineCap='round'
      if(selectedLink){ctx.strokeStyle='#745307';ctx.lineWidth=zoomLevel.value>11?9:7;ctx.stroke()}
      ctx.strokeStyle=selected
        ? (!props.selectedLinkId || selectedLink ? SELECTED_SECTION_COLOR : LINK_COLORS[membership?.colorIndex||0])
        : '#a8b9b2'
      ctx.lineWidth=selected?(zoomLevel.value>11?5:3.5):(zoomLevel.value>11?2.5:1.8);ctx.stroke()
      if(selected && props.arrows && zoomLevel.value>=11) {
        const reverse=String(feature.properties.oneway)==='-1';let distance=0
        for(let i=1;i<path.length;i++) {const a=path[i-1],b=path[i],dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy);distance+=len;if(distance>65&&len>10){distance=0;const angle=Math.atan2(dy,dx)+(reverse?Math.PI:0);ctx.save();ctx.translate((a[0]+b[0])/2,(a[1]+b[1])/2);ctx.rotate(angle);ctx.beginPath();ctx.moveTo(-4,-3);ctx.lineTo(0,0);ctx.lineTo(-4,3);ctx.strokeStyle='#fff';ctx.lineWidth=1.7;ctx.stroke();if(String(feature.properties.oneway)==='no'){ctx.rotate(Math.PI);ctx.translate(9,0);ctx.beginPath();ctx.moveTo(-4,-3);ctx.lineTo(0,0);ctx.lineTo(-4,3);ctx.stroke()}ctx.restore()}}
      }
      if(selected && props.endpoints && zoomLevel.value>=(props.selectedLinkId?10:12)){for(const [p,role] of [[path[0],1],[path.at(-1),2]]){const key=p.map(v=>v.toFixed(2)).join(',');const existing=points.get(key);points.set(key,{p,role:role|(existing?.role||0)})}}
    }
  }
  for(const {p,role} of points.values()){ctx.beginPath();ctx.arc(...p,3.2,0,Math.PI*2);ctx.fillStyle=role===3?'#896bc4':role===1?'#24ac80':'#e6894c';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1;ctx.stroke()}
  if (!online) {
    ctx.font='12px "PingFang SC",sans-serif';ctx.textAlign='center'
    for(const [name,lng,lat] of CITIES){const [x,y]=pixel(mercator([lng,lat]));ctx.fillStyle='#edf4f1';ctx.fillRect(x-20,y-11,40,19);ctx.fillStyle='#5e7773';ctx.fillText(name,x,y+3)}ctx.textAlign='left'
  }
  emit('ready', { engine: engine.value, zoom: zoomLevel.value })
}
function pick(x,y) {
  let best=null, min=8
  for(const {feature,path,box} of drawn){if(x<box[0]-8||x>box[2]+8||y<box[1]-8||y>box[3]+8)continue
    for(let i=1;i<path.length;i++){const a=path[i-1],b=path[i],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1)));const d=Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);if(d<min){min=d;best=feature}}
  }return best
}
function position(e){const r=host.value.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top]}
function pointerdown(e){if(e.target.closest('button'))return;dragging={x:e.clientX,y:e.clientY,center:[...center]};moved=false;if(!online)host.value.setPointerCapture(e.pointerId)}
function pointermove(e){const [x,y]=position(e);if(dragging){const dx=e.clientX-dragging.x,dy=e.clientY-dragging.y;if(Math.hypot(dx,dy)>4)moved=true;if(!online){center=[dragging.center[0]-dx/scale,dragging.center[1]-dy/scale];schedule()}hover.value=null;return}const feature=pick(x,y);hover.value=feature?{feature,x:Math.min(x+16,width-270),y:Math.max(10,y-65)}:null;host.value.style.cursor=feature?'pointer':'grab'}
function pointerup(e){if(dragging&&!moved){const [x,y]=position(e),f=pick(x,y);if(f)emit('select',f)}dragging=null}
function wheel(e){if(online)return;e.preventDefault();const [x,y]=position(e),before=[center[0]+(x-width/2)/scale,center[1]+(y-height/2)/scale];scale=Math.max(256*2**5,Math.min(256*2**19,scale*Math.exp(-e.deltaY*.001)));center=[before[0]-(x-width/2)/scale,before[1]-(y-height/2)/scale];schedule()}
function resize(){const r=host.value.getBoundingClientRect();width=r.width;height=r.height;canvas.value.width=width*(window.devicePixelRatio||1);canvas.value.height=height*(window.devicePixelRatio||1);schedule()}
function loadAMap(){
  if(!__AMAP_KEY__)return
  engine.value='高德加载中 · 路网视图可用'
  if(__AMAP_SERVICE_HOST__){
    window._AMapSecurityConfig={serviceHost:new URL(__AMAP_SERVICE_HOST__,window.location.origin).href.replace(/\/$/,'')}
  }else if(__AMAP_SECURITY_CODE__){
    window._AMapSecurityConfig={securityJsCode:__AMAP_SECURITY_CODE__}
  }
  sdkScript=document.createElement('script');sdkScript.src=`https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(__AMAP_KEY__)}`
  sdkTimer=setTimeout(()=>{if(!online)engine.value='路网视图 · 高德未连接'},12000)
  sdkScript.onerror=()=>{engine.value='路网视图 · 高德未连接'}
  sdkScript.onload=()=>{if(destroyed||!window.AMap)return;try{map=new window.AMap.Map(host.value.querySelector('.basemap'),{viewMode:'2D',zoom:8,center:[109.7,19.2],mapStyle:'amap://styles/whitesmoke',pitch:0,rotation:0,rotateEnable:false,pitchEnable:false,showLabel:true});online=true;engine.value='高德地图 · GCJ-02';cache=new WeakMap();clearTimeout(sdkTimer);map.on('mapmove',schedule);map.on('zoomchange',schedule);map.on('complete',schedule);fit([],true);schedule()}catch{engine.value='路网视图 · 高德未连接'}}
  document.head.appendChild(sdkScript)
}
onMounted(()=>{observer=new ResizeObserver(resize);observer.observe(host.value);resize();fit([],true);host.value.addEventListener('wheel',wheel,{passive:false});loadAMap()})
onBeforeUnmount(()=>{destroyed=true;observer?.disconnect();cancelAnimationFrame(frame);clearTimeout(sdkTimer);map?.destroy();sdkScript?.remove();host.value?.removeEventListener('wheel',wheel)})
watch(()=>[props.roads,props.sectionByLink,props.selectedSectionKey,props.selectedLinkId,props.endpoints,props.arrows],schedule)
defineExpose({fit,zoom})
</script>

<template>
  <div ref="host" class="road-map" @pointerdown="pointerdown" @pointermove="pointermove" @pointerup="pointerup" @pointercancel="dragging=null" @pointerleave="hover=null" @dblclick="!online && zoom(1)">
    <div class="basemap"></div><canvas ref="canvas" aria-label="海南高速路链地图，使用旁边的列表可搜索和选择道路"></canvas>
    <div v-if="hover" class="map-tooltip" :style="{left:hover.x+'px',top:hover.y+'px'}"><strong>{{ hover.feature.properties.name || (hover.feature.properties.highway==='motorway'?'未命名高速主线':'未命名高速匝道') }}</strong><span>{{ sectionByLink?.get(hover.feature.properties.link_id)?.sectionKey==='pilot'?'先导段':'非先导段' }}{{ hover.feature.properties.pilot_continuity?' · 拓扑补齐':'' }} · {{ hover.feature.properties.link_id }}</span><small v-if="hover.feature.properties.length_m">{{ Number(hover.feature.properties.length_m).toFixed(1) }} m · {{ hover.feature.properties.direction_annotation?.label || '上下行待确认' }}</small></div>
    <div class="map-controls" @pointerdown.stop><button title="放大" aria-label="放大地图" @click="zoom(1)">＋</button><button title="缩小" aria-label="缩小地图" @click="zoom(-1)">−</button><hr><button title="显示当前筛选范围" aria-label="显示全部路链" @click="fit()">⌖</button></div>
    <div class="map-attribution">{{ engine }} <span>© 高德 / OpenStreetMap</span></div>
    <div v-if="selectedSectionKey && endpoints && zoomLevel < (selectedLinkId?10:12)" class="zoom-note">放大至 {{ selectedLinkId?10:12 }} 级查看端点 · 11 级查看方向箭头</div>
  </div>
</template>
