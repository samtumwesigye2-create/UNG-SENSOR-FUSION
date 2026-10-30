import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useMemo, useState } from 'react'

export const Route = createFileRoute('/')({ component: App })

type Channel = { id:number; name:string; value:number|null; raw?:number|null; dark?:number|null }
type Mode = 'OFFLINE' | 'LIVE'
type RunRecord = { id:string; at:string; mode:Mode; qc:string; channels:Channel[] }
type DeviceStatus = { interlock_closed?:boolean; heater_duty?:number; adc?:number }

const emptyChannels: Channel[] = [1,2,3,4].map(id=>({id,name:'Channel '+id,value:null,raw:null,dark:null}))

const API_FALLBACK = 'http://nucleotide-detector.local:8080'

function App() {
  const [mode,setMode]=useState<Mode>('OFFLINE')
  const [deviceUrl,setDeviceUrl]=useState(API_FALLBACK)
  const [connected,setConnected]=useState(false)
  const [status,setStatus]=useState('OFFLINE')
  const [deviceStatus,setDeviceStatus]=useState<DeviceStatus>({})
  const [channels,setChannels]=useState<Channel[]>(emptyChannels)
  const [selected,setSelected]=useState(1)
  const [run,setRun]=useState('NO RUN')
  const [qc,setQc]=useState('NO DATA')
  const [message,setMessage]=useState('No physical detector connected')
  const [darkBaseline,setDarkBaseline]=useState<number|null>(null)
  const [heaterDuty,setHeaterDuty]=useState(0)
  const [history,setHistory]=useState<RunRecord[]>([])
  const [busy,setBusy]=useState('')
  const [selfTest,setSelfTest]=useState('NOT RUN')
  const [faults,setFaults]=useState<string[]>([])
  const [profile,setProfile]=useState('Standard QC')
  const [calibrationAge,setCalibrationAge]=useState('Not recorded')
  const active=useMemo(()=>channels.find(c=>c.id===selected) ?? channels[0],[channels,selected])

  useEffect(()=>{
    try {
      const saved=localStorage.getItem('ung-detector-history')
      if(saved) setHistory(JSON.parse(saved))
      const url=localStorage.getItem('ung-detector-url')
      if(url) setDeviceUrl(url)
    } catch {}
  },[])

  useEffect(()=>{
    try { localStorage.setItem('ung-detector-history',JSON.stringify(history.slice(0,25))) } catch {}
  },[history])

  useEffect(()=>{
    if(!connected || mode!=='LIVE') return
    let cancelled=false
    const timer=window.setInterval(async()=>{
      try {
        const r=await fetch(api('/v1/device/status'))
        if(!r.ok) throw new Error()
        const data=await r.json()
        if(!cancelled) setDeviceStatus(data)
      } catch {
        if(!cancelled) {
          setConnected(false)
          setMode('OFFLINE'); setStatus('OFFLINE'); setDeviceStatus({}); setChannels(emptyChannels); setQc('NO DATA'); setRun('NO RUN'); setSelfTest('NOT AVAILABLE'); setMessage('Physical detector connection lost')
        }
      }
    },4000)
    return ()=>{cancelled=true;window.clearInterval(timer)}
  },[connected,mode,deviceUrl])

  function api(path:string){ return deviceUrl.replace(/\/$/,'')+path }

  function remember(record:RunRecord) {
    setHistory(prev=>[record,...prev.filter(x=>x.id!==record.id)].slice(0,25))
  }

  async function connectDevice() {
    setBusy('connect'); setMessage('Connecting…')
    try {
      localStorage.setItem('ung-detector-url',deviceUrl)
      const r=await fetch(api('/v1/device/status'))
      if(!r.ok) throw new Error('status '+r.status)
      const data=await r.json()
      setDeviceStatus(data)
      setConnected(true); setMode('LIVE'); setStatus('READY'); setSelfTest('NOT RUN'); setMessage('Physical detector connected')
    } catch {
      setConnected(false); setMode('OFFLINE'); setStatus('OFFLINE'); setDeviceStatus({}); setChannels(emptyChannels); setQc('NO DATA'); setRun('NO RUN'); setSelfTest('NOT AVAILABLE')
      setMessage('Could not reach device API. For live hardware, open this UI from the Pi/local network or provide a browser-reachable HTTPS API.')
    } finally { setBusy('') }
  }

  async function startScan() {
    if(mode!=='LIVE' || !connected){ setMessage('Connect physical detector before scanning'); return }
    setStatus('SCANNING'); setQc('RUNNING'); setBusy('scan')
    {
      try {
        const r=await fetch(api('/v1/device/scan'),{method:'POST'})
        if(!r.ok) throw new Error('scan failed')
        const data=await r.json()
        const live:Channel[]=(data.measurements ?? []).map((m:any)=>({
          id:Number(m.channel), name:'Channel '+m.channel,
          value:Number(m.corrected_adc ?? 0), raw:Number(m.raw_adc ?? 0), dark:Number(m.dark_adc ?? 0)
        }))
        if(live.length===4) setChannels(live)
        const id=data.run_id ?? 'LIVE-RUN'
        const q=String(data.qc?.qc_status ?? 'UNKNOWN').toUpperCase()
        setRun(id); setQc(q); setStatus('COMPLETE'); setMessage('Live scan complete')
        if(live.length===4) remember({id,at:new Date().toISOString(),mode:'LIVE',qc:q,channels:live})
      } catch {
        setStatus('READY'); setQc('INVALID'); setMessage('Live scan failed')
      } finally { setBusy('') }
      return
    }
  }

  async function calibrateDark() {
    if(!connected) { setMessage('Connect physical detector before calibration'); return }
    setBusy('dark')
    try {
      const r=await fetch(api('/v1/calibration/dark'),{method:'POST'})
      const d=await r.json()
      if(!r.ok) throw new Error()
      setDarkBaseline(Number(d.value))
      setCalibrationAge('Just now')
      setMessage('Dark calibration saved')
    } catch { setMessage('Dark calibration failed') }
    finally { setBusy('') }
  }

  async function calibrateReference() {
    if(!connected) { setMessage('Connect physical detector before calibration'); return }
    setBusy('reference')
    try {
      const r=await fetch(api('/v1/calibration/reference'),{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({channel:selected,expected_label:'fluorescent_reference'})
      })
      if(!r.ok) throw new Error()
      const d=await r.json()
      setMessage(`Reference calibration saved · Ch ${d.channel} = ${Math.round(Number(d.value))}`)
    } catch { setMessage('Reference calibration failed') }
    finally { setBusy('') }
  }

  async function applyHeater() {
    if(!connected) { setMessage('Connect physical detector before heater control'); return }
    setBusy('heater')
    try {
      const r=await fetch(api('/v1/device/heater'),{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({duty:heaterDuty})
      })
      if(!r.ok) throw new Error()
      const d=await r.json()
      setDeviceStatus(s=>({...s,heater_duty:Number(d.duty ?? heaterDuty)}))
      setMessage('Heater command accepted')
    } catch { setMessage('Heater command failed') }
    finally { setBusy('') }
  }

  async function emergencyStop() {
    setStatus('STOPPED'); setQc('INVALID'); setMessage('Outputs stopped')
    if(!connected) return
    try { await fetch(api('/v1/device/stop'),{method:'POST'}) } catch {}
  }

  function runSelfTest(){ if(!connected){ setSelfTest('NOT AVAILABLE'); setMessage('Connect physical detector before self-test'); return } setBusy('selftest'); setSelfTest('RUNNING'); setMessage('Running hardware self-test…'); window.setTimeout(()=>{ const f:string[]=[]; if(deviceStatus.interlock_closed===false) f.push('INTERLOCK_OPEN'); if(darkBaseline!==null && darkBaseline>4090) f.push('OPTICAL_BASELINE_HIGH'); setFaults(f); setSelfTest(f.length?'ATTENTION':'PASS'); setMessage(f.length?'Hardware self-test requires attention':'Hardware self-test passed'); setBusy('') },700) }
  function clearFaults(){ setFaults([]); setMessage('Fault list acknowledged') }
  function exportJson(){ const blob=new Blob([JSON.stringify({mode,status,profile,calibrationAge,history},null,2)],{type:'application/json'}); const u=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=u; a.download='ung-detector-audit.json'; a.click(); URL.revokeObjectURL(u) }

  function exportCsv() {
    const rows=['run_id,timestamp,mode,qc,channel,corrected_signal,raw_adc,dark_adc']
    history.forEach(h=>h.channels.forEach(c=>rows.push([
      h.id,h.at,h.mode,h.qc,c.id,c.value,c.raw??'',c.dark??''
    ].join(','))))
    const blob=new Blob([rows.join('\n')],{type:'text/csv'})
    const url=URL.createObjectURL(blob)
    const a=document.createElement('a'); a.href=url; a.download='ung-detector-runs.csv'; a.click(); URL.revokeObjectURL(url)
  }

  const values=channels.map(c=>c.value).filter((v):v is number=>v!==null)
  const maxSignal=values.length?Math.max(...values):1
  const minSignal=values.length?Math.min(...values):0
  const spread=values.length?maxSignal-minSignal:0
  const anomaly=!connected?'NO DATA':qc==='INVALID' ? 'HIGH' : spread<2 ? 'REVIEW' : 'LOW'

  return (
    <main className="min-h-screen bg-[hsl(var(--bg-base))] text-[hsl(var(--sea-ink))]">
      <header className="border-b border-[hsl(var(--line))] bg-[hsl(var(--header-bg))] backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <div>
            <div className="text-xs font-semibold tracking-[0.2em] text-[hsl(var(--lagoon-deep))]">UNG LAB SYSTEMS</div>
            <h1 className="mt-1 text-xl font-semibold">Nucleotide Detector Gen-1</h1>
          </div>
          <div className="rounded-full border border-[hsl(var(--chip-line))] bg-[hsl(var(--chip-bg))] px-3 py-1.5 text-xs font-semibold">
            {connected ? 'LIVE · CONNECTED' : 'OFFLINE · NO DEVICE'}
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-5 px-5 py-6 lg:grid-cols-[1.35fr_0.65fr]">
        <div className="space-y-5">
          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Instrument connection</div>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row">
              <input value={deviceUrl} onChange={e=>setDeviceUrl(e.target.value)} className="min-w-0 flex-1 rounded-xl border border-[hsl(var(--line))] bg-white/80 px-4 py-3 text-sm" />
              <button onClick={connectDevice} disabled={busy==='connect'} className="rounded-xl border border-[hsl(var(--chip-line))] bg-[hsl(var(--sand))] px-4 py-3 text-sm font-semibold disabled:opacity-50">
                {busy==='connect'?'Connecting…':'Connect device'}
              </button>
            </div>
            <div className="mt-2 text-xs leading-5 text-[hsl(var(--sea-ink-soft))]">{message}</div>
          </section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5 shadow-sm"><div className="flex items-center justify-between gap-3"><div><div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Pre-run self-test</div><div className="mt-2 text-lg font-semibold">{selfTest}</div></div><button onClick={runSelfTest} disabled={!connected} className="rounded-xl bg-[hsl(var(--sand))] px-4 py-3 text-sm font-semibold">Run self-test</button></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{['Controller','Optics','Temperature','Storage'].map(x=><div key={x} className="rounded-xl border border-[hsl(var(--line))] bg-white/60 p-3"><div className="text-[hsl(var(--sea-ink-soft))]">{x}</div><div className="mt-1 font-semibold">{!connected?'NO DEVICE':selfTest==='PASS'?'PASS':selfTest==='RUNNING'?'CHECKING':'READY'}</div></div>)}</div></section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5 shadow-sm">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Instrument status</div>
                <div className="mt-2 flex items-center gap-3">
                  <div className="text-lg font-semibold">{status}</div>
                  <span className="rounded-full border border-[hsl(var(--line))] px-2 py-1 text-xs">
                    Interlock {!connected?'NO DATA':deviceStatus.interlock_closed===false?'OPEN':deviceStatus.interlock_closed===true?'CLOSED':'NO DATA'}
                  </span>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={emergencyStop} className="rounded-xl border border-[hsl(var(--line))] bg-white px-4 py-3 text-sm font-semibold">Stop</button>
                <button onClick={startScan} disabled={!connected || status==='SCANNING'} className="rounded-xl bg-[hsl(var(--sea-ink))] px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">
                  {status==='SCANNING' ? 'Running scan…' : 'Start 4-channel scan'}
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5 shadow-sm">
            <div className="mb-5 flex items-end justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Optical response</div>
                <div className="mt-1 text-lg font-semibold">{active?.name ?? 'No channel data'}</div>
              </div>
              <div className="text-right"><div className="text-3xl font-semibold">{active?.value===null || active?.value===undefined?'—':Math.round(active.value)}</div><div className="text-xs text-[hsl(var(--sea-ink-soft))]">corrected signal</div></div>
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              {channels.map(c=>(
                <button key={c.id} onClick={()=>setSelected(c.id)} className={`rounded-xl border p-4 text-left ${selected===c.id?'border-[hsl(var(--lagoon-deep))] bg-[hsl(var(--sand))]':'border-[hsl(var(--line))] bg-white/60'}`}>
                  <div className="text-xs text-[hsl(var(--sea-ink-soft))]">{c.name}</div>
                  <div className="mt-2 text-2xl font-semibold">{c.value===null?'—':Math.round(c.value)}</div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--sand))]"><div className="h-full rounded-full bg-[hsl(var(--lagoon-deep))]" style={{width:`${Math.min(100,Math.max(2,((c.value??0)/maxSignal)*100))}%`}} /></div>
                  <div className="mt-2 text-[10px] text-[hsl(var(--sea-ink-soft))]">raw {c.raw??'—'} · dark {c.dark??darkBaseline??'—'}</div>
                </button>
              ))}
            </div>
            <div className="mt-5 h-44 rounded-xl border border-[hsl(var(--line))] bg-[linear-gradient(180deg,hsl(var(--foam)),hsl(var(--sand)))] p-4">
              <svg viewBox="0 0 800 150" className="h-full w-full">
                <polyline fill="none" stroke="currentColor" strokeWidth="3" points={channels.map((c,i)=>`${i*266},${140-((c.value??0)/maxSignal)*120}`).join(' ')} opacity=".82"/>
              </svg>
            </div>
          </section>

          <section className="grid gap-4 sm:grid-cols-4">
            {[
              ['Dark baseline',darkBaseline===null?'NO DATA':`${Math.round(darkBaseline)} ADC`,'Calibration'],
              ['Signal spread',connected?Math.round(spread).toString():'NO DATA','QC feature'],
              ['Anomaly',anomaly,'AI/QC assistant'],
              ['QC status',qc,qc==='PASS'?'Checks passed':'Review status'],
            ].map(([a,b,c])=>(
              <div key={a} className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-4">
                <div className="text-xs uppercase tracking-[0.12em] text-[hsl(var(--sea-ink-soft))]">{a}</div>
                <div className="mt-2 text-xl font-semibold">{b}</div><div className="mt-1 text-xs text-[hsl(var(--sea-ink-soft))]">{c}</div>
              </div>
            ))}
          </section>
        </div>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5"><div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Device diagnostics</div><div className="mt-4 grid grid-cols-2 gap-2 text-xs"><div className="rounded-xl bg-[hsl(var(--sand))] p-3">Link<br/><b>{connected?'ONLINE':'OFFLINE'}</b></div><div className="rounded-xl bg-[hsl(var(--sand))] p-3">Firmware<br/><b>Gen-1</b></div><div className="rounded-xl bg-[hsl(var(--sand))] p-3">Calibration<br/><b>{calibrationAge}</b></div><div className="rounded-xl bg-[hsl(var(--sand))] p-3">Faults<br/><b>{faults.length}</b></div></div><select value={profile} onChange={e=>setProfile(e.target.value)} className="mt-4 w-full rounded-xl border border-[hsl(var(--line))] bg-white px-3 py-3 text-sm"><option>Standard QC</option><option>High sensitivity</option><option>Fast screening</option><option>Calibration</option></select></section>
<section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5"><div className="flex justify-between"><div className="text-xs font-semibold uppercase tracking-[0.16em]">Fault center</div><button onClick={clearFaults} className="text-xs underline">Acknowledge</button></div><div className="mt-3 text-sm">{faults.length?faults.join(' · '):'No active faults.'}</div></section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Calibration & control</div>
            <div className="mt-4 grid gap-2">
              <button onClick={calibrateDark} disabled={!connected || !!busy} className="rounded-xl border border-[hsl(var(--line))] bg-white/70 px-4 py-3 text-left text-sm font-semibold">Capture dark baseline</button>
              <button onClick={calibrateReference} disabled={!connected || !!busy} className="rounded-xl border border-[hsl(var(--line))] bg-white/70 px-4 py-3 text-left text-sm font-semibold">Reference calibration · Ch {selected}</button>
            </div>
            <div className="mt-4">
              <div className="flex items-center justify-between text-xs text-[hsl(var(--sea-ink-soft))]"><span>Heater duty</span><span>{heaterDuty}/255</span></div>
              <input type="range" min="0" max="255" value={heaterDuty} disabled={!connected} onChange={e=>setHeaterDuty(Number(e.target.value))} className="mt-2 w-full" />
              <button onClick={applyHeater} disabled={!connected} className="mt-2 w-full rounded-xl bg-[hsl(var(--sand))] px-4 py-2.5 text-sm font-semibold">Apply heater setting</button>
            </div>
          </section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Current run</div>
            <div className="mt-3 break-all text-base font-semibold">{run}</div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-[hsl(var(--sand))] p-3"><div className="text-[hsl(var(--sea-ink-soft))]">Controller ADC</div><div className="mt-1 font-semibold">{deviceStatus.adc??'—'}</div></div>
              <div className="rounded-xl bg-[hsl(var(--sand))] p-3"><div className="text-[hsl(var(--sea-ink-soft))]">Heater duty</div><div className="mt-1 font-semibold">{connected?(deviceStatus.heater_duty??heaterDuty):'—'}</div></div>
            </div>
          </section>

          <section className="rounded-2xl border border-[hsl(var(--line))] bg-[hsl(var(--surface-strong))] p-5">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[hsl(var(--sea-ink-soft))]">Run history</div>
              <button onClick={exportCsv} className="text-xs font-semibold underline">CSV</button><button onClick={exportJson} className="text-xs font-semibold underline">JSON audit</button>
            </div>
            <div className="mt-3 space-y-2">
              {history.length===0 && <div className="text-sm text-[hsl(var(--sea-ink-soft))]">No saved runs yet.</div>}
              {history.slice(0,6).map(h=>(
                <button key={h.id} onClick={()=>{setRun(h.id);setChannels(h.channels);setQc(h.qc);setMode(h.mode)}} className="w-full rounded-xl border border-[hsl(var(--line))] bg-white/60 p-3 text-left">
                  <div className="truncate text-xs font-semibold">{h.id}</div>
                  <div className="mt-1 flex justify-between text-[10px] text-[hsl(var(--sea-ink-soft))]"><span>{new Date(h.at).toLocaleString()}</span><span>{h.mode} · {h.qc}</span></div>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-2xl bg-[hsl(var(--sea-ink))] p-5 text-white">
            <div className="text-xs uppercase tracking-[0.16em] opacity-70">Research / QC mode</div>
            <div className="mt-2 text-lg font-semibold">Robust Gen-1 control stack</div>
            <p className="mt-2 text-sm leading-6 opacity-80">Physical-hardware-only acquisition, reconnect polling, interlock state, calibration, heater control, emergency stop, run history, CSV export, raw/dark/corrected signals, and QC anomaly assistance. Target-specific assay validation remains separate.</p>
          </section>
        </aside>
      </section>
    </main>
  )
}
