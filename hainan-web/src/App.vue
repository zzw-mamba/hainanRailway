<script setup>
import { ref, shallowRef, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import RoadMap from './components/RoadMap.vue'
const data=shallowRef(null),error=ref(''),query=ref(''),roadType=ref('all'),route=ref('all'),structure=ref('all'),direction=ref('all'),selected=shallowRef(null),page=ref(1),map=ref(null),endpoints=ref(true),arrows=ref(true),showValidation=ref(false),toast=ref(''),mapState=ref({engine:'路网视图',zoom:8})
const maxLength=ref(500),generating=ref(false),generationMessage=ref(''),generationError=ref(''),generationAvailable=ref(null)
const editor=ref(null),editError=ref('')
const validMaxLength=computed(()=>Number.isFinite(Number(maxLength.value))&&Number(maxLength.value)>=100&&Number(maxLength.value)<=10000)
let generationTimer,activeJobId,disposed=false
let editFocus=null
let toastTimer
const PAGE_SIZE=40
const fmt=n=>new Intl.NumberFormat('zh-CN').format(n)
const tagged=v=>v!=null&&String(v)!==''&&String(v)!=='no'
const roads=computed(()=>data.value?.roads||[])
const routes=computed(()=>[...new Set(roads.value.map(f=>f.properties.ref).filter(Boolean))].sort())
const mapRoads=computed(()=>roads.value.filter(f=>{const p=f.properties;return(roadType.value==='all'||p.highway===roadType.value)&&(route.value==='all'||p.ref===route.value)&&(structure.value==='all'||tagged(p[structure.value]))&&(direction.value==='all'||p.direction_annotation?.code===direction.value||p.direction_annotation?.status===direction.value)}))
const visibleRoads=computed(()=>{const q=query.value.trim().toLowerCase();return q?mapRoads.value.filter(f=>{const p=f.properties;return[p.name,p.ref,p.link_id,p.source_link_id,p.osm_link_id,p.osm_source_link_id,...(p.business_association?.matches||[]).flatMap(m=>[m.businessLinkId,m.unitId,m.unitName,m.startStakeNum,m.endStakeNum])].some(v=>String(v||'').toLowerCase().includes(q))}):mapRoads.value})
const list=visibleRoads
const pages=computed(()=>Math.max(1,Math.ceil(list.value.length/PAGE_SIZE)))
const pageItems=computed(()=>list.value.slice((page.value-1)*PAGE_SIZE,page.value*PAGE_SIZE))
const filteredLength=computed(()=>mapRoads.value.reduce((sum,f)=>sum+Number(f.properties.length_m||0),0)/1000)
const mainCount=computed(()=>roads.value.filter(f=>f.properties.highway==='motorway').length)
const bridgeCount=computed(()=>roads.value.filter(f=>tagged(f.properties.bridge)).length)
const tunnelCount=computed(()=>roads.value.filter(f=>tagged(f.properties.tunnel)).length)
const properties=computed(()=>selected.value?.properties||{})
const pointCoordinateSystem=ref('WGS84')
const gisPoints=computed(()=>{
  const feature=selected.value
  if(!feature)return []
  const coordinates=pointCoordinateSystem.value==='GCJ-02' ? feature.gcjCoordinates : feature.geometry.coordinates
  return coordinates.map(([longitude,latitude],index)=>({index:index+1,longitude,latitude,
    role:index===0?'起点':index===coordinates.length-1?'终点':''}))
})
const coordinateText=value=>Number(value).toFixed(7)
const idIndex=computed(()=>new Map(roads.value.map(f=>[f.properties.link_id,f])))
const relationIndex=computed(()=>{const next=new Map(),prev=new Map();for(const r of data.value?.relationships||[]){if(!next.has(r.currentLinkId))next.set(r.currentLinkId,[]);if(!prev.has(r.nextLinkId))prev.set(r.nextLinkId,[]);if(!next.get(r.currentLinkId).includes(r.nextLinkId))next.get(r.currentLinkId).push(r.nextLinkId);if(!prev.get(r.nextLinkId).includes(r.currentLinkId))prev.get(r.nextLinkId).push(r.currentLinkId)}return {next,prev}})
const nextLinks=computed(()=>relationIndex.value.next.get(properties.value.link_id)||[]),prevLinks=computed(()=>relationIndex.value.prev.get(properties.value.link_id)||[])
const extraProperties=computed(()=>Object.entries(properties.value).filter(([key])=>!['name','ref','link_id','length_m','source_link_id','segment_index','highway','coordinate_system','source','direction_annotation','business_association'].includes(key)))
const businessIndex=computed(()=>new Map((data.value?.businessData?.links||[]).map(l=>[l.id,l])))
const associatedLinks=computed(()=>[...new Set((properties.value.business_association?.matches||[]).map(m=>m.businessLinkId))].map(id=>{
  const match=properties.value.business_association.matches.find(m=>m.businessLinkId===id)
  return {...businessIndex.value.get(id),match,gantries:(data.value.businessData.gantries||[]).filter(g=>g.linkId===id)}
}))
const businessRelations=computed(()=>{const ids=new Set(associatedLinks.value.map(l=>l.id));return(data.value?.businessData?.relationships||[]).filter(r=>ids.has(r.currentLinkId)||ids.has(r.nextLinkId))})
function locateUnit(id){const features=roads.value.filter(f=>f.properties.business_association?.matches.some(m=>m.unitId===id));if(!features.length){notify('该收费单元暂无通过检查的地图关联');return}reset();select(features[0]);nextTick(()=>map.value?.fit(features))}
function compareHighway(ref){reset();const features=roads.value.filter(f=>f.properties.ref?.split(';').includes(ref)&&f.properties.highway==='motorway');nextTick(()=>map.value?.fit(features))}
function locateAssociations(){reset();const features=roads.value.filter(f=>f.properties.business_association);nextTick(()=>map.value?.fit(features))}
function locateBusiness(id){const features=roads.value.filter(f=>f.properties.business_association?.matches.some(m=>m.businessLinkId===id));if(!features.length){notify('该接口路链尚未可靠关联到地图');return}reset();select(features[0]);nextTick(()=>map.value?.fit(features))}
function notify(message){toast.value=message;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.value='',2800)}
function select(feature,locate=false){selected.value=feature;if(locate)nextTick(()=>map.value?.fit([feature]))}
function relationKind(id){return idIndex.value.get(id)?.properties.source_link_id===properties.value.source_link_id?'内部':'跨原链'}
function related(id){const f=idIndex.value.get(id);if(f){query.value='';roadType.value='all';route.value='all';structure.value='all';direction.value='all';select(f,true)}}
function reset(){query.value='';roadType.value='all';route.value='all';structure.value='all';direction.value='all';selected.value=null;nextTick(()=>map.value?.fit())}
function download(){const features=visibleRoads.value;const geojson={type:'FeatureCollection',features:features.map(({gcjCoordinates,...f})=>f)};const blob=new Blob([JSON.stringify(geojson,null,2)],{type:'application/geo+json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='hainan-links-filtered.geojson';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);notify(`已导出 ${fmt(features.length)} 个要素（WGS84）`)}
async function copyId(){try{await navigator.clipboard.writeText(properties.value.link_id);notify('编号已复制')}catch{notify('当前浏览器无法复制，请选中编号手动复制')}}
async function copyGisPoints(){
  const lines=['序号,经度,纬度',...gisPoints.value.map(point=>`${point.index},${point.longitude},${point.latitude}`)]
  try{await navigator.clipboard.writeText(lines.join('\n'));notify(`已复制 ${gisPoints.value.length} 个 ${pointCoordinateSystem.value} 坐标点`)}
  catch{notify('当前浏览器无法复制坐标，请手动选择列表内容')}
}
async function load(focus=null){error.value='';try{const response=await fetch(`${import.meta.env.BASE_URL}data/hainan.json`,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json();const id=focus?.linkId||selected.value?.properties.link_id;data.value=payload;selected.value=payload.roads.find(f=>f.properties.link_id===id)||null;if(!selected.value&&focus?.sourceId){const siblings=payload.roads.filter(f=>f.properties.osm_source_link_id===focus.sourceId);selected.value=siblings[0]||null}page.value=1;maxLength.value=payload.generation?.maxLinkLengthM||500}catch(e){error.value=`海南数据加载失败：${e.message}`;throw e}}
async function generationRequest(options,endpoint='generation'){const response=await fetch(`${import.meta.env.BASE_URL}api/${endpoint}`,options);const body=await response.json();if(!response.ok)throw new Error(body.error||'本地生成服务暂不可用');return body}
async function checkGeneration(){
  if(disposed)return
  try{
    const job=await generationRequest();generationAvailable.value=true
    if(disposed)return
    if(job.status==='running'){
      activeJobId=job.id;generating.value=true;generationMessage.value=job.message
      generationTimer=setTimeout(checkGeneration,1200)
    }else if(activeJobId===job.id){
      if(job.status==='done'){
        await load(editFocus);generationMessage.value=`已生成 ${fmt(roads.value.length)} 条路链`;notify(editFocus?'路链编辑已保存，路网已更新':'新路网已生成并更新到地图');editFocus=null
      }else if(job.status==='failed'){generationError.value=job.message;editError.value=job.message;generationMessage.value='';editFocus=null}
      activeJobId=null;generating.value=false
    }else if(generating.value){
      generating.value=false;activeJobId=null;generationError.value='生成服务已重启，请重新生成'
    }
  }catch(e){generating.value=false;generationError.value=activeJobId?`状态读取失败：${e.message}，可刷新页面查看进度`:'请通过本地 dev 或 preview 服务使用实时生成';generationAvailable.value=false}
}
async function generate(){
  if(!validMaxLength.value||generating.value)return
  generationError.value='';generating.value=true;generationMessage.value='正在启动生成…'
  try{
    const job=await generationRequest({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({maxLinkLengthM:Number(maxLength.value)})})
    activeJobId=job.id;generationMessage.value=job.message;clearTimeout(generationTimer);if(!disposed)generationTimer=setTimeout(checkGeneration,1000)
  }catch(e){generating.value=false;generationError.value=e.message}
}
function openEditor(action){
  editError.value=''
  if(action==='add'){
    editor.value={action,name:'',ref:'',highway:'motorway',oneway:'yes',lanes:'',maxspeed:'',coordinates:''}
    return
  }
  if(!selected.value)return
  const p=selected.value.properties
  editor.value={action,linkId:p.link_id,sourceId:p.osm_source_link_id,
    name:p.name||'',ref:p.ref||'',highway:p.highway||'motorway',oneway:p.oneway||'yes',
    lanes:String(p.lanes||''),maxspeed:String(p.maxspeed||''),
    coordinates:selected.value.geometry.coordinates.map(point=>point.join(', ')).join('\n')}
}
function parseEditorCoordinates(value){
  const lines=value.trim().split(/\r?\n/).map(line=>line.trim()).filter(Boolean)
  if(lines.length<2)throw new Error('至少输入两个 WGS84 GIS 点，每行“经度, 纬度”')
  return lines.map((line,index)=>{
    const values=line.replace(/[\[\]]/g,'').split(/[\s,，]+/).filter(Boolean).map(Number)
    if(values.length!==2||values.some(v=>!Number.isFinite(v)))throw new Error(`第 ${index+1} 行坐标格式错误`)
    return values
  })
}
async function submitEdit(){
  if(!editor.value||generating.value)return
  editError.value=''
  const form=editor.value
  let body
  try{
    body={action:form.action,linkId:form.linkId,maxLinkLengthM:Number(data.value.generation?.maxLinkLengthM||500)}
    if(form.action!=='delete'){
      body.properties={name:form.name,ref:form.ref,highway:form.highway,oneway:form.oneway,
        lanes:form.lanes,maxspeed:form.maxspeed}
      body.coordinates=parseEditorCoordinates(form.coordinates)
    }
  }catch(e){editError.value=e.message;return}
  generating.value=true;generationError.value='';generationMessage.value='正在保存路链编辑…'
  editFocus=form.action==='add'?null:{sourceId:form.sourceId,linkId:form.action==='delete'?null:form.linkId}
  try{
    const job=await generationRequest({method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)},'link-edit')
    activeJobId=job.id;generationMessage.value=job.message;editor.value=null
    clearTimeout(generationTimer);if(!disposed)generationTimer=setTimeout(checkGeneration,1000)
  }catch(e){generating.value=false;generationMessage.value='';editError.value=e.message;editFocus=null}
}
watch([query,roadType,route,structure,direction],()=>{page.value=1})
watch(selected,()=>{pointCoordinateSystem.value='WGS84'})
onMounted(async()=>{try{await load()}catch{};if(!disposed)checkGeneration()})
onBeforeUnmount(()=>{disposed=true;clearTimeout(generationTimer);clearTimeout(toastTimer)})
</script>

<template>
  <div class="app-shell">
    <div v-if="!data" class="loading-screen"><span class="loading-orbit">⌖</span><h2>{{ error ? '暂时无法加载数据' : '正在展开海南路网' }}</h2><p>{{ error || '读取本地路链与连通关系…' }}</p><button v-if="error" @click="load">重新加载</button></div>
    <template v-else>
      <main class="workspace">
        <aside class="explorer">
          <div class="section-title"><h2>路网资源</h2><div class="resource-heading-actions"><button class="add-link-button" :disabled="generationAvailable!==true||generating" @click="openEditor('add')">＋ 添加路链</button><span class="count-pill">{{ fmt(list.length) }}</span></div></div>
          <form class="generation-control" @submit.prevent="generate">
            <label for="max-link-length">路链最大长度</label>
            <div class="generation-input"><input id="max-link-length" v-model.number="maxLength" type="number" min="100" max="10000" step="any" required :disabled="generating"><span>m</span><button type="submit" :disabled="generating||!validMaxLength||generationAvailable!==true">{{ generating?'生成中…':'重新生成' }}</button></div>
            <small v-if="!generating">当前 {{ data.generation?.maxLinkLengthM || 500 }} m · 可设 100–10,000 m</small>
            <p v-if="generating||generationMessage" class="generation-status" role="status"><i v-if="generating" class="generation-spinner"></i>{{ generationMessage }}</p>
            <p v-if="generationError" class="generation-error" role="alert">{{ generationError }}</p>
          </form>
          <div class="filters"><label class="search"><span>⌕</span><input v-model="query" placeholder="搜索路名、路链编号或桩号" aria-label="搜索路网"><button v-if="query" aria-label="清除搜索" @click="query=''">×</button><kbd v-else>搜索</kbd></label>
            <div class="filter-grid"><label>道路类型<select v-model="roadType"><option value="all">全部类型</option><option value="motorway">高速主线</option><option value="motorway_link">高速匝道</option></select></label><label>路线编号<select v-model="route"><option value="all">全部路线</option><option v-for="r in routes" :key="r" :value="r">{{ r }}</option></select></label><label>道路结构<select v-model="structure"><option value="all">全部结构</option><option value="bridge">桥梁</option><option value="tunnel">隧道</option></select></label><label>上下行<select v-model="direction"><option value="all">全部方向</option><option value="UP">上行</option><option value="DOWN">下行</option><option value="unconfirmed">待确认</option><option value="bidirectional">双向</option></select></label></div>
          </div>
          <div class="result-label"><span>路链列表 <b>{{ fmt(list.length) }}</b></span><button @click="reset">重置</button></div>
          <div class="resource-list"><button v-for="feature in pageItems" :key="feature.properties.link_id" class="resource-item" :class="{selected:selected===feature}" @click="select(feature,true)"><span class="road-symbol" :class="{ramp:feature.properties.highway==='motorway_link'}">⌁</span><div><strong>{{ feature.properties.name || (feature.properties.highway==='motorway'?'未命名高速主线':'未命名高速匝道') }}</strong><small>{{ feature.properties.link_id }}</small><span class="direction-badge" :class="{inferred:feature.properties.direction_annotation?.status==='inferred'}">{{ feature.properties.direction_annotation?.label || '上下行待确认' }}</span><div class="item-meta"><span v-if="feature.properties.ref" class="route-tag">{{ feature.properties.ref }}</span><span>{{ feature.properties.highway==='motorway'?'高速主线':'高速匝道' }}</span><b>{{ Number(feature.properties.length_m).toFixed(1) }} m</b></div></div><span class="item-arrow">›</span></button><div v-if="!list.length" class="empty-results">没有找到匹配的路链<button @click="reset">清除筛选条件</button></div></div>
          <div class="pagination"><span>{{ page }} / {{ pages }} 页</span><div><button :disabled="page===1" aria-label="上一页" @click="page--">‹</button><button :disabled="page===pages" aria-label="下一页" @click="page++">›</button></div></div>
        </aside>
        <section class="map-panel"><div class="map-heading"><div><i class="tiny-dot"></i><h2>海南高速路网</h2><span>可交互地图</span></div><button @click="map?.fit()">⌖ 全域视图</button></div>
          <RoadMap ref="map" :roads="mapRoads" :selected="selected" :endpoints="endpoints" :arrows="arrows" @select="select" @ready="mapState=$event" />
          <div class="layer-control"><span>图层</span><label><input v-model="endpoints" type="checkbox">路链端点</label><label><input v-model="arrows" type="checkbox">方向箭头</label></div>
          <div class="map-legend"><span><i class="legend-line"></i>高速主线</span><span><i class="legend-line ramp"></i>匝道</span><span><i class="legend-line associated"></i>已关联接口</span><span><i class="legend-line selected"></i>当前选中</span><span><i class="legend-dot start"></i>起点</span><span><i class="legend-dot end"></i>终点</span><span><i class="legend-dot purple"></i>共用端点</span></div>
          <div class="map-footer"><span><i class="tiny-dot"></i>显示 {{ fmt(mapRoads.length) }} 条路链 · {{ filteredLength.toFixed(1) }} km</span><span>缩放 {{ mapState.zoom }} · 拖动平移 / 滚轮缩放</span></div>
        </section>
        <aside class="detail-panel">
          <div class="section-title"><h2>{{ selected?'要素详情':'路网概览' }}</h2><button v-if="selected" class="close-button" aria-label="关闭详情" @click="selected=null">×</button><span v-else class="live-label">已载入</span></div>
          <template v-if="selected">
            <div class="detail-title"><h3>{{ properties.name || (properties.highway==='motorway'?'未命名高速主线':'未命名高速匝道') }}</h3><span v-if="properties.ref" class="route-tag">{{ properties.ref }}</span><span class="type-tag">{{ properties.highway==='motorway'?'高速主线':'高速匝道' }}</span></div>
            <div class="id-block"><label>路链编号</label><button title="复制编号" @click="copyId">{{ properties.link_id }} <span>⧉</span></button></div>
            <div class="detail-metrics"><div><small>长度</small><strong>{{ Number(properties.length_m).toFixed(1) }}<span> m</span></strong></div><div><small>上下行</small><strong class="direction-value">{{ properties.direction_annotation?.label || '待确认' }}</strong></div></div>
            <div v-if="generationAvailable===true" class="link-edit-actions"><button :disabled="generating" @click="openEditor('update')">编辑本段</button><button class="delete-link-button" :disabled="generating" @click="openEditor('delete')">删除本段</button></div>
            <div v-if="properties.business_association" class="detail-section api-association"><h4>接口关联 <span>{{ associatedLinks.length }} 条</span></h4><p class="detail-note">覆盖本段 {{ (properties.business_association.coverage*100).toFixed(0) }}% · 空间匹配待复核</p>
              <p v-if="properties.business_association.directionStatus==='conflict'" class="association-warning">接口方向存在冲突，未采用接口上下行。</p>
              <article v-for="link in associatedLinks" :key="link.id" class="business-link"><p>{{ link.match.unitName }}</p><p class="stake-range">{{ link.startStakeNum || '未提供桩号' }} → {{ link.endStakeNum || '未提供桩号' }}</p>
                <details class="compact-details"><summary>接口属性与门架</summary><button class="business-id" @click="locateBusiness(link.id)">{{ link.id }} ↗</button><dl><dt>方向</dt><dd>{{ link.match.direction?.code==='UP'?'上行':link.match.direction?.code==='DOWN'?'下行':'未提供' }}{{ link.match.directionNameConflict?' · 与单元名称矛盾':'' }}</dd><dt>长度</dt><dd>{{ link.length }} m</dd><dt>端点偏差</dt><dd>{{ link.match.startDistanceM }} / {{ link.match.endDistanceM }} m</dd><dt>版本</dt><dd>{{ data.businessData.version }}</dd></dl><p v-for="gate in link.gantries" :key="gate.id" class="associated-gantry">门架：{{ gate.name }} · {{ gate.stakeNum }}</p></details>
              </article>
              <details v-if="businessRelations.length" class="compact-details"><summary>接口连通关系（{{ businessRelations.length }}）</summary><div v-for="rel in businessRelations" :key="rel.id" class="business-relation"><button @click="locateBusiness(rel.currentLinkId)">{{ rel.currentLinkId }}</button><small>→ {{ rel.direction==='UP'?'上行':'下行' }} →</small><button v-if="String(rel.nextLinkId)!=='0'" @click="locateBusiness(rel.nextLinkId)">{{ rel.nextLinkId }}</button><span v-else>无下一跳</span></div></details>
            </div>
            <div class="detail-section compact-topology"><h4>相邻路链</h4><div v-for="id in prevLinks" :key="id" class="relation"><small>← 驶入</small><button @click="related(id)">{{ id }} ↗ <span class="relation-kind">{{ relationKind(id) }}</span></button></div><div v-for="id in nextLinks" :key="id" class="relation"><small>→ 驶出</small><button @click="related(id)">{{ id }} ↗ <span class="relation-kind">{{ relationKind(id) }}</span></button></div><p v-if="!prevLinks.length&&!nextLinks.length" class="muted">当前路网中暂无已确认连接</p></div>
            <details :key="properties.link_id" class="detail-section geometry-points"><summary>路链 GIS 点 <span>{{ gisPoints.length }} 个</span></summary>
              <p>按路链几何顺序排列，相邻点连成地图上的线。</p>
              <div class="point-actions"><label>坐标系<select v-model="pointCoordinateSystem" aria-label="GIS 点坐标系"><option>WGS84</option><option>GCJ-02</option></select></label><button @click="copyGisPoints">复制坐标</button></div>
              <ol class="point-list"><li v-for="point in gisPoints" :key="point.index"><span class="point-index">{{ point.index }}</span><div><span>经度 {{ coordinateText(point.longitude) }}</span><span>纬度 {{ coordinateText(point.latitude) }}</span></div><small v-if="point.role">{{ point.role }}</small></li></ol>
            </details>
            <details :key="properties.link_id" class="raw-properties"><summary>更多属性与方向依据</summary><dl><dt>原链编号</dt><dd>{{ properties.source_link_id }}</dd><dt>拆分序号</dt><dd>{{ properties.segment_index }}</dd><dt>车道 / 限速</dt><dd>{{ properties.lanes || '未标注' }} / {{ properties.maxspeed || '未标注' }}</dd><dt>通行方向</dt><dd>{{ properties.oneway==='no'?'双向':properties.oneway==='-1'?'反向单行':properties.oneway==='yes'?'正向单行':'未标注' }}</dd><dt>道路结构</dt><dd>{{ [tagged(properties.bridge)?'桥梁':'',tagged(properties.tunnel)?'隧道':''].filter(Boolean).join(' / ') || '普通路段' }}</dd></dl>
              <div class="direction-detail"><p>{{ properties.direction_annotation?.basis }}</p><p v-if="properties.direction_annotation?.osmRouteHeadings?.length">OSM 路线方向：{{ properties.direction_annotation.osmRouteHeadings.join(' / ') }}</p><template v-if="properties.direction_annotation?.status==='inferred'"><small>派生推断，尚未通过业务方向复核。</small><a :href="data.directionSummary.sources[0].url" target="_blank" rel="noopener noreferrer">查看方向依据 ↗</a></template></div>
              <p v-if="properties.business_association?.directionStatus==='partialOrMissing'" class="detail-note">覆盖不足 80% 或缺少接口方向，保留原有上下行标注。</p><p class="detail-note">相邻关系按通行方向建立，包含内部拆分与 OSM 共享节点确认的跨原链连接。</p><details class="compact-details"><summary>全部源属性</summary><dl><template v-for="[key,value] in extraProperties" :key="key"><dt>{{ key }}</dt><dd>{{ typeof value==='object'?JSON.stringify(value):value }}</dd></template></dl></details>
            </details>
            <button class="locate-button" @click="map?.fit([selected])">⌖ 定位此路链</button>
          </template>
          <template v-else><div class="overview-art"><svg viewBox="0 0 240 150" aria-hidden="true"><defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="#d9e7e2" stroke-width=".5"/></pattern></defs><rect width="240" height="150" fill="url(#grid)"/><path d="M50 132L91 100 105 57 165 20M91 100L163 110 187 55 165 20M105 57L187 55M105 57L163 110" fill="none" stroke="#bed6cf" stroke-width="8"/><path d="M50 132L91 100 105 57 165 20M91 100L163 110 187 55 165 20M105 57L187 55" fill="none" stroke="#278c7c" stroke-width="2"/><g fill="#fff" stroke="#278c7c" stroke-width="2"><circle cx="91" cy="100" r="5"/><circle cx="105" cy="57" r="5"/><circle cx="163" cy="110" r="5"/><circle cx="187" cy="55" r="5"/></g><circle cx="105" cy="57" r="13" fill="#278c7c" opacity=".1"/></svg><strong>从一条路链开始探索</strong><p>点击地图中的道路，或从左侧列表选择，查看属性与连接关系。</p></div><div class="detail-section direction-coverage"><h4>上下行标注范围</h4><p>G98 主线：上行 {{ fmt(data.directionSummary.inferredUp) }} 条，下行 {{ fmt(data.directionSummary.inferredDown) }} 条，均为推断。</p><p class="detail-note">已关联接口的部分路链采用接口方向；其余路线及匝道待确认。</p></div><div v-if="data.associationSummary" class="detail-section association-coverage"><h4>接口关联范围</h4><p>G9811 北段：{{ fmt(data.associationSummary.matchedBusinessLinks) }} / {{ fmt(data.associationSummary.businessLinks) }} 条接口路链，对应 {{ fmt(data.associationSummary.associatedOsmLinks) }} 条地图路链。</p><p>{{ fmt(data.associationSummary.businessDirectionOsmLinks) }} 条地图路链采用接口空间关联方向。</p><button class="association-show" @click="locateAssociations">定位关联区域 ↗</button><p class="detail-note">先按整条高速对照主线，再按互通与收费单元逐一匹配匝道。空间关联待人工复核。</p><details class="highway-comparison"><summary>按高速与收费单元逐一对照</summary><div v-for="ref in data.associationSummary.groups.routes" :key="ref" class="comparison-route"><button @click="compareHighway(ref)">对照 {{ ref }} 整条主线 ↗</button><p>{{ data.associationSummary.groups.mainUnits.length }} 个主线单元，先核对两幅单向道路与接口顺序。</p></div><div class="comparison-units"><strong>主线收费单元</strong><button v-for="unit in data.associationSummary.groups.mainUnits" :key="unit.unitId" @click="locateUnit(unit.unitId)">{{ unit.name }}<small>{{ unit.statusCounts.matched || 0 }} / {{ unit.businessLinkIds.length }} 条通过关联检查</small></button><strong>互通匝道与服务区</strong><button v-for="unit in data.associationSummary.groups.rampUnits" :key="unit.unitId" @click="locateUnit(unit.unitId)">{{ unit.name }}<small>{{ unit.statusCounts.matched || 0 }} / {{ unit.businessLinkIds.length }} 条通过关联检查</small></button></div></details></div><div class="detail-section"><h4>道路组成</h4><div class="composition-bar"><span :style="{width:mainCount/roads.length*100+'%'}"></span></div><div class="composition-label"><span><i class="legend-dot start"></i>主线 {{ fmt(mainCount) }}</span><span><i class="legend-dot end"></i>匝道 {{ fmt(roads.length-mainCount) }}</span></div></div><div class="detail-section"><h4>特殊道路结构</h4><div class="structure-row"><span>桥梁路链</span><b>{{ fmt(bridgeCount) }}<small>条</small></b></div><div class="structure-row"><span>隧道路链</span><b>{{ fmt(tunnelCount) }}<small>条</small></b></div><p class="detail-note">按 OSM 结构标签统计，计数单位为拆分后的路链。</p></div><div class="source-card"><span class="eyebrow">DATA SOURCE</span><strong>OpenStreetMap</strong><p>海南高速主线与匝道<br>本地嵌入 · WGS84 / GCJ-02</p><span class="source-status"><i class="tiny-dot"></i>数据校验{{ data.validation.valid?'通过':'需检查' }}</span></div></template>
        </aside>
      </main>
      <footer class="page-footer"><span>海南自由流项目 <b>/</b> 路链数据探索平台</span><span>本地数据快照 · 非实时交通数据 <i>© OpenStreetMap contributors</i></span></footer>
      <div v-if="editor" class="modal-backdrop" @click.self="editor=null"><section class="link-editor-modal" role="dialog" aria-modal="true" aria-labelledby="link-editor-title"><button class="close-button" aria-label="关闭路链编辑" @click="editor=null">×</button>
        <h2 id="link-editor-title">{{ editor.action==='add'?'添加路链':editor.action==='delete'?'删除选中路链':'编辑选中路链' }}</h2>
        <p v-if="editor.linkId" class="editor-target">{{ editor.linkId }}</p>
        <template v-if="editor.action==='delete'"><p class="editor-note">仅删除当前选中的拆分段。保存后会重算相邻段、连通关系与编号；原始 OSM 数据保留。</p><div class="editor-footer"><button @click="editor=null">取消</button><button class="editor-danger" :disabled="generating" @click="submitEdit">确认删除本段</button></div></template>
        <form v-else @submit.prevent="submitEdit"><p class="editor-note">坐标使用 WGS84，每行一个“经度, 纬度”。编辑现有路链时须保留本段起点与终点；名称、路线及通行属性将同步到所属原链。</p>
          <div class="editor-fields"><label>道路名称<input v-model="editor.name" maxlength="120" placeholder="例如：海南环线高速"></label><label>路线编号<input v-model="editor.ref" maxlength="120" placeholder="例如：G98"></label><label>道路类型<select v-model="editor.highway"><option value="motorway">高速主线</option><option value="motorway_link">高速匝道</option></select></label><label>通行方向<select v-model="editor.oneway"><option value="yes">正向单行</option><option value="-1">反向单行</option><option value="no">双向</option></select></label><label>车道数<input v-model="editor.lanes" maxlength="120"></label><label>限速<input v-model="editor.maxspeed" maxlength="120"></label></div>
          <label class="editor-coordinates">GIS 点（WGS84）<textarea v-model="editor.coordinates" rows="9" spellcheck="false" placeholder="110.0341221, 18.5324053&#10;110.0354483, 18.5337118" required></textarea></label>
          <p v-if="editError" class="generation-error" role="alert">{{ editError }}</p>
          <div class="editor-footer"><button type="button" @click="editor=null">取消</button><button type="submit" :disabled="generating">{{ editor.action==='add'?'添加并重新拆分':'保存并重新拆分' }}</button></div>
        </form>
        <p v-if="editor.action==='delete'&&editError" class="generation-error" role="alert">{{ editError }}</p>
      </section></div>
      <div v-if="showValidation" class="modal-backdrop" @click.self="showValidation=false"><section class="validation-modal" role="dialog" aria-modal="true" aria-labelledby="validation-title"><button class="close-button" aria-label="关闭校验报告" @click="showValidation=false">×</button><span class="eyebrow">DATA VALIDATION</span><h2 id="validation-title">海南路链校验报告</h2><div class="validation-result">{{ data.validation.valid?'✓ 校验通过':'! 存在校验问题' }}</div><dl><dt>检查路链</dt><dd>{{ fmt(data.validation.checkedLinks) }} 条</dd><dt>原始路链</dt><dd>{{ fmt(data.validation.checkedSources) }} 条</dd><dt>OSM 有向关系</dt><dd>{{ fmt(data.relationships.length) }} 条</dd><dt>错误</dt><dd>{{ data.validation.errors.length }}</dd><dt>警告</dt><dd>{{ data.validation.warnings.length }}</dd></dl><p>当前快照的拆分校验报告，涵盖长度、ID、连续性、长度守恒及关系引用检查。</p><pre v-if="data.validation.errors.length || data.validation.warnings.length">{{ JSON.stringify({errors:data.validation.errors,warnings:data.validation.warnings},null,2) }}</pre><button class="locate-button" @click="showValidation=false">返回路网探索</button></section></div>
      <div v-if="toast" class="toast" role="status">✓ {{ toast }}</div>
    </template>
  </div>
</template>
