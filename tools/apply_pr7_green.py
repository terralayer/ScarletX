from pathlib import Path
from textwrap import dedent


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_main() -> None:
    target = Path("scarletx/main.py")
    text = target.read_text(encoding="utf-8")

    anchor = "from .list_queries import performer_summary_page, scene_summary_page, studio_summary_page\n"
    if text.count(anchor) != 1:
        raise SystemExit("main.py: import anchor mismatch")
    text = text.replace(
        anchor,
        anchor + "from .event_stream import QueueEvent, format_sse, queue_event_broker, queue_event_pump\n",
        1,
    )

    watcher = "        asyncio.create_task(media_watch_loop(SessionLocal)),\n"
    if text.count(watcher) != 1:
        raise SystemExit("main.py: watcher anchor mismatch")
    text = text.replace(
        watcher,
        watcher + "        asyncio.create_task(queue_event_pump(_load_cached_activity_queue_data)),\n",
        1,
    )

    route_start = text.index('@app.get("/api/activity/stream")')
    route_end = text.index("\n\n_SYSTEM_STATUS_CACHE", route_start)
    replacement = dedent(
        '''
        async def _load_activity_stream_snapshot() -> dict:
            return await asyncio.to_thread(_load_cached_activity_queue_data)


        @app.get("/api/activity/stream")
        async def activity_stream(request: Request):
            raw_last_event_id = request.headers.get("last-event-id")
            try:
                last_event_id = int(raw_last_event_id) if raw_last_event_id is not None else None
            except ValueError:
                last_event_id = None

            async def events():
                subscription = queue_event_broker.subscribe(last_event_id)
                try:
                    if last_event_id is None:
                        snapshot_id = int(queue_event_broker.snapshot()["last_event_id"])
                        payload = await _load_activity_stream_snapshot()
                        yield format_sse(QueueEvent(snapshot_id, "snapshot", payload))
                    while not await request.is_disconnected():
                        try:
                            event = await asyncio.wait_for(anext(subscription), timeout=15.0)
                        except TimeoutError:
                            yield ": keepalive\\n\\n"
                            continue
                        if event.kind == "resync":
                            payload = await _load_activity_stream_snapshot()
                            event = QueueEvent(
                                event.id,
                                "resync",
                                {"reason": event.payload.get("reason", "resync"), "snapshot": payload},
                            )
                        yield format_sse(event)
                except asyncio.CancelledError:
                    raise
                finally:
                    await subscription.aclose()

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        '''
    ).strip()
    text = text[:route_start] + replacement + text[route_end:]
    target.write_text(text, encoding="utf-8")


def patch_status_console() -> None:
    replace_once(
        "scarletx/status_console.py",
        '            StatusRow("SSE Event Stream", "READY", "Nginx buffering disabled", "ok"),',
        '            StatusRow("SSE Event Stream", "READY", "global queue stream | replay 512 | subscriber 64", "ok"),',
    )


def patch_auth() -> None:
    target = Path("frontend/auth.js")
    text = target.read_text(encoding="utf-8")
    old_state = "  const state = {setupRequired:false, username:'', appStarted:false, appBoot:null};\n  const el = id => document.getElementById(id);\n"
    new_state = dedent(
        '''
          const state = {setupRequired:false, username:'', appStarted:false, appBoot:null, queueSource:null, queueFailures:0, queueRetryTimer:null};
          const el = id => document.getElementById(id);
          const QUEUE_KINDS = ['snapshot','progress','transition','history','resync'];

          function dispatchQueue(name, detail={}) {
            window.dispatchEvent(new CustomEvent(name, {detail}));
          }

          function stopQueueStream() {
            if (state.queueRetryTimer) {
              clearTimeout(state.queueRetryTimer);
              state.queueRetryTimer = null;
            }
            if (state.queueSource) {
              state.queueSource.close();
              state.queueSource = null;
            }
          }

          function startQueueStream() {
            if (state.queueSource) return;
            if (!window.EventSource) {
              dispatchQueue('scarletx:queue-stream-fallback', {reason:'unsupported'});
              return;
            }
            const source = new EventSource('/api/activity/stream');
            state.queueSource = source;
            source.onopen = () => {
              if (state.queueSource !== source) return;
              state.queueFailures = 0;
              dispatchQueue('scarletx:queue-stream-healthy');
            };
            const handle = kind => event => {
              let payload = {};
              try { payload = event.data ? JSON.parse(event.data) : {}; } catch { return; }
              dispatchQueue('scarletx:queue-event', {kind, id:Number(event.lastEventId || 0), payload});
            };
            QUEUE_KINDS.forEach(kind => source.addEventListener(kind, handle(kind)));
            source.onerror = () => {
              if (state.queueSource !== source) return;
              state.queueFailures += 1;
              if (state.queueFailures < 3) return;
              source.close();
              state.queueSource = null;
              dispatchQueue('scarletx:queue-stream-fallback', {reason:'repeated_failure'});
              state.queueRetryTimer = setTimeout(() => {
                state.queueRetryTimer = null;
                startQueueStream();
              }, 30000);
            };
          }
        '''
    ).lstrip()
    if text.count(old_state) != 1:
        raise SystemExit("auth.js: state anchor mismatch")
    text = text.replace(old_state, new_state, 1)

    show_anchor = "    el('authAccountUsername').value = state.username;\n"
    if text.count(show_anchor) != 1:
        raise SystemExit("auth.js: showApp anchor mismatch")
    text = text.replace(show_anchor, show_anchor + "    startQueueStream();\n", 1)

    logout_anchor = "  el('authLogoutButton').addEventListener('click', async () => {\n    el('authLogoutButton').disabled = true;\n"
    if text.count(logout_anchor) != 1:
        raise SystemExit("auth.js: logout anchor mismatch")
    text = text.replace(logout_anchor, logout_anchor + "    stopQueueStream();\n", 1)
    target.write_text(text, encoding="utf-8")


def patch_index() -> None:
    target = Path("frontend/index.html")
    text = target.read_text(encoding="utf-8")
    replacements = [
        (
            "let liveQueueTimer=null,liveQueueBusy=false,liveQueueSource=null;",
            "let liveQueueTimer=null,liveQueueBusy=false,liveQueueSnapshot={tracked:[],clients:{}};",
        ),
        (
            "  await updateChrome();render();\n  setInterval(()=>{if(view!=='activity')updateQueueBadge()},5000);",
            "  await updateChrome();render();",
        ),
        (
            "function stopLiveQueue(){if(liveQueueTimer){clearTimeout(liveQueueTimer);liveQueueTimer=null}if(liveQueueSource){liveQueueSource.close();liveQueueSource=null}liveQueueBusy=false}\nasync function updateQueueBadge(){try{let q=await api('/api/activity/queue');$('#queueBadge').textContent=(q.tracked||[]).length}catch{}}\nasync function render(){if(view!=='activity')stopLiveQueue();nav();",
            "function stopLiveQueue(){if(liveQueueTimer){clearTimeout(liveQueueTimer);liveQueueTimer=null}liveQueueBusy=false}\nasync function render(){nav();",
        ),
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise SystemExit(f"index.html: replacement anchor mismatch: {old[:80]!r}")
        text = text.replace(old, new, 1)

    live_start = text.index("async function refreshLiveQueue(){")
    live_end = text.index("\n\nasync function activity(){", live_start)
    live_block = dedent(
        '''
        async function resyncLiveQueue(){
          if(liveQueueBusy)return;
          liveQueueBusy=true;
          try{liveQueueSnapshot=await api('/api/activity/queue');applyLiveQueue(liveQueueSnapshot)}catch(_){}finally{liveQueueBusy=false}
        }
        function mergeLiveQueueJob(job){
          let rows=[...(liveQueueSnapshot.tracked||[])],key=String(job.external_id||job.id||''),i=rows.findIndex(x=>String(x.external_id||x.id||'')===key);
          if(i>=0)rows[i]={...rows[i],...job};else rows.push(job);
          liveQueueSnapshot={...liveQueueSnapshot,tracked:rows};applyLiveQueue(liveQueueSnapshot);
        }
        async function refreshLiveQueueFallback(){
          await resyncLiveQueue();
          if(!liveQueueTimer)liveQueueTimer=setTimeout(()=>{liveQueueTimer=null;refreshLiveQueueFallback()},15000);
        }
        window.addEventListener('scarletx:queue-event',e=>{
          let detail=e.detail||{},kind=detail.kind,payload=detail.payload||{};
          if(kind==='snapshot'){liveQueueSnapshot=payload;applyLiveQueue(liveQueueSnapshot);return}
          if((kind==='progress'||kind==='transition')&&payload.job){mergeLiveQueueJob(payload.job);return}
          if(kind==='resync'){
            if(payload.snapshot){liveQueueSnapshot=payload.snapshot;applyLiveQueue(liveQueueSnapshot)}else resyncLiveQueue();
          }
        });
        window.addEventListener('scarletx:queue-stream-fallback',()=>{
          if(!liveQueueTimer)liveQueueTimer=setTimeout(()=>{liveQueueTimer=null;refreshLiveQueueFallback()},15000);
        });
        window.addEventListener('scarletx:queue-stream-healthy',()=>stopLiveQueue());
        '''
    ).strip()
    text = text[:live_start] + live_block + text[live_end:]

    activity_stop = "async function activity(){\n  stopLiveQueue();"
    if text.count(activity_stop) != 1:
        raise SystemExit("index.html: activity stop anchor mismatch")
    text = text.replace(activity_stop, "async function activity(){", 1)

    old_action = "await api(`/api/downloads/native/${encodeURIComponent(b.dataset.job)}/${b.dataset.nativeAct}`,post());await refreshLiveQueue()"
    if text.count(old_action) != 1:
        raise SystemExit("index.html: queue action anchor mismatch")
    text = text.replace(
        old_action,
        "await api(`/api/downloads/native/${encodeURIComponent(b.dataset.job)}/${b.dataset.nativeAct}`,post());await resyncLiveQueue()",
        1,
    )

    old_initial = "    $('#activityQueue').innerHTML=activityQueueHtml(rows);$('#queueBadge').textContent=rows.length;"
    if text.count(old_initial) != 1:
        raise SystemExit("index.html: activity initial queue anchor mismatch")
    text = text.replace(old_initial, "    liveQueueSnapshot=q;applyLiveQueue(q);", 1)

    if text.count("    startLiveQueue();") != 1:
        raise SystemExit("index.html: startLiveQueue anchor mismatch")
    text = text.replace("    startLiveQueue();\n", "", 1)
    target.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_main()
    patch_status_console()
    patch_auth()
    patch_index()
