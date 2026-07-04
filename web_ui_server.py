from flask import Flask, render_template_string, jsonify, request, url_for
import json, os, requests, time, sys

# ------------------------------ CONFIG ----------------------------------
from config_dialog import read_config, write_config
config = read_config() or {}
role   = config.get("role", "FLIGHT")

ROLES = [
    "FLIGHT", "CAPCOM", "PRO", "BME", "EVA", "SCIENCE", "CONTACT", "AA"
]

# Build HTML option tags for roles once
options = "".join(f"<option value='{r}'>{r}</option>" for r in ROLES)

# Load loops for the selected role
def load_loops(r):
    path = os.path.join('LOOPS', f'loops_{r.upper()}.txt')
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print('Loop load error', e)
        return []

LOOPS = load_loops(role)

# ------------------------------ BOT POOL ---------------------------------
BOTS = [
    {"name": "BOT1", "port": 6001},
    {"name": "BOT2", "port": 6002},
    {"name": "BOT3", "port": 6003},
]

bot_pool   = {b['name']: {**b, 'assigned': None, 'last_used': 0} for b in BOTS}
loop_states = {l['name']: (0, None) for l in LOOPS}
loop_volumes = {l['name']: 1.0 for l in LOOPS}

def refresh_state_from_role():
    global LOOPS, loop_states, loop_volumes
    LOOPS = load_loops(role)
    loop_states = {l['name']: (0, None) for l in LOOPS}
    loop_volumes = {l['name']: 1.0 for l in LOOPS}

def find_idle_bot():
    idle = [n for n, d in bot_pool.items() if d['assigned'] is None]
    if not idle:
        return None
    idle.sort(key=lambda n: bot_pool[n]['last_used'])
    return idle[0]

# ------------------------------ FLASK APP --------------------------------
app = Flask(__name__)

# Track whether audio delay mode is enabled. When True, bot commands that mute
# or leave will use delayed variants to allow any buffered audio to finish
# playing out before the state change takes effect.
delay_enabled = False

# ------------------------------ TEMPLATES --------------------------------
MAIN_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCC Voice Loops</title>
<link rel="icon" type="image/png" href="{{ url_for('static', filename='logo2.png') }}">
<style>
 :root{--bg:#1e1e1e;--panel:#2b2b2b;--txt:#ddd;--listen:#325c8d;--talk:#3c6d2d;--danger:#b41b1b}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--txt);font-family:sans-serif}
 #controls{display:flex;align-items:center;padding:10px;background:var(--panel)}
 select,button{margin-right:10px;padding:6px 10px;background:#3a3a3a;border:none;border-radius:4px;color:var(--txt)}
 select:hover,button:hover{background:#4a4a4a;cursor:pointer}
 #wave{width:150px;height:40px;margin-left:auto;border:1px solid #444;border-radius:4px}
 #grid{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:220px;gap:18px;padding:18px}
 .card{position:relative;background:var(--panel);border-radius:12px;box-shadow:0 0 6px #000a;overflow:hidden}
 .listen{background:var(--listen)} .talk{background:var(--talk)}
 .priv{position:absolute;top:8px;left:10px;font-size:1rem}
 .cnt{position:absolute;top:8px;right:10px;font-size:.9rem}
.name{position:absolute;top:45%;left:50%;transform:translate(-50%,-50%);text-align:center;font-weight:600;padding:0 4px;user-select:none;pointer-events:none}
.talkers{position:absolute;top:58%;left:50%;transform:translate(-50%,0);font-size:.8rem;text-align:center;pointer-events:none;user-select:none}
 .vol{position:absolute;bottom:10px;left:10px;width:55%}
 .off{position:absolute;bottom:6px;right:10px;padding:4px 10px;background:var(--danger);border:none;border-radius:4px;color:#fff;font-weight:600}
  #alarm{background:#c22c2c;border:2px solid #ff4444;font-weight:700;padding:6px 14px}#alarm:hover{background:#e03333}#alarm:active{background:#8f1f1f}
  #logo{position:fixed;bottom:10px;right:10px;height:60px;opacity:.6}
</style></head>
<body>
  <div id="controls">
    <label>Input:<select id="inDev"></select></label>
    <label>Output:<select id="outDev"></select></label>
    <button id="delay">Delay</button>
    <button id="alarm">🔔 ALARM</button>
    <canvas id="wave"></canvas>
  </div>
  <div id="grid"></div>
  <img id="logo" src="{{ url_for('static', filename='logo3.png') }}" alt="logo">
<script>
 const LOOPS = {{ loops|tojson }};
 const BOTS  = {{ bots|tojson }};
 const primary = BOTS[0].port;
 let delay=false;
 // ------------- build grid -------------
function grid(){const g=document.getElementById('grid');g.innerHTML='';LOOPS.forEach((l,i)=>{const c=document.createElement('div');c.dataset.loop=l.name;c.dataset.port='';c.className='card';c.innerHTML=`<span class='priv'>${l.can_listen?'🎧':''}${l.can_talk?'🎤':''}</span><span class='cnt'>👥0</span><div class='name'>${l.name}</div><div class='talkers'></div><input type='range' min='0' max='2' step='0.01' value='1' class='vol'><button class='off'>OFF</button>`;c.onclick=e=>{if(e.target===c)act('toggle',l.name)};c.querySelector('.off').onclick=e=>{e.stopPropagation();act('off',l.name)};c.querySelector('.vol').oninput=e=>{e.stopPropagation();fetch('/api/set_volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({loop:l.name,volume:e.target.value})})};g.append(c);})}
 // ------------- device list -------------
 async function devices(){try{const d=await navigator.mediaDevices.enumerateDevices();const iSel=inDev,oSel=outDev;d.filter(x=>x.kind==='audioinput').forEach((d,i)=>iSel.add(new Option(d.label||`Mic ${i}`,d.deviceId)));d.filter(x=>x.kind==='audiooutput').forEach((d,i)=>oSel.add(new Option(d.label||`Spkr ${i}`,d.deviceId)));iSel.onchange=()=>chg('in',iSel.value);oSel.onchange=()=>chg('out',oSel.value);}catch(e){}}
 function chg(t,id){fetch(`http://127.0.0.1:${primary}/device_${t}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device:id})})}
 // ------------- waveform -------------
 async function wave(){try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});const ctx=new(window.AudioContext||window.webkitAudioContext)();const src=ctx.createMediaStreamSource(stream);const analyser=ctx.createAnalyser();analyser.fftSize=256;src.connect(analyser);const data=new Uint8Array(analyser.fftSize);const cvs=document.getElementById('wave');const c=cvs.getContext('2d');const H=cvs.height;const W=cvs.width;(function draw(){requestAnimationFrame(draw);analyser.getByteTimeDomainData(data);c.clearRect(0,0,W,H);c.beginPath();data.forEach((v,i)=>{const x=i*W/data.length;const y=(1-(v-128)/128)*H/2;i?c.lineTo(x,y):c.moveTo(x,y)});c.strokeStyle='#ffffff';c.lineWidth=2;c.stroke();})();}catch(e){console.error(e);}}
 // ------------- actions -------------
 async function act(a,l){const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a,loop:l})});try{const j=await r.json();if('port'in j){const c=document.querySelector(`[data-loop="${l}"]`);if(c)c.dataset.port=j.port||'';}}catch(e){}refresh()}
  const dBtn=document.getElementById('delay');
  dBtn.onclick = async () => {
      delay = !delay;
      dBtn.style.background = delay ? '#43d843' : '#c22c2c';
      await fetch('/api/command', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:'delay', enabled: delay})
      });
  };
  document.getElementById('alarm').onclick = async () => {
      await fetch('/api/alarm', { method: 'POST' });
  };
// ------------- poll -------------
async function refresh(){const r=await (await fetch('/api/status')).json();delay=r.delay;dBtn.style.background=delay?'#43d843':'#c22c2c';LOOPS.forEach(l=>{const c=document.querySelector(`[data-loop="${l.name}"]`);if(!c)return;c.dataset.port=r.assignments[l.name]||'';c.querySelector('.cnt').textContent=`👥${r.user_counts[l.name]||0}`;c.classList.remove('listen','talk');if(r.states[l.name]==1)c.classList.add('listen');if(r.states[l.name]==2)c.classList.add('talk');const t=c.querySelector('.talkers');if(t)t.textContent=(r.talkers[l.name]||[]).join(', ');const v=c.querySelector('.vol');if(v&&r.volumes)v.value=r.volumes[l.name]??1;});}
 // ------------- init -------------
 devices();wave();grid();refresh();setInterval(refresh,1000);
</script></body></html>
"""

CONFIG_HTML = f"""
<!DOCTYPE html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Config</title>
<style>
 body{{background:#1e1e1e;color:#ddd;font-family:sans-serif;padding:40px}}
 input,select{{width:100%;padding:6px 8px;margin:6px 0;background:#2b2b2b;border:none;border-radius:4px;color:#ddd}}
 button{{padding:8px 14px;background:#3c6d2d;border:none;color:#fff;border-radius:4px;margin-top:12px}}
</style></head>
<body>
  <h2>Mission Control Setup</h2>
  <label>Server<input id='srv'></label>
  <label>Port<input id='prt' type='number'></label>
  <label>Password<input id='pwd' type='password'></label>
  <label>Bot Base<input id='bot'></label>
  <label>Role <select id='role'>{options}</select></label>
  <button id='save'>Save</button>
<script>
 async function load(){{
   const cfg = await (await fetch('/api/get_config')).json();
   document.getElementById('srv').value  = cfg.server   || '';
   document.getElementById('prt').value  = cfg.port     || '';
   document.getElementById('pwd').value  = cfg.password || '';
   document.getElementById('bot').value  = cfg.bot_base || '';
   document.getElementById('role').value = cfg.role     || 'FLIGHT';
 }}
 async function save(){{
   const cfg = {{
     server:  document.getElementById('srv').value,
     port:    +document.getElementById('prt').value,
    password:document.getElementById('pwd').value,
     bot_base:document.getElementById('bot').value,
     role:    document.getElementById('role').value
   }};
   await fetch('/api/save_config', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(cfg)}});
   location.href='/'
 }}
 document.addEventListener('DOMContentLoaded',() => {{ load(); document.getElementById('save').onclick = save; }});
</script></body></html>
"""

# ------------------------------ ROUTES -----------------------------------
@app.route('/')
def main_page():
    return render_template_string(MAIN_HTML, loops=LOOPS, bots=BOTS)

@app.route('/config')
def cfg_page():
    return render_template_string(CONFIG_HTML)

@app.route('/api/get_config')
def api_get_config():
    return jsonify(config)

@app.route('/api/save_config', methods=['POST'])
def api_save_config():
    cfg = request.get_json()
    write_config(**cfg)
        # Update globals so the UI reflects the new role immediately
    global config, role
    config = cfg
    role   = cfg.get("role", role)
    requests.post("http://127.0.0.1:6001/leave")
    requests.post("http://127.0.0.1:6002/leave")
    requests.post("http://127.0.0.1:6003/leave")
    bot_pool["BOT1"]['assigned'] = None
    bot_pool["BOT1"]['last_used'] = time.time()
    bot_pool["BOT2"]['assigned'] = None
    bot_pool["BOT2"]['last_used'] = time.time()
    bot_pool["BOT3"]['assigned'] = None
    bot_pool["BOT3"]['last_used'] = time.time()
    refresh_state_from_role()
    return '', 204

@app.route('/api/status')
def status_api():
    counts = {l['name']: 0 for l in LOOPS}
    states = {name: st for name, (st, _) in loop_states.items()}
    talkers = {l['name']: [] for l in LOOPS}
    for bot in BOTS:
        try:
            res = requests.get(
                f"http://127.0.0.1:{bot['port']}/status", timeout=0.5
            ).json()
            counts.update(res.get('user_counts', {}))
            for ln, names in res.get('talkers', {}).items():
                talkers.setdefault(ln, [])
                talkers[ln].extend(names)
            for ln, st in res.get('states', {}).items():
                states[ln] = st
        except Exception:
            pass
    assignments = {
        ln: (bot_pool[b]['port'] if b else None)
        for ln, (_, b) in loop_states.items()
    }
    return jsonify(user_counts=counts, states=states, assignments=assignments,
                   talkers=talkers, volumes=loop_volumes, delay=delay_enabled)

@app.route('/api/set_volume', methods=['POST'])
def api_set_volume():
    data = request.get_json(force=True)
    loop = data.get('loop')
    vol = max(0.0, min(2.0, float(data.get('volume', 1.0))))
    loop_volumes[loop] = vol
    _, bot_name = loop_states.get(loop, (0, None))
    if bot_name:
        port = bot_pool[bot_name]['port']
        try:
            requests.post(
                f"http://127.0.0.1:{port}/set_volume",
                json={'volume': vol},
                timeout=0.5,
            )
        except Exception:
            pass
    return '', 204

@app.route('/api/command', methods=['POST'])
def command_api():
    data = request.get_json(force=True)
    act = data.get('action')
    loop = data.get('loop')
    if act == 'delay':
        global delay_enabled
        delay_enabled = bool(data.get('enabled'))
        for b in bot_pool.values():
            path = 'delay_on' if delay_enabled else 'delay_off'
            try:
                # send an empty JSON body so bot_server doesn't crash when
                # accessing request.json
                requests.post(
                    f"http://127.0.0.1:{b['port']}/{path}", json={}
                )
            except Exception:
                pass
        return '', 204

    old_state, old_bot = loop_states.get(loop, (0, None))
    if act == 'off':
        if old_bot:
            p = bot_pool[old_bot]['port']
            if delay_enabled:
                requests.post(
                    f"http://127.0.0.1:{p}/leave_after_delay", json={}
                )
            else:
                requests.post(f"http://127.0.0.1:{p}/leave")
                requests.post(f"http://127.0.0.1:{p}/mute")
            bot_pool[old_bot]['assigned'] = None
            bot_pool[old_bot]['last_used'] = time.time()
        loop_states[loop] = (0, None)
        return jsonify(port=None)

    cfg = next((l for l in LOOPS if l['name'] == loop), {})
    new_state = 1 if old_state == 0 else (2 if old_state == 1 and cfg.get('can_talk') else 1)
    if not cfg.get('can_listen'):
        return '', 204

    assigned = old_bot or find_idle_bot()
    if not assigned:
        return jsonify(port=None)
    port = bot_pool[assigned]['port']

    if new_state == 1:
        requests.post(f"http://127.0.0.1:{port}/join", json={'loop': loop})
        requests.post(f"http://127.0.0.1:{port}/set_volume", json={'volume': loop_volumes.get(loop, 1.0)})
        if delay_enabled and old_state == 2:
            requests.post(f"http://127.0.0.1:{port}/mute_after_delay", json={})
        else:
            requests.post(f"http://127.0.0.1:{port}/mute")
    elif new_state == 2:
        for other, (st, ob) in loop_states.items():
            if st == 2 and ob:
                op = bot_pool[ob]['port']
                if delay_enabled:
                    requests.post(f"http://127.0.0.1:{op}/mute_after_delay", json={})
                else:
                    requests.post(f"http://127.0.0.1:{op}/mute")
                loop_states[other] = (1, ob)
        requests.post(f"http://127.0.0.1:{port}/join", json={'loop': loop})
        requests.post(f"http://127.0.0.1:{port}/set_volume", json={'volume': loop_volumes.get(loop, 1.0)})
        requests.post(f"http://127.0.0.1:{port}/talk")

    bot_pool[assigned]['assigned'] = loop
    bot_pool[assigned]['last_used'] = time.time()
    loop_states[loop] = (new_state, assigned)
    return jsonify(port=port)

# ------------------------------ ALARM ------------------------------------
ALARM_BOT_PORT = 6004

@app.route('/api/alarm', methods=['POST'])
def api_alarm():
    for b in bot_pool.values():
        try:
            requests.post(
                f"http://127.0.0.1:{b['port']}/play_alarm", json={}, timeout=1.0
            )
        except Exception:
            pass
    broadcast_port = BOTS[0]['port']
    try:
        requests.post(
            f"http://127.0.0.1:{broadcast_port}/transmit_alarm",
            json={}, timeout=1.0,
        )
    except Exception:
        pass
    try:
        requests.post(
            f"http://127.0.0.1:{ALARM_BOT_PORT}/play_alarm", json={}, timeout=1.0
        )
    except Exception:
        pass
    return '', 204


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--config-only', action='store_true')
    args = parser.parse_args()
    if args.config_only:
        print(f"Running in config-only mode – open http://127.0.0.1:{args.port}/config to set up.")
        app.run(port=args.port, debug=True)
    else:
        app.run(port=args.port, debug=True)
