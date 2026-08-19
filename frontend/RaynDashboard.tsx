/**
 * RAYN.AI — Autonomous Talent Intelligence
 * Single-file candidate sourcing dashboard. Drop it into any React 18+ app
 * (Next.js App Router or Vite) — no Tailwind config, no CSS file, no context.
 *
 *   npm i lucide-react framer-motion
 *
 * Next.js App Router: this is a client component ("use client" below).
 * Vite: delete the "use client" line.
 *
 * Every colour is a literal Tailwind class, so there is nothing to wire up.
 * State is local and fully interactive — swap the handlers at the bottom of
 * `RaynDashboard` for your API calls.
 */
'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle, BarChart3, Bell, Bookmark, Briefcase, Check, ChevronDown, Command, FileText,
  Github, Globe, Layers, Link2, Loader2, Minus, Moon, Paperclip, Plus, Rocket, Search, Send,
  Settings, SlidersHorizontal, Sparkles, Sun, Target, TrendingUp, Upload, X, Zap,
  type LucideIcon,
} from 'lucide-react';

/* ═══════════════════════════ types ═══════════════════════════ */

type Mode = 'dark' | 'light';
type StudioTab = 'prompt' | 'document' | 'url';
type SourceId = 'linkedin' | 'indeed' | 'wellfound' | 'github';

export interface AttachedFile {
  name: string;
  /** size in bytes */
  size: number;
}

export interface LaunchConfig {
  prompt: string;
  perPlatform: number;
  platforms: SourceId[];
  targetTitle: string;
  seniority: string;
  semanticScoring: boolean;
  careerRoadmap: boolean;
  estimatedCost: number;
}

export interface RaynDashboardProps {
  /** Fired when the dock CTA is pressed. Return a promise to drive the busy state. */
  onLaunch?: (config: LaunchConfig) => void | Promise<void>;
  /** Fired by the ✨ Auto-Extract button. Resolve with the detected role title. */
  onAutoExtract?: (prompt: string) => Promise<string | void>;
  /** Remaining compute credits, in dollars. */
  credits?: number;
  /** Total plan budget, used for the credits meter. */
  budget?: number;
  defaultMode?: Mode;
}

/* ═══════════════════════════ constants ═══════════════════════════ */

const COST_PER_PROFILE = 0.0026;
const MIN_PER_PLATFORM = 10;
const MAX_PER_PLATFORM = 50;
const STEP = 5;
const SECONDS_PER_PLATFORM = 30;

const NAV: { id: string; label: string; Icon: LucideIcon; badge?: number }[] = [
  { id: 'overview', label: 'Overview', Icon: BarChart3 },
  { id: 'new', label: 'New Search', Icon: Sparkles },
  { id: 'pipeline', label: 'Pipeline', Icon: Layers },
  { id: 'pool', label: 'Talent Pool', Icon: Target },
  { id: 'saved', label: 'Saved Matches', Icon: Bookmark, badge: 12 },
  { id: 'outreach', label: 'Outreach', Icon: Send, badge: 3 },
  { id: 'analytics', label: 'Analytics', Icon: TrendingUp },
  { id: 'settings', label: 'Settings', Icon: Settings },
];

const SOURCES: { id: SourceId; label: string; Icon: LucideIcon }[] = [
  { id: 'linkedin', label: 'LinkedIn', Icon: Briefcase },
  { id: 'indeed', label: 'Indeed', Icon: Search },
  { id: 'wellfound', label: 'Wellfound', Icon: Globe },
  { id: 'github', label: 'GitHub', Icon: Github },
];

const STUDIO_TABS: { id: StudioTab; label: string; Icon: LucideIcon }[] = [
  { id: 'prompt', label: 'Prompt Studio', Icon: Sparkles },
  { id: 'document', label: 'Document / Resume Drop', Icon: FileText },
  { id: 'url', label: 'Job Posting URL', Icon: Link2 },
];

const SENIORITY = ['Any level', 'Junior', 'Mid-level', 'Senior', 'Lead / Staff', 'Principal'];

const MODELS = [
  { id: 'deepseek-v4-pro', label: 'DeepSeek-v4-Pro', hint: 'Balanced reasoning · default' },
  { id: 'claude-sonnet-5', label: 'Claude Sonnet 5', hint: 'Highest ranking accuracy' },
  { id: 'gpt-5-mini', label: 'GPT-5 mini', hint: 'Fastest, lowest cost' },
];

const SAMPLE_JD = `Senior Backend Engineer — Bengaluru (Hybrid)

We are hiring a Senior Backend Engineer with 5+ years of experience building REST APIs at scale.

Must have: Python, FastAPI, PostgreSQL, AWS, Redis, Kafka, Docker.
Nice to have: Kubernetes, event-driven architecture, observability tooling.

You will own service design, drive code reviews, and mentor two junior engineers.`;

/* ═══════════════════════════ theme tokens ═══════════════════════════ */

/* One flat map per mode. Components read `t.card`, never a raw hex — so a
   palette change stays a one-line edit instead of a find-and-replace. */
const TOKENS = {
  dark: {
    shell: 'bg-[#0B0F17] bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-950/40 via-[#0B0F17] to-[#0B0F17]',
    rail: 'bg-[#0A0E16]/70 border-white/10',
    bar: 'bg-[#0B0F17]/70 border-white/10',
    card: 'bg-[#111625]/80 border-white/10 hover:border-indigo-500/40',
    dock: 'bg-[#111625]/90 border-white/10',
    inner: 'bg-white/[0.03] border-white/10',
    input: 'bg-[#0B0F17]/70 border-white/10 text-slate-100 placeholder:text-slate-500',
    hover: 'hover:bg-white/[0.06]',
    title: 'text-slate-50',
    titleHover: 'hover:text-slate-50',
    placeholder: 'placeholder:text-slate-500',
    body: 'text-slate-300',
    muted: 'text-slate-400',
    faint: 'text-slate-500',
    chip: 'border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/25',
    chipOn: 'border-indigo-400/40 bg-indigo-500/15 text-indigo-200',
    track: 'bg-white/10',
    divide: 'border-white/10',
  },
  light: {
    shell: 'bg-slate-50 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-100 via-slate-50 to-slate-50',
    rail: 'bg-white/80 border-slate-200',
    bar: 'bg-white/70 border-slate-200',
    card: 'bg-white/85 border-slate-200 hover:border-indigo-300',
    dock: 'bg-white/90 border-slate-200',
    inner: 'bg-slate-50 border-slate-200',
    input: 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400',
    hover: 'hover:bg-slate-100',
    title: 'text-slate-900',
    titleHover: 'hover:text-slate-900',
    placeholder: 'placeholder:text-slate-400',
    body: 'text-slate-700',
    muted: 'text-slate-500',
    faint: 'text-slate-400',
    chip: 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
    chipOn: 'border-indigo-300 bg-indigo-50 text-indigo-700',
    track: 'bg-slate-200',
    divide: 'border-slate-200',
  },
} as const;

type Tokens = (typeof TOKENS)[Mode];

const ACCENT = 'bg-gradient-to-br from-indigo-500 via-purple-500 to-indigo-600';
const GLOW = 'shadow-[0_10px_34px_-12px_rgba(99,102,241,0.65)]';
const RING = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent';

/* ═══════════════════════════ helpers ═══════════════════════════ */

const fmtBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1_048_576 ? `${Math.round(n / 1024)} KB` : `${(n / 1_048_576).toFixed(1)} MB`;

/* ═══════════════════════════ primitives ═══════════════════════════ */

/* Prism mark — the logo lives here so the rail and any future splash screen
   can never drift apart. */
function RaynMark({ size = 34 }: { size?: number }) {
  return (
    <span
      aria-hidden
      style={{ height: size, width: size }}
      className={`relative grid shrink-0 place-items-center rounded-xl ${ACCENT} ${GLOW}`}
    >
      <Sparkles size={Math.round(size * 0.52)} strokeWidth={2.4} className="relative z-10 text-white" />
      <span className="absolute inset-0 rounded-xl bg-gradient-to-b from-white/30 to-transparent" />
    </span>
  );
}

/* iOS / Linear style switch. Emerald when on, and the knob carries a check —
   so the state never depends on colour alone. */
function Switch({
  id, on, onChange, disabled, describedBy, t,
}: {
  id: string; on: boolean; onChange: (next: boolean) => void;
  disabled?: boolean; describedBy?: string; t: Tokens;
}) {
  return (
    <button
      type="button" role="switch" aria-checked={on} id={id} aria-describedby={describedBy}
      disabled={disabled} onClick={() => onChange(!on)}
      className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors duration-200 disabled:opacity-50 ${RING} ${
        on ? 'border-emerald-500 bg-emerald-500' : `border-slate-400/60 ${t.track}`
      }`}
    >
      <motion.span
        layout transition={{ type: 'spring', stiffness: 700, damping: 38 }}
        className={`absolute top-[2px] grid h-[18px] w-[18px] place-items-center rounded-full bg-white shadow ${
          on ? 'left-[22px]' : 'left-[2px]'
        }`}
      >
        {on
          ? <Check size={11} strokeWidth={3.5} aria-hidden className="text-emerald-600" />
          : <X size={10} strokeWidth={3} aria-hidden className="text-slate-400" />}
      </motion.span>
    </button>
  );
}

function StatusBadge({ on }: { on: boolean }) {
  return on ? (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-500">
      <Check size={11} strokeWidth={3} aria-hidden /> Enabled
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-400/30 bg-slate-400/10 px-2 py-0.5 text-xs font-semibold text-slate-400">
      <X size={11} strokeWidth={3} aria-hidden /> Disabled
    </span>
  );
}

/* Segmented control — the active pill slides between options via layoutId. */
function SegmentedTabs<T extends string>({
  tabs, value, onChange, groupId, t,
}: {
  tabs: { id: T; label: string; Icon: LucideIcon }[];
  value: T; onChange: (id: T) => void; groupId: string; t: Tokens;
}) {
  return (
    <div role="tablist" aria-label="Input mode"
         className={`flex gap-1 overflow-x-auto rounded-xl border p-1 ${t.inner}`}>
      {tabs.map(({ id, label, Icon }) => {
        const active = value === id;
        return (
          <button
            key={id} type="button" role="tab" aria-selected={active} onClick={() => onChange(id)}
            className={`relative flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors ${RING} ${
              active ? 'font-semibold text-white' : `font-medium ${t.muted} ${t.titleHover}`
            }`}
          >
            {active && (
              <motion.span
                aria-hidden layoutId={`${groupId}-segment`}
                transition={{ type: 'spring', stiffness: 460, damping: 36 }}
                className={`absolute inset-0 rounded-lg ${ACCENT} ${GLOW}`}
              />
            )}
            <Icon size={14} aria-hidden className="relative z-10" />
            <span className="relative z-10 whitespace-nowrap">{label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════ sidebar ═══════════════════════════ */

function Sidebar({
  view, setView, collapsed, setCollapsed, credits, budget, t,
}: {
  view: string; setView: (id: string) => void;
  collapsed: boolean; setCollapsed: (next: boolean) => void;
  credits: number; budget: number; t: Tokens;
}) {
  const pct = Math.max(0, Math.min(100, (credits / budget) * 100));
  const low = credits < 1;

  return (
    <aside
      className={`relative flex h-full shrink-0 flex-col border-r backdrop-blur-xl transition-[width] duration-300 ease-out ${t.rail} ${
        collapsed ? 'w-[76px]' : 'w-[248px]'
      }`}
    >
      {/* ── brand ── */}
      <div className={`flex h-16 shrink-0 items-center gap-2.5 ${collapsed ? 'justify-center' : 'px-4'}`}>
        <RaynMark size={collapsed ? 34 : 32} />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-base font-bold tracking-tight text-transparent">
              RAYN.AI
            </p>
            <p className={`truncate text-[11px] leading-4 ${t.faint}`}>Autonomous Talent Intelligence</p>
          </div>
        )}
      </div>

      {/* ── nav ── */}
      <nav aria-label="Main" className={`flex-1 space-y-1 overflow-y-auto py-2 ${collapsed ? 'px-2.5' : 'px-3'}`}>
        {NAV.map(({ id, label, Icon, badge }) => {
          const active = view === id;
          return (
            <button
              key={id} onClick={() => setView(id)} title={collapsed ? label : undefined}
              aria-current={active ? 'page' : undefined}
              className={`relative flex w-full items-center gap-3 rounded-xl py-2.5 text-sm transition-colors ${RING} ${
                collapsed ? 'justify-center' : 'px-3'
              } ${active ? 'font-semibold text-white' : `font-medium ${t.body} ${t.hover}`}`}
            >
              {active && (
                <motion.span
                  aria-hidden layoutId="rayn-nav-pill"
                  transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                  className={`absolute inset-0 rounded-xl ${ACCENT} ${GLOW}`}
                />
              )}
              <Icon size={16} aria-hidden className={`relative z-10 shrink-0 ${active ? 'text-white' : t.muted}`} />
              {!collapsed && <span className="relative z-10 flex-1 text-left">{label}</span>}
              {!collapsed && badge ? (
                <span className={`relative z-10 rounded-md px-1.5 text-xs font-semibold tabular-nums ${
                  active ? 'bg-white/20 text-white' : `border ${t.chip}`
                }`}>
                  {badge}
                </span>
              ) : null}
              {collapsed && badge ? (
                <span aria-hidden className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-purple-400" />
              ) : null}
            </button>
          );
        })}
      </nav>

      {/* ── profile + compute credits ── */}
      <div className={`shrink-0 border-t p-3 ${t.divide}`}>
        {collapsed ? (
          <div className="grid place-items-center py-1" title={`Anshu Kumar — Pro Agent Plan, $${credits.toFixed(2)} left`}>
            <span aria-hidden className={`grid h-9 w-9 place-items-center rounded-full text-xs font-bold text-white ${ACCENT}`}>AK</span>
          </div>
        ) : (
          <div className={`rounded-xl border p-3 ${t.inner}`}>
            <div className="flex items-center gap-2.5">
              <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-xs font-bold text-white ${ACCENT}`}>AK</span>
              <div className="min-w-0 flex-1">
                <p className={`truncate text-sm font-semibold ${t.title}`}>Anshu Kumar</p>
                <p className="truncate text-xs font-medium text-indigo-400">Pro Agent Plan</p>
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-2">
              <span className={`flex items-center gap-1.5 text-xs font-medium ${t.muted}`}>
                {low ? <AlertTriangle size={11} aria-hidden className="text-amber-500" /> : <Zap size={11} aria-hidden />}
                {low ? 'Low credits' : 'Compute credits'}
              </span>
              <span className={`text-xs font-semibold tabular-nums ${low ? 'text-amber-500' : t.body}`}>
                ${credits.toFixed(2)} left
              </span>
            </div>

            <div role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
                 aria-label="Compute credits remaining"
                 className={`mt-1.5 h-1.5 overflow-hidden rounded-full ${t.track}`}>
              <motion.div
                initial={false} animate={{ width: `${pct}%` }}
                transition={{ type: 'spring', stiffness: 180, damping: 26 }}
                className={`h-full rounded-full ${low ? 'bg-amber-500' : ACCENT}`}
              />
            </div>
          </div>
        )}
      </div>

      <button
        type="button" onClick={() => setCollapsed(!collapsed)}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className={`absolute -right-3 top-[60px] grid h-6 w-6 place-items-center rounded-full border shadow ${t.rail} ${t.muted} ${RING} transition-colors hover:text-indigo-400`}
      >
        <ChevronDown size={13} className={`transition-transform duration-300 ${collapsed ? '-rotate-90' : 'rotate-90'}`} />
      </button>
    </aside>
  );
}

/* ═══════════════════════════ top bar ═══════════════════════════ */

function ModelPill({ model, setModel, t }: { model: string; setModel: (id: string) => void; t: Tokens }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const active = MODELS.find((m) => m.id === model) ?? MODELS[0];

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}
        className={`flex h-9 items-center gap-2 rounded-full border px-3 text-sm font-medium backdrop-blur-md transition-colors ${t.chip} ${RING}`}
      >
        <Zap size={13} aria-hidden className="text-indigo-400" />
        <span className="hidden max-w-[150px] truncate sm:inline">{active.label}</span>
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_#10B981]" />
        <ChevronDown size={13} aria-hidden className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox" aria-label="Scoring model"
            initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14 }}
            className={`absolute right-0 top-[calc(100%+6px)] z-40 w-72 overflow-hidden rounded-xl border p-1 shadow-2xl backdrop-blur-xl ${t.dock}`}
          >
            {MODELS.map((m) => {
              const on = m.id === model;
              return (
                <li key={m.id} role="option" aria-selected={on}>
                  <button
                    type="button" onClick={() => { setModel(m.id); setOpen(false); }}
                    className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${on ? t.chipOn : t.hover} ${RING}`}
                  >
                    <span aria-hidden className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${on ? 'bg-emerald-500' : 'bg-slate-500'}`} />
                    <span className="min-w-0 flex-1">
                      <span className={`block truncate text-sm font-semibold ${on ? '' : t.body}`}>{m.label}</span>
                      <span className={`block truncate text-xs ${t.faint}`}>{m.hint}</span>
                    </span>
                    {on && <Check size={13} strokeWidth={3} aria-hidden className="mt-0.5 shrink-0" />}
                  </button>
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

function TopBar({
  mode, setMode, model, setModel, onOpenPalette, t,
}: {
  mode: Mode; setMode: (m: Mode) => void; model: string; setModel: (id: string) => void;
  onOpenPalette: () => void; t: Tokens;
}) {
  const dark = mode === 'dark';
  return (
    <header className={`sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b px-4 backdrop-blur-xl sm:px-6 ${t.bar}`}>
      <button
        type="button" onClick={onOpenPalette}
        className={`flex h-9 min-w-0 flex-1 items-center gap-2 rounded-full border px-3 text-left text-sm transition-colors lg:max-w-md ${t.input} ${RING}`}
      >
        <Search size={14} aria-hidden className={`shrink-0 ${t.faint}`} />
        <span className={`min-w-0 flex-1 truncate ${t.faint}`}>Search candidates, runs, saved matches…</span>
        <kbd aria-hidden className={`hidden shrink-0 items-center gap-0.5 rounded border px-1.5 py-0.5 text-xs font-medium sm:inline-flex ${t.chip}`}>
          <Command size={10} /> K
        </kbd>
      </button>

      <div className="flex shrink-0 items-center gap-2">
        <div className="hidden md:block"><ModelPill model={model} setModel={setModel} t={t} /></div>

        <button
          type="button" aria-label="Notifications"
          className={`relative grid h-9 w-9 place-items-center rounded-full border backdrop-blur-md transition-colors ${t.chip} ${RING}`}
        >
          <Bell size={15} />
          <span aria-hidden className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-purple-400" />
        </button>

        <button
          type="button" role="switch" aria-checked={dark}
          aria-label={dark ? 'Dark mode on, switch to light' : 'Dark mode off, switch to dark'}
          onClick={() => setMode(dark ? 'light' : 'dark')}
          className={`relative flex h-9 w-[60px] shrink-0 items-center rounded-full border ${t.chip} ${RING}`}
        >
          <motion.span
            aria-hidden layout transition={{ type: 'spring', stiffness: 500, damping: 34 }}
            className={`absolute top-[3px] h-[30px] w-[27px] rounded-full ${ACCENT} ${dark ? 'left-[30px]' : 'left-[3px]'}`}
          />
          <span aria-hidden className="relative z-10 grid w-1/2 place-items-center">
            <Sun size={14} strokeWidth={2.4} className={dark ? t.faint : 'text-white'} />
          </span>
          <span aria-hidden className="relative z-10 grid w-1/2 place-items-center">
            <Moon size={14} strokeWidth={2.4} className={dark ? 'text-white' : t.faint} />
          </span>
        </button>

        <button
          type="button" aria-label="Quick settings"
          className={`grid h-9 w-9 place-items-center rounded-full border backdrop-blur-md transition-colors ${t.chip} ${RING}`}
        >
          <SlidersHorizontal size={15} />
        </button>
      </div>
    </header>
  );
}

/* ═══════════════════════════ AI prompt studio ═══════════════════════════ */

function PromptStudio({
  prompt, setPrompt, tab, setTab, attached, setAttached, postingUrl, setPostingUrl,
  extracting, onAutoExtract, t,
}: {
  prompt: string; setPrompt: (v: string) => void;
  tab: StudioTab; setTab: (v: StudioTab) => void;
  attached: AttachedFile | null; setAttached: (f: AttachedFile | null) => void;
  postingUrl: string; setPostingUrl: (v: string) => void;
  extracting: boolean; onAutoExtract: () => void; t: Tokens;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const chars = prompt.trim().length;

  const take = (file?: File) => {
    if (!file) return;
    setAttached({ name: file.name, size: file.size });
    setTab('prompt');
  };

  const attachUrl = () => {
    const url = postingUrl.trim();
    if (!url) return;
    setPrompt(`${prompt.trimEnd()}${prompt.trim() ? '\n\n' : ''}Reference posting: ${url}`);
    setPostingUrl('');
    setTab('prompt');
  };

  return (
    <section
      aria-labelledby="studio-head"
      onDragEnter={(e) => { e.preventDefault(); depth.current++; setDragging(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => { if (--depth.current <= 0) { depth.current = 0; setDragging(false); } }}
      onDrop={(e) => { e.preventDefault(); depth.current = 0; setDragging(false); take(e.dataTransfer.files?.[0]); }}
      className={`relative overflow-hidden rounded-2xl border shadow-2xl backdrop-blur-md transition-colors ${t.card} ${
        dragging ? '!border-indigo-500' : ''
      }`}
    >
      <div className={`flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${t.divide}`}>
        <div className="flex items-center gap-2">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg border border-indigo-400/40 bg-indigo-500/15 text-indigo-300">
            <Sparkles size={14} />
          </span>
          <h2 id="studio-head" className={`text-base font-semibold ${t.title}`}>AI Prompt Studio</h2>
        </div>
        <SegmentedTabs tabs={STUDIO_TABS} value={tab} onChange={setTab} groupId="studio" t={t} />
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.16, ease: 'easeOut' }}
        >
          {tab === 'prompt' && (
            <>
              <label htmlFor="rayn-prompt" className="sr-only">Ideal candidate profile</label>
              <textarea
                id="rayn-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} spellCheck={false}
                placeholder="Describe your ideal candidate — role, must-have skills, seniority, location, and anything that makes a profile a strong fit…"
                className={`block h-56 w-full resize-none border-0 bg-transparent px-5 py-4 text-sm leading-6 focus:outline-none focus:ring-0 ${t.title} ${t.placeholder}`}
              />
            </>
          )}

          {tab === 'document' && (
            <div className="px-5 py-6">
              <button
                type="button" onClick={() => fileRef.current?.click()}
                className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center transition-colors hover:border-indigo-500 ${t.inner} ${RING}`}
              >
                <span aria-hidden className="grid h-11 w-11 place-items-center rounded-full border border-indigo-400/40 bg-indigo-500/15 text-indigo-300">
                  <Upload size={18} />
                </span>
                <span className={`text-sm font-semibold ${t.title}`}>Drop a resume or JD, or click to browse</span>
                <span className={`text-xs ${t.faint}`}>PDF, DOCX, TXT or Markdown · up to 10 MB</span>
              </button>
            </div>
          )}

          {tab === 'url' && (
            <div className="px-5 py-6">
              <label htmlFor="rayn-url" className={`block text-sm font-semibold ${t.title}`}>Job posting or careers page URL</label>
              <p className={`mt-1 text-xs ${t.faint}`}>The link is appended to your prompt as extra context for the extractor.</p>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <input
                  id="rayn-url" type="url" value={postingUrl} onChange={(e) => setPostingUrl(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); attachUrl(); } }}
                  placeholder="https://company.com/careers/senior-backend-engineer"
                  className={`h-10 flex-1 rounded-lg border px-3 text-sm transition-colors ${t.input} ${RING}`}
                />
                <button
                  type="button" onClick={attachUrl} disabled={!postingUrl.trim()}
                  className={`inline-flex h-10 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-medium transition-colors disabled:opacity-50 ${t.chip} ${RING}`}
                >
                  <Link2 size={14} aria-hidden /> Add to prompt
                </button>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* ── studio bar ── */}
      <div className={`flex flex-col gap-3 border-t px-3 py-2.5 lg:flex-row lg:items-center lg:justify-between ${t.divide} ${t.inner}`}>
        <div className="flex min-w-0 items-center gap-2">
          <AnimatePresence initial={false} mode="wait">
            {attached ? (
              <motion.span
                key="chip"
                initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.94 }}
                transition={{ duration: 0.15, ease: 'easeOut' }}
                className={`inline-flex min-w-0 items-center gap-2 rounded-lg border py-1 pl-2 pr-1 ${t.chip}`}
              >
                <FileText size={14} aria-hidden className="shrink-0 text-indigo-400" />
                <span className={`truncate text-sm font-medium ${t.title}`}>{attached.name}</span>
                <span className={`shrink-0 text-xs tabular-nums ${t.faint}`}>{fmtBytes(attached.size)}</span>
                <button
                  type="button" onClick={() => { setAttached(null); if (fileRef.current) fileRef.current.value = ''; }}
                  aria-label={`Remove ${attached.name}`}
                  className={`shrink-0 rounded p-1 transition-colors ${t.muted} ${t.hover} ${RING}`}
                >
                  <X size={12} />
                </button>
              </motion.span>
            ) : (
              <motion.button
                key="attach" type="button" onClick={() => fileRef.current?.click()}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className={`inline-flex items-center gap-2 rounded-lg px-2 py-1 text-sm font-medium transition-colors ${t.body} ${t.hover} ${RING}`}
              >
                <Paperclip size={14} aria-hidden /> Attach resume or JD
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className={`rounded-md border px-2 py-1 text-xs tabular-nums ${t.chip}`}>
            {chars.toLocaleString()} chars
          </span>
          <button
            type="button" onClick={() => { setPrompt(SAMPLE_JD); setTab('prompt'); }}
            className={`inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors ${t.body} ${t.hover} ${RING}`}
          >
            <FileText size={13} aria-hidden /> Load Sample JD
          </button>
          <motion.button
            type="button" onClick={onAutoExtract} disabled={extracting || chars < 20}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            className={`inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold text-white transition-shadow disabled:pointer-events-none disabled:opacity-50 ${ACCENT} ${GLOW} ${RING}`}
          >
            {extracting
              ? <><Loader2 size={14} aria-hidden className="animate-spin" /> Extracting…</>
              : <><Sparkles size={14} aria-hidden /> Auto-Extract Attributes</>}
          </motion.button>
        </div>
      </div>

      <input
        ref={fileRef} type="file" className="sr-only"
        accept=".pdf,.docx,.doc,.txt,.md,.rtf"
        onChange={(e) => take(e.target.files?.[0])}
      />

      {dragging && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-2xl border-2 border-dashed border-indigo-500 bg-indigo-500/10 backdrop-blur-sm">
          <span className="text-sm font-semibold text-indigo-300">Drop the file to read it</span>
        </div>
      )}
    </section>
  );
}

/* ═══════════════════════════ configuration bento ═══════════════════════════ */

function BentoCard({
  Icon, title, hint, children, t,
}: { Icon: LucideIcon; title: string; hint: string; children: React.ReactNode; t: Tokens }) {
  return (
    <div className={`flex flex-col rounded-2xl border p-5 shadow-2xl backdrop-blur-md transition-colors ${t.card}`}>
      <div className="flex items-start gap-2.5">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-indigo-400/40 bg-indigo-500/15 text-indigo-300">
          <Icon size={15} />
        </span>
        <div className="min-w-0">
          <h3 className={`text-base font-semibold ${t.title}`}>{title}</h3>
          <p className={`mt-0.5 text-xs ${t.faint}`}>{hint}</p>
        </div>
      </div>
      <div className="mt-5 flex-1 space-y-5">{children}</div>
    </div>
  );
}

function SwitchRow({
  id, title, subtitle, on, onChange, disabled, note, t,
}: {
  id: string; title: string; subtitle: string; on: boolean; onChange: (v: boolean) => void;
  disabled?: boolean; note?: string; t: Tokens;
}) {
  return (
    <div className={`rounded-xl border p-3.5 transition-colors ${t.inner} ${disabled ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <label htmlFor={id} className={`block text-sm font-semibold ${t.title}`}>{title}</label>
          <p id={`${id}-state`} className={`mt-0.5 text-xs ${t.faint}`}>{subtitle}</p>
        </div>
        <Switch id={id} on={on} onChange={onChange} disabled={disabled} describedBy={`${id}-state`} t={t} />
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        <StatusBadge on={on} />
        {note && <span className={`min-w-0 truncate text-xs ${t.faint}`}>{note}</span>}
      </div>
    </div>
  );
}

function ConfigGrid({
  perPlatform, setPerPlatform, cost, platforms, togglePlatform, targetTitle, setTargetTitle,
  seniority, setSeniority, scoring, setScoring, roadmap, setRoadmap, t,
}: {
  perPlatform: number; setPerPlatform: (n: number) => void; cost: string;
  platforms: SourceId[]; togglePlatform: (id: SourceId) => void;
  targetTitle: string; setTargetTitle: (v: string) => void;
  seniority: number; setSeniority: (n: number) => void;
  scoring: boolean; setScoring: (v: boolean) => void;
  roadmap: boolean; setRoadmap: (v: boolean) => void;
  t: Tokens;
}) {
  return (
    <section aria-labelledby="config-head" className="space-y-3">
      <div>
        <h2 id="config-head" className={`text-xl font-semibold tracking-tight ${t.title}`}>Search &amp; Intelligence Configuration</h2>
        <p className={`mt-1 text-sm ${t.muted}`}>How wide RAYN sources, and how hard it thinks about what it finds.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* ── column 1 — sourcing ── */}
        <BentoCard Icon={Target} title="Target Pool & Platforms" hint="Where RAYN looks, and how many profiles it pulls per platform." t={t}>
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <label htmlFor="per-platform" className={`text-sm font-semibold ${t.title}`}>Candidates per platform</label>
              <span className="rounded-full border border-indigo-400/40 bg-indigo-500/10 px-2 py-0.5 text-xs font-semibold tabular-nums text-indigo-300">
                ~${cost} total
              </span>
            </div>
            <div className="flex items-center gap-3">
              <div className={`flex h-11 items-center rounded-xl border ${t.input}`}>
                <button
                  type="button" aria-label="Fewer candidates" disabled={perPlatform <= MIN_PER_PLATFORM}
                  onClick={() => setPerPlatform(Math.max(MIN_PER_PLATFORM, perPlatform - STEP))}
                  className={`grid h-full w-11 place-items-center rounded-l-xl transition-colors disabled:opacity-40 ${t.body} ${t.hover} ${RING}`}
                >
                  <Minus size={15} />
                </button>
                <input
                  id="per-platform" type="text" inputMode="numeric" value={perPlatform} readOnly
                  aria-label="Candidates to scan per platform"
                  className={`h-full w-14 border-x bg-transparent text-center text-xl font-semibold tabular-nums focus:outline-none ${t.divide} ${t.title}`}
                />
                <button
                  type="button" aria-label="More candidates" disabled={perPlatform >= MAX_PER_PLATFORM}
                  onClick={() => setPerPlatform(Math.min(MAX_PER_PLATFORM, perPlatform + STEP))}
                  className={`grid h-full w-11 place-items-center rounded-r-xl transition-colors disabled:opacity-40 ${t.body} ${t.hover} ${RING}`}
                >
                  <Plus size={15} />
                </button>
              </div>
              <p className={`text-sm ${t.muted}`}>
                Candidates<br />
                <span className={`text-xs ${t.faint}`}>{MIN_PER_PLATFORM}–{MAX_PER_PLATFORM} per platform</span>
              </p>
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className={`text-sm font-semibold ${t.title}`}>Sourcing platforms</span>
              {platforms.length === 0 ? (
                <span className="flex items-center gap-1 text-xs font-medium text-rose-400">
                  <AlertTriangle size={11} aria-hidden /> Pick one
                </span>
              ) : (
                <span className={`text-xs ${t.faint}`}>
                  {platforms.length} selected · ~{perPlatform * platforms.length} profiles
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {SOURCES.map(({ id, label, Icon }) => {
                const on = platforms.includes(id);
                return (
                  <motion.button
                    key={id} type="button" aria-pressed={on} whileTap={{ scale: 0.96 }}
                    onClick={() => togglePlatform(id)}
                    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${RING} ${
                      on ? `${t.chipOn} ${GLOW}` : t.chip
                    }`}
                  >
                    <Icon size={13} aria-hidden />
                    {label}
                    {on && <Check size={13} strokeWidth={3} aria-hidden />}
                  </motion.button>
                );
              })}
            </div>
          </div>

          <div>
            <label htmlFor="target-title" className={`mb-2 block text-sm font-semibold ${t.title}`}>Target role / title</label>
            <input
              id="target-title" value={targetTitle} onChange={(e) => setTargetTitle(e.target.value)}
              placeholder="Auto-detected from your prompt"
              className={`h-11 w-full rounded-xl border px-3 text-sm transition-colors ${t.input} ${RING}`}
            />
            <p className={`mt-1.5 text-xs ${t.faint}`}>Leave blank to let RAYN extract the title from your prompt.</p>
          </div>
        </BentoCard>

        {/* ── column 2 — intelligence ── */}
        <BentoCard Icon={SlidersHorizontal} title="AI Evaluation & Ranking" hint="How every sourced profile is scored, ranked and explained." t={t}>
          <SwitchRow
            id="scoring" title="Deep Semantic Scoring & Fit Analysis"
            subtitle="Every profile is scored against your prompt and ranked best-first."
            on={scoring} onChange={setScoring}
            note={scoring ? 'adds ~30s and tokens' : 'sourcing only, no scores'} t={t}
          />
          <SwitchRow
            id="roadmap" title="Career Growth & Skill-Gap Roadmap"
            subtitle="Turns near-misses into a 15/30-day upskilling plan."
            on={roadmap && scoring} onChange={setRoadmap} disabled={!scoring}
            note={!scoring ? 'needs semantic scoring on' : roadmap ? 'offered with results' : 'off'} t={t}
          />

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <label htmlFor="seniority" className={`text-sm font-semibold ${t.title}`}>Seniority focus</label>
              <span className="rounded-full border border-indigo-400/40 bg-indigo-500/10 px-2 py-0.5 text-xs font-semibold text-indigo-300">
                {SENIORITY[seniority]}
              </span>
            </div>
            {/* Native range, restyled with accent-* so there is no extra CSS file. */}
            <input
              id="seniority" type="range" min={0} max={SENIORITY.length - 1} step={1}
              value={seniority} onChange={(e) => setSeniority(Number(e.target.value))}
              aria-valuetext={SENIORITY[seniority]}
              className={`w-full cursor-pointer accent-indigo-500 ${RING}`}
            />
            <div aria-hidden className={`mt-2 flex justify-between text-xs ${t.faint}`}>
              <span>Any</span><span>Senior</span><span>Principal</span>
            </div>
          </div>
        </BentoCard>
      </div>
    </section>
  );
}

/* ═══════════════════════════ floating action dock ═══════════════════════════ */

function ActionDock({
  profiles, cost, seconds, busy, blocked, onLaunch, t,
}: {
  profiles: number; cost: string; seconds: number;
  busy: boolean; blocked: boolean; onLaunch: () => void; t: Tokens;
}) {
  return (
    <div className="pointer-events-none sticky bottom-5 z-30 flex justify-center">
      <motion.div
        initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 260, damping: 28 }}
        className={`pointer-events-auto flex w-full max-w-2xl flex-col gap-3 rounded-2xl border p-3 shadow-2xl backdrop-blur-xl sm:w-auto sm:flex-row sm:items-center sm:gap-5 sm:rounded-full sm:pl-5 sm:pr-3 ${t.dock}`}
      >
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <Zap size={14} aria-hidden className="shrink-0 text-indigo-400" />
          <span className={`min-w-0 truncate ${t.body}`}>
            <span className={`font-semibold tabular-nums ${t.title}`}>{profiles}</span> profiles to scan
            <span className={`mx-1.5 ${t.faint}`}>•</span>
            est. <span className={`font-semibold tabular-nums ${t.title}`}>~${cost}</span>
            <span className={`mx-1.5 ${t.faint}`}>•</span>
            <span className="tabular-nums">~{seconds}s</span>
          </span>
        </div>

        <motion.button
          type="button" onClick={onLaunch} disabled={busy || blocked}
          whileHover={busy || blocked ? undefined : { scale: 1.03 }}
          whileTap={busy || blocked ? undefined : { scale: 0.97 }}
          className={`inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-full px-6 text-sm font-semibold text-white transition-shadow disabled:pointer-events-none disabled:opacity-60 ${ACCENT} ${GLOW} hover:shadow-[0_18px_52px_-14px_rgba(99,102,241,0.85)] ${RING}`}
        >
          {busy
            ? <><Loader2 size={16} aria-hidden className="animate-spin" /> Running pipeline…</>
            : <><Rocket size={16} aria-hidden /> Launch RAYN Pipeline</>}
        </motion.button>
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════ dashboard ═══════════════════════════ */

export default function RaynDashboard({
  onLaunch, onAutoExtract, credits = 4.9, budget = 5, defaultMode = 'dark',
}: RaynDashboardProps = {}) {
  const [mode, setMode] = useState<Mode>(defaultMode);
  const [view, setView] = useState('new');
  const [collapsed, setCollapsed] = useState(false);
  const [model, setModel] = useState(MODELS[0].id);

  const [prompt, setPrompt] = useState('');
  const [tab, setTab] = useState<StudioTab>('prompt');
  const [attached, setAttached] = useState<AttachedFile | null>(null);
  const [postingUrl, setPostingUrl] = useState('');
  const [extracting, setExtracting] = useState(false);

  const [perPlatform, setPerPlatform] = useState(20);
  const [platforms, setPlatforms] = useState<SourceId[]>(['linkedin', 'indeed']);
  const [targetTitle, setTargetTitle] = useState('');
  const [seniority, setSeniority] = useState(0);
  const [scoring, setScoring] = useState(true);
  const [roadmap, setRoadmap] = useState(false);
  const [busy, setBusy] = useState(false);

  const t = TOKENS[mode];

  const profiles = perPlatform * Math.max(platforms.length, 1);
  const costValue = profiles * COST_PER_PROFILE;
  const cost = costValue.toFixed(2);
  const seconds = SECONDS_PER_PLATFORM * Math.max(platforms.length, 1) + (scoring ? 30 : 0);

  const togglePlatform = useCallback((id: SourceId) => {
    setPlatforms((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  }, []);

  const handleAutoExtract = useCallback(async () => {
    setExtracting(true);
    try {
      const title = await onAutoExtract?.(prompt.trim());
      if (typeof title === 'string' && title) setTargetTitle(title);
    } finally {
      setExtracting(false);
    }
  }, [onAutoExtract, prompt]);

  const handleLaunch = useCallback(async () => {
    setBusy(true);
    try {
      await onLaunch?.({
        prompt: prompt.trim(),
        perPlatform,
        platforms,
        targetTitle: targetTitle.trim(),
        seniority: SENIORITY[seniority],
        semanticScoring: scoring,
        careerRoadmap: roadmap && scoring,
        estimatedCost: costValue,
      });
    } finally {
      setBusy(false);
    }
  }, [onLaunch, prompt, perPlatform, platforms, targetTitle, seniority, scoring, roadmap, costValue]);

  const openPalette = useCallback(() => {
    // Wire your command palette here. ⌘K already routes to this callback.
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openPalette]);

  const heading = useMemo(() => {
    const found = NAV.find((n) => n.id === view);
    return view === 'new'
      ? { title: 'Launch New Candidate Search', sub: 'Describe your ideal profile, select sourcing channels, and let RAYN rank top talent.' }
      : { title: found?.label ?? 'Overview', sub: 'This view is yours to build — the shell, theme and navigation already work.' };
  }, [view]);

  return (
    <div className={`flex h-screen overflow-hidden font-sans antialiased ${t.shell} ${t.body}`}>
      <Sidebar
        view={view} setView={setView} collapsed={collapsed} setCollapsed={setCollapsed}
        credits={credits} budget={budget} t={t}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar mode={mode} setMode={setMode} model={model} setModel={setModel} onOpenPalette={openPalette} t={t} />

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 sm:py-8">
            <div className="mb-6">
              <h1 className={`text-3xl font-bold tracking-tight ${t.title}`}>{heading.title}</h1>
              <p className={`mt-1.5 max-w-2xl text-sm ${t.muted}`}>{heading.sub}</p>
            </div>

            {view === 'new' ? (
              <div className="space-y-6">
                <PromptStudio
                  prompt={prompt} setPrompt={setPrompt} tab={tab} setTab={setTab}
                  attached={attached} setAttached={setAttached}
                  postingUrl={postingUrl} setPostingUrl={setPostingUrl}
                  extracting={extracting} onAutoExtract={handleAutoExtract} t={t}
                />

                <ConfigGrid
                  perPlatform={perPlatform} setPerPlatform={setPerPlatform} cost={cost}
                  platforms={platforms} togglePlatform={togglePlatform}
                  targetTitle={targetTitle} setTargetTitle={setTargetTitle}
                  seniority={seniority} setSeniority={setSeniority}
                  scoring={scoring} setScoring={setScoring}
                  roadmap={roadmap} setRoadmap={setRoadmap} t={t}
                />

                <ActionDock
                  profiles={profiles} cost={cost} seconds={seconds}
                  busy={busy} blocked={platforms.length === 0} onLaunch={handleLaunch} t={t}
                />
              </div>
            ) : (
              <div className={`grid place-items-center rounded-2xl border py-24 text-sm ${t.card} ${t.faint}`}>
                Nothing here yet — “{heading.title}” is wired up and ready for your content.
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
