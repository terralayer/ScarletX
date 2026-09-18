const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDate=v=>{if(!v)return'—';let s=String(v),d;if(/^\d{4}-\d{2}-\d{2}$/.test(s)){let [y,m,day]=s.split('-').map(Number);d=new Date(y,m-1,day)}else d=new Date(v);return d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})};
const bytes=n=>{if(!n&&n!==0)return'—';let u=['B','KB','MB','GB','TB'],i=0,x=Number(n);while(x>=1024&&i<u.length-1){x/=1024;i++}return`${x.toFixed(i>2?2:i?1:0)} ${u[i]}`};
const durationText=n=>{if(n==null)return'—';let x=Math.max(0,Math.floor(Number(n))),h=Math.floor(x/3600),m=Math.floor((x%3600)/60),sec=x%60;return h?`${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`:`${m}:${String(sec).padStart(2,'0')}`};
const api=async(path,opts={})=>{let h={'Content-Type':'application/json',...(opts.headers||{})};let r=await fetch(path,{...opts,headers:h});if(r.status===401){window.dispatchEvent(new Event('scarletx:session-expired'));}if(r.status===204)return null;let text=await r.text(),data;try{data=JSON.parse(text)}catch{data=text}if(!r.ok)throw new Error(data?.detail||data||`${r.status}`);return data};
const patch=body=>({method:'PATCH',body:JSON.stringify(body)}), post=body=>({method:'POST',body:body===undefined?undefined:JSON.stringify(body)}), put=body=>({method:'PUT',body:JSON.stringify(body)});
function notify(msg,type='info'){let n=document.createElement('div');n.className=`notice ${type}`;n.textContent=msg;$('#app').prepend(n);setTimeout(()=>n.remove(),4500)}
function pageHead(title,sub,actions=''){return `<div class="pagehead"><div><h1>${esc(title)}</h1></div><div class="actions">${actions}</div></div>`}
function empty(msg){return `<div class="empty">${esc(msg)}</div>`}
function modal(title,html){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=html;$('#modal').classList.add('open')}
