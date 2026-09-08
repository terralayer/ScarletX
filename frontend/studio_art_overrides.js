const STUDIO_ART_HTTP_VERSION='v4';
studioArtUrl=function(id){return `/api/artwork/studios/${encodeURIComponent(id)}?v=${STUDIO_ART_HTTP_VERSION}`;};

studioLink=function(x){
  let st=x.studio;if(!st)return '<span class="muted">—</span>';
  let name=typeof st==='string'?st:(st.name||'Studio'),id=typeof st==='object'?(st.id||st.tpdb_id||''):(x.studio_id||'');
  let logo=id?`<span class="studio-logo"><img src="${studioArtUrl(id)}" alt="" loading="lazy" onerror="this.closest('.studio-logo').remove()"></span>`:'';
  return `<span class="studio-credit">${logo}${id?`<button class="studio-link" data-studio-link="${esc(id)}">${esc(name)}</button>`:esc(name)}</span>`;
};

entityCard=function(type,x,inLibrary){
  let id=x.tpdb_id||x.id, img=x.image_url||x.poster_url||x.logo_url||'', title=x.title||x.name||'Untitled',sub=x.aliases||x.description||'';
  let posterClass=type==='performers'?'media-poster performer-poster':'media-poster';
  let cachedImg=type==='performers'?`/api/artwork/performers/${encodeURIComponent(id)}?size=card`:type==='studios'?studioArtUrl(id):img;
  let renderImg=type==='studios'||!!img;
  return `<article class="media-card ${type==='performers'?'performer-card':type==='studios'?'studio-card':''}" data-id="${esc(id)}" data-local-id="${inLibrary?esc(x.id):''}"><div class="${posterClass}">${renderImg?`<img src="${esc(cachedImg)}" loading="lazy" ${type==='performers'?'data-performer-image title="Open performer profile"':''} onerror="this.remove()">`:''}</div><div class="media-body"><h3>${esc(title)}</h3><p>${esc(typeof sub==='string'?sub:'')}</p><div class="actions">${inLibrary?`<button class="btn small" data-detail>Details</button><button class="btn small danger" data-remove>Remove</button>`:`<button class="btn small primary" data-add>Add & Monitor All</button><button class="btn small" data-remote-detail>Details</button>`}</div></div></article>`;
};
