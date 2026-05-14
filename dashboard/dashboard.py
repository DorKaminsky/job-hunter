import sys, os, json, threading
from flask import Flask, jsonify, send_file, render_template_string, request
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.db import get_conn, init_db

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

CV_PATH = os.environ.get("CV_PATH", os.path.expanduser("~/Desktop/Personal/CV_SW_DorKaminsky.pdf"))
PDFS_DIR = os.path.join(os.path.dirname(__file__), '..', 'pdfs')

app = Flask(__name__)
pipeline_running = False
last_run_summary = None   # populated after each run


def run_pipeline(sources=None):
    """sources: list of 'goozali' | 'techaviv'. None = both."""
    global pipeline_running, last_run_summary
    if pipeline_running:
        return
    pipeline_running = True
    summary = {
        'started_at': _now_str(),
        'sources': {},
        'new_jobs': 0,
        'scored': 0,
        'claude_scored': 0,
        'tailored': 0,
        'errors': [],
    }
    if sources is None:
        sources = ['goozali', 'techaviv', 'secrettelaviv']

    try:
        # ── Scraping ──
        if 'goozali' in sources:
            try:
                from scraper.scraper import run as scrape_goozali
                n = scrape_goozali()
                summary['sources']['goozali'] = n
                summary['new_jobs'] += n
            except Exception as e:
                summary['errors'].append(f'goozali: {e}')
                summary['sources']['goozali'] = 0

        if 'techaviv' in sources:
            try:
                from scraper.techaviv import run as scrape_techaviv
                n = scrape_techaviv()
                summary['sources']['techaviv'] = n
                summary['new_jobs'] += n
            except Exception as e:
                summary['errors'].append(f'techaviv: {e}')
                summary['sources']['techaviv'] = 0

        if 'secrettelaviv' in sources:
            try:
                from scraper.secrettelaviv import run as scrape_stlv
                n = scrape_stlv()
                summary['sources']['secrettelaviv'] = n
                summary['new_jobs'] += n
            except Exception as e:
                summary['errors'].append(f'secrettelaviv: {e}')
                summary['sources']['secrettelaviv'] = 0

        # ── Matching ──
        try:
            from matcher.matcher import run as match
            scored, claude_scored = match(CV_PATH)
            summary['scored'] = scored
            summary['claude_scored'] = claude_scored
        except Exception as e:
            summary['errors'].append(f'matcher: {e}')

        # ── Tailoring ──
        try:
            from tailor.tailor import run as tailor
            n = tailor(CV_PATH, PDFS_DIR)
            summary['tailored'] = n
        except Exception as e:
            summary['errors'].append(f'tailor: {e}')

    finally:
        summary['finished_at'] = _now_str()
        last_run_summary = summary
        pipeline_running = False


def _now_str():
    from datetime import datetime
    return datetime.now().strftime('%H:%M:%S')


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Hunter</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f6f9; color: #1a1a2e; }

  /* ── Header ── */
  header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white; padding: 0 32px;
    display: flex; align-items: center; justify-content: space-between;
    height: 64px; box-shadow: 0 2px 12px rgba(0,0,0,.25);
  }
  .logo { display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 700; letter-spacing: -.3px; }
  .logo-dot { width: 10px; height: 10px; border-radius: 50%; background: #4A9BAF; }
  .header-right { display: flex; align-items: center; gap: 12px; }
  .pipeline-status { font-size: 12px; color: #aaa; }
  .running { color: #f9a825; animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

  .source-toggles { display: flex; gap: 6px; align-items: center; }
  .src-btn {
    border: 1.5px solid rgba(255,255,255,.25); border-radius: 16px;
    padding: 5px 12px; font-size: 11px; font-weight: 700;
    background: transparent; color: rgba(255,255,255,.6); cursor: pointer; transition: all .2s;
  }
  .src-btn.active { background: rgba(74,155,175,.35); color: white; border-color: #4A9BAF; }
  .src-btn:hover:not(.active) { border-color: rgba(255,255,255,.5); color: white; }

  /* ── Stats bar ── */
  .stats-bar {
    background: white; padding: 12px 32px;
    display: flex; gap: 32px; align-items: center;
    border-bottom: 1px solid #e8eaf0; font-size: 13px; color: #555;
  }
  .stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .stat-value { font-size: 22px; font-weight: 800; color: #1a1a2e; line-height: 1; }
  .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: #888; }
  .stat-teal .stat-value { color: #4A9BAF; }

  /* ── Filter bar ── */
  .filter-bar {
    background: white; padding: 14px 32px;
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    border-bottom: 1px solid #e8eaf0; position: sticky; top: 0; z-index: 10;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .filter-bar input[type=text] {
    border: 1.5px solid #e0e3ea; border-radius: 8px;
    padding: 8px 14px; font-size: 13px; width: 220px; outline: none;
    transition: border .2s;
  }
  .filter-bar input[type=text]:focus { border-color: #4A9BAF; }
  .filter-bar select {
    border: 1.5px solid #e0e3ea; border-radius: 8px;
    padding: 8px 12px; font-size: 13px; background: white; outline: none; cursor: pointer;
    transition: border .2s;
  }
  .filter-bar select:focus { border-color: #4A9BAF; }

  .toggle-group { display: flex; gap: 8px; }
  .toggle-btn {
    border: 1.5px solid #e0e3ea; border-radius: 20px;
    padding: 6px 14px; font-size: 12px; font-weight: 600;
    background: white; color: #555; cursor: pointer; transition: all .2s; white-space: nowrap;
  }
  .toggle-btn.active { background: #4A9BAF; color: white; border-color: #4A9BAF; }
  .toggle-btn:hover:not(.active) { border-color: #4A9BAF; color: #4A9BAF; }

  .slider-wrap { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #555; white-space: nowrap; }
  .slider-wrap input[type=range] { width: 90px; accent-color: #4A9BAF; }

  .filter-divider { width: 1px; height: 24px; background: #e0e3ea; }
  .count-label { font-size: 12px; color: #999; margin-left: auto; white-space: nowrap; }

  /* ── Grid ── */
  .grid { padding: 24px 32px; display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 18px; }

  /* ── Card ── */
  .card {
    background: white; border-radius: 14px; padding: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
    display: flex; flex-direction: column; gap: 10px;
    transition: transform .18s, box-shadow .18s;
    border: 1.5px solid transparent;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,.12); border-color: #e8f4f7; }

  .card-top { display: flex; gap: 14px; align-items: flex-start; }

  .avatar {
    width: 44px; height: 44px; border-radius: 10px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 800; color: white;
  }

  .card-meta { flex: 1; min-width: 0; }
  .card-title { font-size: 15px; font-weight: 700; color: #1a1a2e; line-height: 1.3; }
  .card-company { font-size: 12px; color: #777; margin-top: 2px; }

  .score-badge {
    width: 48px; height: 48px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; font-weight: 900; color: white;
  }
  .score-high { background: linear-gradient(135deg, #43a047, #1b5e20); }
  .score-mid  { background: linear-gradient(135deg, #fb8c00, #e65100); }
  .score-low  { background: linear-gradient(135deg, #78909c, #37474f); }

  .tags { display: flex; flex-wrap: wrap; gap: 5px; }
  .tag {
    display: inline-flex; align-items: center; gap: 4px;
    border-radius: 20px; padding: 3px 9px; font-size: 11px; font-weight: 600;
  }
  .tag-field    { background: #e8f4f7; color: #2d8a9e; }
  .tag-loc      { background: #e8f0fe; color: #3949ab; }
  .tag-exp      { background: #fff3e0; color: #e65100; }
  .tag-kw-scored { background: #f3e5f5; color: #6a1b9a; }

  .reason { font-size: 12px; color: #666; line-height: 1.55; font-style: italic; }

  .keywords { display: flex; flex-wrap: wrap; gap: 4px; }
  .kw { background: #f0f0f0; border-radius: 4px; padding: 2px 7px; font-size: 11px; color: #444; }

  .card-actions { display: flex; gap: 6px; align-items: center; margin-top: 2px; flex-wrap: wrap; }
  .card-actions a { font-size: 12px; color: #4A9BAF; text-decoration: none; font-weight: 500; }
  .card-actions a:hover { text-decoration: underline; }
  .spacer { flex: 1; }

  .status-badge { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 10px; letter-spacing: .3px; }
  .status-applied { background: #c8e6c9; color: #2e7d32; }
  .status-skipped { background: #ffcdd2; color: #c62828; }
  .status-saved   { background: #fff9c4; color: #c17900; }
  .status-new     { background: #e3f2fd; color: #1565c0; }

  .action-btns { display: flex; gap: 5px; }
  .btn { border: none; border-radius: 7px; padding: 6px 12px; font-size: 11px; font-weight: 700; cursor: pointer; transition: opacity .15s; }
  .btn:hover { opacity: .85; }
  .btn-apply { background: #e8f5e9; color: #2e7d32; }
  .btn-save  { background: #fff8e1; color: #c17900; }
  .btn-skip  { background: #fce4ec; color: #c62828; }
  .btn-refresh { background: #4A9BAF; color: white; border: none; border-radius: 8px; padding: 9px 18px; font-size: 13px; font-weight: 700; cursor: pointer; transition: background .2s; }
  .btn-refresh:hover { background: #3a8a9e; }
  .btn-refresh:disabled { background: #aaa; cursor: not-allowed; }

  .empty { text-align: center; color: #bbb; padding: 80px; font-size: 16px; grid-column: 1/-1; }
  .empty-icon { font-size: 48px; margin-bottom: 12px; }

  /* ── Diff modal ── */
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5);
    z-index: 100; align-items: center; justify-content: center;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: white; border-radius: 16px; width: 720px; max-width: 95vw;
    max-height: 85vh; display: flex; flex-direction: column;
    box-shadow: 0 20px 60px rgba(0,0,0,.3);
  }
  .modal-header {
    padding: 20px 24px 16px; border-bottom: 1px solid #eee;
    display: flex; justify-content: space-between; align-items: flex-start;
  }
  .modal-header h2 { font-size: 16px; color: #1a1a2e; }
  .modal-header p  { font-size: 12px; color: #888; margin-top: 2px; }
  .modal-close { font-size: 20px; cursor: pointer; color: #999; line-height: 1; background: none; border: none; }
  .modal-close:hover { color: #333; }
  .modal-body { padding: 20px 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 18px; }
  .diff-section-title { font-size: 11px; font-weight: 800; color: #4A9BAF; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }
  .diff-entry-title { font-size: 13px; font-weight: 700; color: #1a1a2e; margin-bottom: 4px; }
  .diff-bullet { font-size: 12px; line-height: 1.6; padding: 3px 0; border-radius: 4px; }
  .diff-bullet.changed { background: #fffde7; padding: 3px 6px; border-left: 3px solid #f9a825; }
  .diff-summary-box { background: #f8f9fa; border-radius: 8px; padding: 12px; font-size: 12px; line-height: 1.7; color: #444; border-left: 3px solid #4A9BAF; }

  /* ── Run summary modal ── */
  .summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .summary-stat { background: #f8f9fa; border-radius: 10px; padding: 14px 16px; text-align: center; }
  .summary-stat .val { font-size: 28px; font-weight: 900; color: #1a1a2e; }
  .summary-stat .lbl { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .6px; margin-top: 2px; }
  .summary-stat.accent .val { color: #4A9BAF; }
  .summary-sources { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
  .summary-source-chip { background: #e8f4f7; color: #2d8a9e; border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }
  .summary-errors { background: #fff3e0; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #e65100; }
  .summary-time { font-size: 11px; color: #aaa; text-align: right; margin-top: 8px; }

  /* ── Source badge on cards ── */
  .source-badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 8px; }
  .source-goozali      { background: #e8f5e9; color: #2e7d32; }
  .source-techaviv     { background: #e8eaf6; color: #3949ab; }
  .source-secrettelaviv { background: #fce4ec; color: #c62828; }

  /* ── Notes / tracking modal ── */
  .stage-select { border: 1.5px solid #e0e3ea; border-radius: 8px; padding: 8px 10px; font-size: 13px; background: white; outline: none; width: 100%; }
  .stage-select:focus { border-color: #4A9BAF; }
  .notes-textarea { border: 1.5px solid #e0e3ea; border-radius: 8px; padding: 10px; font-size: 13px; resize: vertical; width: 100%; min-height: 80px; font-family: inherit; outline: none; }
  .notes-textarea:focus { border-color: #4A9BAF; }
  .btn-save-notes { background: #4A9BAF; color: white; border: none; border-radius: 8px; padding: 9px 20px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .btn-save-notes:hover { background: #3a8a9e; }
  .interview-stage-badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 8px; background: #e8f4f7; color: #2d8a9e; }
  .btn-notes { background: #f0f4ff; color: #3949ab; border: none; border-radius: 7px; padding: 6px 10px; font-size: 11px; font-weight: 700; cursor: pointer; }
  .btn-notes:hover { background: #e8eaf6; }
  .btn-customize { background: #4A9BAF; color: white; border: none; border-radius: 7px; padding: 6px 10px; font-size: 11px; font-weight: 700; cursor: pointer; }
  .btn-customize:hover { background: #3a8a9e; }

  /* ── Thumb feedback buttons ── */
  .thumb-group { display: flex; gap: 4px; }
  .btn-thumb { border: 1.5px solid #e0e3ea; border-radius: 7px; padding: 5px 9px; font-size: 13px; background: white; cursor: pointer; transition: all .15s; line-height: 1; }
  .btn-thumb:hover { border-color: #4A9BAF; }
  .btn-thumb.active-up   { background: #e8f5e9; border-color: #43a047; }
  .btn-thumb.active-down { background: #fce4ec; border-color: #e53935; }

  /* ── Profile modal ── */
  .profile-textarea { border: 1.5px solid #e0e3ea; border-radius: 8px; padding: 10px; font-size: 13px; resize: vertical; width: 100%; min-height: 140px; font-family: inherit; outline: none; line-height: 1.6; }
  .profile-textarea:focus { border-color: #4A9BAF; }
  .profile-hint { font-size: 11px; color: #999; line-height: 1.6; }
  .btn-profile { background: transparent; border: 1.5px solid rgba(255,255,255,.3); border-radius: 8px; color: rgba(255,255,255,.75); padding: 7px 14px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all .2s; }
  .btn-profile:hover { border-color: white; color: white; background: rgba(255,255,255,.1); }

  /* ── Ungraded modal ── */
  .ungraded-modal .modal { width: 860px; max-width: 96vw; }
  .ungraded-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .ungraded-table th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #888; font-weight: 700; padding: 0 10px 8px 0; border-bottom: 1px solid #eee; }
  .ungraded-table td { padding: 9px 10px 9px 0; border-bottom: 1px solid #f4f4f4; vertical-align: top; }
  .ungraded-table tr:last-child td { border-bottom: none; }
  .ungraded-table tr:hover td { background: #f9fbfc; }
  .ungraded-title-link { color: #1a1a2e; font-weight: 600; text-decoration: none; }
  .ungraded-title-link:hover { color: #4A9BAF; text-decoration: underline; }
  .kw-score-chip { background: #f3e5f5; color: #6a1b9a; border-radius: 5px; padding: 2px 6px; font-size: 10px; font-weight: 700; }
  .btn-grade-now { background: #4A9BAF; color: white; border: none; border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 700; cursor: pointer; white-space: nowrap; }
  .btn-grade-now:hover { background: #3a8a9e; }
  .btn-ungraded { background: #f3e5f5; color: #6a1b9a; border: none; border-radius: 8px; padding: 9px 16px; font-size: 13px; font-weight: 700; cursor: pointer; transition: background .2s; white-space: nowrap; }
  .btn-ungraded:hover { background: #e8d5f0; }
</style>
</head>
<body>

<header>
  <div class="logo"><div class="logo-dot"></div> Job Hunter</div>
  <div class="header-right">
    <div class="source-toggles">
      <span style="font-size:11px;color:rgba(255,255,255,.45);margin-right:2px;">Sources:</span>
      <button class="src-btn active" id="srcGoozali" onclick="toggleSource('goozali')">🟢 Goozali</button>
      <button class="src-btn active" id="srcTechaviv" onclick="toggleSource('techaviv')">🔵 TechAviv</button>
      <button class="src-btn active" id="srcSecrettelaviv" onclick="toggleSource('secrettelaviv')">🔴 Secret TLV</button>
    </div>
    <span class="pipeline-status" id="pipelineStatus"></span>
    <button class="btn-profile" onclick="openProfile()">👤 My Profile</button>
    <button class="btn-refresh" onclick="refresh()" id="refreshBtn">↺ Refresh Now</button>
  </div>
</header>

<div class="stats-bar" id="statsBar">
  <div class="stat stat-teal"><span class="stat-value" id="statTotal">—</span><span class="stat-label">Positions</span></div>
  <div class="stat"><span class="stat-value" id="statAvg">—</span><span class="stat-label">Avg Score</span></div>
  <div class="stat"><span class="stat-value" id="statTop">—</span><span class="stat-label">Top Score</span></div>
  <div class="stat"><span class="stat-value" id="statApplied">—</span><span class="stat-label">Applied</span></div>
  <div style="margin-left:auto">
    <button class="btn-ungraded" onclick="openUngraded()">🔎 Ungraded Jobs</button>
  </div>
</div>

<div class="filter-bar">
  <input type="text" id="filterSearch" placeholder="🔍 Search title / company..." oninput="loadJobs()">

  <select id="filterDate" onchange="loadJobs()">
    <option value="1">Today</option>
    <option value="3">Last 3 days</option>
    <option value="7">Last 7 days</option>
    <option value="30">All time</option>
  </select>

  <select id="filterStatus" onchange="loadJobs()">
    <option value="">All statuses</option>
    <option value="new">New</option>
    <option value="saved">Saved ★</option>
    <option value="applied">Applied ✓</option>
    <option value="skipped">Skipped</option>
  </select>

  <div class="filter-divider"></div>

  <div class="slider-wrap">
    ⭐ Min score:
    <input type="range" id="minScore" min="0" max="100" value="40" oninput="updateScoreLabel();loadJobs()">
    <span id="minScoreLabel">40</span>
  </div>

  <div class="slider-wrap">
    🎓 Max exp:
    <input type="range" id="maxExp" min="0" max="15" value="5" oninput="updateExpLabel();loadJobs()">
    <span id="maxExpLabel">5y</span>
  </div>

  <div class="filter-divider"></div>

  <div class="toggle-group">
    <button class="toggle-btn active" id="btnTelAviv" onclick="toggleFilter('telAviv')">📍 Tel Aviv</button>
    <button class="toggle-btn active" id="btnExcludeSenior" onclick="toggleFilter('excludeSenior')">🚫 No Senior/QA/Mgr</button>
  </div>

  <span class="count-label" id="countLabel"></span>
</div>

<div class="modal-overlay" id="diffModal" onclick="closeDiff(event)">
  <div class="modal">
    <div class="modal-header">
      <div>
        <h2 id="diffTitle">CV Changes</h2>
        <p id="diffSubtitle"></p>
      </div>
      <button class="modal-close" onclick="closeDiffModal()">✕</button>
    </div>
    <div class="modal-body" id="diffBody"></div>
  </div>
</div>

<div class="modal-overlay" id="summaryModal" onclick="closeSummaryModal(event)">
  <div class="modal" style="width:480px">
    <div class="modal-header">
      <div><h2>Run Summary</h2><p id="summaryTime"></p></div>
      <button class="modal-close" onclick="document.getElementById('summaryModal').classList.remove('open')">✕</button>
    </div>
    <div class="modal-body" id="summaryBody"></div>
  </div>
</div>

<div class="modal-overlay" id="notesModal" onclick="closeNotesModal(event)">
  <div class="modal" style="width:460px">
    <div class="modal-header">
      <div><h2>Track Application</h2><p id="notesJobTitle"></p></div>
      <button class="modal-close" onclick="document.getElementById('notesModal').classList.remove('open')">✕</button>
    </div>
    <div class="modal-body" style="gap:14px">
      <div>
        <div style="font-size:12px;font-weight:700;color:#555;margin-bottom:6px">Interview Stage</div>
        <select class="stage-select" id="notesStage">
          <option value="">— Not started —</option>
          <option value="applied">Applied</option>
          <option value="screening">HR Screening</option>
          <option value="technical">Technical Interview</option>
          <option value="home_assignment">Home Assignment</option>
          <option value="final">Final Round</option>
          <option value="offer">Offer Received</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>
      <div>
        <div style="font-size:12px;font-weight:700;color:#555;margin-bottom:6px">Notes</div>
        <textarea class="notes-textarea" id="notesText" placeholder="Add notes about this application, contacts, deadlines..."></textarea>
      </div>
      <button class="btn-save-notes" onclick="saveNotes()">Save</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="profileModal" onclick="closeProfileModal(event)">
  <div class="modal" style="width:540px">
    <div class="modal-header">
      <div>
        <h2>My Grading Profile</h2>
        <p>Tell the AI what you want — it will calibrate scores on every future run</p>
      </div>
      <button class="modal-close" onclick="document.getElementById('profileModal').classList.remove('open')">✕</button>
    </div>
    <div class="modal-body" style="gap:14px">
      <div class="profile-hint">
        Describe yourself, your target roles, what excites you, and what you want to avoid.
        The more specific, the better the grading.<br><br>
        <strong>Example:</strong> "I'm a mid-level DevOps/AI engineer with 4 years experience.
        I love CI/CD pipelines, GenAI integrations, and backend Python. I prefer startups or scale-ups
        in Tel Aviv. I'm NOT interested in pure QA, infrastructure-only ops, or roles requiring more
        than 5 years of experience."
      </div>
      <textarea class="profile-textarea" id="profileText" placeholder="Describe yourself and your ideal role..."></textarea>
      <button class="btn-save-notes" onclick="saveProfile()">Save Profile</button>
    </div>
  </div>
</div>

<div class="modal-overlay ungraded-modal" id="ungradedModal" onclick="closeUngradedModal(event)">
  <div class="modal">
    <div class="modal-header">
      <div>
        <h2>Ungraded Jobs</h2>
        <p id="ungradedSubtitle">Jobs scraped but never sent through the matcher</p>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <select id="ungradedDays" onchange="loadUngraded()" style="border:1.5px solid #e0e3ea;border-radius:8px;padding:6px 10px;font-size:12px;background:white;outline:none">
          <option value="7">Last 7 days</option>
          <option value="30" selected>Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
        <button class="modal-close" onclick="document.getElementById('ungradedModal').classList.remove('open')">✕</button>
      </div>
    </div>
    <div class="modal-body" style="padding:0 24px 20px">
      <div id="ungradedContent" style="overflow-x:auto"></div>
    </div>
  </div>
</div>

<div class="grid" id="grid"></div>

<script>
const filters = { telAviv: true, excludeSenior: true };

const AVATAR_COLORS = ['#4A9BAF','#3949ab','#e64a19','#2e7d32','#7b1fa2','#00838f','#c62828','#f57c00'];
function avatarColor(name) {
  let h = 0; for (let c of (name||'?')) h = (h*31 + c.charCodeAt(0)) % AVATAR_COLORS.length;
  return AVATAR_COLORS[h];
}

function toggleFilter(key) {
  filters[key] = !filters[key];
  const btnId = key === 'telAviv' ? 'btnTelAviv' : 'btnExcludeSenior';
  document.getElementById(btnId).classList.toggle('active', filters[key]);
  loadJobs();
}

function updateScoreLabel() {
  document.getElementById('minScoreLabel').textContent = document.getElementById('minScore').value;
}
function updateExpLabel() {
  const v = document.getElementById('maxExp').value;
  document.getElementById('maxExpLabel').textContent = v == 15 ? 'Any' : v + 'y';
}

async function loadJobs() {
  const status = document.getElementById('filterStatus').value;
  const days = document.getElementById('filterDate').value;
  const q = document.getElementById('filterSearch').value.trim();
  const minScore = document.getElementById('minScore').value;
  const maxExp = document.getElementById('maxExp').value;

  const params = new URLSearchParams({ days, min_score: minScore });
  if (status) params.set('status', status);
  if (q) params.set('q', q);
  if (filters.telAviv) params.set('tel_aviv_only', '1');
  if (filters.excludeSenior) params.set('exclude_senior', '1');
  params.set('max_exp', maxExp);

  const res = await fetch('/api/jobs?' + params);
  const jobs = await res.json();

  document.getElementById('countLabel').textContent = jobs.length + ' positions';
  document.getElementById('statTotal').textContent = jobs.length;
  const scores = jobs.map(j => j.score);
  document.getElementById('statAvg').textContent = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : '—';
  document.getElementById('statTop').textContent = scores.length ? Math.max(...scores) : '—';
  document.getElementById('statApplied').textContent = jobs.filter(j => j.status === 'applied').length;

  const grid = document.getElementById('grid');
  if (!jobs.length) {
    grid.innerHTML = '<div class="empty"><div class="empty-icon">🔍</div>No matching positions found.</div>';
    return;
  }

  grid.innerHTML = jobs.map(j => {
    const sc = j.score;
    const scClass = sc >= 80 ? 'score-high' : sc >= 60 ? 'score-mid' : 'score-low';
    const initial = (j.company || '?')[0].toUpperCase();
    const color = avatarColor(j.company);
    const kws = (j.keywords || []).slice(0, 8).map(k => `<span class="kw">${esc(k)}</span>`).join('');
    const hasCV = !!j.pdf_path;
    const expTag = j.min_exp != null ? `<span class="tag tag-exp">📚 ${j.min_exp}y exp</span>` : '';
    const locTag = j.location ? `<span class="tag tag-loc">📍 ${esc(j.location)}</span>` : '';
    const kwOnly = j.reason && j.reason.startsWith('Keyword') ? `<span class="tag tag-kw-scored">⚡ KW-scored</span>` : '';
    const stageLabel = j.interview_stage ? `<span class="interview-stage-badge">${esc(j.interview_stage.replace('_',' '))}</span>` : '';
    const jobDesc = (j.description || '') + (j.requirements ? '\\n\\nRequirements:\\n' + j.requirements : '');
    const fbUp   = j.feedback === 'up'   ? 'active-up'   : '';
    const fbDown = j.feedback === 'down' ? 'active-down' : '';

    return `<div class="card" id="card-${j.job_id}" data-jobdesc="${esc(jobDesc)}">
      <div class="card-top">
        <div class="avatar" style="background:${color}">${initial}</div>
        <div class="card-meta">
          <div class="card-title">${esc(j.title)}</div>
          <div class="card-company">${esc(j.company)}</div>
        </div>
        <div class="score-badge ${scClass}">${sc}</div>
      </div>
      <div class="tags">
        <span class="tag tag-field">${esc(j.field)}</span>
        ${locTag}${expTag}${kwOnly}
        <span class="source-badge source-${j.source||'goozali'}">${j.source||'goozali'}</span>
        ${stageLabel}
      </div>
      <div class="reason">${esc(j.reason)}</div>
      ${kws ? `<div class="keywords">${kws}</div>` : ''}
      ${j.notes ? `<div style="font-size:11px;color:#888;background:#fafafa;border-radius:6px;padding:6px 8px;border-left:3px solid #e0e3ea">${esc(j.notes)}</div>` : ''}
      <div class="card-actions">
        ${j.url ? `<a href="${esc(j.url)}" target="_blank">View Job ↗</a>` : ''}
        ${hasCV ? `<a href="/download/${j.app_id}">⬇ CV</a>` : ''}
        ${hasCV ? `<a href="#" onclick="showDiff(${j.app_id}, event)">🔍 Changes</a>` : ''}
        <span class="spacer"></span>
        <div class="thumb-group">
          <button class="btn-thumb ${fbUp}"   onclick="setFeedback('${j.job_id}',${j.match_id},'up',   this)" title="Good match for me">👍</button>
          <button class="btn-thumb ${fbDown}" onclick="setFeedback('${j.job_id}',${j.match_id},'down', this)" title="Not a good match">👎</button>
        </div>
        <span class="status-badge status-${j.status}">${j.status}</span>
      </div>
      <div class="card-actions">
        <div class="action-btns">
          <button class="btn btn-apply" onclick="setStatus('${j.job_id}',${j.app_id},'applied')">✓ Applied</button>
          <button class="btn btn-save"  onclick="setStatus('${j.job_id}',${j.app_id},'saved')">★ Save</button>
          <button class="btn btn-skip"  onclick="setStatus('${j.job_id}',${j.app_id},'skipped')">✗ Skip</button>
          <button class="btn-notes" onclick="openNotes(${j.app_id})" data-title="${esc(j.title)}" data-stage="${esc(j.interview_stage||'')}" data-notes="${esc(j.notes||'')}">📝 Notes</button>
          <button class="btn-customize" onclick="customizeCV(this)">✨ Customize CV</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function setStatus(jobId, appId, status) {
  await fetch('/api/status', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({job_id: jobId, app_id: appId, status})});
  loadJobs();
}

const activeSources = new Set(['goozali', 'techaviv', 'secrettelaviv']);

function toggleSource(src) {
  if (activeSources.has(src)) {
    if (activeSources.size === 1) return;
    activeSources.delete(src);
  } else {
    activeSources.add(src);
  }
  document.getElementById('srcGoozali').classList.toggle('active', activeSources.has('goozali'));
  document.getElementById('srcTechaviv').classList.toggle('active', activeSources.has('techaviv'));
  document.getElementById('srcSecrettelaviv').classList.toggle('active', activeSources.has('secrettelaviv'));
}

async function refresh() {
  document.getElementById('refreshBtn').disabled = true;
  document.getElementById('pipelineStatus').className = 'pipeline-status running';
  document.getElementById('pipelineStatus').textContent = '⟳ Pipeline running...';
  await fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({sources: [...activeSources]})
  });
  pollStatus();
}

async function pollStatus() {
  const res = await fetch('/api/pipeline-status');
  const d = await res.json();
  if (d.running) {
    setTimeout(pollStatus, 3000);
  } else {
    document.getElementById('refreshBtn').disabled = false;
    document.getElementById('pipelineStatus').className = 'pipeline-status';
    document.getElementById('pipelineStatus').textContent = '';
    if (d.summary) showSummary(d.summary);
    loadJobs();
  }
}

function showSummary(s) {
  const sources = s.sources || {};
  const sourceChips = Object.entries(sources)
    .map(([k,v]) => `<span class="summary-source-chip">${k}: +${v} new</span>`)
    .join('');

  document.getElementById('summaryTime').textContent =
    `${s.started_at} → ${s.finished_at}`;

  document.getElementById('summaryBody').innerHTML = `
    <div class="summary-grid">
      <div class="summary-stat accent">
        <div class="val">${s.new_jobs}</div>
        <div class="lbl">New Jobs Found</div>
      </div>
      <div class="summary-stat">
        <div class="val">${s.scored}</div>
        <div class="lbl">Jobs Scored</div>
      </div>
      <div class="summary-stat">
        <div class="val">${s.claude_scored}</div>
        <div class="lbl">Claude-Scored</div>
      </div>
      <div class="summary-stat">
        <div class="val">${s.tailored}</div>
        <div class="lbl">CVs Tailored</div>
      </div>
    </div>
    <div style="margin-top:12px">
      <div style="font-size:11px;color:#888;margin-bottom:6px;font-weight:700;text-transform:uppercase;letter-spacing:.6px">By Source</div>
      <div class="summary-sources">${sourceChips || '<span style="color:#aaa;font-size:12px">No sources ran</span>'}</div>
    </div>
    ${s.errors && s.errors.length ? `<div class="summary-errors">⚠ Errors: ${s.errors.map(e => esc(e)).join(' · ')}</div>` : ''}
  `;
  document.getElementById('summaryModal').classList.add('open');
}

function closeSummaryModal(e) {
  if (!e || e.target === document.getElementById('summaryModal'))
    document.getElementById('summaryModal').classList.remove('open');
}

let _notesAppId = null;
function openNotes(appId) {
  const btn = document.querySelector(`[onclick="openNotes(${appId})"]`);
  _notesAppId = appId;
  document.getElementById('notesJobTitle').textContent = btn ? btn.dataset.title : '';
  document.getElementById('notesStage').value = btn ? btn.dataset.stage : '';
  document.getElementById('notesText').value = btn ? btn.dataset.notes : '';
  document.getElementById('notesModal').classList.add('open');
}

async function saveNotes() {
  if (!_notesAppId) return;
  const stage = document.getElementById('notesStage').value;
  const notes = document.getElementById('notesText').value;
  await fetch('/api/notes', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({app_id: _notesAppId, interview_stage: stage, notes})
  });
  document.getElementById('notesModal').classList.remove('open');
  loadJobs();
}

function closeNotesModal(e) {
  if (e.target === document.getElementById('notesModal'))
    document.getElementById('notesModal').classList.remove('open');
}

function customizeCV(btn) {
  const card = btn.closest('.card');
  const desc = card.dataset.jobdesc || '';
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = 'http://localhost:5050/prefill';
  form.target = '_blank';
  const inp = document.createElement('input');
  inp.type = 'hidden'; inp.name = 'job_description'; inp.value = desc;
  form.appendChild(inp);
  document.body.appendChild(form);
  form.submit();
  document.body.removeChild(form);
}

function esc(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function showDiff(appId, e) {
  e.preventDefault();
  const res = await fetch(`/api/diff/${appId}`);
  if (!res.ok) { alert('No diff data — re-run the tailor to generate changes'); return; }
  const d = await res.json();
  document.getElementById('diffTitle').textContent = `CV tailored for: ${d.title}`;
  document.getElementById('diffSubtitle').textContent = d.company;

  const body = document.getElementById('diffBody');
  let html = '';

  // Summary
  if (d.tailored.summary) {
    html += `<div><div class="diff-section-title">Summary</div><div class="diff-summary-box">${esc(d.tailored.summary)}</div></div>`;
  }

  // Sections
  for (const sec of (d.tailored.sections || [])) {
    html += `<div><div class="diff-section-title">${esc(sec.title)}</div>`;
    for (const entry of (sec.entries || [])) {
      const heading = [entry.role, entry.company].filter(Boolean).join(' — ');
      if (heading) html += `<div class="diff-entry-title">${esc(heading)}</div>`;
      for (const b of (entry.bullets || [])) {
        html += `<div class="diff-bullet">${esc(b)}</div>`;
      }
    }
    html += `</div>`;
  }

  body.innerHTML = html;
  document.getElementById('diffModal').classList.add('open');
}

function closeDiff(e) { if (e.target === document.getElementById('diffModal')) closeDiffModal(); }
function closeDiffModal() { document.getElementById('diffModal').classList.remove('open'); }

async function setFeedback(jobId, matchId, value, btn) {
  // Toggle off if clicking the same thumb again
  const isActive = btn.classList.contains('active-up') || btn.classList.contains('active-down');
  const actualValue = isActive ? '' : value;

  // Update UI immediately
  const group = btn.closest('.thumb-group');
  group.querySelectorAll('.btn-thumb').forEach(b => b.classList.remove('active-up', 'active-down'));
  if (actualValue === 'up')   btn.classList.add('active-up');
  if (actualValue === 'down') btn.classList.add('active-down');

  await fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({match_id: matchId, feedback: actualValue})
  });
}

async function openProfile() {
  const res = await fetch('/api/profile');
  const d = await res.json();
  document.getElementById('profileText').value = d.profile || '';
  document.getElementById('profileModal').classList.add('open');
}

async function saveProfile() {
  const profile = document.getElementById('profileText').value.trim();
  await fetch('/api/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({profile})
  });
  document.getElementById('profileModal').classList.remove('open');
}

function closeProfileModal(e) {
  if (e.target === document.getElementById('profileModal'))
    document.getElementById('profileModal').classList.remove('open');
}

async function openUngraded() {
  document.getElementById('ungradedModal').classList.add('open');
  await loadUngraded();
}

async function loadUngraded() {
  const days = document.getElementById('ungradedDays').value;
  document.getElementById('ungradedContent').innerHTML = '<div style="padding:24px;text-align:center;color:#aaa;font-size:13px">Loading...</div>';
  const res = await fetch('/api/ungraded?days=' + days);
  const jobs = await res.json();

  document.getElementById('ungradedSubtitle').textContent =
    `${jobs.length} job${jobs.length !== 1 ? 's' : ''} scraped but never graded`;

  if (!jobs.length) {
    document.getElementById('ungradedContent').innerHTML =
      '<div style="padding:32px;text-align:center;color:#bbb;font-size:14px">All scraped jobs have been graded ✓</div>';
    return;
  }

  document.getElementById('ungradedContent').innerHTML = `
    <table class="ungraded-table">
      <thead>
        <tr>
          <th>Title / Company</th>
          <th>Source</th>
          <th>Location</th>
          <th>Exp</th>
          <th>Discovered</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${jobs.map(j => {
          const disc = j.discovered ? j.discovered.slice(0, 10) : '';
          const loc  = j.location || '—';
          const exp  = j.min_exp != null ? j.min_exp + 'y' : '—';
          const link = j.url
            ? `<a class="ungraded-title-link" href="${esc(j.url)}" target="_blank">${esc(j.title)}</a>`
            : `<span class="ungraded-title-link">${esc(j.title)}</span>`;
          const srcBadge = `<span class="source-badge source-${j.source||'goozali'}">${j.source||'goozali'}</span>`;
          return `<tr>
            <td><div>${link}</div><div style="font-size:11px;color:#888;margin-top:2px">${esc(j.company||'')}</div></td>
            <td>${srcBadge}</td>
            <td style="color:#555">${esc(loc)}</td>
            <td style="color:#888">${exp}</td>
            <td style="color:#aaa">${disc}</td>
            <td></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

function closeUngradedModal(e) {
  if (e.target === document.getElementById('ungradedModal'))
    document.getElementById('ungradedModal').classList.remove('open');
}

loadJobs();
setInterval(loadJobs, 60000);
</script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/jobs')
def api_jobs():
    days = int(request.args.get('days', 1))
    status = request.args.get('status', '')
    q = request.args.get('q', '').lower()
    min_score = int(request.args.get('min_score', 60))
    max_exp = request.args.get('max_exp')
    tel_aviv_only = request.args.get('tel_aviv_only') == '1'
    exclude_senior = request.args.get('exclude_senior') == '1'

    conn = get_conn()
    query = """
        SELECT j.id as job_id, j.title, j.company, j.field, j.url, j.location, j.min_exp, j.source,
               j.description, j.requirements,
               m.id as match_id, m.score, m.keywords, m.reason, COALESCE(m.feedback, '') as feedback,
               a.id as app_id, COALESCE(a.status, 'new') as status, a.pdf_path,
               COALESCE(a.interview_stage, '') as interview_stage, COALESCE(a.notes, '') as notes
        FROM jobs j
        JOIN matches m ON m.job_id = j.id
        LEFT JOIN applications a ON a.job_id = j.id
        WHERE m.score >= ? AND j.discovered >= datetime('now', ?)
    """
    params = [min_score, f'-{days} days']

    if status:
        if status == 'new':
            query += " AND (a.status IS NULL OR a.status = 'new')"
        else:
            query += " AND a.status = ?"
            params.append(status)

    if q:
        query += " AND (LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)"
        params += [f'%{q}%', f'%{q}%']

    if exclude_senior:
        for word in ('senior', 'staff ', 'principal', 'team lead', 'tech lead',
                     'manager', 'director', 'vp ', 'head of', 'architect',
                     'qa ', 'quality', 'tester', 'test engineer', 'test automation'):
            query += f" AND LOWER(j.title) NOT LIKE ?"
            params.append(f'%{word}%')

    if tel_aviv_only:
        query += " AND (j.location LIKE '%Tel Aviv%' OR j.location = '' OR j.location IS NULL)"

    if max_exp is not None and int(max_exp) < 15:
        query += " AND (j.min_exp IS NULL OR j.min_exp <= ?)"
        params.append(int(max_exp))

    query += " ORDER BY m.score DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    result = []
    for r in rows:
        row = dict(r)
        row['keywords'] = json.loads(row['keywords'] or '[]')
        result.append(row)
    return jsonify(result)


@app.route('/api/status', methods=['POST'])
def api_status():
    data = request.get_json()
    job_id = data.get('job_id')
    app_id = data.get('app_id')
    status = data['status']
    conn = get_conn()
    if app_id:
        conn.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    elif job_id:
        # No application row yet — create one
        existing = conn.execute("SELECT id FROM applications WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            conn.execute("UPDATE applications SET status=? WHERE job_id=?", (status, job_id))
        else:
            conn.execute("INSERT INTO applications (job_id, status) VALUES (?,?)", (job_id, status))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/notes', methods=['POST'])
def api_notes():
    data = request.get_json()
    app_id = data.get('app_id')
    stage = data.get('interview_stage', '')
    notes = data.get('notes', '')
    conn = get_conn()
    updated = conn.execute(
        "UPDATE applications SET interview_stage=?, notes=? WHERE id=?",
        (stage, notes, app_id)
    ).rowcount
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'updated': updated})


@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    data = request.get_json()
    match_id = data.get('match_id')
    feedback = data.get('feedback', '')  # 'up', 'down', or ''
    conn = get_conn()
    conn.execute("UPDATE matches SET feedback=? WHERE id=?", (feedback, match_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/profile', methods=['GET'])
def api_profile_get():
    conn = get_conn()
    row = conn.execute("SELECT value FROM user_profile WHERE key='profile'").fetchone()
    conn.close()
    return jsonify({'profile': row['value'] if row else ''})


@app.route('/api/profile', methods=['POST'])
def api_profile_post():
    data = request.get_json()
    profile = data.get('profile', '')
    conn = get_conn()
    conn.execute(
        "INSERT INTO user_profile (key, value) VALUES ('profile', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (profile,)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/ungraded')
def api_ungraded():
    days = int(request.args.get('days', 30))
    conn = get_conn()
    rows = conn.execute("""
        SELECT j.id, j.title, j.company, j.field, j.location, j.min_exp, j.source,
               j.url, j.description, j.requirements, j.discovered
        FROM jobs j
        LEFT JOIN matches m ON m.job_id = j.id
        WHERE m.id IS NULL
          AND j.discovered >= datetime('now', ?)
        ORDER BY j.discovered DESC
    """, (f'-{days} days',)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/run', methods=['POST'])
def api_run():
    if not pipeline_running:
        data = request.get_json(silent=True) or {}
        sources = data.get('sources', None)  # None = both
        threading.Thread(target=run_pipeline, args=(sources,), daemon=True).start()
    return jsonify({'started': True})


@app.route('/api/pipeline-status')
def api_pipeline_status():
    return jsonify({'running': pipeline_running, 'summary': last_run_summary})


@app.route('/download/<int:app_id>')
def download(app_id):
    conn = get_conn()
    row = conn.execute("SELECT pdf_path FROM applications WHERE id=?", (app_id,)).fetchone()
    conn.close()
    if not row or not row['pdf_path']:
        return "PDF not found", 404
    return send_file(row['pdf_path'], mimetype='application/pdf', as_attachment=True,
                     download_name=os.path.basename(row['pdf_path']))


@app.route('/api/diff/<int:app_id>')
def api_diff(app_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT a.tailored_json, j.title, j.company FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?",
        (app_id,)
    ).fetchone()
    conn.close()
    if not row or not row['tailored_json']:
        return jsonify({'error': 'No diff data available — re-run tailor to generate'}), 404
    data = json.loads(row['tailored_json'])
    return jsonify({'title': row['title'], 'company': row['company'], 'tailored': data})


if __name__ == '__main__':
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_pipeline, 'cron', hour=8, minute=0)
    scheduler.start()
    print("[dashboard] Running on http://localhost:3000 — daily pipeline at 08:00")
    app.run(debug=False, port=3000)
