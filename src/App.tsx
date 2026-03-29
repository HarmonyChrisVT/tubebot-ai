import { useState, useEffect } from 'react'
import {
  TrendingUp, FileText, Mic, Video, Image, Search,
  Upload, BarChart2, Play, Pause, Youtube, Zap,
  CheckCircle, AlertCircle, Clock, RefreshCw
} from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────
interface AgentInfo { running: boolean; last_run?: string }
interface SystemStatus {
  running: boolean
  agents: Record<string, AgentInfo>
}
interface PipelineStats { [status: string]: number }
interface Project {
  id: number; topic: string; status: string; trend_score: number
  yt_title?: string; yt_video_id?: string; yt_url?: string
  views: number; ctr: number; created_at: string; published_at?: string
}
interface LogEntry {
  agent: string; action: string; status: string
  message: string; project_id?: number; time: string
}

// ── Agent config ───────────────────────────────────────────────────────────
const AGENTS = [
  { key: 'trend',     label: 'Trend Agent',     icon: TrendingUp, color: 'from-violet-500 to-purple-600',
    desc: 'Scans trending senior health & Medicare topics daily' },
  { key: 'script',    label: 'Script Agent',    icon: FileText,   color: 'from-blue-500 to-blue-600',
    desc: 'Writes 8–10 min scripts with GPT-4' },
  { key: 'voice',     label: 'Voice Agent',     icon: Mic,        color: 'from-sky-500 to-cyan-500',
    desc: 'Generates voiceover via edge-tts (free)' },
  { key: 'video',     label: 'Video Agent',     icon: Video,      color: 'from-pink-500 to-rose-500',
    desc: 'Assembles video via Pictory API' },
  { key: 'thumbnail', label: 'Thumbnail Agent', icon: Image,      color: 'from-orange-500 to-amber-500',
    desc: 'Creates thumbnails with DALL-E 3' },
  { key: 'seo',       label: 'SEO Agent',       icon: Search,     color: 'from-green-500 to-emerald-500',
    desc: 'Writes titles, descriptions & tags' },
  { key: 'upload',    label: 'Upload Agent',    icon: Upload,     color: 'from-teal-500 to-teal-600',
    desc: 'Schedules & uploads to YouTube API' },
  { key: 'analytics', label: 'Analytics Agent', icon: BarChart2,  color: 'from-red-500 to-rose-600',
    desc: 'Monitors performance & feeds back to Trend Agent' },
]

const PIPELINE_ORDER = [
  'trending', 'scripted', 'voiced', 'thumbnailed', 'seod', 'rendered', 'uploaded', 'failed'
]
const PIPELINE_LABELS: Record<string, string> = {
  trending: 'Trending', scripted: 'Scripted', voiced: 'Voiced',
  thumbnailed: 'Thumbnailed', seod: 'SEO Done', rendered: 'Rendered',
  uploaded: 'Uploaded', failed: 'Failed',
}
const PIPELINE_COLORS: Record<string, string> = {
  trending: 'bg-violet-100 text-violet-700', scripted: 'bg-blue-100 text-blue-700',
  voiced: 'bg-sky-100 text-sky-700', thumbnailed: 'bg-orange-100 text-orange-700',
  seod: 'bg-green-100 text-green-700', rendered: 'bg-pink-100 text-pink-700',
  uploaded: 'bg-emerald-100 text-emerald-700', failed: 'bg-red-100 text-red-700',
}

// ── Components ─────────────────────────────────────────────────────────────
function AgentCard({ agent, info }: { agent: typeof AGENTS[0]; info?: AgentInfo }) {
  const Icon = agent.icon
  const running = info?.running ?? false
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className={`p-2 rounded-lg bg-gradient-to-br ${agent.color}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
        <span className={`text-xs font-medium px-2 py-1 rounded-full ${
          running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
        }`}>
          {running ? '● Running' : '○ Idle'}
        </span>
      </div>
      <h3 className="font-semibold text-sm text-gray-900">{agent.label}</h3>
      <p className="text-xs text-gray-500 mt-1">{agent.desc}</p>
      {info?.last_run && (
        <p className="text-xs text-gray-400 mt-2">Last run: {new Date(info.last_run).toLocaleTimeString()}</p>
      )}
    </div>
  )
}

function PipelineBadge({ status, count }: { status: string; count: number }) {
  return (
    <div className={`flex flex-col items-center p-3 rounded-lg ${PIPELINE_COLORS[status] ?? 'bg-gray-100 text-gray-600'}`}>
      <span className="text-2xl font-bold">{count}</span>
      <span className="text-xs font-medium mt-1">{PIPELINE_LABELS[status] ?? status}</span>
    </div>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return ok
    ? <CheckCircle className="w-4 h-4 text-green-500 inline mr-1" />
    : <AlertCircle className="w-4 h-4 text-gray-400 inline mr-1" />
}

// ── App ────────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState<'dashboard' | 'agents' | 'projects' | 'logs'>('dashboard')
  const [status, setStatus]     = useState<SystemStatus | null>(null)
  const [pipeline, setPipeline] = useState<PipelineStats>({})
  const [projects, setProjects] = useState<Project[]>([])
  const [logs, setLogs]         = useState<LogEntry[]>([])
  const [loading, setLoading]   = useState(true)

  async function fetchAll() {
    try {
      const [s, p, pr, l] = await Promise.all([
        fetch('/api/status').then(r => r.json()),
        fetch('/api/pipeline').then(r => r.json()),
        fetch('/api/projects?limit=20').then(r => r.json()),
        fetch('/api/logs?limit=50').then(r => r.json()),
      ])
      setStatus(s); setPipeline(p); setProjects(pr); setLogs(l)
    } catch {
      // backend not yet reachable
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 10000)
    return () => clearInterval(interval)
  }, [])

  const totalUploaded = pipeline['uploaded'] ?? 0
  const totalProjects = Object.values(pipeline).reduce((a, b) => a + b, 0)
  const activeAgents  = status ? Object.values(status.agents).filter(a => a.running).length : 0

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-red-500 to-rose-600 rounded-xl">
              <Youtube className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">TubeBot AI</h1>
              <p className="text-xs text-gray-500">Automated Faceless YouTube Channel</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className={`flex items-center gap-1 text-sm font-medium px-3 py-1 rounded-full ${
              status?.running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {status?.running ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
              {status?.running ? 'System Active' : 'Starting…'}
            </span>
            <button onClick={fetchAll}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Nav */}
      <div className="bg-white border-b border-gray-200 px-6">
        <div className="max-w-7xl mx-auto flex gap-6">
          {(['dashboard', 'agents', 'projects', 'logs'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`py-3 text-sm font-medium border-b-2 capitalize transition-colors ${
                tab === t ? 'border-red-500 text-red-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-6 py-6">

        {/* ── Dashboard ── */}
        {tab === 'dashboard' && (
          <div className="space-y-6">
            {/* Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Videos Uploaded', value: totalUploaded, icon: Youtube, color: 'text-red-500' },
                { label: 'Total Projects', value: totalProjects, icon: Zap, color: 'text-violet-500' },
                { label: 'Active Agents', value: activeAgents, icon: Play, color: 'text-green-500' },
                { label: 'In Pipeline', value: totalProjects - totalUploaded, icon: Clock, color: 'text-blue-500' },
              ].map(({ label, value, icon: Icon, color }) => (
                <div key={label} className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-sm text-gray-500">{label}</p>
                      <p className="text-3xl font-bold text-gray-900 mt-1">{loading ? '–' : value}</p>
                    </div>
                    <Icon className={`w-6 h-6 ${color}`} />
                  </div>
                </div>
              ))}
            </div>

            {/* Pipeline */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <h2 className="font-semibold text-gray-900 mb-4">Video Pipeline</h2>
              <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
                {PIPELINE_ORDER.map(s => (
                  <PipelineBadge key={s} status={s} count={pipeline[s] ?? 0} />
                ))}
              </div>
            </div>

            {/* Agent grid */}
            <div>
              <h2 className="font-semibold text-gray-900 mb-3">Agents</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {AGENTS.map(a => (
                  <AgentCard key={a.key} agent={a} info={status?.agents[a.key]} />
                ))}
              </div>
            </div>

            {/* Recent activity */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <h2 className="font-semibold text-gray-900 mb-3">Recent Activity</h2>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {logs.slice(0, 15).map((log, i) => (
                  <div key={i} className="flex items-start gap-3 text-sm p-2 rounded-lg hover:bg-gray-50">
                    <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                      log.status === 'success' ? 'bg-green-500' : log.status === 'error' ? 'bg-red-500' : 'bg-blue-500'
                    }`} />
                    <span className="text-xs text-gray-400 w-24 shrink-0">
                      {log.time ? new Date(log.time).toLocaleTimeString() : '—'}
                    </span>
                    <span className="text-xs font-medium text-gray-600 w-28 shrink-0">{log.agent}</span>
                    <span className="text-gray-700 text-xs">{log.message}</span>
                  </div>
                ))}
                {logs.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-4">No activity yet — agents are starting up</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Agents tab ── */}
        {tab === 'agents' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {AGENTS.map(a => {
              const Icon = a.icon
              const info = status?.agents[a.key]
              return (
                <div key={a.key} className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={`p-2.5 rounded-lg bg-gradient-to-br ${a.color}`}>
                      <Icon className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-gray-900">{a.label}</h3>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          info?.running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {info?.running ? 'Running' : 'Idle'}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500">{a.desc}</p>
                    </div>
                  </div>
                  <div className="border-t border-gray-100 pt-3 text-xs text-gray-500">
                    {info?.last_run
                      ? `Last run: ${new Date(info.last_run).toLocaleString()}`
                      : 'Not yet run this session'}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── Projects tab ── */}
        {tab === 'projects' && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {['ID', 'Topic', 'Status', 'Score', 'Title', 'Views', 'CTR', 'Created'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {projects.map(p => (
                  <tr key={p.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-400">#{p.id}</td>
                    <td className="px-4 py-3 max-w-xs truncate text-gray-700">{p.topic}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PIPELINE_COLORS[p.status] ?? 'bg-gray-100 text-gray-600'}`}>
                        {PIPELINE_LABELS[p.status] ?? p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{(p.trend_score * 100).toFixed(0)}%</td>
                    <td className="px-4 py-3 max-w-xs truncate text-gray-700">
                      {p.yt_url
                        ? <a href={p.yt_url} target="_blank" rel="noreferrer" className="text-red-500 hover:underline">{p.yt_title}</a>
                        : <span className="text-gray-400">{p.yt_title ?? '—'}</span>}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{p.views ?? 0}</td>
                    <td className="px-4 py-3 text-gray-500">{p.ctr ? `${(p.ctr * 100).toFixed(1)}%` : '—'}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {p.created_at ? new Date(p.created_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
                {projects.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No projects yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Logs tab ── */}
        {tab === 'logs' && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
            {logs.map((log, i) => (
              <div key={i} className="flex items-start gap-4 px-5 py-3 hover:bg-gray-50">
                <span className={`w-2 h-2 rounded-full mt-2 shrink-0 ${
                  log.status === 'success' ? 'bg-green-500' : log.status === 'error' ? 'bg-red-500' : 'bg-blue-400'
                }`} />
                <span className="text-xs text-gray-400 w-36 shrink-0 pt-0.5">
                  {log.time ? new Date(log.time).toLocaleString() : '—'}
                </span>
                <span className="text-xs font-semibold text-gray-600 w-36 shrink-0 pt-0.5">{log.agent}</span>
                <span className="text-sm text-gray-700">{log.message}</span>
              </div>
            ))}
            {logs.length === 0 && (
              <p className="text-center py-8 text-gray-400 text-sm">No logs yet</p>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
